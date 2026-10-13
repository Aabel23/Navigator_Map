"""The Routing Service: a trip between two coordinates, start to finish.

This is what the API calls. It is the layer between "a driver asked for a
route from here to there" and :class:`~routing.router.Router`, which knows
only about node ids and a graph that is already loaded.

    API request  ->  RouteQuery  ->  RoutingService  ->  Router  ->  Route

Everything the service does is orchestration, and each step is a decision
routing must not make for itself:

1. **Which area to load.** The endpoints define a box; the padding gives the
   search somewhere to detour to. A route hugging the edge of an unpadded box
   would be forced straight even where going around is obviously right.
2. **Where the endpoints are on the network.** Coordinates become node ids by
   asking the graph view to snap them. Routing's contract is explicit that
   this is not routing's job.
3. **What the roads cost right now.** Traffic multipliers and road-condition
   multipliers are combined and handed to a
   :class:`~routing.costs.DynamicCostModel`.
4. **What cannot be used at all.** Blocked edges become a request-time
   constraint, never a graph edit, so one shared graph serves concurrent
   requests carrying different rules.

What the service does *not* do is compute anything. No search, no cost
arithmetic, no geometry. If a change to this file starts to look like an
algorithm, it belongs in the engine.

Inputs:  RouteQuery, and the three providers in :mod:`routing.providers`
Outputs: Route, or a RoutingError
Not here: HTTP, JSON, or any knowledge of where provider data comes from
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from domain import BBox, GeoPoint

from .constraints import RouteConstraints, avoid_road_classes
from .costs import CostMode, DynamicCostModel, StaticCostModel
from .errors import InvalidRequest, NoRouteFound, RoutingError
from .models import Route, RouteRequest
from .providers import MapGraphProvider, RoadStateProvider, TrafficCostProvider
from .router import Router

__all__ = ["RouteQuery", "RoutingService", "RoutingPolicy", "combine_multipliers"]

#: How far outside the straight line between the endpoints roads are loaded,
#: in degrees. Roughly 2.2 km at the equator -- enough for a realistic detour
#: around a closure without loading a region to cross a district.
DEFAULT_PAD_DEGREES = 0.02

#: How far a coordinate may be from the nearest junction and still snap to it.
#: Past this the answer is "you are not on the network", which is a better
#: reply than a route starting a kilometre from the driver.
DEFAULT_SNAP_RADIUS_M = 250.0

#: Ceiling on a combined multiplier. A road twelve times slower than free flow
#: is not a road anyone should be routed down, and an uncapped product of
#: conditions can make the cost bookkeeping meaningless while still being
#: finite. Blocking is expressed by :meth:`RoadStateProvider.blocked_edges`,
#: not by an enormous number.
MAX_MULTIPLIER = 12.0


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """The knobs the service exposes to configuration, and their defaults.

    Configuration belongs here rather than baked into the code below, so that
    changing how much map a route request loads is a settings change and not
    an edit to domain logic.
    """

    pad_degrees: float = DEFAULT_PAD_DEGREES
    snap_radius_m: float = DEFAULT_SNAP_RADIUS_M
    max_multiplier: float = MAX_MULTIPLIER

    def __post_init__(self) -> None:
        if self.pad_degrees < 0:
            raise ValueError("pad_degrees must not be negative")
        if self.snap_radius_m <= 0:
            raise ValueError("snap_radius_m must be positive")
        if self.max_multiplier < 1.0:
            raise ValueError("max_multiplier below 1.0 would speed a road up")


@dataclass(frozen=True, slots=True)
class RouteQuery:
    """One trip, in the terms a client actually has.

    Coordinates, not node ids: a client knows where the driver is, not which
    junction the server calls that. This is the routing subsystem's
    application-level input contract; :class:`~routing.models.RouteRequest` is
    the engine's, and the service is what turns one into the other.

    Attributes:
        origin: Where the trip starts.
        destination: Where it ends.
        waypoints: Ordered stops between the two. Each leg is searched
            separately and the legs are joined, so a waypoint is a place the
            route genuinely passes through rather than a hint.
        profile: Vehicle profile name -- ``"car"``, ``"truck"``, and so on.
        cost_mode: ``"fastest"`` or ``"shortest"``.
        departure: Timezone-aware start time, passed to the cost model
            unchanged. A naive datetime is rejected rather than assigned a
            zone.
        avoid_road_classes: Road classes this trip must not use. A preference,
            evaluated per request; it never touches the shared graph.
        allow_u_turns: Whether the route may reverse along the edge it arrived
            on.
        use_traffic: Whether live traffic is priced into this route. Off gives
            a free-flow route, which is what a "usual journey time" comparison
            needs.
    """

    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[GeoPoint, ...] = ()
    profile: str = "car"
    cost_mode: str = "fastest"
    departure: datetime | None = None
    avoid_road_classes: frozenset[str] = field(default_factory=frozenset)
    allow_u_turns: bool = False
    use_traffic: bool = True

    @property
    def points(self) -> tuple[GeoPoint, ...]:
        """Origin, waypoints and destination, in travel order."""
        return (self.origin, *self.waypoints, self.destination)


class RoutingService:
    """Turns a :class:`RouteQuery` into a :class:`~routing.models.Route`.

    Args:
        graphs: Where the road graph comes from.
        traffic: Live congestion, or ``None`` to route on free-flow speeds.
        road_state: Closures and conditions, or ``None`` to ignore them.
        policy: Area padding, snap radius and multiplier ceiling.

    The two optional providers are optional on purpose rather than by
    accident: a server started with no traffic source still routes, and says
    so in :meth:`describe`. A navigation system that refused to answer because
    a feed was down would be worse than one that answered without it.
    """

    def __init__(
        self,
        *,
        graphs: MapGraphProvider,
        traffic: TrafficCostProvider | None = None,
        road_state: RoadStateProvider | None = None,
        policy: RoutingPolicy | None = None,
    ) -> None:
        self._graphs = graphs
        self._traffic = traffic
        self._road_state = road_state
        self._policy = policy or RoutingPolicy()

    @property
    def policy(self) -> RoutingPolicy:
        return self._policy

    def describe(self) -> dict[str, object]:
        """What this service is wired to. Used by the health endpoint."""
        return {
            "graphs": type(self._graphs).__name__,
            "traffic": type(self._traffic).__name__ if self._traffic else None,
            "road_state": type(self._road_state).__name__ if self._road_state else None,
            "pad_degrees": self._policy.pad_degrees,
            "snap_radius_m": self._policy.snap_radius_m,
        }

    # --- The one operation -------------------------------------------------

    def route(self, query: RouteQuery) -> Route:
        """Compute the route for ``query``.

        Raises:
            InvalidRequest: an endpoint is not near any road, or the query
                names a profile or cost mode that does not exist.
            NoRouteFound: nothing legal connects the endpoints under the
                current conditions.
            RoutingError: anything else, including a provider failure. No
                other exception type leaves this method -- the API above must
                not have to know what a map-data source raises.
        """
        try:
            return self._route(query)
        except RoutingError:
            raise
        except Exception as exc:  # noqa: BLE001 - contract: nothing else escapes
            raise RoutingError(f"routing service failure: {exc}") from exc

    def _route(self, query: RouteQuery) -> Route:
        area = BBox.covering(
            [point.as_tuple() for point in query.points],
            pad_degrees=self._policy.pad_degrees,
        )
        view = self._graphs.graph_for(area)
        nodes = self._snap(view, query.points)

        router = Router(graph=view.graph, costs=self._cost_model(area, query))
        constraints = self._constraints(area, query)

        legs = [
            router.find(
                RouteRequest(
                    origin=start,
                    destination=end,
                    profile=query.profile,
                    cost_mode=query.cost_mode,
                    departure=query.departure,
                    constraints=constraints,
                    allow_u_turns=query.allow_u_turns,
                )
            )
            for start, end in zip(nodes, nodes[1:])
        ]
        return _join(legs, query.cost_mode)

    # --- Steps -------------------------------------------------------------

    def _snap(self, view, points: Sequence[GeoPoint]) -> tuple[str, ...]:
        snapped: list[str] = []
        for index, point in enumerate(points):
            node = view.nearest_node(point, within_m=self._policy.snap_radius_m)
            if node is None:
                where = _position_name(index, len(points))
                raise InvalidRequest(
                    f"{where} ({point.lon}, {point.lat}) is not within "
                    f"{self._policy.snap_radius_m:.0f} m of any road in the loaded area"
                )
            snapped.append(node)
        return tuple(snapped)

    def _cost_model(self, area: BBox, query: RouteQuery):
        base = StaticCostModel(CostMode(query.cost_mode))
        sources: list[Mapping[str, float]] = []
        if query.use_traffic and self._traffic is not None:
            sources.append(self._traffic.multipliers_for(area))
        if self._road_state is not None:
            sources.append(self._road_state.multipliers_for(area))
        if not sources:
            return base
        combined = combine_multipliers(sources, ceiling=self._policy.max_multiplier)
        return DynamicCostModel(base, combined)

    def _constraints(self, area: BBox, query: RouteQuery) -> RouteConstraints | None:
        rules: list = []
        if query.avoid_road_classes:
            rules.append(avoid_road_classes(set(query.avoid_road_classes)))

        blocked: frozenset[str] = frozenset()
        if self._road_state is not None:
            blocked = frozenset(self._road_state.blocked_edges(area))

        if not rules and not blocked:
            return None
        # Closed edges go in `blocked_edges` rather than an `avoid_edges` rule
        # so that a caller -- or a test, or an explanation shown to a driver --
        # can read back what was closed without evaluating a closure.
        return RouteConstraints(blocked_edges=blocked, rules=tuple(rules))


# --- Helpers ---------------------------------------------------------------


def combine_multipliers(
    sources: Sequence[Mapping[str, float]], *, ceiling: float = MAX_MULTIPLIER
) -> dict[str, float]:
    """Merge several condition maps by taking the worst value per edge.

    The worst, not the product. Congestion and flooding on the same street are
    overwhelmingly the same event observed twice -- a flooded road is slow
    *because* it is flooded -- and multiplying them would charge the driver
    for it twice. Taking the maximum says "this road is as bad as the worst
    thing known about it", which is both defensible and bounded.

    Values below 1.0 are raised to 1.0 rather than rejected: a provider
    reporting a road as faster than free flow is reporting a bug, and the
    right response is to ignore that claim, not to fail a route request over
    it. Values above ``ceiling`` are clamped, because blocking is expressed by
    a constraint and not by a large number.
    """
    worst: dict[str, float] = {}
    for source in sources:
        for edge_id, value in source.items():
            bounded = min(max(float(value), 1.0), ceiling)
            if bounded > worst.get(edge_id, 1.0):
                worst[edge_id] = bounded
    return worst


def _position_name(index: int, total: int) -> str:
    if index == 0:
        return "origin"
    if index == total - 1:
        return "destination"
    return f"waypoint {index}"


def _join(legs: Sequence[Route], cost_mode: str) -> Route:
    """Concatenate consecutive legs into one route.

    A one-leg trip is returned untouched, which is the common case and must
    stay byte-identical to what :meth:`Router.find` produced -- the contract's
    determinism guarantee is stated about that object.

    Joining drops the duplicated junction between legs from ``nodes`` and the
    duplicated coordinate from ``geometry``, and leaves ``steps`` as they are:
    each leg ends with an arrival and the next begins with a departure, which
    is exactly what a driver stopping at a waypoint experiences.
    """
    if not legs:
        raise NoRouteFound("a route needs at least one leg")
    if len(legs) == 1:
        return legs[0]

    nodes: list[str] = list(legs[0].nodes)
    segments: list[str] = list(legs[0].segments)
    steps = list(legs[0].steps)
    geometry = list(legs[0].geometry)
    for leg in legs[1:]:
        nodes.extend(leg.nodes[1:])
        segments.extend(leg.segments)
        steps.extend(leg.steps)
        geometry.extend(leg.geometry[1:] if leg.geometry else ())

    return Route(
        nodes=tuple(nodes),
        segments=tuple(segments),
        steps=tuple(steps),
        geometry=tuple(geometry),
        distance=sum(leg.distance for leg in legs),
        travel_time=sum(leg.travel_time for leg in legs),
        total_cost=sum(leg.total_cost for leg in legs),
        cost_mode=cost_mode,
        nodes_expanded=sum(leg.nodes_expanded for leg in legs),
    )
