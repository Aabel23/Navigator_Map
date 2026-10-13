"""Modelled traffic, for the parts of the world that publish none.

Most of the planet has no free live traffic feed. Ho Chi Minh City, which is
where this project centres its map, is one of those places: the city runs a
camera-based traffic portal, but there is no open API behind it. A navigation
system still has to have something to draw and something to route against, so
this provider produces a defensible estimate instead of a blank map.

It is a model, not a measurement, and it says so on every record: the source
string is exactly :data:`traffic.models.SIMULATED_SOURCE`, and confidence is
:data:`SIMULATED_CONFIDENCE`, low enough that anything weighing sources will
prefer a real sensor. A snapshot made only of these answers ``True`` to
:attr:`TrafficSnapshot.is_simulated`, so a UI can say so to the driver.

The model itself is three multiplied factors:

* **Time of day.** Two Gaussian rush-hour humps plus a midday bump, over a
  quiet baseline. Congestion is overwhelmingly a function of the clock.
* **Road class.** An arterial jams before a residential street does, and a
  grade-separated motorway resists longest.
* **A per-segment constant.** Hashed from the segment id, so the same street
  is always the bad one. Real congestion is not spatially random -- an
  intersection that backs up backs up every day -- and a model that reshuffles
  every refresh looks like noise rather than traffic.

Everything is derived by hashing, never by :mod:`random`, so the same inputs
give the same map on every machine and in every test. Between five-minute
buckets the per-segment factor is interpolated rather than stepped, so the
picture drifts the way traffic does instead of flickering.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..levels import level_for_speed
from ..models import (
    SIMULATED_SOURCE,
    BBox,
    RoadSegment,
    TrafficSegment,
    TrafficSnapshot,
)
from ..provider import RoadSource, TrafficProvider

__all__ = ["SimulatedTrafficProvider", "SIMULATED_CONFIDENCE", "congestion_curve"]

#: Low on purpose. A cost model that weighs by confidence will lean on a real
#: sensor over this every time, and a UI can hide it behind a warning.
SIMULATED_CONFIDENCE = 0.15

#: How much of the free-flow speed the worst modelled congestion takes away.
#: 0.85 bottoms out at 15% of free flow -- crawling, not stopped, because a
#: model has no business inventing a full standstill.
MAX_SLOWDOWN = 0.85

#: How readily each road class jams, relative to a primary arterial.
CLASS_PRESSURE: dict[str, float] = {
    "motorway": 0.55,
    "motorway_link": 0.65,
    "trunk": 0.75,
    "trunk_link": 0.8,
    "primary": 1.0,
    "primary_link": 0.95,
    "secondary": 0.95,
    "secondary_link": 0.9,
    "tertiary": 0.8,
    "tertiary_link": 0.75,
    "residential": 0.55,
    "unclassified": 0.5,
}

DEFAULT_CLASS_PRESSURE = 0.7


def congestion_curve(local_hour: float) -> float:
    """Baseline congestion pressure, 0 to 1, for an hour of the local day.

    Two commuter peaks and a midday bump over a quiet floor. The evening peak
    is the taller and wider of the two, which is what every city measures.
    """
    morning = _bump(local_hour, centre=7.75, width=1.05)
    evening = _bump(local_hour, centre=17.5, width=1.35)
    midday = _bump(local_hour, centre=12.0, width=1.6)
    return _clamp(0.10 + 0.80 * morning + 0.92 * evening + 0.28 * midday, 0.0, 1.0)


class SimulatedTrafficProvider(TrafficProvider):
    """Derives a traffic level for every road in a reference network.

    Args:
        road_source: Where the geometry comes from. Anything satisfying
            :class:`traffic.provider.RoadSource`.
        seed: Changes the per-segment pattern without changing the model.
        clock: Returns the current UTC time. Injected for tests.
        utc_offset_hours: Local time zone of the area being modelled. Rush
            hour is a local-clock phenomenon; UTC+7 is Vietnam.
        bucket_minutes: How often the pattern is allowed to change.
        coverage_area: Restrict this provider to one region. ``None`` means
            it answers anywhere, which is what makes it the fallback.
    """

    name = SIMULATED_SOURCE

    def __init__(
        self,
        road_source: RoadSource,
        *,
        seed: int = 1,
        clock: Callable[[], datetime] | None = None,
        utc_offset_hours: float = 7.0,
        bucket_minutes: int = 5,
        coverage_area: BBox | None = None,
    ) -> None:
        self._roads = road_source
        self._seed = seed
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._offset = timedelta(hours=utc_offset_hours)
        self._bucket_s = max(60, bucket_minutes * 60)
        self._coverage = coverage_area

    def coverage(self) -> BBox | None:
        return self._coverage

    def fetch(self, bbox: BBox) -> TrafficSnapshot:
        now = self._clock()
        roads = [r for r in self._roads.roads(bbox) if bbox.touches_any(r.geometry)]
        pressure = congestion_curve(self._local_hour(now))
        segments = tuple(self._segment_for(road, pressure, now) for road in roads)
        return TrafficSnapshot(
            bbox=bbox,
            observed_at=now,
            sources=(self.name,),
            segments=segments,
        )

    def _segment_for(
        self, road: RoadSegment, pressure: float, now: datetime
    ) -> TrafficSegment:
        speed = self._speed_for(road, pressure, now)
        return TrafficSegment(
            id=f"sim:{road.id}",
            geometry=road.geometry,
            level=level_for_speed(speed, road.free_flow_kph),
            observed_at=now,
            source=self.name,
            speed_kph=round(speed, 1),
            free_flow_kph=road.free_flow_kph,
            confidence=SIMULATED_CONFIDENCE,
            road_name=road.name,
            road_class=road.road_class,
            edge_id=road.id,
        )

    def _speed_for(self, road: RoadSegment, pressure: float, now: datetime) -> float:
        class_pressure = CLASS_PRESSURE.get(road.road_class, DEFAULT_CLASS_PRESSURE)
        local = self._segment_factor(road.id, now)
        combined = _clamp(pressure * class_pressure * local, 0.0, 1.0)
        return max(3.0, road.free_flow_kph * (1.0 - MAX_SLOWDOWN * combined))

    def _segment_factor(self, segment_id: str, now: datetime) -> float:
        """A stable per-segment multiplier that drifts between time buckets.

        Hashing on the bucket index alone would make every road change at the
        same instant, five minutes apart. Interpolating to the next bucket
        instead lets each segment slide toward its next value continuously.
        """
        elapsed = now.timestamp() / self._bucket_s
        bucket = math.floor(elapsed)
        fraction = elapsed - bucket
        start = _hash01(f"{self._seed}:{segment_id}:{bucket}")
        end = _hash01(f"{self._seed}:{segment_id}:{bucket + 1}")
        blended = start + (end - start) * fraction
        # 0.45 to 1.45: some roads stay clear at rush hour, some are worse
        # than the average of their class.
        return 0.45 + blended

    def _local_hour(self, now: datetime) -> float:
        local = now + self._offset
        return local.hour + local.minute / 60.0 + local.second / 3600.0


def _bump(hour: float, centre: float, width: float) -> float:
    """A Gaussian on a 24-hour circle, so 23:30 is near 00:30."""
    distance = abs(hour - centre)
    distance = min(distance, 24.0 - distance)
    return math.exp(-0.5 * (distance / width) ** 2)


def _hash01(key: str) -> float:
    """A stable float in [0, 1) from a string. Deterministic across runs.

    :func:`hash` is salted per process, so it cannot be used here -- two
    workers would disagree about the same street.
    """
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sample_curve(step_minutes: int = 30) -> list[tuple[float, float]]:
    """The congestion curve over a whole day. For plots and sanity checks."""
    steps = int(24 * 60 / step_minutes)
    hours = [i * step_minutes / 60.0 for i in range(steps)]
    return [(h, congestion_curve(h)) for h in hours]
