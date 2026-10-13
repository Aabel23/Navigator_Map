"""Admissible A* heuristics, built from node coordinates.

Internal to the block. The router builds the heuristic itself and never lets a
caller supply one, because a heuristic that does not match the active cost
mode silently returns a worse route rather than an error -- a distance bound
in meters used against a cost measured in seconds will happily overestimate by
three orders of magnitude, and nothing downstream can tell.

Both builders return a heuristic that is not merely admissible but
*consistent*: a great-circle metric, optionally divided by a positive
constant, satisfies the triangle inequality. The search settles each state
once and never reopens it, which admissibility alone would not justify.

Main functions:
    build_heuristic   pick and bind the right heuristic for a request
    zero_heuristic    the trivial bound; turns A* into Dijkstra
"""

from __future__ import annotations

from typing import Callable

from .costs import CostMode, VehicleProfile
from .geometry import haversine_degrees
from .graph import RoadGraph

#: A lower bound on the remaining cost from a node to the goal bound into the
#: closure. Taking only a node id keeps the hot loop free of lookups the
#: builder has already done.
Heuristic = Callable[[str], float]


def zero_heuristic(node_id: str) -> float:
    """The trivial admissible bound; makes A* behave exactly like Dijkstra."""
    return 0.0


def build_heuristic(
    graph: RoadGraph,
    *,
    mode: CostMode,
    profile: VehicleProfile,
    goal_id: str,
) -> Heuristic:
    """Return a consistent heuristic toward ``goal_id`` for this mode.

    For :data:`~routing.costs.CostMode.SHORTEST`, straight-line distance: a
    road can never be shorter than the great-circle line, and road class
    penalties are constrained to be at least 1.0, so the bound holds.

    For :data:`~routing.costs.CostMode.FASTEST`, straight-line distance over
    the fastest speed anything in the graph could travel under this profile.
    No real route beats a straight line driven at top speed.

    Raises:
        ValueError: if the graph has no edges, so no speed bound exists.
    """
    goal = graph.get_node(goal_id)
    goal_latitude, goal_longitude = goal.latitude, goal.longitude
    get_node = graph.get_node

    # One entry per node the search touches. Because a search state is
    # (via_edge, node), a single junction is pushed once per road leading into
    # it, and the bound is identical every time -- on a road network that is
    # three or four haversines where one will do. The cache lives and dies
    # with the request.
    cache: dict[str, float] = {}

    scale = 1.0
    if mode is not CostMode.SHORTEST:
        scale = graph.max_speed() * profile.speed_factor

    def bound(node_id: str) -> float:
        cached = cache.get(node_id)
        if cached is not None:
            return cached
        node = get_node(node_id)
        value = (
            haversine_degrees(node.latitude, node.longitude, goal_latitude, goal_longitude)
            / scale
        )
        cache[node_id] = value
        return value

    return bound
