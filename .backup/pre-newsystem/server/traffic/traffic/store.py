"""One question in, one snapshot out, however many providers are behind it.

A caller -- the routing cost model, the sandbox overlay, a future HUD -- does
not want to know that Finland has a sensor network and Vietnam has a model.
It wants the traffic for a box. The store is what turns a list of providers
into that single answer, and it carries the three policies that decision
needs:

* **Coverage routing.** A provider that declares a region is only asked about
  boxes inside it. This is what keeps a world of national feeds usable.
* **Measured beats modelled.** A fallback provider is consulted only where no
  measuring provider produced anything. Real numbers are never diluted by
  invented ones.
* **Failure is not fatal.** A provider that raises is dropped from that
  refresh and recorded, because a route without traffic is worse than one
  with it, but a route that never computes is worse than both.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .errors import TrafficError
from .models import BBox, TrafficSnapshot
from .provider import TrafficProvider

__all__ = ["TrafficStore", "StoreResult"]


@dataclass(frozen=True, slots=True)
class StoreResult:
    """A snapshot plus what happened while getting it.

    The failures matter as much as the data: a map that quietly shows an
    empty city because a feed timed out is worse than one that says so.
    """

    snapshot: TrafficSnapshot
    from_cache: bool = False
    failures: tuple[tuple[str, str], ...] = ()

    def meta(self) -> dict[str, Any]:
        return {
            **self.snapshot.meta(),
            "from_cache": self.from_cache,
            "failures": [{"provider": name, "error": text} for name, text in self.failures],
        }


@dataclass(slots=True)
class _Entry:
    result: StoreResult
    fetched_at: float


class TrafficStore:
    """Caches and combines providers behind one :meth:`snapshot` call.

    Args:
        providers: Measuring providers, in preference order.
        fallback: Consulted only when no measuring provider returned data for
            the box. This is where a modelled provider belongs.
        ttl_s: How long a snapshot stays servable. Sixty seconds matches the
            fastest free feed found, and no camera pan should out-run it.
        quantize_places: Decimal places the cache key rounds the box to.
            Three is roughly 100 m, so small pans reuse one entry.
        clock: Monotonic seconds. Injected for tests.
    """

    def __init__(
        self,
        providers: Sequence[TrafficProvider],
        *,
        fallback: TrafficProvider | None = None,
        ttl_s: float = 60.0,
        quantize_places: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._providers = tuple(providers)
        self._fallback = fallback
        self._ttl_s = ttl_s
        self._places = quantize_places
        self._clock = clock
        self._cache: dict[tuple[float, ...], _Entry] = {}

    @property
    def providers(self) -> tuple[TrafficProvider, ...]:
        """Every provider, fallback last. Read-only."""
        if self._fallback is None:
            return self._providers
        return self._providers + (self._fallback,)

    def snapshot(self, bbox: BBox) -> StoreResult:
        """Traffic for ``bbox``, from cache when one is still fresh."""
        key = bbox.quantized(self._places).as_tuple()
        entry = self._cache.get(key)
        if entry is not None and (self._clock() - entry.fetched_at) < self._ttl_s:
            return StoreResult(
                snapshot=entry.result.snapshot,
                from_cache=True,
                failures=entry.result.failures,
            )

        result = self._collect(bbox)
        self._cache[key] = _Entry(result, self._clock())
        return result

    def invalidate(self) -> None:
        """Drop every cached snapshot. Used when a provider set changes."""
        self._cache.clear()

    def _collect(self, bbox: BBox) -> StoreResult:
        merged = TrafficSnapshot.empty(bbox)
        failures: list[tuple[str, str]] = []
        measured = False

        for provider in self._providers:
            if not provider.covers(bbox):
                continue
            snapshot = self._try(provider, bbox, failures)
            if snapshot is None:
                continue
            merged = merged.merge(snapshot)
            measured = measured or not snapshot.is_empty

        if not measured and self._fallback is not None and self._fallback.covers(bbox):
            snapshot = self._try(self._fallback, bbox, failures)
            if snapshot is not None:
                merged = merged.merge(snapshot)

        return StoreResult(snapshot=merged.clip(bbox), failures=tuple(failures))

    def _try(
        self,
        provider: TrafficProvider,
        bbox: BBox,
        failures: list[tuple[str, str]],
    ) -> TrafficSnapshot | None:
        try:
            return provider.fetch(bbox)
        except TrafficError as err:
            failures.append((provider.name, str(err)))
            return None
        except Exception as err:  # noqa: BLE001 - a provider bug must not stop the rest
            failures.append((provider.name, f"{type(err).__name__}: {err}"))
            return None
