"""The search itself: A*, generalized to Dijkstra by a zero heuristic.

This is the only module that runs an algorithm. It knows nothing about where
the graph's data came from (:mod:`routing.graph`'s contract), nothing about
what an edge is worth beyond asking a :class:`~routing.costs.CostModel`, and
nothing about how a path becomes a drawable route (:mod:`routing.assemble`).

A search state is a ``(via_edge, node)`` pair, not a bare node. That is what
makes turn restrictions expressible at all: whether leaving a junction into a
given street is legal depends on the street you arrived by, so the arrival
edge has to be part of the state. The cost is roughly one state per directed
edge instead of one per node.

Inputs:  RoadGraph, CostModel, CostContext, RouteConstraints, a heuristic
Outputs: SearchResult -- predecessors, costs, and the settled goal states
Not here: request validation (routing.router), Route construction
    (routing.assemble)
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from typing import Iterable

from .constraints import RouteConstraints
from .costs import CostContext, CostModel
from .graph import RoadGraph
from .heuristics import Heuristic
from .models import Edge

#: ``(id of the edge arrived by, node)``. The origin's state has no edge.
State = tuple[str | None, str]

INFINITY = float("inf")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """What one search run produced.

    Attributes:
        came_from: State to the state it was first reached most cheaply from.
        cost_so_far: Best known cost to each state.
        settled_goals: Goal node id to the settled state that reached it
            cheapest. A goal absent from this map was not reachable.
        states_settled: How many states were popped and finalized. A
            benchmark signal; it is the A*-versus-Dijkstra difference made
            visible.
    """

    came_from: dict[State, State]
    cost_so_far: dict[State, float]
    settled_goals: dict[str, State]
    states_settled: int


def astar(
    graph: RoadGraph,
    *,
    origin: str,
    goals: Iterable[str],
    cost_model: CostModel,
    context: CostContext,
    constraints: RouteConstraints,
    heuristic: Heuristic,
    allow_u_turns: bool = False,
) -> SearchResult:
    """Search from ``origin`` until every goal is settled or the frontier empties.

    Ties on priority are broken by insertion order through a monotonic
    counter, which keeps the result deterministic and avoids ever comparing
    two node ids against each other.

    With more than one goal the caller must pass
    :func:`~routing.heuristics.zero_heuristic`: a heuristic aimed at one goal
    says nothing useful about the others, and settling states once under it
    would return wrong answers for the rest.
    """
    remaining = set(goals)
    counter = itertools.count()
    start: State = (None, origin)

    frontier: list[tuple[float, int, State]] = [(heuristic(origin), next(counter), start)]
    cost_so_far: dict[State, float] = {start: 0.0}
    came_from: dict[State, State] = {}
    settled: set[State] = set()
    settled_goals: dict[str, State] = {}

    while frontier and remaining:
        _, _, current = heapq.heappop(frontier)
        if current in settled:
            continue
        settled.add(current)

        via_edge_id, node = current
        if node in remaining:
            settled_goals[node] = current
            remaining.discard(node)
            if not remaining:
                break

        via_edge = graph.get_edge(via_edge_id) if via_edge_id is not None else None
        outgoing = list(graph.get_outgoing_edges(node))
        is_dead_end = len(outgoing) == 1
        current_cost = cost_so_far[current]

        for edge in outgoing:
            if not _may_traverse(
                graph,
                edge=edge,
                node=node,
                via_edge=via_edge,
                constraints=constraints,
                allow_u_turns=allow_u_turns,
                is_dead_end=is_dead_end,
            ):
                continue

            next_state: State = (edge.id, edge.other_end(node))
            if next_state in settled:
                continue

            step = _step_cost(cost_model, edge=edge, node=node, via_edge=via_edge, context=context)
            if step == INFINITY:
                continue

            new_cost = current_cost + step
            if new_cost >= cost_so_far.get(next_state, INFINITY):
                continue

            cost_so_far[next_state] = new_cost
            came_from[next_state] = current
            priority = new_cost + heuristic(next_state[1])
            heapq.heappush(frontier, (priority, next(counter), next_state))

    return SearchResult(
        came_from=came_from,
        cost_so_far=cost_so_far,
        settled_goals=settled_goals,
        states_settled=len(settled),
    )


def path_to_edges(result: SearchResult, goal_state: State) -> list[str]:
    """Walk ``came_from`` back from a settled goal state; return edge ids in order."""
    edge_ids: list[str] = []
    current = goal_state
    while current in result.came_from:
        edge_ids.append(current[0])  # the edge arrived by; never None off the origin
        current = result.came_from[current]
    edge_ids.reverse()
    return edge_ids


# --- Internal --------------------------------------------------------------


def _may_traverse(
    graph: RoadGraph,
    *,
    edge: Edge,
    node: str,
    via_edge: Edge | None,
    constraints: RouteConstraints,
    allow_u_turns: bool,
    is_dead_end: bool,
) -> bool:
    """Whether leaving ``node`` by ``edge``, having arrived by ``via_edge``, is legal.

    Ordered cheapest check first. A dead end is exempt from the U-turn rule
    because turning around there is not a manoeuvre the driver chose.
    """
    if not constraints.allows(edge):
        return False
    if via_edge is None:
        return True
    if edge.id == via_edge.id and not allow_u_turns and not is_dead_end:
        return False
    return graph.is_turn_allowed(via_edge.id, node, edge.id)


def _step_cost(
    cost_model: CostModel,
    *,
    edge: Edge,
    node: str,
    via_edge: Edge | None,
    context: CostContext,
) -> float:
    """Edge cost plus, when there is one, the cost of the turn onto it."""
    cost = cost_model.edge_cost(edge, context)
    if cost == INFINITY or via_edge is None:
        return cost
    return cost + cost_model.turn_cost(via_edge, node, edge, context)
