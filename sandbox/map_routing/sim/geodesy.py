"""Spherical geometry the sandbox needs for itself.

The traffic block has the same functions, but they live in ``traffic.geo``,
which that block's ``__init__`` deliberately does not re-export -- it is an
internal module, and the sandbox is not entitled to it. So the handful of
formulas the simulator needs are written here instead of reached for across a
block boundary.

Coordinates are ``(lon, lat)`` in degrees, GeoJSON order, matching every other
lon/lat pair that crosses the wire in this project. The routing block speaks
``LatLon(lat, lon)``; the conversion happens at that boundary and nowhere else.
"""

from __future__ import annotations

import math
from typing import Sequence

__all__ = [
    "EARTH_RADIUS_M",
    "Coord",
    "haversine_m",
    "polyline_length_m",
    "bearing_deg",
    "point_to_segment_m",
    "walk_polyline",
]

EARTH_RADIUS_M = 6_371_008.8

Coord = tuple[float, float]


def haversine_m(a: Coord, b: Coord) -> float:
    """Great-circle distance between two lon/lat points, in metres."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def polyline_length_m(points: Sequence[Coord]) -> float:
    """Summed great-circle length of a polyline. Zero for fewer than 2 points."""
    if len(points) < 2:
        return 0.0
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def bearing_deg(a: Coord, b: Coord) -> float:
    """Initial compass bearing from ``a`` to ``b``, degrees clockwise from north."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def _local_metres(origin: Coord) -> tuple[float, float]:
    """Metres per degree of longitude and latitude near ``origin``.

    An equirectangular approximation. Over the few hundred metres this is ever
    asked about it is accurate to well under a metre, and it turns a
    point-to-segment distance into plain 2D algebra instead of a spherical
    projection.
    """
    lat_rad = math.radians(origin[1])
    return (
        EARTH_RADIUS_M * math.cos(lat_rad) * math.pi / 180.0,
        EARTH_RADIUS_M * math.pi / 180.0,
    )


def point_to_segment_m(point: Coord, start: Coord, end: Coord) -> tuple[float, Coord]:
    """Distance from ``point`` to the segment ``start``-``end``, and the foot of it.

    Returns:
        ``(metres, closest_point)``. The closest point is clamped to the
        segment's ends, so a reading beside a road is matched to the road
        rather than to the infinite line through it.
    """
    mx, my = _local_metres(point)
    px, py = (point[0] - start[0]) * mx, (point[1] - start[1]) * my
    ex, ey = (end[0] - start[0]) * mx, (end[1] - start[1]) * my
    span = ex * ex + ey * ey
    t = 0.0 if span == 0.0 else max(0.0, min(1.0, (px * ex + py * ey) / span))
    foot = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
    return math.hypot(px - ex * t, py - ey * t), foot


def walk_polyline(points: Sequence[Coord], distance_m: float) -> tuple[Coord, float, bool]:
    """Walk ``distance_m`` along a polyline from its start.

    Returns:
        ``(position, bearing, finished)``. ``finished`` is true once the walk
        has run past the end, in which case the position is the last vertex.
    """
    if not points:
        raise ValueError("walk_polyline() needs at least one point")
    if len(points) == 1 or distance_m <= 0:
        heading = bearing_deg(points[0], points[1]) if len(points) > 1 else 0.0
        return points[0], heading, len(points) == 1

    walked = 0.0
    for i in range(len(points) - 1):
        leg = haversine_m(points[i], points[i + 1])
        if leg <= 0:
            continue
        if walked + leg >= distance_m:
            t = (distance_m - walked) / leg
            here = (
                points[i][0] + (points[i + 1][0] - points[i][0]) * t,
                points[i][1] + (points[i + 1][1] - points[i][1]) * t,
            )
            return here, bearing_deg(points[i], points[i + 1]), False
        walked += leg
    return points[-1], bearing_deg(points[-2], points[-1]), True
