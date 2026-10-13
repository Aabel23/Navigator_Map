"""Graphs the tests and the benchmark run against.

These live under `tests/` rather than in a `sandbox/` directory because the
test suite is part of what the block promises: production must never import
sandbox code, and a test that does is a production dependency wearing a
disguise. Nothing in `routing/` imports anything from here.
"""

from .grid import random_grid_graph
from .sample_graph import small_town_graph, town_with_turn_restrictions

__all__ = ["random_grid_graph", "small_town_graph", "town_with_turn_restrictions"]
