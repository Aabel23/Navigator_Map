"""Geographic math utilities: distance (Haversine) and bearing.

Pure functions, independently testable, with no dependency on the rest
of the location subsystem.
"""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0  # mean Earth radius in meters


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in meters (Haversine).

    Cartesian subtraction of raw lat/lon is deliberately not used --
    it is inaccurate and gets worse away from the equator.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    return EARTH_RADIUS_M * c


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, in degrees.

    0 = North, 90 = East, 180 = South, 270 = West. Result is normalized
    to the range [0, 360).
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)

    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        d_lambda
    )
    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360.0) % 360.0
