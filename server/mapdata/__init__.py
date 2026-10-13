"""Map data -- the server's authoritative road network, and the graph from it.

    from mapdata import OverpassRoadSource, RoadGraphProvider
    from domain import BBox

    source = OverpassRoadSource(cache=backend.cache)
    graphs = RoadGraphProvider(source)
    view = graphs.graph_for(BBox(106.675, 10.758, 106.725, 10.798))

Owns:
    reading map sources, normalising them into road segments, persisting them,
    and building the routable graph the router searches -- including the
    nearest-junction lookup that turns a coordinate into a node id

Does not own:
    how fast traffic is moving on it (`traffic`), what is closed or flooded
    (`roadstate`), what a road costs to drive (`routing`), where the driver
    is, or how any of it is *drawn*. The client renders the map; this block
    supplies the data the server computes with. Those are different things
    that happen to share the word "map".

This module is the block's entire public surface. ``mapdata.roads.overpass``,
``mapdata.graph.build`` and ``mapdata.http`` are internal and may change
without a contract version bump.

Stdlib-only, so a build script or a test can import it without installing
anything.
"""

from domain import BBox, Coord, bounds_of, haversine_m, polyline_length_m

from .addresses import Address, NominatimAddressSource, parse_nominatim
from .errors import BadResponse, MapDataError, SourceUnavailable
from .graph import GraphBuild, NetworkGraphView, RoadGraphProvider, build_graph, node_id_for
from .http import HttpClient
from .models import RoadSegment, coords_of
from .network import RoadNetwork
from .roads import (
    FREE_FLOW_BY_CLASS,
    ROAD_CLASSES,
    OverpassRoadSource,
    free_flow_for,
    parse_maxspeed,
    parse_overpass,
)
from .store import PersistingRoadNetwork, RoadStore, StoredRoadNetwork

__all__ = [
    # Geography, re-exported from domain so a consumer needs one import
    "BBox",
    "Coord",
    "bounds_of",
    "haversine_m",
    "polyline_length_m",
    # The published network
    "RoadSegment",
    "RoadNetwork",
    "coords_of",
    # Sources
    "OverpassRoadSource",
    "ROAD_CLASSES",
    "FREE_FLOW_BY_CLASS",
    "parse_overpass",
    "free_flow_for",
    "parse_maxspeed",
    # Addresses
    "Address",
    "NominatimAddressSource",
    "parse_nominatim",
    # Persistence
    "RoadStore",
    "StoredRoadNetwork",
    "PersistingRoadNetwork",
    # The graph, and the provider routing asks
    "RoadGraphProvider",
    "NetworkGraphView",
    "build_graph",
    "GraphBuild",
    "node_id_for",
    # Transport, exposed so a test can inject a fake
    "HttpClient",
    # Errors
    "MapDataError",
    "SourceUnavailable",
    "BadResponse",
]
