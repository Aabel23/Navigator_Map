"""Block tests for the RoadGraph interface and its in-memory implementation."""

import pytest

from routing import (
    Access,
    Direction,
    Edge,
    InMemoryRoadGraph,
    Node,
    TurnKind,
    TurnRestriction,
    UnknownEdge,
    UnknownNode,
)


def make_graph() -> InMemoryRoadGraph:
    graph = InMemoryRoadGraph()
    graph.add_node(Node("A", 0.0, 0.0))
    graph.add_node(Node("B", 0.0, 0.01))
    graph.add_node(Node("C", 0.0, 0.02))
    graph.add_edge(Edge("AB", "A", "B", distance=1100, speed=10))
    graph.add_edge(Edge("BC", "B", "C", distance=1100, speed=20, direction=Direction.ONE_WAY))
    return graph


# --- Lookups ---------------------------------------------------------------


def test_get_node_and_edge():
    graph = make_graph()
    assert graph.get_node("A").id == "A"
    assert graph.get_edge("AB").id == "AB"


def test_unknown_node_raises():
    with pytest.raises(UnknownNode):
        make_graph().get_node("Z")


def test_unknown_edge_raises():
    with pytest.raises(UnknownEdge):
        make_graph().get_edge("ZZ")


def test_has_node():
    graph = make_graph()
    assert graph.has_node("A")
    assert not graph.has_node("Z")


def test_len_reports_node_count():
    assert len(make_graph()) == 3


def test_max_speed_is_the_fastest_edge():
    assert make_graph().max_speed() == 20


def test_max_speed_of_an_edgeless_graph_raises():
    graph = InMemoryRoadGraph()
    graph.add_node(Node("A", 0.0, 0.0))
    with pytest.raises(ValueError):
        graph.max_speed()


def test_max_speed_is_recomputed_after_an_edge_is_added():
    graph = make_graph()
    assert graph.max_speed() == 20
    graph.add_edge(Edge("AC", "A", "C", distance=2200, speed=30))
    assert graph.max_speed() == 30


# --- Direction -------------------------------------------------------------


def test_bidirectional_edge_traversable_both_ways():
    graph = make_graph()
    assert "B" in set(graph.get_neighbors("A"))
    assert "A" in set(graph.get_neighbors("B"))


def test_one_way_edge_only_forward():
    graph = make_graph()
    assert "C" in set(graph.get_neighbors("B"))
    assert "B" not in set(graph.get_neighbors("C"))


def test_get_edge_between_respects_direction():
    graph = make_graph()
    assert graph.get_edge_between("A", "B").id == "AB"
    assert graph.get_edge_between("C", "B") is None


def test_blocked_edge_is_still_returned_by_the_graph():
    """Whether a closure applies to this request is the cost model's call."""
    graph = InMemoryRoadGraph()
    graph.add_node(Node("A", 0.0, 0.0))
    graph.add_node(Node("B", 0.0, 0.01))
    graph.add_edge(Edge("AB", "A", "B", distance=1100, speed=10, access=Access.BLOCKED))
    edges = list(graph.get_outgoing_edges("A"))
    assert len(edges) == 1
    assert edges[0].access is Access.BLOCKED


# --- Construction guards ---------------------------------------------------


def test_adding_an_edge_with_an_unknown_node_raises():
    graph = InMemoryRoadGraph()
    graph.add_node(Node("A", 0.0, 0.0))
    with pytest.raises(UnknownNode):
        graph.add_edge(Edge("AB", "A", "B", distance=1, speed=1))


def test_duplicate_edge_id_is_rejected():
    """Overwriting would strand the old endpoints' adjacency entries."""
    graph = make_graph()
    with pytest.raises(ValueError, match="duplicate edge id"):
        graph.add_edge(Edge("AB", "A", "C", distance=2200, speed=10))


def test_a_rejected_duplicate_leaves_the_graph_intact():
    graph = make_graph()
    with pytest.raises(ValueError):
        graph.add_edge(Edge("AB", "A", "C", distance=2200, speed=10))
    assert sorted(graph.get_neighbors("A")) == ["B"]
    assert sorted(graph.get_neighbors("B")) == ["A", "C"]


# --- Turn restrictions -----------------------------------------------------


def test_a_graph_without_turn_data_allows_every_turn():
    graph = make_graph()
    assert graph.is_turn_allowed("AB", "B", "BC")


def test_prohibited_turn_is_refused():
    graph = make_graph()
    graph.add_turn_restriction(TurnRestriction("AB", "B", "BC", TurnKind.PROHIBITED))
    assert not graph.is_turn_allowed("AB", "B", "BC")


def test_a_prohibition_only_binds_its_own_from_edge():
    graph = make_graph()
    graph.add_turn_restriction(TurnRestriction("AB", "B", "BC", TurnKind.PROHIBITED))
    assert graph.is_turn_allowed("BC", "B", "AB")


def test_mandatory_turn_forbids_every_other_exit():
    graph = make_graph()
    graph.add_node(Node("D", 0.01, 0.01))
    graph.add_edge(Edge("BD", "B", "D", distance=1100, speed=10))
    graph.add_turn_restriction(TurnRestriction("AB", "B", "BC", TurnKind.MANDATORY))
    assert graph.is_turn_allowed("AB", "B", "BC")
    assert not graph.is_turn_allowed("AB", "B", "BD")


def test_turn_restriction_naming_an_unknown_edge_raises():
    graph = make_graph()
    with pytest.raises(UnknownEdge):
        graph.add_turn_restriction(TurnRestriction("AB", "B", "ZZ"))


def test_turn_restriction_through_an_unrelated_node_raises():
    graph = make_graph()
    with pytest.raises(ValueError, match="does not touch"):
        graph.add_turn_restriction(TurnRestriction("AB", "C", "BC"))


def test_get_turn_restrictions_reports_what_was_added():
    graph = make_graph()
    restriction = TurnRestriction("AB", "B", "BC", TurnKind.PROHIBITED)
    graph.add_turn_restriction(restriction)
    assert list(graph.get_turn_restrictions("B")) == [restriction]
    assert list(graph.get_turn_restrictions("A")) == []


def test_indexed_and_default_turn_logic_agree():
    """InMemoryRoadGraph overrides is_turn_allowed for speed; it must not diverge."""
    from routing.graph import RoadGraph

    graph = make_graph()
    graph.add_turn_restriction(TurnRestriction("AB", "B", "BC", TurnKind.PROHIBITED))
    assert RoadGraph.is_turn_allowed(graph, "AB", "B", "BC") is graph.is_turn_allowed("AB", "B", "BC")
    assert RoadGraph.is_turn_allowed(graph, "BC", "B", "AB") is graph.is_turn_allowed("BC", "B", "AB")
