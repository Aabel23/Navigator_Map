"""SQLite behind the storage interface.

This file and its schema are the only place in the server that knows SQLite
exists. Everything above holds a :class:`~storage.interface.StorageBackend`,
so swapping this for the PostgreSQL backend is a configuration change and an
import in one module, not a rewrite of routing, traffic, road state, map data
or the API.

Three engine decisions worth stating, because each is a place a later reader
would otherwise wonder:

* **Timestamps are ISO-8601 text, always UTC, always timezone-aware.** SQLite
  has no instant type. Text sorts correctly when the offset is always the
  same, which is enforced on the way in; a naive datetime is rejected at the
  :class:`~storage.interface.StoredDocument` boundary rather than silently
  assigned a zone.
* **Payloads are JSON text.** The block never reads inside one. That is the
  boundary rule: a column per domain field would make a domain type change
  into a database migration.
* **One connection, ``check_same_thread=False``, guarded by a lock.** A Flask
  development server serves requests on several threads; SQLite tolerates that
  with serialised access, and serialising writes at this volume costs nothing
  measurable. A backend that needed real concurrency is the reason the
  PostgreSQL path exists.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..interface.records import StoredDocument
from ..interface.store import Cache, DocumentStore, StorageBackend, StorageError

__all__ = ["SqliteStorage", "SqliteDocumentStore", "SqliteCache"]

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

MEMORY = ":memory:"


def _to_text(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat()


def _from_text(text: str | None) -> datetime | None:
    if text is None:
        return None
    return datetime.fromisoformat(text)


class _Connection:
    """One serialised sqlite3 connection, shared by both stores."""

    def __init__(self, path: Path | str) -> None:
        target = str(path)
        if target != MEMORY:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.path = target
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(target, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                cursor = self._conn.execute(sql, params)
                rows = cursor.fetchall()
                self._conn.commit()
                return rows
            except sqlite3.Error as err:
                self._conn.rollback()
                raise StorageError(f"sqlite: {err}") from err

    def execute_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        with self._lock:
            try:
                cursor = self._conn.executemany(sql, rows)
                self._conn.commit()
                return cursor.rowcount if cursor.rowcount != -1 else len(rows)
            except sqlite3.Error as err:
                self._conn.rollback()
                raise StorageError(f"sqlite: {err}") from err

    def execute_script(self, sql: str) -> None:
        with self._lock:
            try:
                self._conn.executescript(sql)
                self._conn.commit()
            except sqlite3.Error as err:
                self._conn.rollback()
                raise StorageError(f"sqlite: {err}") from err

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


class SqliteDocumentStore(DocumentStore):
    def __init__(self, connection: _Connection) -> None:
        self._db = connection

    def put(self, documents: Iterable[StoredDocument]) -> int:
        rows = [
            (
                doc.collection,
                doc.key,
                doc.west,
                doc.south,
                doc.east,
                doc.north,
                _to_text(doc.recorded_at),
                _to_text(doc.valid_from),
                _to_text(doc.valid_to),
                json.dumps(dict(doc.payload)),
            )
            for doc in documents
        ]
        if not rows:
            return 0
        return self._db.execute_many(
            """
            INSERT INTO documents
                (collection, key, west, south, east, north,
                 recorded_at, valid_from, valid_to, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (collection, key) DO UPDATE SET
                west = excluded.west, south = excluded.south,
                east = excluded.east, north = excluded.north,
                recorded_at = excluded.recorded_at,
                valid_from = excluded.valid_from,
                valid_to = excluded.valid_to,
                payload = excluded.payload
            """,
            rows,
        )

    def get(self, collection: str, key: str) -> StoredDocument | None:
        rows = self._db.execute(
            "SELECT * FROM documents WHERE collection = ? AND key = ?", (collection, key)
        )
        return _document_of(rows[0]) if rows else None

    def find(
        self,
        collection: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        at: datetime | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[StoredDocument]:
        sql = ["SELECT * FROM documents WHERE collection = ?"]
        params: list[Any] = [collection]
        if bbox is not None:
            west, south, east, north = bbox
            # Rectangle intersection, spelled as the negation of "disjoint".
            sql.append("AND east >= ? AND west <= ? AND north >= ? AND south <= ?")
            params += [west, east, south, north]
        if at is not None:
            moment = _to_text(at)
            sql.append("AND (valid_from IS NULL OR valid_from <= ?)")
            params.append(moment)
            sql.append("AND (valid_to IS NULL OR valid_to >= ?)")
            params.append(moment)
        if since is not None:
            sql.append("AND recorded_at >= ?")
            params.append(_to_text(since))
        sql.append("ORDER BY recorded_at DESC, key ASC")
        if limit is not None:
            sql.append("LIMIT ?")
            params.append(int(limit))
        return tuple(_document_of(row) for row in self._db.execute(" ".join(sql), params))

    def delete(self, collection: str, key: str) -> bool:
        before = self.count(collection)
        self._db.execute(
            "DELETE FROM documents WHERE collection = ? AND key = ?", (collection, key)
        )
        return self.count(collection) < before

    def prune(self, collection: str, *, recorded_before: datetime) -> int:
        before = self.count(collection)
        self._db.execute(
            "DELETE FROM documents WHERE collection = ? AND recorded_at < ?",
            (collection, _to_text(recorded_before)),
        )
        return before - self.count(collection)

    def count(self, collection: str) -> int:
        rows = self._db.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE collection = ?", (collection,)
        )
        return int(rows[0]["n"])


class SqliteCache(Cache):
    """Cache rows in the same database file. Every failure is a miss."""

    def __init__(self, connection: _Connection, *, ttl_s: float = 24 * 3600.0) -> None:
        self._db = connection
        self._ttl_s = ttl_s

    def get(self, key: str) -> Any | None:
        try:
            rows = self._db.execute(
                "SELECT stored_at, payload FROM cache_entries WHERE key = ?", (key,)
            )
        except StorageError:
            return None
        if not rows:
            return None
        if (time.time() - float(rows[0]["stored_at"])) > self._ttl_s:
            return None
        try:
            return json.loads(rows[0]["payload"])
        except (TypeError, ValueError):
            return None

    def put(self, key: str, payload: Any) -> None:
        try:
            body = json.dumps(payload)
        except (TypeError, ValueError):
            return
        try:
            self._db.execute(
                """
                INSERT INTO cache_entries (key, stored_at, payload) VALUES (?, ?, ?)
                ON CONFLICT (key) DO UPDATE SET
                    stored_at = excluded.stored_at, payload = excluded.payload
                """,
                (key, time.time(), body),
            )
        except StorageError:
            return

    def forget(self, key: str) -> None:
        try:
            self._db.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
        except StorageError:
            return

    def clear(self) -> int:
        try:
            rows = self._db.execute("SELECT COUNT(*) AS n FROM cache_entries")
            removed = int(rows[0]["n"])
            self._db.execute("DELETE FROM cache_entries")
            return removed
        except StorageError:
            return 0


class SqliteStorage(StorageBackend):
    """A SQLite file -- or an in-memory database -- behind the storage interface.

    Args:
        path: Database file. Parent directories are created. Passing
            :data:`MEMORY` gives a private database that vanishes on
            :meth:`close`.
        cache_ttl_s: How long a cache entry stays usable.
    """

    name = "sqlite"

    def __init__(self, path: Path | str, *, cache_ttl_s: float = 24 * 3600.0) -> None:
        self._db = _Connection(path)
        self._documents = SqliteDocumentStore(self._db)
        self._cache = SqliteCache(self._db, ttl_s=cache_ttl_s)
        self._closed = False

    @property
    def documents(self) -> DocumentStore:
        return self._documents

    @property
    def cache(self) -> Cache:
        return self._cache

    def migrate(self) -> None:
        self._db.execute_script(SCHEMA_PATH.read_text(encoding="utf-8"))

    def close(self) -> None:
        if not self._closed:
            self._db.close()
            self._closed = True


def _document_of(row: sqlite3.Row) -> StoredDocument:
    return StoredDocument(
        collection=row["collection"],
        key=row["key"],
        west=row["west"],
        south=row["south"],
        east=row["east"],
        north=row["north"],
        payload=json.loads(row["payload"]),
        recorded_at=_from_text(row["recorded_at"]),
        valid_from=_from_text(row["valid_from"]),
        valid_to=_from_text(row["valid_to"]),
    )
