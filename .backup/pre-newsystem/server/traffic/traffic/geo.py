"""Spherical geometry on `(lon, lat)` pairs.

Coordinates are GeoJSON order -- longitude first -- everywhere in this block,
because every free source it reads (Overpass, Digitraffic) speaks GeoJSON and
the map block's configuration already uses `[lon, lat]`.

Nothing here knows what traffic is. It works on plain tuples so that
:mod:`traffic.models` can use it without a circular import.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

__all__ = [
    "EARTH_RADIUS_M",
    "Coord",
    "haversine_m",
    "polyline_length_m",
    "bearing_deg",
    "midpoint",
    "bounds_of",
]

EARTH_RADIUS_M = 6_371_008.8

#: A single position, longitude first, in degrees.
Coord = tuple[float, float]


def haversine_m(a: Coord, b: Coord) -> float:
    """Great-circle distance between two lon/lat points, in metres."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def polyline_length_m(points: Sequence[Coord]) -> float:
    """Summed great-circle length of a polyline. Zero for fewer than 2 points."""
    if len(points) < 2:
        return 0.0
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def bearing_deg(a: Coord, b: Coord) -> float:
    """Initial compass bearing from a to b, degrees clockwise from north."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def midpoint(points: Sequence[Coord]) -> Coord:
    """The vertex nearest the halfway point along a polyline.

    A real vertex rather than an interpolated one, so a marker placed here
    always sits on the road rather than across the chord of a bend.
    """
    if not points:
        raise ValueError("midpoint() needs at least one point")
    if len(points) < 3:
        return points[0]
    half = polyline_length_m(points) / 2
    walked = 0.0
    for i in range(len(points) - 1):
        walked += haversine_m(points[i], points[i + 1])
        if walked >= half:
            return points[i + 1]
    return points[-1]


def bounds_of(points: Iterable[Coord]) -> tuple[float, float, float, float]:
    """West, south, east, north of a point cloud. Raises on an empty one."""
    lons: list[float] = []
    lats: list[float] = []
    for lon, lat in points:
        lons.append(lon)
        lats.append(lat)
    if not lons:
        raise ValueError("bounds_of() needs at least one point")
    return min(lons), min(lats), max(lons), max(lats)
