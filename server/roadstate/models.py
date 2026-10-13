"""What a road condition is: something temporarily true about a road.

The distinction from `traffic` is the one this block exists to hold. Traffic
is a measurement that decays -- a speed, true for minutes, replaced by the next
reading. A condition is a *statement with a validity window*: this street is
closed from Tuesday, this underpass floods when it rains, these works run
until the end of the month. It does not decay, it ends; and until it does, it
is as true at 3 a.m. as at rush hour.

That difference has a consequence routing cares about. A jam makes a road
slower. A closure makes it unusable, and expressing that as a very large cost
rather than as a prohibition is the classic navigation bug: when nothing else
connects, the search happily "uses" the closed road and returns a route down a
flooded street instead of reporting that there is none.

So every condition declares which it is, through :attr:`RoadCondition.blocking`,
and the provider sends the two down different paths -- blocking conditions
become request constraints, the rest become cost multipliers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from domain import BBox, Coord, bounds_of

__all__ = [
    "ConditionKind",
    "Severity",
    "RoadCondition",
    "RoadStateSnapshot",
    "DEFAULT_MULTIPLIERS",
]


class ConditionKind(str, Enum):
    """What is wrong with the road.

    Deliberately coarse, and deliberately the same vocabulary the free
    upstream feeds use, so normalising an incident does not require inventing
    a category it has to be squeezed into.
    """

    CLOSURE = "closure"
    FLOODING = "flooding"
    CONSTRUCTION = "construction"
    INCIDENT = "incident"
    RESTRICTION = "restriction"
    HAZARD = "hazard"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]


#: How much a non-blocking condition of each kind slows a road, by severity.
#: These are product decisions, not measurements, and they live in one table
#: so that changing what "a flooded road at medium severity costs" is a
#: one-line edit rather than a hunt through four modules.
#:
#: Every value is at least 1.0. A condition may slow a road down, never speed
#: it up -- routing rejects anything lower because it would make the A*
#: heuristic inadmissible, which returns a worse route silently.
DEFAULT_MULTIPLIERS: Mapping[ConditionKind, Mapping[Severity, float]] = {
    ConditionKind.FLOODING: {
        Severity.LOW: 1.6,
        Severity.MEDIUM: 2.5,
        Severity.HIGH: 4.0,
        Severity.CRITICAL: 6.0,
    },
    ConditionKind.CONSTRUCTION: {
        Severity.LOW: 1.2,
        Severity.MEDIUM: 1.6,
        Severity.HIGH: 2.5,
        Severity.CRITICAL: 4.0,
    },
    ConditionKind.INCIDENT: {
        Severity.LOW: 1.3,
        Severity.MEDIUM: 2.0,
        Severity.HIGH: 3.0,
        Severity.CRITICAL: 5.0,
    },
    ConditionKind.RESTRICTION: {
        Severity.LOW: 1.1,
        Severity.MEDIUM: 1.4,
        Severity.HIGH: 2.0,
        Severity.CRITICAL: 3.0,
    },
    ConditionKind.HAZARD: {
        Severity.LOW: 1.2,
        Severity.MEDIUM: 1.6,
        Severity.HIGH: 2.5,
        Severity.CRITICAL: 4.0,
    },
    # A closure has no multiplier: it is always blocking, and the provider
    # never reaches this table for it.
    ConditionKind.CLOSURE: {
        Severity.LOW: 1.0,
        Severity.MEDIUM: 1.0,
        Severity.HIGH: 1.0,
        Severity.CRITICAL: 1.0,
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RoadCondition:
    """One thing that is temporarily true about one or more roads.

    Attributes:
        id: Stable, and carrying its provenance
            (``digitraffic:GUID``, ``operator:2026-09-13-1``). Re-reporting
            the same event under the same id replaces it rather than
            accumulating duplicates, which every republishing feed requires.
        kind: What is wrong.
        severity: How badly.
        road_ids: Published roads this applies to. May be empty when a feed
            gave geometry but no road reference -- the condition is still
            reportable and drawable, just not routable, and saying so is
            better than attaching it to a guess.
        geometry: Where it is, longitude first. A point for a crash, a line
            for a closed stretch.
        source: Who said so.
        reported_at: When the server learned of it.
        starts_at / ends_at: The validity window. ``None`` at either end means
            open -- several feeds publish a closure with no end time and
            simply withdraw it once the road reopens.
        blocking: Whether the road is unusable, as opposed to merely worse.
            A closure is always blocking; everything else defaults to not.
        description: Free text for a human, never parsed.
    """

    id: str
    kind: ConditionKind
    severity: Severity
    geometry: tuple[Coord, ...]
    source: str
    road_ids: tuple[str, ...] = ()
    reported_at: datetime = field(default_factory=_utcnow)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    blocking: bool = False
    description: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("a road condition needs an id")
        if not self.geometry:
            raise ValueError(f"road condition {self.id!r} needs geometry")
        for name in ("reported_at", "starts_at", "ends_at"):
            moment = getattr(self, name)
            if moment is not None and moment.tzinfo is None:
                raise ValueError(f"road condition {self.id!r} has a naive {name}")
        if self.kind is ConditionKind.CLOSURE and not self.blocking:
            raise ValueError(
                f"road condition {self.id!r} is a closure that is not blocking. "
                "A closed road that a route may still use is not a closure; "
                "record it as a restriction instead"
            )

    @property
    def area(self) -> BBox:
        west, south, east, north = bounds_of(self.geometry)
        return BBox(west, south, east, north)

    @property
    def is_point(self) -> bool:
        return len(self.geometry) == 1

    def active_at(self, moment: datetime | None = None) -> bool:
        """Whether this is in force at ``moment`` (default: now)."""
        when = moment or _utcnow()
        if self.starts_at is not None and when < self.starts_at:
            return False
        if self.ends_at is not None and when > self.ends_at:
            return False
        return True

    def multiplier(
        self, table: Mapping[ConditionKind, Mapping[Severity, float]] = DEFAULT_MULTIPLIERS
    ) -> float:
        """How much this slows a road. 1.0 for a blocking condition.

        Blocking returns 1.0 rather than infinity on purpose: a blocked road is
        excluded by a constraint, and giving it a cost as well would mean two
        mechanisms had to agree about one fact.
        """
        if self.blocking:
            return 1.0
        return max(1.0, table.get(self.kind, {}).get(self.severity, 1.0))

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "road_ids": list(self.road_ids),
            "geometry": [list(point) for point in self.geometry],
            "source": self.source,
            "reported_at": self.reported_at.isoformat(),
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "blocking": self.blocking,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RoadStateSnapshot:
    """Every condition in force in one area at one moment."""

    area: BBox
    taken_at: datetime
    conditions: tuple[RoadCondition, ...] = ()

    @property
    def blocking(self) -> tuple[RoadCondition, ...]:
        return tuple(c for c in self.conditions if c.blocking)

    def of_kind(self, kind: ConditionKind) -> tuple[RoadCondition, ...]:
        return tuple(c for c in self.conditions if c.kind is kind)

    def blocked_road_ids(self) -> frozenset[str]:
        return frozenset(rid for c in self.blocking for rid in c.road_ids)

    def counts(self) -> dict[str, int]:
        counts = {kind.value: 0 for kind in ConditionKind}
        for condition in self.conditions:
            counts[condition.kind.value] += 1
        return counts

    def meta(self) -> dict[str, Any]:
        return {
            "area": list(self.area.as_tuple()),
            "taken_at": self.taken_at.isoformat(),
            "total": len(self.conditions),
            "blocking": len(self.blocking),
            "by_kind": self.counts(),
        }
