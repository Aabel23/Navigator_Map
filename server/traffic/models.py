"""What traffic *state* is made of, as opposed to what was observed.

The distinction is the boundary between this block and `ingest`, and it is
worth being precise about because the two look similar from a distance.

An ingest record is evidence: a sensor at this point reported this speed at
this time, from this source. A :class:`RoadSpeed` is a conclusion: *this
published road* is currently moving at this fraction of its free-flow speed,
which puts it at this level, and here is how much confidence that deserves.
Getting from one to the other means attaching a measurement to a road,
choosing between measurements that disagree, and applying a threshold table --
three judgements, all of which belong here and none of which belong in a
provider.

:class:`TrafficSnapshot` is the whole picture for one area at one moment: the
road speeds plus the incidents that were not attributable to any one road.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from domain import BBox, Coord

from .levels import TrafficLevel, level_for_ratio

__all__ = ["RoadSpeed", "TrafficSnapshot", "SIMULATED_SOURCE"]

#: The source name that marks modelled rather than measured numbers. Anything
#: that must not act on invented data checks for this exact string, and the
#: API reports it so a driver is never shown a model as a measurement.
SIMULATED_SOURCE = "simulated"


@dataclass(frozen=True, slots=True)
class RoadSpeed:
    """How fast one published road is moving right now.

    Attributes:
        road_id: The :class:`mapdata.RoadSegment` id this is about. This is
            the join key for everything downstream -- the cost provider turns
            it into edge ids, the API reports it, and a client colours by it.
        speed_kph: Current speed. ``None`` when only a ratio is known.
        free_flow_kph: The reference this is measured against.
        observed_at: When the underlying measurement was taken, not when it
            was processed. A stale reading must be recognisable as stale.
        source: Which provider it came from. ``"simulated"`` means modelled.
        confidence: 0-1. A modelled number carries a low one so a real sensor
            always wins the merge.
        sample_count: How many observations were combined into this.
    """

    road_id: str
    speed_kph: float | None
    free_flow_kph: float
    observed_at: datetime
    source: str
    confidence: float = 1.0
    sample_count: int = 1

    def __post_init__(self) -> None:
        if self.free_flow_kph <= 0:
            raise ValueError(f"road {self.road_id!r} has a non-positive free flow")
        if self.observed_at.tzinfo is None:
            raise ValueError(f"road {self.road_id!r} has a naive observation time")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"road {self.road_id!r} has confidence outside 0-1")

    @property
    def ratio(self) -> float | None:
        """Current speed over free flow, or ``None`` without a speed."""
        if self.speed_kph is None:
            return None
        return self.speed_kph / self.free_flow_kph

    @property
    def level(self) -> TrafficLevel:
        return level_for_ratio(self.ratio)

    @property
    def is_simulated(self) -> bool:
        return self.source == SIMULATED_SOURCE

    def age_s(self, now: datetime | None = None) -> float:
        moment = now or datetime.now(timezone.utc)
        return (moment - self.observed_at).total_seconds()

    def is_fresh(self, *, max_age_s: float, now: datetime | None = None) -> bool:
        return self.age_s(now) <= max_age_s

    def beats(self, other: "RoadSpeed") -> bool:
        """Whether this reading should replace ``other`` for the same road.

        Measured beats modelled, then higher confidence, then newer. The
        ordering matters: a fresh model must never displace a sensor reading
        taken a minute ago, because "recent" and "true" are different
        properties and only one of them is what a driver needs.
        """
        if self.is_simulated != other.is_simulated:
            return other.is_simulated
        if abs(self.confidence - other.confidence) > 1e-9:
            return self.confidence > other.confidence
        return self.observed_at > other.observed_at

    def to_payload(self) -> dict[str, object]:
        return {
            "road_id": self.road_id,
            "speed_kph": self.speed_kph,
            "free_flow_kph": self.free_flow_kph,
            "ratio": self.ratio,
            "level": self.level.slug,
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
            "confidence": self.confidence,
            "sample_count": self.sample_count,
            "simulated": self.is_simulated,
        }


@dataclass(frozen=True, slots=True)
class TrafficSnapshot:
    """Road speeds for one area at one moment, plus what produced them.

    Immutable: a snapshot is evidence of what the server believed when it was
    taken, so anything that would change it returns a new one.
    """

    area: BBox
    taken_at: datetime
    speeds: tuple[RoadSpeed, ...] = ()
    sources: tuple[str, ...] = ()
    failures: tuple[tuple[str, str], ...] = ()

    @classmethod
    def empty(cls, area: BBox) -> "TrafficSnapshot":
        return cls(area=area, taken_at=datetime.now(timezone.utc))

    @property
    def is_empty(self) -> bool:
        return not self.speeds

    @property
    def is_simulated(self) -> bool:
        """True when every reading here is modelled rather than measured."""
        return bool(self.speeds) and all(speed.is_simulated for speed in self.speeds)

    def by_road(self) -> dict[str, RoadSpeed]:
        return {speed.road_id: speed for speed in self.speeds}

    def worst_first(self) -> tuple[RoadSpeed, ...]:
        return tuple(sorted(self.speeds, key=lambda s: (-int(s.level), s.road_id)))

    def meta(self) -> dict[str, object]:
        return {
            "area": list(self.area.as_tuple()),
            "taken_at": self.taken_at.isoformat(),
            "roads": len(self.speeds),
            "sources": list(self.sources),
            "simulated": self.is_simulated,
            "failures": [{"source": name, "error": text} for name, text in self.failures],
        }
