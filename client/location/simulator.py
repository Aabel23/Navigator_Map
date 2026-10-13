"""Deterministic simulated location source.

Lets routing/navigation/map code be exercised end-to-end without real
GPS or a browser, and lets tests construct exact scenarios: steady
movement, jitter, jumps, and stale measurements.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .models import PositionSource, RawPosition
from .sources import LocationSource, RawPositionCallback


@dataclass(frozen=True)
class SimulatedPoint:
    """One scripted waypoint. Only latitude/longitude are required."""

    latitude: float
    longitude: float
    timestamp: Optional[int] = None    # explicit override; else auto-derived
    accuracy: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None


class SimulatorLocationSource(LocationSource):
    """Deterministic, controllable ``LocationSource`` for dev/testing.

    Example:

        sim = SimulatorLocationSource(
            points=[(10.7769, 106.7009), (10.7770, 106.7011)],
            start_timestamp_ms=1_700_000_000_000,
            interval_ms=1000,
        )
        sim.start(lambda raw: processor.process(raw))
        sim.advance()   # emits point 1
        sim.advance()   # emits point 2

    Jitter, jumps, and stale timestamps can be injected explicitly by
    passing ``SimulatedPoint`` objects instead of plain (lat, lon)
    tuples, or via ``inject_jitter`` / ``inject_jump`` / ``inject_stale``.
    """

    def __init__(
        self,
        points: Sequence[Tuple[float, float] | SimulatedPoint],
        start_timestamp_ms: int = 0,
        interval_ms: int = 1000,
        default_accuracy: Optional[float] = 5.0,
        seed: Optional[int] = None,
    ) -> None:
        self._points: List[SimulatedPoint] = [
            p if isinstance(p, SimulatedPoint) else SimulatedPoint(latitude=p[0], longitude=p[1])
            for p in points
        ]
        self._start_timestamp_ms = start_timestamp_ms
        self._interval_ms = interval_ms
        self._default_accuracy = default_accuracy
        self._rng = random.Random(seed)

        self._index = 0
        self._callback: Optional[RawPositionCallback] = None
        self._running = False

    # -- LocationSource interface ---------------------------------------

    def start(self, callback: RawPositionCallback) -> None:
        self._callback = callback
        self._running = True
        self._index = 0

    def stop(self) -> None:
        self._running = False
        self._callback = None

    # -- Simulator controls -----------------------------------------------

    def advance(self) -> Optional[RawPosition]:
        """Emit the next scripted point, if any remain."""
        if not self._running or self._callback is None:
            return None
        if self._index >= len(self._points):
            return None

        point = self._points[self._index]
        timestamp = (
            point.timestamp
            if point.timestamp is not None
            else self._start_timestamp_ms + self._index * self._interval_ms
        )
        raw = RawPosition(
            latitude=point.latitude,
            longitude=point.longitude,
            timestamp=timestamp,
            accuracy=point.accuracy if point.accuracy is not None else self._default_accuracy,
            heading=point.heading,
            speed=point.speed,
            source=PositionSource.SIMULATOR,
        )
        self._index += 1
        self._callback(raw)
        return raw

    def run_all(self) -> List[RawPosition]:
        """Advance through every remaining scripted point."""
        emitted = []
        while True:
            raw = self.advance()
            if raw is None:
                break
            emitted.append(raw)
        return emitted

    def inject_jitter(self, base: Tuple[float, float], magnitude_deg: float = 0.00002) -> Tuple[float, float]:
        """Return a jittered coordinate near ``base`` (tiny random offset)."""
        lat, lon = base
        return (
            lat + self._rng.uniform(-magnitude_deg, magnitude_deg),
            lon + self._rng.uniform(-magnitude_deg, magnitude_deg),
        )

    @staticmethod
    def inject_jump(base: Tuple[float, float], offset_deg: float = 0.5) -> Tuple[float, float]:
        """Return a coordinate far from ``base`` -- a simulated GPS jump."""
        lat, lon = base
        return (lat + offset_deg, lon + offset_deg)

    def stale_timestamp(self, reference_ms: int, staleness_s: float) -> int:
        """Return a timestamp ``staleness_s`` seconds before ``reference_ms``."""
        return reference_ms - int(staleness_s * 1000)
