"""Dictionaries behind the storage interface.

Not a mock. It implements the same contract as the SQLite backend and is run
against the same conformance suite, which is what makes it usable as the
default for a test, a benchmark, or a first run with no database configured --
and what makes "storage is replaceable" a demonstrated property rather than a
design intention.

It keeps documents by ``(collection, key)`` and scans for every query. That is
the right shape at this size: the areas this server loads are city-sized, the
alternative is a spatial index nothing has asked for yet, and a backend that
must be correct is more useful than one that must be fast.

Payloads are round-tripped through JSON on the way in, exactly as the SQLite
backend does. That costs a little and buys the thing this backend exists for:
a payload that survives here survives there, and a tuple does not come back as
a tuple from one engine and a list from the other. A backend that were more
permissive than the one it stands in for would let a caller build a dependency
on behaviour that disappears in production.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable, Sequence

from ..interface.records import StoredDocument
from ..interface.store import Cache, DocumentStore, StorageBackend

__all__ = ["InMemoryStorage", "InMemoryDocumentStore", "InMemoryCache"]


class InMemoryDocumentStore(DocumentStore):
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], StoredDocument] = {}

    def put(self, documents: Iterable[StoredDocument]) -> int:
        written = 0
        for document in documents:
            stored = replace(document, payload=json.loads(json.dumps(dict(document.payload))))
            self._rows[(stored.collection, stored.key)] = stored
            written += 1
        return written

    def get(self, collection: str, key: str) -> StoredDocument | None:
        return self._rows.get((collection, key))

    def find(
        self,
        collection: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        at: datetime | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[StoredDocument]:
        hits = [doc for (coll, _), doc in self._rows.items() if coll == collection]
        if bbox is not None:
            hits = [doc for doc in hits if doc.intersects(*bbox)]
        if at is not None:
            hits = [doc for doc in hits if doc.active_at(at)]
        if since is not None:
            hits = [doc for doc in hits if doc.recorded_at >= since]
        hits.sort(key=lambda doc: (-doc.recorded_at.timestamp(), doc.key))
        return tuple(hits[:limit] if limit is not None else hits)

    def delete(self, collection: str, key: str) -> bool:
        return self._rows.pop((collection, key), None) is not None

    def prune(self, collection: str, *, recorded_before: datetime) -> int:
        doomed = [
            key
            for key, doc in self._rows.items()
            if key[0] == collection and doc.recorded_at < recorded_before
        ]
        for key in doomed:
            del self._rows[key]
        return len(doomed)

    def count(self, collection: str) -> int:
        return sum(1 for coll, _ in self._rows if coll == collection)


class InMemoryCache(Cache):
    """TTL cache in a dict, holding serialised payloads.

    Storing the JSON text rather than the object does two jobs at once: a
    caller that mutates what it got back cannot corrupt the next hit, and a
    payload this cache accepts is exactly a payload the SQLite cache accepts.
    An unserialisable value is dropped silently here for the same reason it is
    there -- a cache write has no useful failure mode, and the caller can
    always ask upstream again.
    """

    def __init__(self, *, ttl_s: float = 24 * 3600.0, clock=time.monotonic) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._rows: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> Any | None:
        row = self._rows.get(key)
        if row is None:
            return None
        stored_at, body = row
        if (self._clock() - stored_at) > self._ttl_s:
            return None
        try:
            return json.loads(body)
        except (TypeError, ValueError):
            return None

    def put(self, key: str, payload: Any) -> None:
        try:
            body = json.dumps(payload)
        except (TypeError, ValueError):
            return
        self._rows[key] = (self._clock(), body)

    def forget(self, key: str) -> None:
        self._rows.pop(key, None)

    def clear(self) -> int:
        removed = len(self._rows)
        self._rows.clear()
        return removed


class InMemoryStorage(StorageBackend):
    """The whole backend, in process."""

    name = "memory"

    def __init__(self, *, cache_ttl_s: float = 24 * 3600.0) -> None:
        self._documents = InMemoryDocumentStore()
        self._cache = InMemoryCache(ttl_s=cache_ttl_s)

    @property
    def documents(self) -> DocumentStore:
        return self._documents

    @property
    def cache(self) -> Cache:
        return self._cache

    def migrate(self) -> None:
        """Nothing to migrate. Present so the composition root is uniform."""

    def close(self) -> None:
        """Nothing to release."""
