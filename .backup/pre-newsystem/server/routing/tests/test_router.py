"""Block tests for the Router: validation, search behaviour, and find_many."""

from datetime import datetime, timedelta, timezone

import pytest

from routing import (
    CostMode,
    DynamicCostModel,
    InMemoryRoadGraph,
    InvalidRequest,
    Node,
    NoRouteFound,
    RouteConstraints,
    RouteRequest,
    Router,
    StaticCostModel,
    UnknownNode,
    VehicleProfile,
    avoid_edges,
    avoid_road_classes,
)

from .fixtures import random_grid_graph, small_town_graph


@pytest.fixture
def graph():
    return small_town_graph()


@pytest.fixture
def router(graph):
    return Router(graph=graph)


# --- Basic routing ---------------------------------------------------------


def test_route_reaches_its_destination(router):
    route = router.find(RouteRequest(origin="A", destination="I"))
    assert route.nodes[0] == "A"
    assert route.nodes[-1] == "I"
    assert route.distance > 0


def test_origin_equals_destination_is_a_trivial_route(router):
    route = router.find(RouteRequest(origin="A", destination="A"))
    assert route.nodes == ("A",)
    assert route.segments == ()
    assert route.distance == 0.0
    assert route.total_cost == 0.0


def test_cost_mode_is_echoed_back(router):
    assert router.find(RouteRequest(origin="A", destination="I")).cost_mode == "fastest"
    assert (
        router.find(RouteRequest(origin="A", destination="I", cost_mode="shortest")).cost_mode
        == "shortest"
    )


def test_shortest_and_fastest_can_disagree(router):
    """BC is unpaved and slow, so avoiding it costs distance but saves time."""
    shortest = router.find(RouteRequest(origin="B", destination="F", cost_mode="shortest"))
    fastest = router.find(RouteRequest(origin="B", destination="F", cost_mode="fastest"))
    assert fastest.segments == ("BE", "EF")
    assert fastest.travel_time < shortest.travel_time or shortest.segments == fastest.segments


# --- A* versus Dijkstra ----------------------------------------------------


def test_astar_is_on_by_default_and_expands_fewer_nodes(router):
    """Regression: the A* flag once built no heuristic at all and did nothing."""
    astar = router.find(RouteRequest(origin="A", destination="I", use_astar=True))
    dijkstra = router.find(RouteRequest(origin="A", destination="I", use_astar=False))
    assert astar.nodes_expanded < dijkstra.nodes_expanded


def test_astar_and_dijkstra_agree_on_cost(router):
    astar = router.find(RouteRequest(origin="A", destination="I", use_astar=True))
    dijkstra = router.find(RouteRequest(origin="A", destination="I", use_astar=False))
    assert astar.total_cost == pytest.approx(dijkstra.total_cost)


def test_astar_matches_dijkstra_on_a_larger_graph():
    router = Router(graph=random_grid_graph(30, seed=11))
    for mode in (CostMode.FASTEST, CostMode.SHORTEST):
        astar = router.find(RouteRequest(origin="0_0", destination="29_29", cost_mode=mode))
        dijkstra = router.find(
            RouteRequest(origin="0_0", destination="29_29", cost_mode=mode, use_astar=False)
        )
        assert astar.total_cost == pytest.approx(dijkstra.total_cost)
        assert astar.nodes_expanded <= dijkstra.nodes_expanded


# --- Road facts ------------------------------------------------------------


def test_one_way_road_is_not_used_backwards(router):
    """DE runs D to E only, so a route from E cannot take it back to D."""
    route = router.find(RouteRequest(origin="E", destination="D", cost_mode="shortest"))
    assert "DE" not in route.segments
    assert route.nodes[-1] == "D"


def test_blocked_road_is_routed_around(router):
    route = router.find(RouteRequest(origin="G", destination="I", cost_mode="shortest"))
    assert "HI" not in route.segments
    assert route.nodes[-1] == "I"


def test_vehicle_profile_can_bar_a_road_class(graph):
    """A profile restricted to roads the town does not have cannot go anywhere."""
    router = Router(graph=graph)
    request = RouteRequest(
        origin="A",
        destination="I",
        profile=VehicleProfile(name="tram", allowed_road_classes=frozenset({"rail"})),
    )
    with pytest.raises(NoRouteFound):
        router.find(request)


def test_a_custom_profile_object_is_accepted(router):
    slow = VehicleProfile(name="slow", speed_factor=0.5)
    fast = router.find(RouteRequest(origin="A", destination="I"))
    crawl = router.find(RouteRequest(origin="A", destination="I", profile=slow))
    assert crawl.travel_time == pytest.approx(fast.travel_time * 2)


# --- Constraints -----------------------------------------------------------


def test_request_level_edge_constraint_is_respected(router):
    constraints = RouteConstraints(rules=(avoid_edges({"BE"}),))
    route = router.find(
        RouteRequest(origin="A", destination="H", cost_mode="shortest", constraints=constraints)
    )
    assert "BE" not in route.segments


def test_request_level_road_class_constraint_is_respected(router):
    constraints = RouteConstraints(rules=(avoid_road_classes({"unpaved"}),))
    route = router.find(
        RouteRequest(origin="A", destination="C", cost_mode="shortest", constraints=constraints)
    )
    assert "BC" not in route.segments


def test_constraints_do_not_mutate_the_graph(graph):
    """Two requests with different rules must be able to share one graph."""
    router = Router(graph=graph)
    blocked = RouteConstraints(blocked_edges=frozenset({"BE"}))
    router.find(RouteRequest(origin="A", destination="H", constraints=blocked))
    after = router.find(RouteRequest(origin="A", destination="H"))
    assert "BE" in after.segments


# --- Failures --------------------------------------------------------------


def test_unknown_origin_raises(router):
    with pytest.raises(UnknownNode):
        router.find(RouteRequest(origin="ZZZ", destination="A"))


def test_unknown_destination_raises(router):
    with pytest.raises(UnknownNode):
        router.find(RouteRequest(origin="A", destination="ZZZ"))


def test_unknown_profile_is_an_invalid_request(router):
    with pytest.raises(InvalidRequest):
        router.find(RouteRequest(origin="A", destination="I", profile="spaceship"))


def test_unknown_cost_mode_is_an_invalid_request(router):
    with pytest.raises(InvalidRequest):
        router.find(RouteRequest(origin="A", destination="I", cost_mode="cheapest"))


def test_naive_departure_is_rejected(router):
    """Guessing a timezone would put a time-dependent cost out by whole hours."""
    with pytest.raises(InvalidRequest, match="timezone-aware"):
        router.find(
            RouteRequest(origin="A", destination="I", departure=datetime(2026, 9, 12, 8, 0))
        )


def test_aware_departure_is_accepted(router):
    departure = datetime(2026, 9, 12, 8, 0, tzinfo=timezone(timedelta(hours=7)))
    assert router.find(RouteRequest(origin="A", destination="I", departure=departure)).distance > 0


def test_disconnected_endpoints_raise_no_route_found():
    graph = InMemoryRoadGraph()
    graph.add_node(Node("A", 0.0, 0.0))
    graph.add_node(Node("B", 1.0, 1.0))
    with pytest.raises(NoRouteFound):
        Router(graph=graph).find(RouteRequest(origin="A", destination="B", use_astar=False))


def test_cost_model_unit_mismatch_is_refused(graph):
    """Meters charged against a request asking for seconds is undetectable downstream."""
    router = Router(graph=graph, costs=StaticCostModel(CostMode.SHORTEST))
    with pytest.raises(InvalidRequest, match="measures"):
        router.find(RouteRequest(origin="A", destination="I", cost_mode="fastest"))


def test_matching_cost_model_unit_is_accepted(graph):
    router = Router(graph=graph, costs=StaticCostModel(CostMode.SHORTEST))
    assert router.find(RouteRequest(origin="A", destination="I", cost_mode="shortest")).distance > 0


# --- Live conditions -------------------------------------------------------


def test_a_congestion_multiplier_can_change_the_route(graph):
    """The seam the traffic block plugs into: a mapping in, a new route out."""
    plain = Router(graph=graph).find(RouteRequest(origin="B", destination="F"))
    assert plain.segments == ("BE", "EF")

    congested = Router(
        graph=graph,
        costs=DynamicCostModel(StaticCostModel(CostMode.FASTEST), {"BE": 8.0, "EF": 8.0}),
    ).find(RouteRequest(origin="B", destination="F"))
    assert congested.segments == ("BC", "CF")


def test_congestion_lengthens_the_reported_travel_time(graph):
    plain = Router(graph=graph).find(RouteRequest(origin="A", destination="B"))
    congested = Router(
        graph=graph, costs=DynamicCostModel(StaticCostModel(CostMode.FASTEST), {"AB": 3.0})
    ).find(RouteRequest(origin="A", destination="B"))
    assert congested.travel_time == pytest.approx(plain.travel_time * 3)


# --- find_many -------------------------------------------------------------


def test_find_many_returns_one_route_per_reachable_destination(router):
    routes = router.find_many("A", ["C", "I", "F"])
    assert set(routes) == {"C", "I", "F"}
    for destination, route in routes.items():
        assert route.nodes[-1] == destination


def test_find_many_matches_find_for_each_destination(router):
    routes = router.find_many("A", ["C", "I"], cost_mode=CostMode.FASTEST)
    for destination, route in routes.items():
        single = router.find(RouteRequest(origin="A", destination=destination))
        assert route.total_cost == pytest.approx(single.total_cost)


def test_find_many_omits_an_unreachable_destination():
    graph = small_town_graph()
    graph.add_node(Node("Z", 20.0, 100.0))
    routes = Router(graph=graph).find_many("A", ["C", "Z"])
    assert set(routes) == {"C"}


def test_find_many_handles_the_origin_as_a_destination(router):
    routes = router.find_many("A", ["A", "C"])
    assert routes["A"].segments == ()
    assert routes["C"].nodes[-1] == "C"


def test_find_many_rejects_an_unknown_destination(router):
    with pytest.raises(UnknownNode):
        router.find_many("A", ["C", "ZZZ"])


def test_find_many_validates_like_find(router):
    with pytest.raises(InvalidRequest):
        router.find_many("A", ["C"], profile="spaceship")
