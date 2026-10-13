"""The interfaces application code is written against.

Nothing above this module names SQLite, PostgreSQL, a file path or a
connection. A block asks a :class:`DocumentStore` for documents and a
:class:`Cache` for a cached payload; which engine answers is a decision the
composition root makes once, from configuration, at startup.

That is what makes the SQLite-today / PostGIS-tomorrow migration a change to
this block alone. It is also what makes every other block testable without a
database: :mod:`storage.memory` satisfies the same interfaces, and the
conformance suite in ``storage/tests`` is run against every implementation so
"satisfies" means something.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Iterable, Sequence

from .records import StoredDocument

__all__ = ["DocumentStore", "Cache", "StorageBackend", "StorageError"]


class StorageError(Exception):
    """A persistence operation failed for a reason the caller cannot fix.

    Engine-specific exceptions are wrapped in this before they leave the
    block: a caller that had to catch ``sqlite3.OperationalError`` would be
    coupled to the engine through its error type, which is the same coupling
    the interface exists to prevent.
    """


class DocumentStore(ABC):
    """Keeps :class:`StoredDocument` rows and finds them by area and time."""

    @abstractmethod
    def put(self, documents: Iterable[StoredDocument]) -> int:
        """Write documents, replacing any with the same collection and key.

        Returns how many were written. Idempotent by construction, because
        every upstream feed republishes.
        """

    @abstractmethod
    def get(self, collection: str, key: str) -> StoredDocument | None:
        """One document, or ``None``."""

    @abstractmethod
    def find(
        self,
        collection: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        at: datetime | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[StoredDocument]:
        """Documents matching every filter given, newest first.

        Args:
            collection: Required. Collections are never searched together.
            bbox: ``(west, south, east, north)``. Keeps documents whose own
                box intersects it.
            at: Keeps documents whose validity window contains this instant.
            since: Keeps documents recorded at or after this instant.
            limit: At most this many.

        Ordering is by ``recorded_at`` descending then ``key`` ascending, so
        the result is deterministic even when a batch shares a timestamp.
        """

    @abstractmethod
    def delete(self, collection: str, key: str) -> bool:
        """Remove one document. ``False`` when it was not there."""

    @abstractmethod
    def prune(self, collection: str, *, recorded_before: datetime) -> int:
        """Drop stale documents. Returns how many went.

        Observation history grows without bound otherwise; every ingest run
        adds rows nothing will read again.
        """

    @abstractmethod
    def count(self, collection: str) -> int:
        """How many documents the collection holds."""


class Cache(ABC):
    """A time-limited store for a payload that can always be re-fetched.

    Every failure degrades to a miss rather than raising: the caller always
    has another way to get its answer -- ask upstream again -- and nothing
    useful it could do with a disk error.
    """

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """The payload under ``key``, or ``None`` for a miss."""

    @abstractmethod
    def put(self, key: str, payload: Any) -> None:
        """Store ``payload``. Silent on failure, by design."""

    @abstractmethod
    def forget(self, key: str) -> None:
        """Drop one entry. Missing is not an error."""

    @abstractmethod
    def clear(self) -> int:
        """Drop everything this cache wrote. Returns how many went."""


class StorageBackend(ABC):
    """One engine, offering both stores plus its lifecycle.

    This is what the composition root holds and what configuration selects.
    """

    #: Short, stable name. Appears in health output and logs.
    name: str = "unnamed"

    @property
    @abstractmethod
    def documents(self) -> DocumentStore: ...

    @property
    @abstractmethod
    def cache(self) -> Cache: ...

    @abstractmethod
    def migrate(self) -> None:
        """Bring the schema up to date. Safe to call on every startup."""

    @abstractmethod
    def close(self) -> None:
        """Release the engine's resources. Safe to call twice."""

    def healthy(self) -> bool:
        """Whether the backend can answer a trivial query right now."""
        try:
            self.documents.count("__health__")
        except Exception:
            return False
        return True

    def __enter__(self) -> "StorageBackend":
        self.migrate()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
