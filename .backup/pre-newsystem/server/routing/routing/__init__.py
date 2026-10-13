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

Usage:
    from routing import Router, RouteRequest

    router = Router(graph=graph)
    route = router.find(RouteRequest(origin="A", destination="Z"))

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

__all__ = [
    # Entry point
    "Router",
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
