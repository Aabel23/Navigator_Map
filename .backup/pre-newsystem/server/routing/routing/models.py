"""The data model the whole block is built around.

Everything here is a frozen dataclass. None of it knows about HTTP, Flask,
MapLibre, or a storage backend; that separation is what lets the same types
serve a web endpoint, a benchmark, and a test.

Inputs:  Node, Edge, TurnRestriction -- supplied by a RoadGraph implementation
Outputs: Route, RouteStep -- returned by Router.find
Not here: cost (see routing.costs), request-time rules (routing.constraints)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .geometry import LatLon

# --- Road facts ------------------------------------------------------------


class Direction(str, Enum):
    """Whether an edge can be traversed one way or both ways."""

    ONE_WAY = "one_way"
    BIDIRECTIONAL = "bidirectional"


class Access(str, Enum):
    """Whether an edge is currently usable at all."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"


class TurnKind(str, Enum):
    """How a :class:`TurnRestriction` constrains movement through a node.

    Attributes:
        PROHIBITED: this turn may not be taken (OSM ``no_left_turn`` and
            friends).
        MANDATORY: this ``from_edge`` may ONLY continue into a ``to_edge``
            named by a mandatory restriction (OSM ``only_straight_on`` and
            friends). Several mandatory entries sharing a ``from_edge`` read
            as the full set of permitted exits.
    """

    PROHIBITED = "prohibited"
    MANDATORY = "mandatory"


@dataclass(frozen=True, slots=True)
class Node:
    """A junction in the road network.

    Attributes:
        id: Stable identifier, unique within a graph.
        latitude: Degrees, WGS84.
        longitude: Degrees, WGS84.
    """

    id: str
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        # Constructed for its range check; the value is deliberately discarded.
        LatLon(self.latitude, self.longitude)

    @property
    def coordinate(self) -> LatLon:
        return LatLon(self.latitude, self.longitude)


@dataclass(frozen=True, slots=True)
class Edge:
    """A road segment between two distinct nodes.

    A physically bidirectional street is one ``Edge`` with
    ``direction=Direction.BIDIRECTIONAL``; the graph exposes it as traversable
    from either endpoint. A one-way street is one ``Edge`` traversable only
    from ``from_node`` to ``to_node``.

    Attributes:
        id: Stable identifier, unique within a graph.
        from_node: Id of the node this edge starts at.
        to_node: Id of the node this edge ends at. Must differ from
            ``from_node``: a segment from a junction to itself has no routing
            meaning, and admitting one corrupts the adjacency index.
        distance: Length in meters. Must be non-negative.
        speed: Free-flow speed in meters/second. Must be positive.
        road_class: ``"highway"``, ``"residential"``, ``"unpaved"``, and so on.
            Cost models and vehicle profiles key off this.
        name: Street name. Used to decide where one manoeuvre ends and the
            next begins. Empty when unknown.
        direction: One-way or bidirectional.
        access: Whether the edge is currently usable.
        geometry: The segment's shape from ``from_node`` to ``to_node``,
            endpoints included. Empty means "a straight line between the two
            nodes", which :mod:`routing.assemble` substitutes. Carrying the
            real polyline here is what lets a Route be drawn without the
            consumer ever touching the graph.
        metadata: Anything a cost model or constraint might want (surface,
            tolls, lanes). The search never reads it.
    """

    id: str
    from_node: str
    to_node: str
    distance: float
    speed: float
    road_class: str = "unclassified"
    name: str = ""
    direction: Direction = Direction.BIDIRECTIONAL
    access: Access = Access.ALLOWED
    geometry: tuple[LatLon, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.from_node == self.to_node:
            raise ValueError(f"edge {self.id!r} is a self-loop at {self.from_node!r}")
        if self.distance < 0:
            raise ValueError(f"edge {self.id!r} has negative distance {self.distance!r}")
        if self.speed <= 0:
            raise ValueError(f"edge {self.id!r} has non-positive speed {self.speed!r}")
        if self.geometry and len(self.geometry) < 2:
            raise ValueError(f"edge {self.id!r} has a one-point geometry")

    @property
    def free_flow_seconds(self) -> float:
        """Travel time at ``speed``, before any profile or dynamic cost."""
        return self.distance / self.speed

    def other_end(self, node_id: str) -> str:
        """Return the endpoint of this edge that is not ``node_id``."""
        if node_id == self.from_node:
            return self.to_node
        if node_id == self.to_node:
            return self.from_node
        raise ValueError(f"edge {self.id!r} does not touch node {node_id!r}")


@dataclass(frozen=True, slots=True)
class TurnRestriction:
    """A rule about moving from one edge to another through a shared node.

    Modelled on the OSM ``restriction`` relation, which is the only form this
    data realistically arrives in. The graph reports these; the search obeys
    them.

    Attributes:
        from_edge: Id of the edge being left.
        via_node: Id of the node both edges touch.
        to_edge: Id of the edge being entered.
        kind: Prohibited or mandatory, see :class:`TurnKind`.
    """

    from_edge: str
    via_node: str
    to_edge: str
    kind: TurnKind = TurnKind.PROHIBITED


# --- Request ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """Everything needed to ask for one route.

    Endpoints are node ids, not coordinates: turning a GPS fix into a node is
    the `map_matching` block's responsibility, and duplicating it here would
    give the system two places to disagree about where the driver is.

    Attributes:
        origin: Node id to start from.
        destination: Node id to reach.
        profile: A :class:`routing.costs.VehicleProfile`, or the name of a
            built-in one.
        cost_mode: A :class:`routing.costs.CostMode`, or its value.
        departure: Timezone-aware start time, handed to the cost model
            unchanged so time-dependent costs are possible. ``None`` means
            unspecified; a naive datetime is rejected rather than guessed at.
        constraints: A :class:`routing.constraints.RouteConstraints` applying
            to this request only, or ``None``.
        allow_u_turns: Whether the route may reverse along the edge it arrived
            on. Off by default; a dead end is always exempt, because leaving
            one is not a choice.
        use_astar: A* with an internally built heuristic (default), or plain
            Dijkstra. Dijkstra is slower but has no heuristic to get wrong,
            which makes it the ground truth in tests and benchmarks.
    """

    origin: str
    destination: str
    profile: Any = "car"
    cost_mode: Any = "fastest"
    departure: datetime | None = None
    constraints: Any = None
    allow_u_turns: bool = False
    use_astar: bool = True


# --- Result ----------------------------------------------------------------


class Maneuver(str, Enum):
    """What the driver does at the start of a :class:`RouteStep`."""

    DEPART = "depart"
    CONTINUE = "continue"
    SLIGHT_LEFT = "slight_left"
    LEFT = "left"
    SHARP_LEFT = "sharp_left"
    SLIGHT_RIGHT = "slight_right"
    RIGHT = "right"
    SHARP_RIGHT = "sharp_right"
    U_TURN = "u_turn"
    ARRIVE = "arrive"


@dataclass(frozen=True, slots=True)
class RouteStep:
    """One manoeuvre and the stretch of road that follows it.

    A step is not one edge. Consecutive edges carrying the same name and
    entered straight-on are merged, so a step is what a driver would be told
    once, rather than once per graph segment.

    Attributes:
        maneuver: The action taken to enter this step.
        name: Street name for the stretch, empty when unknown.
        segments: Edge ids covered, in traversal order.
        from_node: Node the step starts at.
        to_node: Node the step ends at.
        distance: Meters covered by this step.
        travel_time: Seconds, as reported by the cost model.
        bearing_before: Compass bearing on arrival at ``from_node``; ``None``
            for the departing step.
        bearing_after: Compass bearing on leaving ``from_node``; ``None`` for
            the arrival step.
        geometry: Drawable shape of this step.
    """

    maneuver: Maneuver
    name: str
    segments: tuple[str, ...]
    from_node: str
    to_node: str
    distance: float
    travel_time: float
    bearing_before: float | None
    bearing_after: float | None
    geometry: tuple[LatLon, ...]


@dataclass(frozen=True, slots=True)
class Route:
    """The result of a successful :meth:`routing.router.Router.find`.

    Attributes:
        nodes: Node ids visited, in order, origin and destination included.
        segments: Edge ids traversed, in order.
        steps: Manoeuvre-level breakdown, for guidance.
        geometry: The whole route's drawable shape. Present so that drawing a
            route needs no graph access at all -- this one field is what keeps
            `map` independent of road data.
        distance: Meters.
        travel_time: Seconds, summed from the cost model. This is the number
            an ETA is built from; it is real time, never preference-weighted.
        total_cost: What the search minimized, in the cost mode's own unit.
            Equals ``travel_time`` only when nothing penalized or scaled it.
        cost_mode: The mode that produced this route, echoed back.
        nodes_expanded: Search states settled. A benchmark signal, nothing more.
    """

    nodes: tuple[str, ...]
    segments: tuple[str, ...]
    steps: tuple[RouteStep, ...]
    geometry: tuple[LatLon, ...]
    distance: float
    travel_time: float
    total_cost: float
    cost_mode: str
    nodes_expanded: int

    @property
    def edge_count(self) -> int:
        return len(self.segments)
