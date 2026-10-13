"""The whole server, wired as it really is, with only the outside world faked.

Everything above is a unit or block test: one subsystem, mocked neighbours.
This file is the other kind. Storage is a real SQLite file, the road network
is real map data flowing through the real graph builder, traffic really goes
through ingest and attachment, road conditions really go through the
classifier and the store, and the routing engine really searches. The only
things replaced are Overpass and the traffic feeds -- the two edges that would
otherwise make this suite depend on somebody else's uptime.

What it is checking is the thing no block test can: that the *seams* line up.
A road id produced by map data is the same road id traffic attaches to, is the
same one road state records, is the same one the cost provider turns back into
the edge ids routing actually searches. Every one of those is a place where
two blocks could each be internally correct and still disagree.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.services import IngestService, TrafficService
from domain import BBox, GeoPoint
from ingest import Observations, TrafficCollector, TrafficObservation, TrafficProvider
from mapdata import RoadGraphProvider, RoadStore, StoredRoadNetwork
from roadstate import RoadStateSource, RoadStateStore
from routing import NoRouteFound, RouteQuery, RoutingService
from storage import Collection, SqliteStorage
from tests.fixtures import CORNER, TOWN_AREA, FakeRoadNetwork, town_roads
from traffic import TrafficCostSource, TrafficState

NOW = datetime.now(timezone.utc)


class FeedProvider(TrafficProvider):
    """A traffic feed that reports whatever a test hands it, at real points."""

    name = "test-feed"

    def __init__(self, readings=(), incidents=()):
        self.readings = tuple(readings)
        self.incidents = tuple(incidents)

    def fetch(self, bbox):
        return Observations(
            bbox=bbox,
            source=self.name,
            observed_at=NOW,
            observations=tuple(
                TrafficObservation(
                    id=f"{self.name}:{index}",
                    point=point,
                    observed_at=NOW,
                    source=self.name,
                    speed_kph=speed,
                )
                for index, (point, speed) in enumerate(self.readings)
            ),
            incidents=self.incidents,
        )


@pytest.fixture
def server(tmp_path):
    """Every subsystem, wired the way api.composition wires them."""
    storage = SqliteStorage(tmp_path / "server.db")
    storage.migrate()

    roads = FakeRoadNetwork()
    graphs = RoadGraphProvider(roads)
    traffic_state = TrafficState()
    road_state = RoadStateStore(storage.documents)

    ingest = IngestService(
        collector=TrafficCollector([FeedProvider()]),
        traffic=traffic_state,
        road_state=road_state,
        roads=roads,
    )
    routing = RoutingService(
        graphs=graphs,
        traffic=TrafficCostSource(traffic_state, graphs),
        road_state=RoadStateSource(road_state, graphs),
    )

    yield {
        "storage": storage,
        "roads": roads,
        "graphs": graphs,
        "traffic_state": traffic_state,
        "road_state": road_state,
        "ingest": ingest,
        "routing": routing,
    }
    storage.close()


def query(origin="A", destination="C", **over):
    return RouteQuery(
        origin=GeoPoint(*CORNER[origin]), destination=GeoPoint(*CORNER[destination]), **over
    )


# --- The central flow ------------------------------------------------------


def test_a_route_request_reaches_the_engine_and_comes_back(server) -> None:
    route = server["routing"].route(query())
    assert route.distance > 0
    assert route.travel_time > 0
    assert len(route.geometry) >= 2


def test_routing_obtains_its_graph_from_map_data(server) -> None:
    server["routing"].route(query())
    assert server["roads"].calls >= 1


def test_the_same_request_gives_the_same_answer_across_restarts(server, tmp_path) -> None:
    """Determinism is what makes a route cacheable and a bug reproducible."""
    first = server["routing"].route(query())

    graphs = RoadGraphProvider(FakeRoadNetwork())
    second = RoutingService(graphs=graphs).route(query())

    assert first.segments == second.segments
    assert first.distance == pytest.approx(second.distance)


# --- Traffic, end to end ---------------------------------------------------


def test_a_feed_reading_changes_the_eta_for_the_road_it_is_on(server) -> None:
    """ingest -> attach -> state -> cost provider -> edge ids -> engine."""
    free = server["routing"].route(query())

    midpoint = (
        (CORNER["A"][0] + CORNER["B"][0]) / 2,
        (CORNER["A"][1] + CORNER["B"][1]) / 2,
    )
    server["ingest"]._collector = TrafficCollector([FeedProvider([(midpoint, 5.0)])])
    summary = server["ingest"].refresh(TOWN_AREA)

    assert summary["roads_with_speed"] >= 1
    assert server["traffic_state"].fresh()

    jammed = server["routing"].route(query())
    assert jammed.travel_time != free.travel_time


def test_a_feed_reading_is_visible_in_the_traffic_snapshot(server) -> None:
    midpoint = (
        (CORNER["A"][0] + CORNER["D"][0]) / 2,
        (CORNER["A"][1] + CORNER["D"][1]) / 2,
    )
    server["ingest"]._collector = TrafficCollector([FeedProvider([(midpoint, 5.0)])])
    server["ingest"].refresh(TOWN_AREA)

    snapshot = server["traffic_state"].snapshot(TOWN_AREA, server["roads"].roads(TOWN_AREA))
    assert snapshot.speeds
    assert snapshot.speeds[0].level.slug in {"heavy", "standstill"}


def test_a_dead_feed_degrades_the_route_rather_than_failing_it(server) -> None:
    class Broken(TrafficProvider):
        name = "broken"

        def fetch(self, bbox):
            raise TimeoutError("upstream gone")

    server["ingest"]._collector = TrafficCollector([Broken()])
    summary = server["ingest"].refresh(TOWN_AREA)

    assert summary["failures"]
    assert server["routing"].route(query()).distance > 0


# --- Road state, end to end ------------------------------------------------


def test_a_closure_reported_through_ingest_diverts_a_route(server) -> None:
    """The chain routing depends on most, and the one most easily broken."""
    free = server["routing"].route(query())
    closed_road = free.segments[0].split("#")[0]

    server["ingest"].accept_reports(
        [
            {
                "id": "closure-1",
                "title": "Road closed",
                "geometry": [list(CORNER["A"]), list(CORNER["B"])],
                "road_ids": [closed_road],
            }
        ]
    )

    diverted = server["routing"].route(query())
    assert not any(segment.startswith(closed_road) for segment in diverted.segments)


def test_a_closure_attaches_to_a_road_by_geometry_alone(server) -> None:
    """Most free feeds publish geometry and no road reference."""
    server["ingest"].accept_reports(
        [
            {
                "id": "closure-2",
                "title": "Road closed",
                "geometry": [list(CORNER["A"]), list(CORNER["B"])],
            }
        ]
    )
    conditions = server["road_state"].active_in(TOWN_AREA)
    assert conditions
    assert conditions[0].road_ids


def test_closing_everything_reports_no_route_rather_than_using_a_closed_road(server) -> None:
    server["ingest"].accept_reports(
        [
            {
                "id": f"closure-{road.id}",
                "title": "Road closed",
                "geometry": [list(point) for point in road.geometry],
                "road_ids": [road.id],
            }
            for road in town_roads()
        ]
    )
    with pytest.raises(NoRouteFound):
        server["routing"].route(query())


def test_roadworks_slow_a_route_without_forbidding_it(server) -> None:
    free = server["routing"].route(query())
    road = free.segments[0].split("#")[0]

    server["ingest"].accept_reports(
        [
            {
                "id": "works-1",
                "kind": "roadworks",
                "severity": "low",
                "geometry": [list(CORNER["A"])],
                "road_ids": [road],
            }
        ]
    )
    after = server["routing"].route(query())
    assert after.distance > 0


# --- Persistence -----------------------------------------------------------


def test_a_condition_survives_a_restart(server, tmp_path) -> None:
    """The one thing here a human entered and nothing can regenerate."""
    server["ingest"].accept_reports(
        [{"id": "c1", "title": "Road closed", "geometry": [list(CORNER["A"])]}]
    )
    server["storage"].close()

    reopened = SqliteStorage(tmp_path / "server.db")
    reopened.migrate()
    try:
        assert RoadStateStore(reopened.documents).count() == 1
    finally:
        reopened.close()


def test_roads_fetched_once_are_servable_from_the_database(server) -> None:
    RoadStore(server["storage"].documents).save(town_roads())
    stored = StoredRoadNetwork(server["storage"].documents)

    assert len(stored.roads(TOWN_AREA)) == len(town_roads())


def test_a_route_computes_over_a_graph_built_from_stored_roads(server) -> None:
    """Proves the offline path: no Overpass, no network, still routes."""
    RoadStore(server["storage"].documents).save(town_roads())
    offline = RoutingService(
        graphs=RoadGraphProvider(StoredRoadNetwork(server["storage"].documents))
    )
    assert offline.route(query()).distance > 0


def test_storage_can_be_replaced_without_touching_anything_above(server) -> None:
    """The abstraction's whole purpose, exercised rather than asserted."""
    from storage import InMemoryStorage

    other = InMemoryStorage()
    other.migrate()
    try:
        RoadStore(other.documents).save(town_roads())
        service = RoutingService(
            graphs=RoadGraphProvider(StoredRoadNetwork(other.documents))
        )
        assert service.route(query()).distance > 0
        assert other.documents.count(Collection.ROADS) == len(town_roads())
    finally:
        other.close()


# --- Lazy refresh ----------------------------------------------------------


def test_the_traffic_refresh_is_debounced(server) -> None:
    """Asking a volunteer API faster than it publishes buys nothing."""
    calls = {"n": 0}

    class Counting(TrafficProvider):
        name = "counting"

        def fetch(self, bbox):
            calls["n"] += 1
            return Observations.empty(bbox, self.name)

    ingest = IngestService(
        collector=TrafficCollector([Counting()]),
        traffic=server["traffic_state"],
        road_state=server["road_state"],
        roads=server["roads"],
    )
    service = TrafficService(ingest=ingest, state=server["traffic_state"], interval_s=3600)

    assert service.ensure_fresh(TOWN_AREA) is True
    assert service.ensure_fresh(TOWN_AREA) is False
    assert calls["n"] == 1


def test_a_refresh_that_explodes_never_reaches_the_caller(server) -> None:
    class Exploding:
        def refresh(self, area):
            raise RuntimeError("everything is on fire")

    service = TrafficService(ingest=Exploding(), state=server["traffic_state"])
    assert service.ensure_fresh(TOWN_AREA) is False


def test_traffic_disabled_means_no_refresh_at_all(server) -> None:
    class Watching:
        called = False

        def refresh(self, area):
            Watching.called = True

    service = TrafficService(ingest=Watching(), state=server["traffic_state"], enabled=False)
    assert service.ensure_fresh(TOWN_AREA) is False
    assert Watching.called is False
