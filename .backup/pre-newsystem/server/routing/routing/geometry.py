"""Spherical geometry: distances, bearings, and turn angles.

Pure math over WGS84 coordinates. Nothing here reads the graph, the cost
model, or a request -- it exists so that :mod:`routing.heuristics` and
:mod:`routing.assemble` share one implementation of "how far" and "which way"
instead of two.

The `location` block has its own geometry helpers. That duplication is
deliberate: blocks do not import each other, and a handful of trigonometric
functions is a smaller cost than a dependency edge.

Main functions:
    haversine_m        great-circle distance between two coordinates
    initial_bearing    compass bearing when leaving a for b
    turn_angle         signed angle between an incoming and outgoing bearing
    polyline_length_m  total length of a coordinate sequence
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, atan2, cos, degrees, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True, slots=True)
class LatLon:
    """A WGS84 coordinate in degrees.

    Validated on construction: a route's geometry is drawn by another block,
    and a silently swapped lat/lon is far cheaper to catch here than on the
    screen.
    """

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError(f"latitude out of range: {self.latitude!r}")
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError(f"longitude out of range: {self.longitude!r}")


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two coordinates, in meters."""
    return haversine_degrees(a.latitude, a.longitude, b.latitude, b.longitude)


def haversine_degrees(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance from raw degrees, in meters.

    The same computation as :func:`haversine_m` without requiring a
    :class:`LatLon` on either side. A* calls this once per relaxation, and
    constructing a validated coordinate object per call costs more than the
    trigonometry does -- the range check belongs where data enters the system,
    not in the inner loop.
    """
    lat1, lon1, lat2, lon2 = map(radians, (lat_a, lon_a, lat_b, lon_b))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def initial_bearing(a: LatLon, b: LatLon) -> float:
    """Compass bearing in degrees (0 = north, 90 = east) when leaving ``a`` for ``b``.

    Returns ``0.0`` for two identical coordinates, which keeps the caller from
    having to special-case a zero-length segment.
    """
    lat1, lat2 = radians(a.latitude), radians(b.latitude)
    dlon = radians(b.longitude - a.longitude)
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    if x == 0.0 and y == 0.0:
        return 0.0
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def turn_angle(bearing_before: float, bearing_after: float) -> float:
    """Signed turn in degrees, normalized to ``(-180, 180]``.

    Positive is a right turn, negative is a left turn. ``180`` is a U-turn.
    """
    delta = (bearing_after - bearing_before) % 360.0
    if delta > 180.0:
        delta -= 360.0
    return delta


def polyline_length_m(points: tuple[LatLon, ...]) -> float:
    """Summed great-circle length of a coordinate sequence, in meters."""
    return sum(haversine_m(a, b) for a, b in zip(points, points[1:]))
