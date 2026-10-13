"""Routing -- finds a path through the road network.

Takes:
    RouteRequest    origin, destination, vehicle profile, cost mode, departure
    RoadGraph       shared, read-only; supplied by whoever owns road data
    CostModel       edge and turn costs; optional, defaults to a static one

Returns:
    Route           geometry, segments, manoeuvre steps, distance, travel time
    RoutingError    typed failure, and nothing else escapes

Does not handle:
    GPS, map matching, rendering, the driver's progress along the route,
    where road data comes from, or what "fastest" ought to mean

Usage, engine-level -- node ids, a graph you already hold:
    from routing import Router, RouteRequest

    router = Router(graph=graph)
    route = router.find(RouteRequest(origin="A", destination="Z"))

Usage, service-level -- coordinates, and providers that fetch what is needed:
    from routing import RoutingService, RouteQuery
    from domain import GeoPoint

    service = RoutingService(graphs=graphs, traffic=traffic, road_state=state)
    route = service.route(RouteQuery(origin=GeoPoint(106.70, 10.77),
                                     destination=GeoPoint(106.71, 10.78)))

The service is what the API calls. It orchestrates -- choose an area, snap the
endpoints, price the roads, apply closures -- and computes nothing itself.

This module is the block's entire public surface. Everything reachable from
here is contract; everything else -- routing.search, routing.assemble,
routing.heuristics -- is internal and may change without a contract version
bump. Import from ``routing``, never from ``routing.<module>``.
"""

from .constraints import (
    Constraint,
    RouteConstraints,
    avoid_edges,
    avoid_nodes,
    avoid_road_classes,
    avoid_tolls,
    max_metadata_value,
)
from .costs import (
    VEHICLE_PROFILES,
    CallableCostModel,
    CostContext,
    CostMode,
    CostModel,
    DynamicCostModel,
    StaticCostModel,
    VehicleProfile,
    get_vehicle_profile,
)
from .errors import (
    InvalidRequest,
    NoRouteFound,
    RoutingError,
    UnknownEdge,
    UnknownNode,
)
from .geometry import LatLon
from .graph import InMemoryRoadGraph, RoadGraph
from .providers import (
    GraphView,
    MapGraphProvider,
    RoadStateProvider,
    TrafficCostProvider,
)
from .models import (
    Access,
    Direction,
    Edge,
    Maneuver,
    Node,
    Route,
    RouteRequest,
    RouteStep,
    TurnKind,
    TurnRestriction,
)
from .router import Router
from .service import RouteQuery, RoutingPolicy, RoutingService, combine_multipliers

__all__ = [
    # Entry points
    "Router",
    "RoutingService",
    "RouteQuery",
    "RoutingPolicy",
    # What the service needs from the rest of the server
    "MapGraphProvider",
    "TrafficCostProvider",
    "RoadStateProvider",
    "GraphView",
    "combine_multipliers",
    # Request and result
    "RouteRequest",
    "Route",
    "RouteStep",
    "Maneuver",
    # Road data
    "RoadGraph",
    "InMemoryRoadGraph",
    "Node",
    "Edge",
    "TurnRestriction",
    "TurnKind",
    "Direction",
    "Access",
    "LatLon",
    # Cost
    "CostModel",
    "CostMode",
    "CostContext",
    "StaticCostModel",
    "DynamicCostModel",
    "CallableCostModel",
    "VehicleProfile",
    "VEHICLE_PROFILES",
    "get_vehicle_profile",
    # Request-time rules
    "RouteConstraints",
    "Constraint",
    "avoid_edges",
    "avoid_nodes",
    "avoid_road_classes",
    "avoid_tolls",
    "max_metadata_value",
    # Errors
    "RoutingError",
    "InvalidRequest",
    "UnknownNode",
    "UnknownEdge",
    "NoRouteFound",
]
