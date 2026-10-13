"""What a normalized observation is made of.

Three record kinds, because open traffic data really does come in three
shapes and flattening them would be a lie:

* :class:`TrafficObservation` -- a measurement at a *point*. This is what a
  loop detector or a radar mast produces, and it is what almost every free
  government feed publishes. It has a position, not an extent.
* :class:`TrafficSegment` -- a *stretch* of road carrying a measured or
  modelled speed.
* :class:`TrafficIncident` -- an *event* with a validity window: a crash, a
  road work, a closure.
* :class:`GpsProbe` -- one position report from a client. The only record kind
  this server produces itself rather than reading from somewhere else.

**None of them carries a traffic level**, and that absence is this block's
boundary rule showing up in the type system. A level is not a measurement, it
is a judgement about one, and the thresholds behind that judgement are domain
policy belonging to `roadstate`. What leaves this block is what the source
said: a speed, a free-flow reference, and the ratio between them. What that
ratio *means* is decided one block downstream, in one place, for every
provider at once.

A :class:`Observations` batch is all three record kinds from one provider for
one box at one moment. It is immutable, because it is evidence of what a
source reported when it was asked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Sequence

from domain import BBox, Coord, polyline_length_m

__all__ = [
    "Coord",
    "BBox",
    "TrafficObservation",
    "TrafficSegment",
    "IncidentKind",
    "Severity",
    "TrafficIncident",
    "Observations",
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
        """Measured speed over free flow, or ``None`` when either is missing.

        The only interpretation this block performs, and it is arithmetic
        rather than judgement: what fraction of clear-road speed the traffic
        is actually doing.
        """
        if self.speed_kph is None or not self.free_flow_kph:
            return None
        return self.speed_kph / self.free_flow_kph


@dataclass(frozen=True, slots=True)
class TrafficSegment:
    """A stretch of road with a speed reported for it.

    ``road_id`` is the hook back into the published road network -- the
    ``RoadSegment.id`` a provider derived this from, where it derived it from
    one. A provider that measured a stretch without knowing which published
    road it is leaves it ``None``: the record is still drawable, just not
    attributable.
    """

    id: str
    geometry: tuple[Coord, ...]
    observed_at: datetime
    source: str
    speed_kph: float | None = None
    free_flow_kph: float | None = None
    confidence: float = 1.0
    road_name: str | None = None
    road_class: str | None = None
    road_id: str | None = None

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
        return polyline_length_m(self.geometry)

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

    ``blocking`` is the field a router actually cares about: it is the
    difference between "slower here" and "you cannot go this way".
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
    road_ids: tuple[str, ...] = ()

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
class Observations:
    """Everything one provider reported for one box at one moment.

    This is the block's output type -- what crosses the `ingest -> roadstate`
    connector. It carries provenance (``source``, ``observed_at``) and the
    records themselves, and deliberately nothing else: no merging across
    providers, no levels, no serialisation. Those are all decisions, and
    decisions belong downstream.
    """

    bbox: BBox
    source: str
    observed_at: datetime = field(default_factory=_utcnow)
    segments: tuple[TrafficSegment, ...] = ()
    observations: tuple[TrafficObservation, ...] = ()
    incidents: tuple[TrafficIncident, ...] = ()

    @classmethod
    def empty(cls, bbox: BBox, source: str) -> "Observations":
        return cls(bbox=bbox, source=source)

    @property
    def is_empty(self) -> bool:
        return not (self.segments or self.observations or self.incidents)

    @property
    def is_simulated(self) -> bool:
        return self.source == SIMULATED_SOURCE

    def counts(self) -> dict[str, int]:
        return {
            "segments": len(self.segments),
            "observations": len(self.observations),
            "incidents": len(self.incidents),
        }


def coords_of(pairs: Iterable[Sequence[float]]) -> tuple[Coord, ...]:
    """Normalise any iterable of lon/lat pairs into a coordinate tuple."""
    return tuple((float(p[0]), float(p[1])) for p in pairs)
