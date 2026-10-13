"""What the server currently believes about how fast the network is moving.

One object, held by the whole process, holding the freshest reading per road.
Everything that wants traffic -- the cost provider routing consults, the API
endpoint a client draws from, a future HUD -- reads it from here, which is
what keeps them agreeing with each other.

Three policies live in this class, and each exists because a navigation server
gets them wrong in a specific, visible way otherwise:

* **Readings expire.** A speed from twenty minutes ago is not traffic, it is
  history, and routing a driver on it is worse than routing them on free-flow
  speeds. Past ``max_age_s`` a reading is gone rather than stale.
* **Better readings win, they are not averaged.** See
  :meth:`~traffic.models.RoadSpeed.beats`.
* **A refresh failure is not fatal.** A provider that raises is recorded and
  skipped; the rest of the picture stands. A route without traffic is worse
  than one with it, and a route that never computes is worse than both.

Inputs:  ingest batches, plus the roads they may be attributed to
Outputs: TrafficSnapshot, and a road-id-keyed view for the cost provider
Not here: HTTP, provider specifics, persistence, edge ids
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Sequence

from domain import BBox

from ..models import RoadSpeed, TrafficSnapshot
from ..processing.attach import DEFAULT_SNAP_RADIUS_M, RoadIndex, attach

__all__ = ["TrafficState", "DEFAULT_MAX_AGE_S"]

#: How long a reading stays usable. Ten minutes: the fastest free feed found
#: republishes every minute, and a reading older than a few refresh intervals
#: is describing a jam that has either cleared or moved.
DEFAULT_MAX_AGE_S = 600.0


class TrafficState:
    """The current traffic picture, road by road.

    Args:
        max_age_s: How long a reading stays usable.
        snap_radius_m: How far a point observation may be from a road.
        clock: Returns the current aware UTC time. Injected for tests.

    Thread-safe. The API reads it while a refresh writes it, and a half-applied
    update would give one request a mixture of two moments.
    """

    def __init__(
        self,
        *,
        max_age_s: float = DEFAULT_MAX_AGE_S,
        snap_radius_m: float = DEFAULT_SNAP_RADIUS_M,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._max_age_s = max_age_s
        self._snap_radius_m = snap_radius_m
        self._clock = clock
        self._lock = threading.RLock()
        self._speeds: dict[str, RoadSpeed] = {}
        self._sources: set[str] = set()
        self._failures: list[tuple[str, str]] = []
        self._updated_at: datetime | None = None

    # --- Writing -----------------------------------------------------------

    def apply(self, batches: Iterable, roads: Sequence) -> int:
        """Attach batches to roads and merge the result into the state.

        Returns how many roads ended up with a reading from this call.
        """
        # Materialised because it is walked twice -- once to attach, once to
        # record which sources contributed. A generator would silently give
        # the second pass nothing.
        batches = tuple(batches)
        index = RoadIndex(roads)
        readings = attach(batches, index, snap_radius_m=self._snap_radius_m)

        with self._lock:
            for road_id, reading in readings.items():
                held = self._speeds.get(road_id)
                if held is None or reading.beats(held):
                    self._speeds[road_id] = reading
            for batch in batches:
                source = getattr(batch, "source", None)
                if source:
                    self._sources.add(source)
            self._updated_at = self._clock()
        return len(readings)

    def record_failure(self, source: str, error: str) -> None:
        """Note that a source could not be read. Shown, not swallowed."""
        with self._lock:
            self._failures = [f for f in self._failures if f[0] != source]
            self._failures.append((source, error))

    def clear_failures(self, source: str) -> None:
        with self._lock:
            self._failures = [f for f in self._failures if f[0] != source]

    def expire(self, now: datetime | None = None) -> int:
        """Drop readings past ``max_age_s``. Returns how many went."""
        moment = now or self._clock()
        with self._lock:
            doomed = [
                road_id
                for road_id, speed in self._speeds.items()
                if not speed.is_fresh(max_age_s=self._max_age_s, now=moment)
            ]
            for road_id in doomed:
                del self._speeds[road_id]
        return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._speeds.clear()
            self._sources.clear()
            self._failures.clear()
            self._updated_at = None

    # --- Reading -----------------------------------------------------------

    @property
    def updated_at(self) -> datetime | None:
        return self._updated_at

    def fresh(self, now: datetime | None = None) -> dict[str, RoadSpeed]:
        """Every unexpired reading, keyed by road id.

        Filters rather than mutates, so a read never changes what a concurrent
        read sees. :meth:`expire` is what actually reclaims the memory, and a
        caller decides when that is worth doing.
        """
        moment = now or self._clock()
        with self._lock:
            return {
                road_id: speed
                for road_id, speed in self._speeds.items()
                if speed.is_fresh(max_age_s=self._max_age_s, now=moment)
            }

    def snapshot(self, area: BBox, roads: Sequence | None = None) -> TrafficSnapshot:
        """The picture for one area.

        Args:
            area: The box asked about.
            roads: The published roads in that box. Needed because a reading
                is keyed by road id and this block does not hold geometry --
                `mapdata` owns that, and duplicating it here would give the
                system two road networks to disagree about.
        """
        readings = self.fresh()
        if roads is not None:
            wanted = {road.id for road in roads}
            readings = {rid: speed for rid, speed in readings.items() if rid in wanted}

        with self._lock:
            sources = tuple(sorted(self._sources))
            failures = tuple(self._failures)

        return TrafficSnapshot(
            area=area,
            taken_at=self._clock(),
            speeds=tuple(readings[key] for key in sorted(readings)),
            sources=sources,
            failures=failures,
        )

    def multipliers_by_road(self, now: datetime | None = None) -> Mapping[str, float]:
        """Road id to cost multiplier, for every road with a fresh reading."""
        from ..processing.cost import multiplier_for

        return {
            road_id: multiplier_for(speed) for road_id, speed in self.fresh(now).items()
        }

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "roads": len(self._speeds),
                "fresh": len(self.fresh()),
                "sources": sorted(self._sources),
                "failures": len(self._failures),
                "updated_at": self._updated_at.isoformat() if self._updated_at else None,
                "max_age_s": self._max_age_s,
            }
