"""Unit tests for the request-time constraint overlay."""

from routing import (
    Edge,
    RouteConstraints,
    avoid_edges,
    avoid_nodes,
    avoid_road_classes,
    avoid_tolls,
    max_metadata_value,
)


def make_edge(**overrides):
    defaults = dict(
        id="e1", from_node="A", to_node="B", distance=10.0, speed=5.0, road_class="residential"
    )
    defaults.update(overrides)
    return Edge(**defaults)


def test_empty_constraints_allow_everything():
    assert RouteConstraints().allows(make_edge())


def test_blocked_edge_id_is_rejected():
    edge = make_edge()
    assert not RouteConstraints(blocked_edges=frozenset({edge.id})).allows(edge)


def test_blocked_node_rejects_every_edge_touching_it():
    edge = make_edge(from_node="A", to_node="B")
    assert not RouteConstraints(blocked_nodes=frozenset({"B"})).allows(edge)
    assert not RouteConstraints(blocked_nodes=frozenset({"A"})).allows(edge)


def test_avoid_edges_helper():
    edge = make_edge()
    assert not avoid_edges({edge.id})(edge)
    assert avoid_edges({"other"})(edge)


def test_avoid_nodes_helper():
    edge = make_edge(from_node="A", to_node="B")
    assert not avoid_nodes({"A"})(edge)
    assert not avoid_nodes({"B"})(edge)
    assert avoid_nodes({"Z"})(edge)


def test_avoid_road_classes_helper():
    assert not avoid_road_classes({"unpaved"})(make_edge(road_class="unpaved"))
    assert avoid_road_classes({"highway"})(make_edge(road_class="unpaved"))


def test_max_metadata_value_helper():
    rule = max_metadata_value("toll_usd", 0)
    assert not rule(make_edge(metadata={"toll_usd": 5.0}))
    assert rule(make_edge(metadata={"toll_usd": 0.0}))


def test_max_metadata_value_allows_a_missing_key():
    """Absence of a toll is not a toll."""
    assert max_metadata_value("toll_usd", 0)(make_edge())


def test_avoid_tolls_reads_either_flag_or_fare():
    rule = avoid_tolls()
    assert not rule(make_edge(metadata={"toll": True}))
    assert not rule(make_edge(metadata={"toll_usd": 2.5}))
    assert rule(make_edge(metadata={"toll_usd": 0.0}))
    assert rule(make_edge())


def test_multiple_rules_are_anded():
    constraints = RouteConstraints(
        rules=(avoid_road_classes({"highway"}), avoid_road_classes({"unpaved"}))
    )
    assert not constraints.allows(make_edge(road_class="unpaved"))
    assert constraints.allows(make_edge(road_class="residential"))


def test_with_blocked_edge_returns_a_new_instance():
    original = RouteConstraints()
    updated = original.with_blocked_edge("e1")
    assert "e1" not in original.blocked_edges
    assert "e1" in updated.blocked_edges


def test_with_blocked_edge_keeps_the_other_rules():
    original = RouteConstraints(
        blocked_nodes=frozenset({"X"}), rules=(avoid_road_classes({"unpaved"}),)
    )
    updated = original.with_blocked_edge("e1")
    assert updated.blocked_nodes == frozenset({"X"})
    assert len(updated.rules) == 1
