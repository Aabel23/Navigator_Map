"""A time-limited JSON cache on disk, satisfying :class:`storage.Cache`.

The one persistence mechanism the server needs today. It exists because two
of the free upstream services this project reads -- Overpass and the national
traffic feeds -- are shared volunteer or public infrastructure with a real
cost per query, and asking them the same question twice is impolite rather
than merely slow.

Nothing here knows what a road, a traffic level or a bounding box is. It is
handed an opaque key and an object that happens to be JSON-serialisable, and
it hands the object back or does not. That ignorance is the block's boundary
rule made concrete: storage provides persistence capabilities, never domain
decisions.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable

from .interface.store import Cache

__all__ = ["JsonFileCache", "cache_key"]


def cache_key(*parts: Any) -> str:
    """A short, stable, filesystem-safe key from any printable parts.

    Hashed rather than escaped: callers key on things like bounding boxes and
    class lists, which contain separators, decimal points and minus signs that
    a filename should not have to carry.
    """
    raw = "|".join(str(part) for part in parts)
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=10).hexdigest()


class JsonFileCache(Cache):
    """One JSON document per key, expiring by file age.

    Args:
        directory: Where documents are written. ``None`` disables the cache
            entirely, which is what a test wants and what a caller with no
            writable location gets by default.
        ttl_s: How long a document stays usable. Past it, :meth:`get` reports
            a miss and leaves the stale file alone -- the next :meth:`put`
            overwrites it.

    A cache that cannot be read or written is a slower cache, never a broken
    one: every failure here degrades to a miss, because the caller always has
    another way to get its answer and no way to do anything useful with a
    disk error.
    """

    def __init__(self, directory: Path | str | None, *, ttl_s: float = 24 * 3600.0) -> None:
        self._directory = Path(directory) if directory else None
        self._ttl_s = ttl_s

    @property
    def enabled(self) -> bool:
        return self._directory is not None

    @property
    def directory(self) -> Path | None:
        return self._directory

    def get(self, key: str) -> Any | None:
        """The document stored under ``key``, or ``None`` for a miss."""
        path = self._path(key)
        if path is None or not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > self._ttl_s:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, payload: Any) -> None:
        """Store ``payload`` under ``key``. Silent on failure, by design."""
        path = self._path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            return

    def forget(self, key: str) -> None:
        """Drop one document. Missing is not an error."""
        path = self._path(key)
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return

    def clear(self) -> int:
        """Drop every document this cache wrote. Returns how many went."""
        if self._directory is None or not self._directory.exists():
            return 0
        removed = 0
        for path in self._directory.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def keys(self) -> Iterable[str]:
        if self._directory is None or not self._directory.exists():
            return ()
        return tuple(path.stem for path in self._directory.glob("*.json"))

    def _path(self, key: str) -> Path | None:
        if self._directory is None:
            return None
        return self._directory / f"{key}.json"
