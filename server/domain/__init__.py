"""Domain -- the vocabulary every subsystem shares, and nothing else.

    from domain import BBox, GeoPoint

One geographic rectangle, one geographic point, and one proximity index,
because the API, the providers and the storage layer all have to name an area
or a position -- and three spellings of the same rectangle, or three
hand-rolled nearest-neighbour grids, is how a server starts disagreeing with
itself about what it was asked.

Owns:
    the neutral geographic types that cross a subsystem boundary, and the
    proximity search several subsystems each need over their own data

Does not own:
    road data, traffic, road conditions, routes, persistence, transport. A
    block's *internal* types stay its own -- ``routing.Edge``,
    ``mapdata.RoadSegment``, ``ingest.TrafficObservation`` are contracts of
    their blocks, not of this one.

This module imports nothing from any other subsystem, and nothing may ever be
added here that does. It is the bottom of the dependency graph.
"""

from .geo import BBox, Coord, GeoPoint, bounds_of, haversine_m, polyline_length_m
from .spatial import SpatialIndex, densify, index_of_polylines

__all__ = [
    "BBox",
    "SpatialIndex",
    "index_of_polylines",
    "densify",
    "Coord",
    "GeoPoint",
    "bounds_of",
    "haversine_m",
    "polyline_length_m",
]
