"""The Routing Service: API request in, Route out, over mock providers.

Every test here runs the real service and the real engine against providers
that hold dictionaries. That is the point of the protocols in
`routing.providers`: a routing test needs no database, no network, no road
source and no clock, so these run in milliseconds and can never fail for a
reason that has nothing to do with routing.

The contract suite (``tests/contract/test_v1.py``) covers what the engine
promises. This covers what the *service* adds: choosing an area, snapping
coordinates, combining conditions, and turning a closure into a constraint
rather than a cost.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain import BBox, GeoPoint
from routing import (
    InvalidRequest,
    NoRouteFound,
    RouteQuery,
    RoutingError,
    RoutingPolicy,
    RoutingService,
    combine_multipliers,
)
from routing.tests.fixtures import small_town_graph

# The hand-built town from the block's own fixtures: a 3x3 grid of junctions
# A..I over central Ho Chi Minh City, with one one-way street, one blocked
# edge and a range of road classes. Reusing it keeps the service tests and the
# engine tests talking about the same network.
GRAPH = small_town_graph()

#: Coordinates of the fixture's corners, read off the graph so the two can
#: never drift apart.
CORNER = {node.id: GeoPoint(node.longitude, node.latitude) for node in GRAPH.nodes()}
ANY_AREA = BBox(-1.0, -1.0, 2.0, 2.0)


class Graphs:
    """A ``MapGraphProvider`` over one fixed graph."""

    def __init__(self, graph=GRAPH, fail_with=None):
        self._graph = graph
        self.fail_with = fail_with
        self.areas: list[BBox] = []

    def graph_for(self, area: BBox):
        self.areas.append(area)
        if self.fail_with:
            raise self.fail_with
        return View(self._graph)


class View:
    def __init__(self, graph):
        self._graph = graph

    @property
    def graph(self):
        return self._graph

    def nearest_node(self, point: GeoPoint, *, within_m=None):
        best, best_m = None, float("inf") if within_m is None else within_m
        for node in self._graph.nodes():
            metres = point.distance_to(GeoPoint(node.longitude, node.latitude))
            if metres <= best_m:
                best, best_m = node.id, metres
        return best


class Traffic:
    def __init__(self, multipliers=None):
        self.multipliers = multipliers or {}

    def multipliers_for(self, area):
        return dict(self.multipliers)


class RoadState:
    def __init__(self, blocked=frozenset(), multipliers=None):
        self.blocked = frozenset(blocked)
        self.multipliers = multipliers or {}

    def blocked_edges(self, area):
        return self.blocked

    def multipliers_for(self, area):
        return dict(self.multipliers)


def query(origin="A", destination="I", **over):
    return RouteQuery(origin=CORNER[origin], destination=CORNER[destination], **over)


# --- The basic flow --------------------------------------------------------


def test_a_route_between_two_coordinates_comes_back() -> None:
    route = RoutingService(graphs=Graphs()).route(query())
    assert route.distance > 0
    assert route.travel_time > 0
    assert len(route.segments) >= 1


def test_the_route_is_deterministic() -> None:
    service = RoutingService(graphs=Graphs())
    first = service.route(query())
    second = service.route(query())
    assert first == second


def test_the_area_loaded_covers_both_endpoints_with_room_to_detour() -> None:
    graphs = Graphs()
    RoutingService(graphs=graphs, policy=RoutingPolicy(pad_degrees=0.05)).route(query())

    area = graphs.areas[0]
    for point in (CORNER["A"], CORNER["I"]):
        assert area.contains(point.as_tuple())
    assert area.east - area.west > 0.1


def test_a_coordinate_far_from_the_network_is_a_client_error() -> None:
    """Not a 500: retrying unchanged will not help, and moving the pin will."""
    service = RoutingService(graphs=Graphs())
    with pytest.raises(InvalidRequest, match="not within"):
        service.route(
            RouteQuery(origin=GeoPoint(50.0, 50.0), destination=CORNER["I"])
        )


def test_the_failing_endpoint_is_named() -> None:
    service = RoutingService(graphs=Graphs())
    with pytest.raises(InvalidRequest, match="destination"):
        service.route(RouteQuery(origin=CORNER["A"], destination=GeoPoint(50.0, 50.0)))


def test_a_provider_failure_becomes_a_routing_error_not_its_own_type() -> None:
    """The API above must not have to know what a map source raises."""
    service = RoutingService(graphs=Graphs(fail_with=TimeoutError("overpass down")))
    with pytest.raises(RoutingError, match="routing service failure"):
        service.route(query())


# --- Traffic ---------------------------------------------------------------


def test_traffic_makes_the_drive_take_longer() -> None:
    """Slowing every edge equally scales the ETA and leaves the route alone.

    Slowing only the chosen route would change which route is chosen -- which
    is the next test, and the reason this one has to slow everything to
    measure the ETA in isolation.
    """
    everywhere = {edge.id: 2.0 for edge in GRAPH.edges()}
    free = RoutingService(graphs=Graphs()).route(query())
    jammed = RoutingService(graphs=Graphs(), traffic=Traffic(everywhere)).route(query())

    assert jammed.segments == free.segments
    assert jammed.travel_time == pytest.approx(free.travel_time * 2.0, rel=1e-6)


def test_traffic_can_change_which_way_the_route_goes() -> None:
    free = RoutingService(graphs=Graphs()).route(query())
    diverted = RoutingService(
        graphs=Graphs(), traffic=Traffic({seg: 8.0 for seg in free.segments})
    ).route(query())

    assert diverted.segments != free.segments


def test_use_traffic_false_gives_the_free_flow_route() -> None:
    """What a "usual journey time" comparison needs."""
    free = RoutingService(graphs=Graphs()).route(query())
    service = RoutingService(graphs=Graphs(), traffic=Traffic({"AB": 8.0, "AD": 8.0, "BE": 8.0}))

    assert service.route(query(use_traffic=False)).travel_time == pytest.approx(
        free.travel_time
    )


def test_a_server_with_no_traffic_source_still_routes() -> None:
    service = RoutingService(graphs=Graphs(), traffic=None)
    assert service.route(query()).distance > 0
    assert service.describe()["traffic"] is None


# --- Road state ------------------------------------------------------------


def test_a_blocked_edge_is_not_used() -> None:
    free = RoutingService(graphs=Graphs()).route(query())
    detour = RoutingService(
        graphs=Graphs(), road_state=RoadState(blocked={free.segments[0]})
    ).route(query())

    assert free.segments[0] not in detour.segments


def test_blocking_every_way_through_reports_no_route_rather_than_using_one() -> None:
    """The classic defect: a huge cost lets the search "use" a closed road."""
    all_edges = {edge.id for edge in GRAPH.edges()}
    service = RoutingService(graphs=Graphs(), road_state=RoadState(blocked=all_edges))

    with pytest.raises(NoRouteFound):
        service.route(query())


def test_a_road_state_cost_slows_a_route_without_forbidding_it() -> None:
    free = RoutingService(graphs=Graphs()).route(query())
    slowed = RoutingService(
        graphs=Graphs(), road_state=RoadState(multipliers={free.segments[0]: 1.5})
    ).route(query())

    assert slowed.travel_time >= free.travel_time


def test_a_failure_reading_closures_fails_the_request_rather_than_ignoring_them() -> None:
    service = RoutingService(
        graphs=Graphs(), road_state=RoadState(blocked={"AB"})
    )
    service._road_state.blocked_edges = _raise  # type: ignore[assignment]
    with pytest.raises(RoutingError):
        service.route(query())


def _raise(area):
    raise RuntimeError("edge index unavailable")


# --- Preferences -----------------------------------------------------------


def test_avoiding_a_road_class_keeps_it_out_of_the_route() -> None:
    classes = {edge.road_class for edge in GRAPH.edges()}
    for road_class in classes:
        service = RoutingService(graphs=Graphs())
        try:
            route = service.route(query(avoid_road_classes=frozenset({road_class})))
        except NoRouteFound:
            continue
        used = {GRAPH.get_edge(seg).road_class for seg in route.segments}
        assert road_class not in used


def test_a_naive_departure_is_refused() -> None:
    service = RoutingService(graphs=Graphs())
    with pytest.raises(InvalidRequest):
        service.route(query(departure=datetime(2026, 9, 13, 8, 0)))


def test_an_aware_departure_is_accepted() -> None:
    service = RoutingService(graphs=Graphs())
    route = service.route(query(departure=datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)))
    assert route.distance > 0


# --- Waypoints -------------------------------------------------------------


def test_a_waypoint_is_actually_passed_through() -> None:
    service = RoutingService(graphs=Graphs())
    route = service.route(query(waypoints=(CORNER["E"],)))
    assert "E" in route.nodes


def test_a_joined_route_has_no_duplicated_junction() -> None:
    service = RoutingService(graphs=Graphs())
    route = service.route(query(waypoints=(CORNER["E"],)))
    assert len(route.nodes) == len(route.segments) + 1


def test_a_joined_routes_distance_is_the_sum_of_its_legs() -> None:
    service = RoutingService(graphs=Graphs())
    whole = service.route(query(waypoints=(CORNER["E"],)))
    first = service.route(query(origin="A", destination="E"))
    second = service.route(query(origin="E", destination="I"))

    assert whole.distance == pytest.approx(first.distance + second.distance)
    assert whole.travel_time == pytest.approx(first.travel_time + second.travel_time)


def test_a_single_leg_route_is_returned_untouched() -> None:
    """The contract's determinism guarantee is stated about that exact object."""
    service = RoutingService(graphs=Graphs())
    assert service.route(query()) == service.route(query())


# --- Combining conditions --------------------------------------------------


def test_two_sources_on_one_edge_take_the_worse_not_the_product() -> None:
    """A flooded road is slow *because* it is flooded; charging twice is wrong."""
    assert combine_multipliers([{"AB": 2.0}, {"AB": 3.0}]) == {"AB": 3.0}


def test_a_multiplier_below_one_is_raised_rather_than_rejected() -> None:
    """A provider claiming a road is faster than free flow is reporting a bug."""
    assert combine_multipliers([{"AB": 0.5}]) == {}


def test_a_multiplier_is_capped() -> None:
    assert combine_multipliers([{"AB": 1e9}], ceiling=12.0) == {"AB": 12.0}


def test_traffic_and_road_state_are_combined_not_multiplied() -> None:
    free = RoutingService(graphs=Graphs()).route(query())
    edge = free.segments[0]

    both = RoutingService(
        graphs=Graphs(),
        traffic=Traffic({edge: 2.0}),
        road_state=RoadState(multipliers={edge: 3.0}),
    ).route(query(avoid_road_classes=frozenset()))
    worse_only = RoutingService(graphs=Graphs(), road_state=RoadState(multipliers={edge: 3.0})).route(
        query()
    )

    assert both.travel_time == pytest.approx(worse_only.travel_time)


# --- Policy ----------------------------------------------------------------


def test_an_impossible_policy_is_refused_at_construction() -> None:
    with pytest.raises(ValueError):
        RoutingPolicy(snap_radius_m=0)
    with pytest.raises(ValueError):
        RoutingPolicy(max_multiplier=0.5)


def test_describe_reports_what_the_service_is_wired_to() -> None:
    described = RoutingService(
        graphs=Graphs(), traffic=Traffic(), road_state=RoadState()
    ).describe()
    assert described["traffic"] == "Traffic"
    assert described["road_state"] == "RoadState"
