"""The storage contract: what a backend must do, and what a row looks like."""

from .records import Collection, StoredDocument, utcnow
from .store import Cache, DocumentStore, StorageBackend, StorageError

__all__ = [
    "Collection",
    "StoredDocument",
    "utcnow",
    "DocumentStore",
    "Cache",
    "StorageBackend",
    "StorageError",
]
