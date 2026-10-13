"""Where road segments come from. One source shipped: OpenStreetMap."""

from .overpass import (
    FREE_FLOW_BY_CLASS,
    ROAD_CLASSES,
    OverpassRoadSource,
    free_flow_for,
    parse_maxspeed,
    parse_overpass,
)

__all__ = [
    "OverpassRoadSource",
    "ROAD_CLASSES",
    "FREE_FLOW_BY_CLASS",
    "parse_overpass",
    "free_flow_for",
    "parse_maxspeed",
]
