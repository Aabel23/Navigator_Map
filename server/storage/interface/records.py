"""The one row shape every storage backend keeps.

A stored document is an opaque payload with three things a server can ask
about it: which collection it belongs to, which piece of the world it covers,
and when it was true. Everything else is JSON.

That generality is the block's boundary rule made concrete. Storage is not
allowed to know what a road, an observation or a closure *is*; if it held a
``road_class`` column it would be holding a piece of map-data policy, and the
next schema change to a domain type would become a database migration. Instead
each domain block converts its own types to and from a payload, keeps that
conversion next to the type it belongs to, and storage stays a place to put
bytes and find them again.

What storage *does* know is the two axes the whole system queries on -- an
area and a moment -- because those are indexable and a JSON blob is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

__all__ = ["Collection", "StoredDocument", "utcnow"]


class Collection:
    """The collection names in use, so a typo is an import error.

    Not an enum: a backend stores whatever string it is given, and a future
    block may add a collection without this module changing. These are the
    ones that exist today.
    """

    ROADS = "roads"
    OBSERVATIONS = "observations"
    ROAD_CONDITIONS = "road_conditions"

    ALL = (ROADS, OBSERVATIONS, ROAD_CONDITIONS)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """One persisted record.

    Attributes:
        collection: Which family of records this belongs to. See
            :class:`Collection`.
        key: Unique within its collection. Writing the same key twice replaces
            the document -- an upstream feed republishing the same incident
            must not accumulate copies.
        west, south, east, north: The area this document covers, in degrees.
            A point document sets west == east and south == north. This is the
            only geographic index a backend is required to provide.
        recorded_at: When the server stored it. Always set.
        valid_from: When the fact starts being true. ``None`` means "already".
        valid_to: When it stops. ``None`` means "until withdrawn" -- several
            free feeds publish an incident with no end time and simply remove
            it once it clears.
        payload: The domain object, as JSON-serialisable data. Storage never
            reads inside it.
    """

    collection: str
    key: str
    west: float
    south: float
    east: float
    north: float
    payload: Mapping[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=utcnow)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        if not self.collection:
            raise ValueError("a document needs a collection")
        if not self.key:
            raise ValueError("a document needs a key")
        if self.west > self.east or self.south > self.north:
            raise ValueError(f"document {self.key!r} has an inverted bounding box")
        for name in ("recorded_at", "valid_from", "valid_to"):
            moment = getattr(self, name)
            if moment is not None and moment.tzinfo is None:
                raise ValueError(
                    f"document {self.key!r} has a naive {name}; storage keeps UTC "
                    "instants, and guessing a zone is wrong by whole hours with "
                    "nothing looking broken"
                )

    def as_area(self) -> tuple[float, float, float, float]:
        """``(west, south, east, north)``, the shape every query filter uses."""
        return (self.west, self.south, self.east, self.north)

    def active_at(self, moment: datetime) -> bool:
        """Whether this document's validity window contains ``moment``."""
        if self.valid_from is not None and moment < self.valid_from:
            return False
        if self.valid_to is not None and moment > self.valid_to:
            return False
        return True

    def intersects(self, west: float, south: float, east: float, north: float) -> bool:
        if self.east < west or east < self.west:
            return False
        return not (self.north < south or north < self.south)
