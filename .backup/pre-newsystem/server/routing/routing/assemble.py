"""Turning a settled path into a Route a consumer can actually use.

The search produces edge ids. Nothing downstream wants edge ids: `map` wants
a polyline it can draw without holding road data, `navigation` wants
manoeuvres it can speak, and `eta` wants seconds. Producing all three is this
module's single responsibility.

Two rules shape what comes out. Geometry is carried on the Route, so drawing a
route never requires graph access. And travel time comes from the cost model,
never from the search's cost, so a preference weighting can never leak into a
number presented to the driver as an arrival time.

Inputs:  RoadGraph, an ordered list of edge ids, CostModel, CostContext
Outputs: Route, with geometry, manoeuvre steps, distance and travel time
Not here: the search (routing.search), request validation (routing.router)
"""

from __future__ import annotations

from dataclasses import dataclass

from .costs import CostContext, CostModel
from .geometry import LatLon, initial_bearing, turn_angle
from .graph import RoadGraph
from .models import Edge, Maneuver, Route, RouteStep

#: Turns smaller than this are "carry on", not a manoeuvre worth announcing.
STRAIGHT_DEGREES = 20.0
#: Beyond this a turn is a reversal rather than a sharp corner.
U_TURN_DEGREES = 160.0
SLIGHT_DEGREES = 60.0
SQUARE_DEGREES = 120.0


@dataclass(frozen=True, slots=True)
class _Leg:
    """One traversed edge, oriented in the direction of travel."""

    edge: Edge
    from_node: str
    to_node: str
    distance: float
    travel_time: float
    entry_bearing: float
    exit_bearing: float
    points: tuple[LatLon, ...]


def assemble_route(
    graph: RoadGraph,
    *,
    origin: str,
    edge_ids: list[str],
    cost_model: CostModel,
    context: CostContext,
    total_cost: float,
    cost_mode: str,
    states_settled: int,
) -> Route:
    """Build a Route from an ordered edge path starting at ``origin``."""
    legs = _build_legs(graph, origin=origin, edge_ids=edge_ids, cost_model=cost_model, context=context)
    maneuvers = _classify_maneuvers(legs)
    boundaries = _step_boundaries(legs, maneuvers)
    steps = _build_steps(
        legs, maneuvers=maneuvers, boundaries=boundaries, cost_model=cost_model, context=context
    )

    nodes = (origin,) + tuple(leg.to_node for leg in legs)
    return Route(
        nodes=nodes,
        segments=tuple(leg.edge.id for leg in legs),
        steps=steps,
        geometry=_join_geometry(legs),
        distance=sum(leg.distance for leg in legs),
        travel_time=_total_travel_time(legs, cost_model=cost_model, context=context),
        total_cost=total_cost,
        cost_mode=cost_mode,
        nodes_expanded=states_settled,
    )


def trivial_route(
    graph: RoadGraph, *, node_id: str, cost_mode: str
) -> Route:
    """The route from a node to itself: no movement, but a valid answer."""
    here = graph.get_node(node_id).coordinate
    arrive = RouteStep(
        maneuver=Maneuver.ARRIVE,
        name="",
        segments=(),
        from_node=node_id,
        to_node=node_id,
        distance=0.0,
        travel_time=0.0,
        bearing_before=None,
        bearing_after=None,
        geometry=(here,),
    )
    return Route(
        nodes=(node_id,),
        segments=(),
        steps=(arrive,),
        geometry=(here,),
        distance=0.0,
        travel_time=0.0,
        total_cost=0.0,
        cost_mode=cost_mode,
        nodes_expanded=0,
    )


# --- Internal --------------------------------------------------------------


def _build_legs(
    graph: RoadGraph,
    *,
    origin: str,
    edge_ids: list[str],
    cost_model: CostModel,
    context: CostContext,
) -> list[_Leg]:
    legs: list[_Leg] = []
    node = origin
    for edge_id in edge_ids:
        edge = graph.get_edge(edge_id)
        points = _oriented_points(graph, edge=edge, from_node=node)
        legs.append(
            _Leg(
                edge=edge,
                from_node=node,
                to_node=edge.other_end(node),
                distance=edge.distance,
                travel_time=cost_model.travel_time(edge, context),
                entry_bearing=initial_bearing(points[0], points[1]),
                exit_bearing=initial_bearing(points[-2], points[-1]),
                points=points,
            )
        )
        node = legs[-1].to_node
    return legs


def _oriented_points(graph: RoadGraph, *, edge: Edge, from_node: str) -> tuple[LatLon, ...]:
    """The edge's shape, running in the direction it is being travelled.

    An edge with no stored geometry degrades to the straight line between its
    two junctions, which is what a graph built from bare node coordinates can
    honestly claim.
    """
    points = edge.geometry
    if not points:
        points = (
            graph.get_node(edge.from_node).coordinate,
            graph.get_node(edge.to_node).coordinate,
        )
    if from_node == edge.to_node:
        return tuple(reversed(points))
    return tuple(points)


def _classify_maneuvers(legs: list[_Leg]) -> list[Maneuver]:
    """One manoeuvre per leg: what the driver does to enter it."""
    maneuvers = [Maneuver.DEPART]
    for previous, leg in zip(legs, legs[1:]):
        maneuvers.append(_maneuver_for(turn_angle(previous.exit_bearing, leg.entry_bearing)))
    return maneuvers


def _maneuver_for(angle: float) -> Maneuver:
    magnitude = abs(angle)
    if magnitude <= STRAIGHT_DEGREES:
        return Maneuver.CONTINUE
    if magnitude > U_TURN_DEGREES:
        return Maneuver.U_TURN
    if angle > 0:
        if magnitude <= SLIGHT_DEGREES:
            return Maneuver.SLIGHT_RIGHT
        if magnitude <= SQUARE_DEGREES:
            return Maneuver.RIGHT
        return Maneuver.SHARP_RIGHT
    if magnitude <= SLIGHT_DEGREES:
        return Maneuver.SLIGHT_LEFT
    if magnitude <= SQUARE_DEGREES:
        return Maneuver.LEFT
    return Maneuver.SHARP_LEFT


def _step_boundaries(legs: list[_Leg], maneuvers: list[Maneuver]) -> list[int]:
    """Indices where a new step starts.

    A step ends when the driver has to do something: turn, or move onto a
    differently named road. Running straight on down the same street is one
    instruction however many graph segments it happens to be cut into.
    """
    boundaries = [0]
    for index in range(1, len(legs)):
        if maneuvers[index] is not Maneuver.CONTINUE:
            boundaries.append(index)
            continue
        if legs[index].edge.name != legs[boundaries[-1]].edge.name:
            boundaries.append(index)
    return boundaries


def _build_steps(
    legs: list[_Leg],
    *,
    maneuvers: list[Maneuver],
    boundaries: list[int],
    cost_model: CostModel,
    context: CostContext,
) -> tuple[RouteStep, ...]:
    steps: list[RouteStep] = []
    for position, start in enumerate(boundaries):
        end = boundaries[position + 1] if position + 1 < len(boundaries) else len(legs)
        group = legs[start:end]
        turn_seconds = _turn_seconds(legs, start=start, end=end, cost_model=cost_model, context=context)
        steps.append(
            RouteStep(
                maneuver=maneuvers[start],
                name=group[0].edge.name,
                segments=tuple(leg.edge.id for leg in group),
                from_node=group[0].from_node,
                to_node=group[-1].to_node,
                distance=sum(leg.distance for leg in group),
                travel_time=sum(leg.travel_time for leg in group) + turn_seconds,
                bearing_before=legs[start - 1].exit_bearing if start > 0 else None,
                bearing_after=group[0].entry_bearing,
                geometry=_join_geometry(group),
            )
        )
    steps.append(_arrival_step(legs[-1]))
    return tuple(steps)


def _total_travel_time(
    legs: list[_Leg], *, cost_model: CostModel, context: CostContext
) -> float:
    """The route's travel time: every segment, then every turn, in order.

    Summed independently of the step breakdown, and in an order the contract
    test can reproduce exactly. Regrouping the same numbers by step would give
    an answer differing in the last bits, and the contract promises this
    equals what the cost model says, not that it nearly does.
    """
    total = sum(leg.travel_time for leg in legs)
    return total + _turn_seconds(legs, start=0, end=len(legs), cost_model=cost_model, context=context)


def _turn_seconds(
    legs: list[_Leg], *, start: int, end: int, cost_model: CostModel, context: CostContext
) -> float:
    """Time spent turning, for every junction this step passes through.

    Includes the turn that enters the step, so the seconds a driver spends
    waiting to turn are attributed to the instruction that told them to.
    """
    first = max(start, 1)
    return sum(
        cost_model.turn_time(legs[i - 1].edge, legs[i].from_node, legs[i].edge, context)
        for i in range(first, end)
    )


def _arrival_step(last: _Leg) -> RouteStep:
    return RouteStep(
        maneuver=Maneuver.ARRIVE,
        name=last.edge.name,
        segments=(),
        from_node=last.to_node,
        to_node=last.to_node,
        distance=0.0,
        travel_time=0.0,
        bearing_before=last.exit_bearing,
        bearing_after=None,
        geometry=(last.points[-1],),
    )


def _join_geometry(legs: list[_Leg]) -> tuple[LatLon, ...]:
    """Concatenate leg shapes, dropping the point each leg shares with the last."""
    if not legs:
        return ()
    points = list(legs[0].points)
    for leg in legs[1:]:
        points.extend(leg.points[1:])
    return tuple(points)
