"""Where road conditions are kept, and how they are asked about.

Conditions are the one thing this server holds that a human entered and cannot
regenerate. A road network can be rebuilt from Overpass and a traffic reading
is replaced within the minute, but "this street is closed until Friday" exists
only because someone said so -- so conditions are persisted through the
storage interface rather than held in memory, and they survive a restart.

Two questions, and they are asked by different callers for different reasons:

* :meth:`RoadStateStore.active_in` -- what is in force here, now. The API
  answers a client with this, and it includes everything: a works site a
  driver should see on the map, not only what changes a route.
* :meth:`RoadStateStore.blocked_road_ids` -- what cannot be driven. Routing
  reads this, through the provider, and it is deliberately narrower.

Neither knows SQLite exists. The store holds a
:class:`storage.DocumentStore` and converts conditions to documents on the way
in -- that conversion lives here, next to the type, because storage is not
allowed to know what a closure is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from domain import BBox
from storage import Collection, DocumentStore, StoredDocument

from .models import ConditionKind, RoadCondition, RoadStateSnapshot, Severity

__all__ = ["RoadStateStore", "DEFAULT_OPEN_ENDED_TTL"]

#: How long a condition with no end time stays in force before the store stops
#: reporting it. Six hours: long enough for a genuine closure to be renewed by
#: the feed that published it, short enough that a crash nobody withdrew stops
#: diverting traffic the same evening. Feeds that do publish an end time are
#: unaffected -- their window is used as given.
DEFAULT_OPEN_ENDED_TTL = timedelta(hours=6)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoadStateStore:
    """Road conditions, persisted and queried by area and time.

    Args:
        documents: Where conditions are kept.
        open_ended_ttl: How long a condition with no ``ends_at`` is honoured.
        clock: Returns the current aware UTC time. Injected for tests.
    """

    def __init__(
        self,
        documents: DocumentStore,
        *,
        open_ended_ttl: timedelta = DEFAULT_OPEN_ENDED_TTL,
        clock=_utcnow,
    ) -> None:
        self._documents = documents
        self._open_ended_ttl = open_ended_ttl
        self._clock = clock

    # --- Writing -----------------------------------------------------------

    def record(self, conditions: Iterable[RoadCondition]) -> int:
        """Persist conditions, replacing any already held under the same id."""
        return self._documents.put(_document_of(c) for c in conditions)

    def withdraw(self, condition_id: str) -> bool:
        """Remove one condition. ``False`` when it was not there.

        Used when a feed says an incident has cleared, and when an operator
        cancels one they entered.
        """
        return self._documents.delete(Collection.ROAD_CONDITIONS, condition_id)

    def prune(self, *, older_than: timedelta) -> int:
        """Drop conditions recorded before a cutoff. Returns how many went."""
        return self._documents.prune(
            Collection.ROAD_CONDITIONS, recorded_before=self._clock() - older_than
        )

    # --- Reading -----------------------------------------------------------

    def active_in(self, area: BBox, at: datetime | None = None) -> tuple[RoadCondition, ...]:
        """Every condition in force in ``area`` at ``at`` (default: now).

        The storage layer filters by area and by the stored validity window;
        the open-ended cutoff is applied here, because "how long do we believe
        an incident nobody withdrew" is road-state policy and storage holds no
        policy.
        """
        moment = at or self._clock()
        found = self._documents.find(Collection.ROAD_CONDITIONS, bbox=area.as_tuple(), at=moment)
        conditions = (_condition_of(document) for document in found)
        return tuple(
            condition
            for condition in conditions
            if self._still_believed(condition, moment)
        )

    def snapshot(self, area: BBox, at: datetime | None = None) -> RoadStateSnapshot:
        moment = at or self._clock()
        return RoadStateSnapshot(
            area=area,
            taken_at=moment,
            conditions=self.active_in(area, moment),
        )

    def blocked_road_ids(self, area: BBox, at: datetime | None = None) -> frozenset[str]:
        """Published road ids that may not be driven in ``area`` right now."""
        return frozenset(
            road_id
            for condition in self.active_in(area, at)
            if condition.blocking
            for road_id in condition.road_ids
        )

    def get(self, condition_id: str) -> RoadCondition | None:
        document = self._documents.get(Collection.ROAD_CONDITIONS, condition_id)
        return _condition_of(document) if document else None

    def count(self) -> int:
        return self._documents.count(Collection.ROAD_CONDITIONS)

    def stats(self) -> dict[str, object]:
        return {"stored": self.count(), "open_ended_ttl_s": self._open_ended_ttl.total_seconds()}

    # --- Policy ------------------------------------------------------------

    def _still_believed(self, condition: RoadCondition, moment: datetime) -> bool:
        if condition.ends_at is not None:
            return True
        start = condition.starts_at or condition.reported_at
        return (moment - start) <= self._open_ended_ttl


def _document_of(condition: RoadCondition) -> StoredDocument:
    area = condition.area
    return StoredDocument(
        collection=Collection.ROAD_CONDITIONS,
        key=condition.id,
        west=area.west,
        south=area.south,
        east=area.east,
        north=area.north,
        recorded_at=condition.reported_at,
        valid_from=condition.starts_at,
        valid_to=condition.ends_at,
        payload=condition.to_payload(),
    )


def _condition_of(document: StoredDocument) -> RoadCondition:
    payload = document.payload
    return RoadCondition(
        id=payload["id"],
        kind=ConditionKind(payload["kind"]),
        severity=Severity(payload["severity"]),
        geometry=tuple(tuple(point) for point in payload["geometry"]),
        source=payload["source"],
        road_ids=tuple(payload.get("road_ids", ())),
        reported_at=_moment(payload["reported_at"]),
        starts_at=_moment(payload.get("starts_at")),
        ends_at=_moment(payload.get("ends_at")),
        blocking=bool(payload.get("blocking", False)),
        description=payload.get("description"),
        metadata=dict(payload.get("metadata", {})),
    )


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None
