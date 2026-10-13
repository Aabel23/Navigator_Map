"""What a traffic report is made of.

Three record kinds, because open traffic data really does come in three
shapes and flattening them would be a lie:

* :class:`TrafficObservation` -- a measurement at a *point*. This is what a
  loop detector or a radar mast produces, and it is what almost every free
  government feed publishes. It has a position, not an extent.
* :class:`TrafficSegment` -- a *stretch* of road carrying a level. This is
  what a driver expects to see coloured on a map, and what the routing cost
  model can price.
* :class:`TrafficIncident` -- an *event* with a validity window: a crash, a
  road work, a closure. Its geometry may be a point or a line.

A :class:`TrafficSnapshot` is all three for one bounding box at one moment,
and it is immutable: a snapshot is evidence of what was true when it was
taken, so anything that changes it returns a new one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from . import geo
from .geo import Coord
from .levels import TrafficLevel, level_for_speed

__all__ = [
    "Coord",
    "BBox",
    "RoadSegment",
    "TrafficObservation",
    "TrafficSegment",
    "IncidentKind",
    "Severity",
    "TrafficIncident",
    "TrafficSnapshot",
    "SIMULATED_SOURCE",
    "coords_of",
]

#: The source name a provider must use when its numbers are modelled rather
#: than measured. Anything downstream that must not act on invented data
#: checks for this exact string.
SIMULATED_SOURCE = "simulated"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class BBox:
    """A lon/lat rectangle in degrees, west/south/east/north.

    Does not cross the anti-meridian. Every provider takes one of these and
    every snapshot records the one it was fetched for, so a cached snapshot
    can never be served for an area it does not cover.
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
        """Read "west,south,east,north" -- the order a URL query uses."""
        parts = text.split(",")
        if len(parts) != 4:
            raise ValueError(f"expected west,south,east,north -- got {text!r}")
        return cls(*(float(p) for p in parts))

    @classmethod
    def around(cls, lon: float, lat: float, half_degrees: float) -> "BBox":
        return cls(lon - half_degrees, lat - half_degrees, lon + half_degrees, lat + half_degrees)

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
        """True when any vertex falls inside. Cheaper than a real clip.

        A line whose vertices all fall outside but whose span crosses the box
        is missed. That is deliberate: providers are asked for a padded box,
        so a rare missed segment at the edge costs a pixel or two of nothing,
        while a real intersection test on every vertex of every polyline is
        paid on every pan.
        """
        return any(self.contains(p) for p in points)

    def expanded(self, degrees: float) -> "BBox":
        return BBox(
            self.west - degrees, self.south - degrees, self.east + degrees, self.north + degrees
        )

    def quantized(self, places: int) -> "BBox":
        """Snap outward to a grid, so nearby viewports share a cache key.

        Rounding *outward* matters: a snapshot cached under the snapped box is
        then always at least as large as the box that was actually asked for.
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


@dataclass(frozen=True, slots=True)
class RoadSegment:
    """A piece of the reference road network that traffic attaches to.

    This block does not own road geometry -- it borrows it. Every traffic
    provider needs some network to hang numbers on, and this is the shape
    that network arrives in, whoever supplies it.
    """

    id: str
    geometry: tuple[Coord, ...]
    road_class: str
    free_flow_kph: float
    name: str | None = None
    oneway: bool = False

    @property
    def length_m(self) -> float:
        return geo.polyline_length_m(self.geometry)


@dataclass(frozen=True, slots=True)
class TrafficObservation:
    """One speed measurement at one point, in one direction of travel.

    ``bearing`` is the direction the measured traffic is heading, not the
    orientation of the sensor. A two-way sensor site produces two of these.
    """

    id: str
    point: Coord
    observed_at: datetime
    source: str
    speed_kph: float | None = None
    free_flow_kph: float | None = None
    flow_vph: float | None = None
    bearing: float | None = None
    confidence: float = 1.0
    road_name: str | None = None

    @property
    def ratio(self) -> float | None:
        if self.speed_kph is None or not self.free_flow_kph:
            return None
        return self.speed_kph / self.free_flow_kph

    @property
    def level(self) -> TrafficLevel:
        return level_for_speed(self.speed_kph, self.free_flow_kph)


@dataclass(frozen=True, slots=True)
class TrafficSegment:
    """A stretch of road with a traffic level on it.

    ``edge_id`` is the hook into the routing graph. When a provider knows
    which routing edge a segment is, the cost model can price it directly;
    when it does not, the segment is still drawable, just not routable.
    """

    id: str
    geometry: tuple[Coord, ...]
    level: TrafficLevel
    observed_at: datetime
    source: str
    speed_kph: float | None = None
    free_flow_kph: float | None = None
    confidence: float = 1.0
    road_name: str | None = None
    road_class: str | None = None
    edge_id: str | None = None

    def __post_init__(self) -> None:
        if len(self.geometry) < 2:
            raise ValueError(f"segment {self.id!r} needs at least 2 points")

    @property
    def ratio(self) -> float | None:
        if self.speed_kph is None or not self.free_flow_kph:
            return None
        return self.speed_kph / self.free_flow_kph

    @property
    def length_m(self) -> float:
        return geo.polyline_length_m(self.geometry)

    @property
    def delay_s(self) -> float | None:
        """Seconds lost on this segment against driving it at free flow."""
        if not self.speed_kph or not self.free_flow_kph:
            return None
        km = self.length_m / 1000.0
        return (km / self.speed_kph - km / self.free_flow_kph) * 3600.0


class IncidentKind(str, Enum):
    """What happened.

    Deliberately coarse. Every feed words this its own way, and a driver only
    needs to know which icon to expect.
    """

    ACCIDENT = "accident"
    ROADWORKS = "roadworks"
    CLOSURE = "closure"
    HAZARD = "hazard"
    WEATHER = "weather"
    EVENT = "event"
    RESTRICTION = "restriction"
    OTHER = "other"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class TrafficIncident:
    """An event on the network, with a validity window.

    ``blocking`` is the field routing actually cares about: it is the
    difference between "slower here" and "you cannot go this way", and it is
    the only thing in this block that produces an infinite edge cost.
    """

    id: str
    kind: IncidentKind
    severity: Severity
    geometry: tuple[Coord, ...]
    source: str
    reported_at: datetime
    title: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    road_name: str | None = None
    blocking: bool = False
    speed_limit_kph: float | None = None
    edge_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.geometry:
            raise ValueError(f"incident {self.id!r} needs geometry")

    @property
    def is_point(self) -> bool:
        return len(self.geometry) == 1

    def active_at(self, when: datetime | None = None) -> bool:
        """Whether the event is in force at ``when`` (default: now).

        An event with no window is treated as in force: several feeds publish
        an incident with no end time and withdraw it once it clears.
        """
        moment = when or _utcnow()
        if self.starts_at and moment < self.starts_at:
            return False
        if self.ends_at and moment > self.ends_at:
            return False
        return True


@dataclass(frozen=True, slots=True)
class TrafficSnapshot:
    """Everything known about traffic in one box at one moment.

    Immutable. :meth:`merge` and :meth:`clip` return new snapshots rather than
    editing this one, so a snapshot handed to the cost model cannot change
    underneath it mid-route.
    """

    bbox: BBox
    observed_at: datetime = field(default_factory=_utcnow)
    sources: tuple[str, ...] = ()
    segments: tuple[TrafficSegment, ...] = ()
    observations: tuple[TrafficObservation, ...] = ()
    incidents: tuple[TrafficIncident, ...] = ()

    @classmethod
    def empty(cls, bbox: BBox, source: str | None = None) -> "TrafficSnapshot":
        return cls(bbox=bbox, sources=(source,) if source else ())

    @property
    def is_empty(self) -> bool:
        return not (self.segments or self.observations or self.incidents)

    @property
    def is_simulated(self) -> bool:
        """True when every source that contributed was a model, not a sensor."""
        return bool(self.sources) and all(s == SIMULATED_SOURCE for s in self.sources)

    def counts(self) -> dict[str, int]:
        return {
            "segments": len(self.segments),
            "observations": len(self.observations),
            "incidents": len(self.incidents),
        }

    def merge(self, other: "TrafficSnapshot") -> "TrafficSnapshot":
        """Union of two snapshots, keeping the newer record per id.

        Two providers covering the same road is the normal case once a
        measured feed and a modelled one are both configured, and the newer
        reading is the one to keep.
        """
        bbox = BBox(
            min(self.bbox.west, other.bbox.west),
            min(self.bbox.south, other.bbox.south),
            max(self.bbox.east, other.bbox.east),
            max(self.bbox.north, other.bbox.north),
        )
        return TrafficSnapshot(
            bbox=bbox,
            observed_at=max(self.observed_at, other.observed_at),
            sources=tuple(dict.fromkeys(self.sources + other.sources)),
            segments=_newest_by_id(self.segments, other.segments, lambda s: s.observed_at),
            observations=_newest_by_id(
                self.observations, other.observations, lambda o: o.observed_at
            ),
            incidents=_newest_by_id(self.incidents, other.incidents, lambda i: i.reported_at),
        )

    def clip(self, bbox: BBox) -> "TrafficSnapshot":
        """Drop everything that does not touch ``bbox``."""
        return replace(
            self,
            bbox=bbox,
            segments=tuple(s for s in self.segments if bbox.touches_any(s.geometry)),
            observations=tuple(o for o in self.observations if bbox.contains(o.point)),
            incidents=tuple(i for i in self.incidents if bbox.touches_any(i.geometry)),
        )

    def active(self, when: datetime | None = None) -> "TrafficSnapshot":
        """Drop incidents whose validity window does not include ``when``."""
        return replace(self, incidents=tuple(i for i in self.incidents if i.active_at(when)))

    def meta(self) -> dict[str, Any]:
        """The snapshot provenance, without its geometry.

        Served alongside the GeoJSON so a client can say where the numbers
        came from and how old they are without walking every feature.
        """
        return {
            "bbox": list(self.bbox.as_tuple()),
            "observed_at": self.observed_at.isoformat(),
            "sources": list(self.sources),
            "simulated": self.is_simulated,
            "counts": self.counts(),
        }

    def to_geojson(self) -> dict[str, Any]:
        """A plain FeatureCollection, one feature per record.

        Every feature carries a ``record`` property -- segment, observation or
        incident -- because the three draw differently and a renderer should
        not have to infer that from the geometry type.
        """
        features: list[dict[str, Any]] = []
        features.extend(_segment_feature(s) for s in self.segments)
        features.extend(_observation_feature(o) for o in self.observations)
        features.extend(_incident_feature(i) for i in self.incidents)
        return {"type": "FeatureCollection", "features": features}


def _newest_by_id(
    first: Sequence[Any], second: Sequence[Any], stamp: Callable[[Any], datetime]
) -> tuple[Any, ...]:
    merged: dict[str, Any] = {}
    for record in list(first) + list(second):
        existing = merged.get(record.id)
        if existing is None or stamp(record) >= stamp(existing):
            merged[record.id] = record
    return tuple(merged.values())


def _line_geometry(points: Sequence[Coord]) -> dict[str, Any]:
    if len(points) == 1:
        return {"type": "Point", "coordinates": [points[0][0], points[0][1]]}
    return {"type": "LineString", "coordinates": [[lon, lat] for lon, lat in points]}


def _segment_feature(s: TrafficSegment) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": _line_geometry(s.geometry),
        "properties": {
            "record": "segment",
            "id": s.id,
            "level": int(s.level),
            "level_slug": s.level.slug,
            "speed_kph": s.speed_kph,
            "free_flow_kph": s.free_flow_kph,
            "ratio": s.ratio,
            "confidence": s.confidence,
            "road_name": s.road_name,
            "road_class": s.road_class,
            "edge_id": s.edge_id,
            "source": s.source,
            "observed_at": s.observed_at.isoformat(),
        },
    }


def _observation_feature(o: TrafficObservation) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [o.point[0], o.point[1]]},
        "properties": {
            "record": "observation",
            "id": o.id,
            "level": int(o.level),
            "level_slug": o.level.slug,
            "speed_kph": o.speed_kph,
            "free_flow_kph": o.free_flow_kph,
            "ratio": o.ratio,
            "flow_vph": o.flow_vph,
            "bearing": o.bearing,
            "confidence": o.confidence,
            "road_name": o.road_name,
            "source": o.source,
            "observed_at": o.observed_at.isoformat(),
        },
    }


def _incident_feature(i: TrafficIncident) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": _line_geometry(i.geometry),
        "properties": {
            "record": "incident",
            "id": i.id,
            "kind": i.kind.value,
            "severity": i.severity.value,
            "blocking": i.blocking,
            "title": i.title,
            "description": i.description,
            "road_name": i.road_name,
            "speed_limit_kph": i.speed_limit_kph,
            "starts_at": i.starts_at.isoformat() if i.starts_at else None,
            "ends_at": i.ends_at.isoformat() if i.ends_at else None,
            "source": i.source,
            "reported_at": i.reported_at.isoformat(),
        },
    }


def coords_of(pairs: Iterable[Sequence[float]]) -> tuple[Coord, ...]:
    """Normalise any iterable of lon/lat pairs into a coordinate tuple."""
    return tuple((float(p[0]), float(p[1])) for p in pairs)
