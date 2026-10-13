"""Unit tests for turning a settled path into a drawable, speakable Route."""

import pytest

from routing import (
    Edge,
    InMemoryRoadGraph,
    LatLon,
    Maneuver,
    Node,
    RouteRequest,
    Router,
)

from .fixtures import small_town_graph


@pytest.fixture
def router():
    return Router(graph=small_town_graph())


# --- Geometry --------------------------------------------------------------


def test_route_carries_geometry_for_every_junction(router):
    route = router.find(RouteRequest(origin="A", destination="I"))
    assert len(route.geometry) == len(route.nodes)
    assert all(isinstance(point, LatLon) for point in route.geometry)


def test_geometry_starts_at_the_origin_and_ends_at_the_destination(router):
    graph = small_town_graph()
    route = router.find(RouteRequest(origin="A", destination="I"))
    assert route.geometry[0] == graph.get_node("A").coordinate
    assert route.geometry[-1] == graph.get_node("I").coordinate


def test_geometry_is_contiguous_and_never_repeats_a_joint(router):
    """Each leg contributes all but its first point, which the last one ended on."""
    route = router.find(RouteRequest(origin="A", destination="I"))
    assert len(route.geometry) == len(route.segments) + 1


def test_stored_edge_geometry_is_used_when_present():
    graph = _curved_road()
    route = Router(graph=graph).find(RouteRequest(origin="n0", destination="n1"))
    assert len(route.geometry) == 3
    assert route.geometry[1] == LatLon(10.005, 106.005)


def test_stored_edge_geometry_is_reversed_when_travelled_backwards():
    graph = _curved_road()
    route = Router(graph=graph).find(RouteRequest(origin="n1", destination="n0"))
    assert route.geometry[0] == graph.get_node("n1").coordinate
    assert route.geometry[-1] == graph.get_node("n0").coordinate


def test_a_trivial_route_still_has_a_position(router):
    route = router.find(RouteRequest(origin="A", destination="A"))
    assert len(route.geometry) == 1
    assert route.steps[0].maneuver is Maneuver.ARRIVE


# --- Steps -----------------------------------------------------------------


def test_first_step_departs_and_last_step_arrives(router):
    steps = router.find(RouteRequest(origin="A", destination="I")).steps
    assert steps[0].maneuver is Maneuver.DEPART
    assert steps[-1].maneuver is Maneuver.ARRIVE


def test_arrival_step_covers_no_ground(router):
    arrive = router.find(RouteRequest(origin="A", destination="I")).steps[-1]
    assert arrive.distance == 0.0
    assert arrive.travel_time == 0.0
    assert arrive.segments == ()
    assert arrive.from_node == arrive.to_node == "I"


def test_steps_cover_every_segment_exactly_once(router):
    route = router.find(RouteRequest(origin="A", destination="I"))
    covered = [segment for step in route.steps for segment in step.segments]
    assert covered == list(route.segments)


def test_step_distances_sum_to_the_route_distance(router):
    route = router.find(RouteRequest(origin="A", destination="I"))
    assert sum(step.distance for step in route.steps) == pytest.approx(route.distance)


def test_step_travel_times_sum_to_the_route_travel_time(router):
    route = router.find(RouteRequest(origin="A", destination="I"))
    assert sum(step.travel_time for step in route.steps) == pytest.approx(route.travel_time)


def test_steps_are_chained_end_to_end(router):
    steps = router.find(RouteRequest(origin="A", destination="I")).steps
    for earlier, later in zip(steps, steps[1:]):
        assert earlier.to_node == later.from_node


def test_consecutive_segments_of_one_street_merge_into_one_step():
    """Nine junctions of Nguyen Hue is one instruction, not nine."""
    route = Router(graph=_straight_street()).find(
        RouteRequest(origin="n0", destination="n3", cost_mode="shortest")
    )
    assert route.segments == ("e0", "e1", "e2")
    assert [step.maneuver for step in route.steps] == [Maneuver.DEPART, Maneuver.ARRIVE]
    assert route.steps[0].segments == ("e0", "e1", "e2")
    assert route.steps[0].name == "Nguyen Hue"


def test_a_name_change_starts_a_new_step_even_going_straight():
    graph = _straight_street()
    graph.add_node(Node("n4", 10.0, 106.04))
    graph.add_edge(Edge("e3", "n3", "n4", distance=1096, speed=10, name="Le Loi"))
    route = Router(graph=graph).find(RouteRequest(origin="n0", destination="n4", cost_mode="shortest"))
    assert [step.name for step in route.steps] == ["Nguyen Hue", "Le Loi", "Le Loi"]


def test_a_turn_starts_a_new_step(router):
    route = router.find(RouteRequest(origin="A", destination="I"))
    turns = [step.maneuver for step in route.steps if step.maneuver not in (Maneuver.DEPART, Maneuver.ARRIVE)]
    assert turns
    assert all(turn is not Maneuver.CONTINUE for turn in turns)


# --- Manoeuvre classification ----------------------------------------------


def test_a_right_angle_to_the_east_is_a_right_turn():
    """Heading north on the first leg, east on the second."""
    route = Router(graph=_corner(corner_lon=0.01)).find(
        RouteRequest(origin="n0", destination="n2", cost_mode="shortest")
    )
    assert route.steps[1].maneuver is Maneuver.RIGHT


def test_a_right_angle_to_the_west_is_a_left_turn():
    route = Router(graph=_corner(corner_lon=-0.01)).find(
        RouteRequest(origin="n0", destination="n2", cost_mode="shortest")
    )
    assert route.steps[1].maneuver is Maneuver.LEFT


def test_bearings_are_recorded_on_each_step():
    route = Router(graph=_corner(corner_lon=0.01)).find(
        RouteRequest(origin="n0", destination="n2", cost_mode="shortest")
    )
    assert route.steps[0].bearing_before is None
    assert route.steps[0].bearing_after == pytest.approx(0.0, abs=1.0)
    assert route.steps[1].bearing_before == pytest.approx(0.0, abs=1.0)
    assert route.steps[1].bearing_after == pytest.approx(90.0, abs=1.0)
    assert route.steps[-1].bearing_after is None


# --- Fixtures --------------------------------------------------------------


def _straight_street() -> InMemoryRoadGraph:
    graph = InMemoryRoadGraph()
    for index in range(4):
        graph.add_node(Node(f"n{index}", 10.0, 106.0 + index * 0.01))
    for index in range(3):
        graph.add_edge(
            Edge(f"e{index}", f"n{index}", f"n{index + 1}", distance=1096, speed=10, name="Nguyen Hue")
        )
    return graph


def _corner(*, corner_lon: float) -> InMemoryRoadGraph:
    """n0 north to n1, then a right angle to n2."""
    graph = InMemoryRoadGraph()
    graph.add_node(Node("n0", 10.0, 106.0))
    graph.add_node(Node("n1", 10.01, 106.0))
    graph.add_node(Node("n2", 10.01, 106.0 + corner_lon))
    graph.add_edge(Edge("e0", "n0", "n1", distance=1106, speed=10, name="Pasteur"))
    graph.add_edge(Edge("e1", "n1", "n2", distance=1096, speed=10, name="Le Loi"))
    return graph


def _curved_road() -> InMemoryRoadGraph:
    """One edge carrying a three-point shape rather than a straight line."""
    graph = InMemoryRoadGraph()
    graph.add_node(Node("n0", 10.0, 106.0))
    graph.add_node(Node("n1", 10.01, 106.01))
    graph.add_edge(
        Edge(
            "e0",
            "n0",
            "n1",
            distance=2000,
            speed=10,
            name="Ben Van Don",
            geometry=(LatLon(10.0, 106.0), LatLon(10.005, 106.005), LatLon(10.01, 106.01)),
        )
    )
    return graph
