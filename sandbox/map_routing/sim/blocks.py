"""Where the sandbox reaches the three server blocks -- and the only place it does.

The sandbox lives outside ``server/``, so the block roots have to go on
``sys.path`` before anything can be imported from them. That path juggling is
confined to this module so the rest of the sandbox reads like ordinary code.

What is imported here is each block's *published* surface and nothing else:

* ``routing``            -- the block states that its package ``__init__`` is
                            its entire public interface, and that
                            ``routing.search`` / ``assemble`` / ``heuristics``
                            are internal. Only the re-exports are used.
* ``traffic``            -- same rule, stated in its ``__init__``: import what
                            the package re-exports. The two adapter modules
                            (``traffic.providers.digitraffic``,
                            ``traffic.sources.overpass``) are imported the way
                            the block's own README documents them.
* ``ui.view.create_app`` -- the map block's documented entry point. The
                            sandbox borrows one view function from it
                            (``/api/config``) so the page it serves is
                            configured and styled by the map block itself,
                            never by a copy that can drift.

No private function, internal module or storage layout of any block is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

SANDBOX_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SANDBOX_ROOT.parents[1]
SERVER_ROOT = PROJECT_ROOT / "server"

MAP_BLOCK = SERVER_ROOT / "map"
ROUTING_BLOCK = SERVER_ROOT / "routing"
TRAFFIC_BLOCK = SERVER_ROOT / "traffic"

#: The map block's browser assets, served by the sandbox unchanged.
MAP_STATIC_DIR = MAP_BLOCK / "ui" / "static"


def _ensure_on_path() -> None:
    for block in (ROUTING_BLOCK, TRAFFIC_BLOCK, MAP_BLOCK):
        if not block.is_dir():
            raise RuntimeError(f"server block not found: {block}")
        text = str(block)
        if text not in sys.path:
            sys.path.append(text)


_ensure_on_path()

# --- routing: public interface only -----------------------------------------
from routing import (  # noqa: E402
    Access,
    CostMode,
    Direction,
    DynamicCostModel,
    Edge,
    InMemoryRoadGraph,
    LatLon,
    NoRouteFound,
    Node,
    Route,
    RouteConstraints,
    RouteRequest,
    Router,
    RoutingError,
    StaticCostModel,
    UnknownNode,
)

# --- traffic: public interface, plus the two adapters its README names -------
from traffic import (  # noqa: E402
    BBox,
    RoadSegment,
    TrafficSnapshot,
    TrafficStore,
    level_payload,
)
from traffic.providers.digitraffic import DigitrafficProvider  # noqa: E402
from traffic.providers.simulated import SimulatedTrafficProvider  # noqa: E402
from traffic.sources.overpass import OverpassRoadSource  # noqa: E402

# --- map: the documented entry point ----------------------------------------
from ui.view import create_app as create_map_app  # noqa: E402

__all__ = [
    "MAP_STATIC_DIR",
    "SANDBOX_ROOT",
    "Access",
    "BBox",
    "CostMode",
    "Direction",
    "DigitrafficProvider",
    "DynamicCostModel",
    "Edge",
    "InMemoryRoadGraph",
    "LatLon",
    "NoRouteFound",
    "Node",
    "OverpassRoadSource",
    "RoadSegment",
    "Route",
    "RouteConstraints",
    "RouteRequest",
    "Router",
    "RoutingError",
    "SimulatedTrafficProvider",
    "StaticCostModel",
    "TrafficSnapshot",
    "TrafficStore",
    "UnknownNode",
    "create_map_app",
    "level_payload",
]
