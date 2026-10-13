"""Storage -- persistence mechanisms and storage adapters.

    from storage import SqliteStorage, StoredDocument, Collection

    backend = SqliteStorage("data/server.db")
    backend.migrate()
    backend.documents.put([...])

Owns:
    how bytes are kept and found again, and which engine does it

Does not own:
    what any of those bytes mean. No road, traffic, map, routing or API policy
    lives here -- this block provides persistence capabilities, not domain
    decisions. It stores a payload it never reads inside, indexed on the two
    axes every consumer queries by: an area and a moment.

Choosing a backend is a decision made once, in the composition root, from
configuration. Everything above holds :class:`StorageBackend`, which is what
makes the SQLite-today / PostGIS-tomorrow migration a change to this block
alone -- see ``postgres/MIGRATION.md``.

This module is the block's entire public surface. Everything reachable from
here is contract; ``storage.sqlite.backend`` and ``storage.memory.backend``
are implementations and may change freely behind it.
"""

from .files import JsonFileCache, cache_key
from .interface import (
    Cache,
    Collection,
    DocumentStore,
    StorageBackend,
    StorageError,
    StoredDocument,
    utcnow,
)
from .memory import InMemoryStorage
from .sqlite import SqliteStorage

__all__ = [
    # The contract
    "StorageBackend",
    "DocumentStore",
    "Cache",
    "StoredDocument",
    "Collection",
    "StorageError",
    "utcnow",
    # The engines shipped today
    "SqliteStorage",
    "InMemoryStorage",
    "JsonFileCache",
    "cache_key",
]
