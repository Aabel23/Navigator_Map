"""Unit tests for the data model's own guarantees.

Most of these are rejections. Every one of them is a fact that, admitted into
a graph, would surface much later as a wrong route or an error from somewhere
unrelated -- so the model refuses it at construction, where the traceback
still points at the cause.
"""

import pytest

from routing import Direction, Edge, LatLon, Node


def make_edge(**overrides):
    defaults = dict(id="e1", from_node="A", to_node="B", distance=100.0, speed=10.0)
    defaults.update(overrides)
    return Edge(**defaults)


def test_node_exposes_its_coordinate():
    assert Node("A", 10.5, 106.5).coordinate == LatLon(10.5, 106.5)


def test_node_rejects_an_impossible_coordinate():
    with pytest.raises(ValueError):
        Node("A", 100.0, 0.0)


def test_edge_rejects_a_self_loop():
    """A segment from a junction to itself has no routing meaning."""
    with pytest.raises(ValueError, match="self-loop"):
        make_edge(from_node="A", to_node="A")


def test_edge_rejects_negative_distance():
    with pytest.raises(ValueError):
        make_edge(distance=-1.0)


def test_edge_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        make_edge(speed=0.0)


def test_edge_rejects_a_one_point_geometry():
    with pytest.raises(ValueError):
        make_edge(geometry=(LatLon(0.0, 0.0),))


def test_edge_accepts_an_empty_geometry():
    """Empty means "a straight line between the nodes", not "invalid"."""
    assert make_edge(geometry=()).geometry == ()


def test_free_flow_seconds_is_distance_over_speed():
    assert make_edge(distance=100.0, speed=10.0).free_flow_seconds == pytest.approx(10.0)


def test_other_end_returns_the_far_node():
    edge = make_edge()
    assert edge.other_end("A") == "B"
    assert edge.other_end("B") == "A"


def test_other_end_rejects_a_node_the_edge_does_not_touch():
    with pytest.raises(ValueError):
        make_edge().other_end("Z")


def test_edges_are_frozen():
    with pytest.raises(Exception):
        make_edge().distance = 5.0


def test_default_direction_is_bidirectional():
    assert make_edge().direction is Direction.BIDIRECTIONAL
