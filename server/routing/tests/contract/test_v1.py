"""Routing contract v1 -- the specification, in executable form.

This suite imports the public surface and nothing else: no internal module, no
private helper, no knowledge of which algorithm is running. That is deliberate
and load-bearing. A replacement implementation -- contraction hierarchies, a
remote service, a rewrite in another language behind the same types -- is
promoted only when it passes this file unchanged, so anything this file
reaches into becomes part of what the block can never change.

Each test names the guarantee it holds, matching `routing/contract.md`.
Anything listed there under NOT GUARANTEED is deliberately not asserted here:
tie-breaking between equal-cost routes, node expansion counts, and the exact
route chosen when a cost model changes are all free to differ.
"""

import time

import pytest

from routing import (
    Access,
    CostContext,
    CostMode,
    Direction,
    InvalidRequest,
    NoRouteFound,
    RouteRequest,
    Router,
    RoutingError,
    StaticCostModel,
    UnknownNode,
    VehicleProfile,
    get_vehicle_profile,
)

from ..fixtures import random_grid_graph, small_town_graph, town_with_turn_restrictions

CORPUS = (
    ("A", "I"),
    ("A", "C"),
    ("G", "I"),
    ("E", "D"),
    ("C", "G"),
    ("B", "F"),
)


@pytest.fixture
def graph():
    return small_town_graph()


@pytest.fixture
def router(graph):
    return Router(graph=graph)


# --- G1 Determinism --------------------------------------------------------


def test_g1_same_request_gives_an_identical_route(router):
    request = RouteRequest(origin="A", destination="I")
    first = router.find(request)
    second = router.find(request)
    assert first == second


def test_g1_a_freshly_built_graph_gives_an_identical_route():
    request = RouteRequest(origin="A", destination="I")
    first = Router(graph=small_town_graph()).find(request)
    second = Router(graph=small_town_graph()).find(request)
    assert first == second


def test_g1_holds_across_the_corpus():
    for origin, destination in CORPUS:
        request = RouteRequest(origin=origin, destination=destination)
        assert Router(graph=small_town_graph()).find(request) == Router(
            graph=small_town_graph()
        ).find(request)


# --- G2 Connectivity -------------------------------------------------------


def test_g2_consecutive_segments_share_a_node(router, graph):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        for node, segment in zip(route.nodes, route.segments):
            edge = graph.get_edge(segment)
            assert node in (edge.from_node, edge.to_node)
        assert len(route.nodes) == len(route.segments) + 1


def test_g2_the_node_path_runs_from_origin_to_destination(router):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        assert route.nodes[0] == origin
        assert route.nodes[-1] == destination


def test_g2_geometry_is_contiguous(router):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        assert len(route.geometry) >= 2
        assert len(set(route.geometry)) == len(route.geometry) or route.distance == 0


def test_g2_steps_tile_the_route_without_gaps_or_overlap(router):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        covered = [segment for step in route.steps for segment in step.segments]
        assert covered == list(route.segments)
        assert route.steps[0].from_node == origin
        assert route.steps[-1].to_node == destination


# --- G3 Legality -----------------------------------------------------------


def test_g3_no_one_way_is_traversed_backwards(router, graph):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        for node, segment in zip(route.nodes, route.segments):
            edge = graph.get_edge(segment)
            if edge.direction is Direction.ONE_WAY:
                assert node == edge.from_node


def test_g3_no_blocked_edge_is_used(router, graph):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        for segment in route.segments:
            assert graph.get_edge(segment).access is not Access.BLOCKED


def test_g3_no_road_class_barred_by_the_profile_is_used(graph):
    router = Router(graph=graph)
    profile = get_vehicle_profile("truck")
    route = router.find(RouteRequest(origin="A", destination="I", profile="truck"))
    for segment in route.segments:
        assert profile.may_use(graph.get_edge(segment))


def test_g3_no_prohibited_turn_is_taken():
    graph = town_with_turn_restrictions()
    router = Router(graph=graph)
    for origin, destination in CORPUS:
        try:
            route = router.find(RouteRequest(origin=origin, destination=destination))
        except NoRouteFound:
            continue
        for index in range(1, len(route.segments)):
            assert graph.is_turn_allowed(
                route.segments[index - 1], route.nodes[index], route.segments[index]
            )


def test_g3_holds_on_a_large_graph():
    graph = random_grid_graph(25, seed=5)
    route = Router(graph=graph).find(RouteRequest(origin="0_0", destination="24_24"))
    for node, segment in zip(route.nodes, route.segments):
        edge = graph.get_edge(segment)
        assert edge.access is not Access.BLOCKED
        if edge.direction is Direction.ONE_WAY:
            assert node == edge.from_node
    for index in range(1, len(route.segments)):
        assert graph.is_turn_allowed(
            route.segments[index - 1], route.nodes[index], route.segments[index]
        )


# --- G4 Consistency with the cost model ------------------------------------


def test_g4_travel_time_equals_what_the_cost_model_reports(router, graph):
    """Exactly, not approximately. An ETA that merely resembles the cost model
    is an ETA nobody can reconcile when it is wrong."""
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        model = StaticCostModel(CostMode(route.cost_mode))
        context = CostContext(profile=get_vehicle_profile("car"))
        expected = sum(
            model.travel_time(graph.get_edge(segment), context) for segment in route.segments
        )
        expected += sum(
            model.turn_time(
                graph.get_edge(route.segments[index - 1]),
                route.nodes[index],
                graph.get_edge(route.segments[index]),
                context,
            )
            for index in range(1, len(route.segments))
        )
        assert route.travel_time == expected


def test_g4_distance_is_the_sum_of_its_segments(router, graph):
    for origin, destination in CORPUS:
        route = router.find(RouteRequest(origin=origin, destination=destination))
        expected = sum(graph.get_edge(segment).distance for segment in route.segments)
        assert route.distance == pytest.approx(expected)


def test_g4_travel_time_is_not_the_penalty_weighted_cost(graph):
    """A profile penalty changes what a route costs, never what it takes.

    The two numbers must move independently: a vehicle that dislikes a road
    pays more to use it without the drive getting any longer. Reporting the
    weighted figure as an arrival time is the failure this guards against.
    """
    router = Router(graph=graph)
    wary = VehicleProfile(name="wary", road_class_penalties={"secondary": 2.0})
    plain = router.find(RouteRequest(origin="A", destination="I"))
    weighted = router.find(RouteRequest(origin="A", destination="I", profile=wary))

    assert plain.total_cost == pytest.approx(plain.travel_time)
    assert weighted.total_cost > weighted.travel_time
    assert weighted.travel_time == pytest.approx(plain.travel_time)


# --- G5 Optimality ---------------------------------------------------------


def test_g5_astar_matches_dijkstra_on_the_corpus(router):
    for origin, destination in CORPUS:
        for mode in (CostMode.FASTEST, CostMode.SHORTEST):
            astar = router.find(
                RouteRequest(origin=origin, destination=destination, cost_mode=mode)
            )
            truth = router.find(
                RouteRequest(
                    origin=origin, destination=destination, cost_mode=mode, use_astar=False
                )
            )
            assert astar.total_cost <= truth.total_cost * 1.005
            assert astar.total_cost >= truth.total_cost - 1e-9


def test_g5_holds_on_a_large_graph():
    router = Router(graph=random_grid_graph(30, seed=17))
    for mode in (CostMode.FASTEST, CostMode.SHORTEST):
        request = dict(origin="0_0", destination="29_29", cost_mode=mode)
        astar = router.find(RouteRequest(**request))
        truth = router.find(RouteRequest(**request, use_astar=False))
        assert astar.total_cost <= truth.total_cost * 1.005
        assert astar.total_cost >= truth.total_cost - 1e-9


def test_g5_holds_with_turn_restrictions_present():
    router = Router(graph=town_with_turn_restrictions())
    for origin, destination in CORPUS:
        try:
            astar = router.find(RouteRequest(origin=origin, destination=destination))
            truth = router.find(
                RouteRequest(origin=origin, destination=destination, use_astar=False)
            )
        except NoRouteFound:
            continue
        assert astar.total_cost == pytest.approx(truth.total_cost)


def test_g5_find_many_agrees_with_find(router):
    routes = router.find_many("A", [destination for _, destination in CORPUS])
    for destination, route in routes.items():
        single = router.find(RouteRequest(origin="A", destination=destination))
        assert route.total_cost == pytest.approx(single.total_cost)


# --- G6 Termination --------------------------------------------------------


def test_g6_a_route_on_a_city_sized_graph_returns_promptly():
    """A loose bound. It exists to catch a search that stops terminating, not
    to police performance -- that is the benchmark's job."""
    router = Router(graph=random_grid_graph(60, seed=2))
    started = time.perf_counter()
    router.find(RouteRequest(origin="0_0", destination="59_59"))
    assert time.perf_counter() - started < 5.0


def test_g6_an_unreachable_destination_returns_rather_than_hanging():
    """An island node is searched for exhaustively, then given up on."""
    from routing import Node

    graph = random_grid_graph(20, seed=4)
    graph.add_node(Node("island", 11.0, 107.0))
    router = Router(graph=graph)
    started = time.perf_counter()
    with pytest.raises(NoRouteFound):
        router.find(RouteRequest(origin="0_0", destination="island", use_astar=False))
    assert time.perf_counter() - started < 5.0


# --- G7 Purity -------------------------------------------------------------


def test_g7_routing_does_not_mutate_the_graph(graph):
    before = _snapshot(graph)
    router = Router(graph=graph)
    for origin, destination in CORPUS:
        router.find(RouteRequest(origin=origin, destination=destination))
    assert _snapshot(graph) == before


def test_g7_a_constrained_request_does_not_affect_the_next_one(graph):
    from routing import RouteConstraints

    router = Router(graph=graph)
    plain = router.find(RouteRequest(origin="A", destination="H"))
    router.find(
        RouteRequest(
            origin="A",
            destination="H",
            constraints=RouteConstraints(blocked_edges=frozenset({"BE"})),
        )
    )
    assert router.find(RouteRequest(origin="A", destination="H")) == plain


def test_g7_one_router_serves_many_requests(router):
    first = router.find(RouteRequest(origin="A", destination="I"))
    router.find(RouteRequest(origin="G", destination="C", cost_mode="shortest"))
    router.find_many("E", ["A", "I"])
    assert router.find(RouteRequest(origin="A", destination="I")) == first


# --- Errors ----------------------------------------------------------------


def test_errors_unknown_origin_raises_unknown_node(router):
    with pytest.raises(UnknownNode):
        router.find(RouteRequest(origin="ZZZ", destination="A"))


def test_errors_unknown_destination_raises_unknown_node(router):
    with pytest.raises(UnknownNode):
        router.find(RouteRequest(origin="A", destination="ZZZ"))


def test_errors_disconnected_endpoints_raise_no_route_found(graph):
    from routing import Node

    graph.add_node(Node("Z", 20.0, 100.0))
    with pytest.raises(NoRouteFound):
        Router(graph=graph).find(RouteRequest(origin="A", destination="Z"))


def test_errors_a_malformed_request_raises_invalid_request(router):
    with pytest.raises(InvalidRequest):
        router.find(RouteRequest(origin="A", destination="I", profile="spaceship"))
    with pytest.raises(InvalidRequest):
        router.find(RouteRequest(origin="A", destination="I", cost_mode="cheapest"))


def test_errors_every_failure_is_a_routing_error(router):
    """No other exception escapes find(); one except clause is enough."""
    bad_requests = [
        RouteRequest(origin="ZZZ", destination="A"),
        RouteRequest(origin="A", destination="ZZZ"),
        RouteRequest(origin="A", destination="I", profile="spaceship"),
        RouteRequest(origin="A", destination="I", cost_mode="cheapest"),
    ]
    for request in bad_requests:
        with pytest.raises(RoutingError):
            router.find(request)


# --- Helpers ---------------------------------------------------------------


def _snapshot(graph):
    return (
        sorted(node.id for node in graph.nodes()),
        sorted(
            (e.id, e.from_node, e.to_node, e.distance, e.speed, e.access, e.direction)
            for e in graph.edges()
        ),
        sorted((n.id, tuple(sorted(graph.get_neighbors(n.id)))) for n in graph.nodes()),
    )
