"""Published road segments, kept and found again through the storage interface.

This is the one place a :class:`~mapdata.models.RoadSegment` becomes a stored
document and back. The conversion lives here, next to the type it converts,
rather than in `storage` -- storage is not allowed to know what a road is, and
a ``road_class`` column would make the next change to this dataclass a
database migration.

Two uses, and they are different:

* **A source of record.** :class:`StoredRoadNetwork` satisfies the same
  ``roads(bbox)`` question an Overpass source answers, from the database
  instead of the network. That is what lets a server run with no internet
  access over an area it has already imported.
* **A write-through wrapper.** :class:`PersistingRoadNetwork` asks an upstream
  source and saves what comes back, so importing an area is a side effect of
  routing across it once.

Neither knows SQLite exists. Both hold a
:class:`storage.DocumentStore` and nothing else.
"""

from __future__ import annotations

from typing import Sequence

from domain import BBox, bounds_of
from storage import Collection, DocumentStore, StoredDocument, utcnow

from .models import RoadSegment, coords_of

__all__ = ["RoadStore", "StoredRoadNetwork", "PersistingRoadNetwork"]


class RoadStore:
    """Reads and writes road segments as stored documents."""

    def __init__(self, documents: DocumentStore) -> None:
        self._documents = documents

    def save(self, segments: Sequence[RoadSegment]) -> int:
        """Persist segments, replacing any already held under the same id."""
        return self._documents.put(_document_of(segment) for segment in segments)

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        """Every stored segment whose own box intersects ``bbox``."""
        found = self._documents.find(Collection.ROADS, bbox=bbox.as_tuple())
        return tuple(_segment_of(document) for document in found)

    def count(self) -> int:
        return self._documents.count(Collection.ROADS)

    def forget(self, segment_id: str) -> bool:
        return self._documents.delete(Collection.ROADS, segment_id)


class StoredRoadNetwork:
    """A ``RoadNetwork`` backed entirely by what has already been imported."""

    def __init__(self, documents: DocumentStore) -> None:
        self._store = RoadStore(documents)

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        return self._store.roads(bbox)


class PersistingRoadNetwork:
    """Asks an upstream network, keeps the answer, and falls back to it.

    The fallback is the point. Overpass is free volunteer infrastructure and
    it does go down; when it does, a server that has routed across this city
    before should keep routing across it rather than start refusing. A stale
    road network is a far smaller problem than no road network -- road
    geometry changes on the order of months.
    """

    def __init__(self, upstream, documents: DocumentStore) -> None:
        self._upstream = upstream
        self._store = RoadStore(documents)

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        try:
            segments = tuple(self._upstream.roads(bbox))
        except Exception:
            return self._store.roads(bbox)
        if segments:
            self._store.save(segments)
        return segments


def _document_of(segment: RoadSegment) -> StoredDocument:
    west, south, east, north = bounds_of(segment.geometry)
    return StoredDocument(
        collection=Collection.ROADS,
        key=segment.id,
        west=west,
        south=south,
        east=east,
        north=north,
        recorded_at=utcnow(),
        payload={
            "id": segment.id,
            "geometry": [list(point) for point in segment.geometry],
            "road_class": segment.road_class,
            "free_flow_kph": segment.free_flow_kph,
            "name": segment.name,
            "oneway": segment.oneway,
        },
    )


def _segment_of(document: StoredDocument) -> RoadSegment:
    payload = document.payload
    return RoadSegment(
        id=payload["id"],
        geometry=coords_of(payload["geometry"]),
        road_class=payload["road_class"],
        free_flow_kph=float(payload["free_flow_kph"]),
        name=payload.get("name"),
        oneway=bool(payload.get("oneway", False)),
    )
