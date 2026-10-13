"""The block's entry point: a request and a graph in, a Route out.

Router validates, picks a cost model and a heuristic, runs the search, and
hands the result to the assembler. It deliberately owns heuristic choice
rather than accepting one from the caller: a heuristic that does not match the
active cost mode returns a worse route silently, with nothing on the result to
show for it, and no caller can be expected to re-derive admissibility every
time they change a cost model.

Inputs:  RouteRequest, plus the RoadGraph and optional CostModel given at
    construction
Outputs: Route, or a RoutingError
Non-responsibilities: where the graph came from, what a road costs, how the
    route is drawn or spoken

Usage:
    router = Router(graph=graph)
    route = router.find(RouteRequest(origin="A", destination="Z"))

Main functions:
    find        one request, one route
    find_many   one origin, many destinations, one search
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .assemble import assemble_route, trivial_route
from .constraints import RouteConstraints
from .costs import CostContext, CostMode, CostModel, StaticCostModel, VehicleProfile, get_vehicle_profile
from .errors import InvalidRequest, NoRouteFound, RoutingError, UnknownNode
from .graph import RoadGraph
from .heuristics import build_heuristic, zero_heuristic
from .models import Route, RouteRequest
from .search import astar, path_to_edges


class Router:
    """Computes routes over a :class:`~routing.graph.RoadGraph`.

    Holds no per-request state, so one router serves many requests. The graph
    is shared and read-only; construct one router per thread rather than
    assuming this object is safe to use from several at once.

    Args:
        graph: The road network to search.
        costs: A cost model used for every request. When ``None`` (the usual
            case) the router builds a
            :class:`~routing.costs.StaticCostModel` per request from that
            request's ``cost_mode``. Supply one to route under live conditions
            -- see :class:`~routing.costs.DynamicCostModel`.
    """

    def __init__(self, *, graph: RoadGraph, costs: CostModel | None = None) -> None:
        self.graph = graph
        self.costs = costs

    # --- Public API --------------------------------------------------------

    def find(self, request: RouteRequest) -> Route:
        """Compute the lowest-cost route satisfying ``request``.

        Raises:
            InvalidRequest: malformed request -- unknown profile or cost mode,
                a naive departure time, or a cost model measuring in a
                different unit than the request asks for.
            UnknownNode: the origin or destination is not in the graph.
            NoRouteFound: both endpoints exist, but nothing legal connects
                them under this profile, these constraints, and the graph's
                turn restrictions.
        """
        try:
            return self._find(request)
        except RoutingError:
            raise
        except Exception as exc:  # noqa: BLE001 - contract: nothing else escapes
            raise RoutingError(f"internal routing failure: {exc}") from exc

    def find_many(
        self,
        origin: str,
        destinations: Iterable[str],
        *,
        profile: VehicleProfile | str = "car",
        cost_mode: CostMode | str = CostMode.FASTEST,
        departure: datetime | None = None,
        constraints: RouteConstraints | None = None,
        allow_u_turns: bool = False,
    ) -> dict[str, Route]:
        """Route from one origin to several destinations in a single search.

        Returns:
            A dict keyed by destination node id. A destination nothing can
            reach is omitted rather than raising, so one unreachable stop does
            not cost the caller all the others.

        Notes:
            This runs Dijkstra, not A*. A heuristic aimed at one destination
            tells the search nothing about the rest, and settling states once
            under it would produce wrong answers for every other goal.
        """
        try:
            return self._find_many(
                origin,
                destinations,
                profile=profile,
                cost_mode=cost_mode,
                departure=departure,
                constraints=constraints,
                allow_u_turns=allow_u_turns,
            )
        except RoutingError:
            raise
        except Exception as exc:  # noqa: BLE001 - contract: nothing else escapes
            raise RoutingError(f"internal routing failure: {exc}") from exc

    # --- Internal ----------------------------------------------------------

    def _find(self, request: RouteRequest) -> Route:
        profile = _resolve_profile(request.profile)
        mode = _resolve_mode(request.cost_mode)
        _check_departure(request.departure)
        self._check_node(request.origin)
        self._check_node(request.destination)

        cost_model = self._resolve_cost_model(mode)
        context = CostContext(profile=profile, departure=request.departure)
        constraints = request.constraints or RouteConstraints()

        if request.origin == request.destination:
            return trivial_route(self.graph, node_id=request.origin, cost_mode=mode.value)

        heuristic = zero_heuristic
        if request.use_astar and cost_model.admits_astar:
            heuristic = build_heuristic(
                self.graph, mode=mode, profile=profile, goal_id=request.destination
            )

        result = astar(
            self.graph,
            origin=request.origin,
            goals=(request.destination,),
            cost_model=cost_model,
            context=context,
            constraints=constraints,
            heuristic=heuristic,
            allow_u_turns=request.allow_u_turns,
        )

        goal_state = result.settled_goals.get(request.destination)
        if goal_state is None:
            raise NoRouteFound(request.origin, request.destination)

        return assemble_route(
            self.graph,
            origin=request.origin,
            edge_ids=path_to_edges(result, goal_state),
            cost_model=cost_model,
            context=context,
            total_cost=result.cost_so_far[goal_state],
            cost_mode=mode.value,
            states_settled=result.states_settled,
        )

    def _find_many(
        self,
        origin: str,
        destinations: Iterable[str],
        *,
        profile: VehicleProfile | str,
        cost_mode: CostMode | str,
        departure: datetime | None,
        constraints: RouteConstraints | None,
        allow_u_turns: bool,
    ) -> dict[str, Route]:
        resolved_profile = _resolve_profile(profile)
        mode = _resolve_mode(cost_mode)
        _check_departure(departure)
        self._check_node(origin)

        targets = list(dict.fromkeys(destinations))
        for target in targets:
            self._check_node(target)

        cost_model = self._resolve_cost_model(mode)
        context = CostContext(profile=resolved_profile, departure=departure)
        result = astar(
            self.graph,
            origin=origin,
            goals=[t for t in targets if t != origin],
            cost_model=cost_model,
            context=context,
            constraints=constraints or RouteConstraints(),
            heuristic=zero_heuristic,
            allow_u_turns=allow_u_turns,
        )

        routes: dict[str, Route] = {}
        for target in targets:
            if target == origin:
                routes[target] = trivial_route(self.graph, node_id=origin, cost_mode=mode.value)
                continue
            goal_state = result.settled_goals.get(target)
            if goal_state is None:
                continue
            routes[target] = assemble_route(
                self.graph,
                origin=origin,
                edge_ids=path_to_edges(result, goal_state),
                cost_model=cost_model,
                context=context,
                total_cost=result.cost_so_far[goal_state],
                cost_mode=mode.value,
                states_settled=result.states_settled,
            )
        return routes

    def _resolve_cost_model(self, mode: CostMode) -> CostModel:
        """Use the router's cost model if it measures in the requested unit.

        The unit check is mechanical on purpose. A model measuring meters used
        for a request asking for seconds does not fail; it returns a route
        that is wrong in a way no downstream consumer can detect.
        """
        if self.costs is None:
            return StaticCostModel(mode)
        model_mode = getattr(self.costs, "mode", None)
        if model_mode is not None and CostMode(model_mode) is not mode:
            raise InvalidRequest(
                f"request asks for cost_mode {mode.value!r} but this router's cost model "
                f"measures {CostMode(model_mode).value!r}"
            )
        return self.costs

    def _check_node(self, node_id: str) -> None:
        if not self.graph.has_node(node_id):
            raise UnknownNode(node_id)


# --- Request normalization -------------------------------------------------


def _resolve_profile(profile: VehicleProfile | str) -> VehicleProfile:
    if isinstance(profile, VehicleProfile):
        return profile
    return get_vehicle_profile(profile)


def _resolve_mode(cost_mode: CostMode | str) -> CostMode:
    try:
        return CostMode(cost_mode)
    except ValueError:
        raise InvalidRequest(
            f"unknown cost mode {cost_mode!r}; known modes: {[m.value for m in CostMode]}"
        ) from None


def _check_departure(departure: datetime | None) -> None:
    """Reject a naive datetime rather than guessing which zone it meant.

    A time-dependent cost model reading a naive timestamp would be wrong by
    whole hours without anything looking broken.
    """
    if departure is None:
        return
    if departure.tzinfo is None or departure.tzinfo.utcoffset(departure) is None:
        raise InvalidRequest("departure must be timezone-aware")
