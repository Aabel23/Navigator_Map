"""Geographic values shared across subsystem boundaries.

Coordinates are ``(longitude, latitude)`` in degrees, WGS84 -- GeoJSON order,
which is the order every free source this project reads (Overpass, the
national traffic feeds) publishes in, and the order the client's map
configuration already uses. The routing block stores its own points
latitude-first because that is what its contract has always promised; the
conversion happens once, at the ``mapdata`` graph boundary, and nowhere else.

Nothing here knows what a road, a traffic level or a route is. That is the
point: these types are allowed to be depended on by everything precisely
because they carry no policy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "Coord",
    "GeoPoint",
    "BBox",
    "haversine_m",
    "polyline_length_m",
    "bounds_of",
]

#: A bare ``(lon, lat)`` pair. Used where a dataclass would be noise -- inside
#: a polyline of several thousand points, for instance.
Coord = tuple[float, float]

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True, slots=True)
class GeoPoint:
    """One position on the surface, longitude first.

    Validated on construction, because a swapped lat/lon pair is the single
    most common bug at a geographic boundary and it produces a plausible
    answer in the Gulf of Guinea rather than an error.
    """

    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not -180.0 <= self.lon <= 180.0:
            raise ValueError(f"longitude {self.lon} is out of range")
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"latitude {self.lat} is out of range")

    @classmethod
    def parse(cls, text: str) -> "GeoPoint":
        """Read ``"lon,lat"`` -- the order a URL query uses."""
        parts = text.split(",")
        if len(parts) != 2:
            raise ValueError(f"expected lon,lat -- got {text!r}")
        return cls(float(parts[0]), float(parts[1]))

    def as_tuple(self) -> Coord:
        return (self.lon, self.lat)

    def distance_to(self, other: "GeoPoint") -> float:
        """Great-circle distance in meters."""
        return haversine_m(self.as_tuple(), other.as_tuple())


@dataclass(frozen=True, slots=True)
class BBox:
    """A lon/lat rectangle in degrees, west/south/east/north.

    Does not cross the anti-meridian. Every request that names an area carries
    one, and every cached artifact records the one it was built for, so a
    cached result can never be served for an area it does not cover.
    """

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if self.west > self.east:
            raise ValueError(f"west {self.west} is east of east {self.east}")
        if self.south > self.north:
            raise ValueError(f"south {self.south} is north of north {self.north}")

    @classmethod
    def parse(cls, text: str) -> "BBox":
        """Read ``"west,south,east,north"`` -- the order a URL query uses."""
        parts = text.split(",")
        if len(parts) != 4:
            raise ValueError(f"expected west,south,east,north -- got {text!r}")
        return cls(*(float(p) for p in parts))

    @classmethod
    def around(cls, lon: float, lat: float, half_degrees: float) -> "BBox":
        return cls(lon - half_degrees, lat - half_degrees, lon + half_degrees, lat + half_degrees)

    @classmethod
    def covering(cls, points: Iterable[Coord], *, pad_degrees: float = 0.0) -> "BBox":
        """The smallest box holding every point, optionally padded.

        This is how a route request over coordinates becomes an area to load:
        the endpoints define the box, the padding gives the search somewhere
        to detour to.
        """
        pts = tuple(points)
        if not pts:
            raise ValueError("cannot cover an empty set of points")
        west, south, east, north = bounds_of(pts)
        return cls(
            west - pad_degrees, south - pad_degrees, east + pad_degrees, north + pad_degrees
        )

    @property
    def center(self) -> Coord:
        return ((self.west + self.east) / 2, (self.south + self.north) / 2)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)

    def contains(self, point: Coord) -> bool:
        lon, lat = point
        return self.west <= lon <= self.east and self.south <= lat <= self.north

    def intersects(self, other: "BBox") -> bool:
        if self.east < other.west or other.east < self.west:
            return False
        return not (self.north < other.south or other.north < self.south)

    def touches_any(self, points: Sequence[Coord]) -> bool:
        """True when any vertex falls inside. Cheaper than a real clip."""
        return any(self.contains(p) for p in points)

    def expanded(self, degrees: float) -> "BBox":
        return BBox(
            self.west - degrees, self.south - degrees, self.east + degrees, self.north + degrees
        )

    def quantized(self, places: int) -> "BBox":
        """Snap outward to a grid, so nearby requests share a cache key.

        Rounding *outward* matters: a result cached under the snapped box is
        then always at least as large as the box actually asked for.
        """
        step = 10.0**-places
        return BBox(
            _floor_to(self.west, step),
            _floor_to(self.south, step),
            _ceil_to(self.east, step),
            _ceil_to(self.north, step),
        )


def _floor_to(value: float, step: float) -> float:
    return round((value // step) * step, 9)


def _ceil_to(value: float, step: float) -> float:
    return round(-((-value) // step) * step, 9)


def haversine_m(a: Coord, b: Coord) -> float:
    """Great-circle distance in meters between two ``(lon, lat)`` pairs."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def polyline_length_m(points: Sequence[Coord]) -> float:
    """Summed great-circle length of a coordinate sequence."""
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))


def bounds_of(points: Iterable[Coord]) -> tuple[float, float, float, float]:
    """``(west, south, east, north)`` of any iterable of coordinates."""
    pts = tuple(points)
    if not pts:
        raise ValueError("no points")
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return (min(lons), min(lats), max(lons), max(lats))
