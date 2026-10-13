"""Tests for the benchmark harness and the synthetic graphs it runs on.

Small sizes only. This asserts the harness reports honest numbers; measuring
performance is what running it by hand is for.
"""

import pytest

from routing.bench.benchmark import format_results, run_benchmark

from .fixtures import random_grid_graph


# --- Synthetic graphs ------------------------------------------------------


def test_grid_has_the_expected_node_count():
    assert len(random_grid_graph(4, 5, seed=1)) == 20


def test_grid_defaults_to_square():
    assert len(random_grid_graph(6, seed=1)) == 36


def test_grid_is_reproducible_for_one_seed():
    first = random_grid_graph(5, seed=7)
    second = random_grid_graph(5, seed=7)
    assert _signature(first) == _signature(second)


def test_different_seeds_give_different_graphs():
    assert _signature(random_grid_graph(8, seed=1)) != _signature(random_grid_graph(8, seed=2))


def test_grid_distances_match_its_coordinates():
    """A distance shorter than the straight line would break the heuristic."""
    from routing.geometry import haversine_m

    graph = random_grid_graph(6, seed=3)
    for edge in graph.edges():
        straight = haversine_m(
            graph.get_node(edge.from_node).coordinate, graph.get_node(edge.to_node).coordinate
        )
        assert edge.distance >= straight - 1e-6


# --- Harness ---------------------------------------------------------------


def test_benchmark_reports_every_size():
    results = run_benchmark([4, 6], repeats=2, seed=1)
    assert {result.grid_size for result in results} == {"4x4", "6x6"}


def test_benchmark_covers_both_algorithms():
    results = run_benchmark([5], repeats=2, seed=1)
    assert {result.algorithm for result in results} == {"dijkstra", "astar"}


def test_benchmark_fields_are_sane():
    for result in run_benchmark([5], repeats=2, seed=1):
        assert result.node_count == 25
        assert result.mean_seconds >= 0
        assert result.trials <= 2


def test_astar_settles_no_more_states_than_dijkstra():
    results = {r.algorithm: r for r in run_benchmark([20], repeats=1, seed=9)}
    if results["astar"].trials == 0 or results["dijkstra"].trials == 0:
        pytest.skip("this grid's corners were disconnected by its random closures")
    assert results["astar"].mean_states_settled <= results["dijkstra"].mean_states_settled


def test_results_format_as_a_table():
    rendered = format_results(run_benchmark([4], repeats=1, seed=1))
    assert "algorithm" in rendered
    assert "astar" in rendered


def _signature(graph):
    return sorted((e.id, e.from_node, e.to_node, e.road_class, e.direction) for e in graph.edges())
