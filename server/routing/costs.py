"""What an edge, and a turn, cost for a given vehicle at a given moment.

Cost is kept out of the graph on purpose: the graph says what the road *is*
(distance, speed, class); a :class:`CostModel` says what that means for this
trip right now. That split is what lets ``cost_mode``, a vehicle profile, and
live traffic vary per request without the graph data changing at all.

Inputs:  Edge, TurnRestriction context, CostContext (profile + departure)
Outputs: a cost in the mode's unit, and a travel time in seconds
Not here: the search itself (routing.search), request-only rules
    (routing.constraints)

Admissibility note
------------------
A* needs the heuristic never to overestimate. The router builds that heuristic
itself from the graph's fastest edge and the profile's speed factor, so every
cost model shipped here is required to stay at or above that optimum -- which
is why ``speed_factor`` must be positive, and why penalties and multipliers
must be at least 1.0. A model that cannot promise this sets
``admits_astar = False`` and the router quietly uses Dijkstra instead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Mapping

from .errors import InvalidRequest
from .models import Access, Edge

# --- Modes and profiles ----------------------------------------------------


class CostMode(str, Enum):
    """Built-in optimization goals.

    Attributes:
        FASTEST: Minimize travel time. Costs are seconds.
        SHORTEST: Minimize distance. Costs are meters.
    """

    FASTEST = "fastest"
    SHORTEST = "shortest"


@dataclass(frozen=True, slots=True)
class VehicleProfile:
    """How a kind of vehicle experiences the road network.

    Attributes:
        name: Identifier, e.g. ``"car"``, ``"truck"``, ``"motorbike"``.
        allowed_road_classes: Road classes this vehicle may use. ``None``
            means no restriction.
        speed_factor: Multiplier on an edge's posted speed. Must be positive.
        road_class_penalties: Extra multiplier per road class, applied to
            cost but never to travel time -- ``2.0`` for ``"unpaved"`` makes
            an unpaved segment *feel* twice as expensive without claiming the
            drive takes twice as long. Each value must be at least 1.0, so the
            router's heuristic stays a lower bound.
    """

    name: str
    allowed_road_classes: frozenset[str] | None = None
    speed_factor: float = 1.0
    road_class_penalties: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.speed_factor <= 0:
            raise ValueError(f"profile {self.name!r} has non-positive speed_factor")
        for road_class, penalty in self.road_class_penalties.items():
            if penalty < 1.0:
                raise ValueError(
                    f"profile {self.name!r} penalty for {road_class!r} is {penalty!r}; "
                    "penalties below 1.0 would make the A* heuristic inadmissible"
                )

    def may_use(self, edge: Edge) -> bool:
        if self.allowed_road_classes is None:
            return True
        return edge.road_class in self.allowed_road_classes

    def effective_speed(self, edge: Edge) -> float:
        return edge.speed * self.speed_factor

    def penalty_for(self, edge: Edge) -> float:
        return self.road_class_penalties.get(edge.road_class, 1.0)


#: A small built-in catalog. Callers are free to construct their own profile
#: instead; nothing here is privileged.
VEHICLE_PROFILES: dict[str, VehicleProfile] = {
    "car": VehicleProfile(name="car"),
    "motorbike": VehicleProfile(
        name="motorbike",
        speed_factor=0.85,
        road_class_penalties={"highway": 1.5},
    ),
    "truck": VehicleProfile(
        name="truck",
        allowed_road_classes=frozenset(
            {"highway", "primary", "secondary", "residential", "service"}
        ),
        speed_factor=0.9,
        road_class_penalties={"residential": 1.2, "unpaved": 3.0},
    ),
    "bike": VehicleProfile(
        name="bike",
        allowed_road_classes=frozenset(
            {"residential", "cycleway", "path", "service", "secondary"}
        ),
        speed_factor=0.15,
    ),
}


def get_vehicle_profile(name: str) -> VehicleProfile:
    """Look up a built-in profile by name.

    Raises:
        InvalidRequest: if ``name`` is not a built-in profile. Deliberately a
            routing error rather than a ``KeyError``, so that nothing outside
            this block's error hierarchy escapes a routing call.
    """
    try:
        return VEHICLE_PROFILES[name]
    except KeyError:
        raise InvalidRequest(
            f"unknown vehicle profile {name!r}; known profiles: {sorted(VEHICLE_PROFILES)}"
        ) from None


@dataclass(frozen=True, slots=True)
class CostContext:
    """Everything a cost model is told about the trip, besides the edge itself.

    Passed as one object rather than as widening argument lists, so adding a
    future input (weather, load, a driver preference) does not change every
    :class:`CostModel` signature in existence.

    Attributes:
        profile: The vehicle this route is for.
        departure: Timezone-aware start time, or ``None`` when unspecified.
            Time-dependent models key off this; the router never interprets it.
    """

    profile: VehicleProfile
    departure: datetime | None = None


# --- Cost models -----------------------------------------------------------


class CostModel(ABC):
    """Decides what one edge, and one turn, cost.

    The search asks this once per edge relaxation and once per turn; it never
    inspects an edge's ``distance``/``speed`` for costing itself. That
    indirection is what lets live traffic sit in front of the same graph and
    the same search without either changing.

    Class attributes:
        admits_astar: Whether this model guarantees its costs never fall below
            the free-flow optimum the router's heuristic assumes. ``False``
            makes the router fall back to Dijkstra, which is slower but has no
            admissibility requirement.
        mode: The unit this model measures in, when it knows. The router
            refuses a request whose ``cost_mode`` names a different unit --
            meters charged against a request asking for seconds does not fail,
            it silently returns a route nothing downstream can tell is wrong.
            ``None`` means the model declines to say, and no check is made.
    """

    admits_astar: bool = True
    mode: CostMode | None = None

    @abstractmethod
    def edge_cost(self, edge: Edge, context: CostContext) -> float:
        """Return the cost of traversing ``edge``.

        Must return ``float("inf")`` for an edge this vehicle cannot or should
        not use, rather than raising -- the search treats an infinite cost as
        impassable and keeps going.
        """

    def turn_cost(
        self, from_edge: Edge, via_node: str, to_edge: Edge, context: CostContext
    ) -> float:
        """Return the extra cost of a turn. Must be non-negative.

        Zero by default. A model that penalizes left turns across traffic, or
        a signalized junction, overrides this.
        """
        return 0.0

    def travel_time(self, edge: Edge, context: CostContext) -> float:
        """Seconds to traverse ``edge``. This is what an ETA is built from.

        Real time, never preference-weighted: a road class penalty changes
        what a route *costs*, not how long driving it takes. The default is
        free-flow time under the profile's speed factor.
        """
        return edge.distance / context.profile.effective_speed(edge)

    def turn_time(
        self, from_edge: Edge, via_node: str, to_edge: Edge, context: CostContext
    ) -> float:
        """Seconds spent performing a turn. Zero by default."""
        return 0.0


class StaticCostModel(CostModel):
    """Cost from the edge's own attributes and the vehicle profile only.

    Supports both built-in :class:`CostMode` values. This is the default the
    router constructs when a caller supplies none.
    """

    def __init__(self, mode: CostMode | str = CostMode.FASTEST) -> None:
        try:
            self.mode = CostMode(mode)
        except ValueError:
            raise InvalidRequest(
                f"unknown cost mode {mode!r}; known modes: {[m.value for m in CostMode]}"
            ) from None

    def edge_cost(self, edge: Edge, context: CostContext) -> float:
        if edge.access is Access.BLOCKED:
            return float("inf")
        if not context.profile.may_use(edge):
            return float("inf")
        if self.mode is CostMode.SHORTEST:
            return edge.distance * context.profile.penalty_for(edge)
        return self.travel_time(edge, context) * context.profile.penalty_for(edge)


class DynamicCostModel(CostModel):
    """Wraps a base model and scales it per edge from a live condition map.

    This is the seam the `traffic` and `road_condition` blocks plug into: they
    maintain the mapping, this applies it, and nothing in the search changes.
    Multipliers scale both cost and travel time, because congestion genuinely
    makes the drive longer -- an ETA that ignored it would be a lie.

    The mapping is held by reference, not copied, so a city-scale condition
    table costs nothing per request. In exchange the caller must not mutate it
    while a route is being computed: build a new mapping and a new model
    instead, via :meth:`with_multipliers`. The contract states this as a
    caller obligation; a mutation mid-search would break both determinism and
    the cost bookkeeping.

    Attributes:
        base: The model to fall back to when an edge has no multiplier.
        multipliers: Edge id to multiplier. Each must be at least 1.0.
    """

    def __init__(self, base: CostModel, multipliers: Mapping[str, float] | None = None) -> None:
        self.base = base
        self.multipliers: Mapping[str, float] = multipliers if multipliers is not None else {}
        self.admits_astar = base.admits_astar
        self.mode = base.mode
        for edge_id, multiplier in self.multipliers.items():
            if multiplier < 1.0:
                raise ValueError(
                    f"multiplier for edge {edge_id!r} is {multiplier!r}; values below 1.0 "
                    "would make the A* heuristic inadmissible. Conditions may slow a road "
                    "down, never speed it past its free-flow speed"
                )

    def with_multipliers(self, multipliers: Mapping[str, float]) -> "DynamicCostModel":
        """Return a new model over the same base with a fresh condition map."""
        return DynamicCostModel(self.base, multipliers)

    def edge_cost(self, edge: Edge, context: CostContext) -> float:
        base_cost = self.base.edge_cost(edge, context)
        if base_cost == float("inf"):
            return base_cost
        return base_cost * self.multipliers.get(edge.id, 1.0)

    def turn_cost(
        self, from_edge: Edge, via_node: str, to_edge: Edge, context: CostContext
    ) -> float:
        return self.base.turn_cost(from_edge, via_node, to_edge, context)

    def travel_time(self, edge: Edge, context: CostContext) -> float:
        return self.base.travel_time(edge, context) * self.multipliers.get(edge.id, 1.0)

    def turn_time(
        self, from_edge: Edge, via_node: str, to_edge: Edge, context: CostContext
    ) -> float:
        return self.base.turn_time(from_edge, via_node, to_edge, context)


class CallableCostModel(CostModel):
    """Adapts a plain function to :class:`CostModel`, for tests and one-offs.

    Because an arbitrary function can return anything, this cannot promise the
    lower bound A* relies on, so ``admits_astar`` is ``False`` and the router
    uses Dijkstra. Correct results, no heuristic to get wrong.
    """

    admits_astar = False

    def __init__(self, fn: Callable[[Edge, CostContext], float]) -> None:
        self._fn = fn

    def edge_cost(self, edge: Edge, context: CostContext) -> float:
        return self._fn(edge, context)
