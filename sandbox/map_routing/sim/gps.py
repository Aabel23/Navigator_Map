"""A GPS receiver that is not one.

The simulator needs a driver's position without a driver, and it needs that
position to be *wrong* in the way a real fix is wrong -- otherwise the map
matching step downstream looks like a no-op and the whole point of routing
from node ids rather than coordinates disappears.

So this produces a position with a metre or two of noise on it, and it can
drive: handed a route's geometry it walks along it at a speed, which is what
turns the three blocks from a still picture into something that moves.

The noise is added to the *reported* fix, never to the position being tracked,
so error never accumulates -- a receiver that drifted a kilometre off the road
over five minutes would be a different bug entirely.
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from .geodesy import Coord, bearing_deg, polyline_length_m, walk_polyline

__all__ = ["Fix", "FakeGps"]

#: Metres in one degree of latitude, for turning a noise radius into degrees.
_M_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True, slots=True)
class Fix:
    """One position report, in the shape a receiver would hand over.

    Attributes:
        point: ``(lon, lat)``, with noise applied.
        truth: ``(lon, lat)`` without noise. A receiver could not tell you
            this; the simulator can, and showing both is what makes the
            matching step visible.
        bearing: Degrees clockwise from north, direction of travel.
        speed_kph: Ground speed. Zero when parked.
        accuracy_m: The noise radius that was applied.
        moving: Whether the vehicle is driving a route.
        time_scale: How much faster than real time the drive is running. The
            speed above stays the road's real speed; only the clock is sped
            up, so a five-minute trip can be watched in under a minute without
            the panel claiming the car is doing 200 km/h.
        progress_m: Distance covered along the route being driven.
        route_m: Length of that route, zero when not driving.
        at: When the fix was taken.
    """

    point: Coord
    truth: Coord
    bearing: float
    speed_kph: float
    accuracy_m: float
    moving: bool
    time_scale: float
    progress_m: float
    route_m: float
    at: datetime

    def as_json(self) -> dict[str, object]:
        return {
            "lon": round(self.point[0], 7),
            "lat": round(self.point[1], 7),
            "truth_lon": round(self.truth[0], 7),
            "truth_lat": round(self.truth[1], 7),
            "bearing": round(self.bearing, 1),
            "speed_kph": round(self.speed_kph, 1),
            "accuracy_m": round(self.accuracy_m, 1),
            "moving": self.moving,
            "time_scale": round(self.time_scale, 2),
            "progress_m": round(self.progress_m, 1),
            "route_m": round(self.route_m, 1),
            "at": self.at.isoformat(),
        }


class FakeGps:
    """A position that can be placed by hand or driven along a route.

    Args:
        start: Where the vehicle sits before anything else happens.
        accuracy_m: One standard deviation of the reported noise.
        seed: Fixes the noise sequence, so two runs of the same scenario
            produce the same wobble.
        clock: Monotonic seconds. Injected so a test never has to wait.
    """

    def __init__(
        self,
        start: Coord,
        *,
        accuracy_m: float = 5.0,
        seed: int = 7,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._random = random.Random(seed)
        self._accuracy_m = accuracy_m
        self._noise_on = True

        self._point: Coord = start
        self._bearing = 0.0
        self._route: tuple[Coord, ...] = ()
        self._route_m = 0.0
        self._speed_mps = 0.0
        self._time_scale = 1.0
        self._started_at = 0.0
        self._moving = False
        self._progress_m = 0.0

    # -- control --------------------------------------------------------------

    def place(self, point: Coord) -> None:
        """Drop the vehicle somewhere. Stops any drive in progress."""
        with self._lock:
            self._point = point
            self._moving = False
            self._route = ()
            self._route_m = 0.0
            self._progress_m = 0.0
            self._speed_mps = 0.0

    def follow(self, shape: Sequence[Coord], speed_kph: float, time_scale: float = 1.0) -> None:
        """Start driving ``shape`` at ``speed_kph``, with the clock at ``time_scale``.

        The speed is supplied rather than derived here: the caller knows the
        route's travel time, and that travel time is the routing block's
        answer under whatever cost model produced it. Driving at a speed the
        route itself implies is what makes a congested route visibly take
        longer than a free-flow one.

        Watching that in real time would mean waiting out the drive, so the
        simulator runs the clock fast instead of inventing a speed. A route
        that the cost model says takes nine minutes still reports the 35 km/h
        it is actually being driven at -- it just gets there sooner.
        """
        points = tuple(shape)
        if len(points) < 2 or speed_kph <= 0:
            return
        with self._lock:
            self._route = points
            self._route_m = polyline_length_m(points)
            self._speed_mps = speed_kph / 3.6
            self._time_scale = max(1.0, time_scale)
            self._started_at = self._clock()
            self._moving = True
            self._progress_m = 0.0
            self._point = points[0]
            self._bearing = bearing_deg(points[0], points[1])

    def stop(self) -> None:
        """Park where the vehicle currently is."""
        with self._lock:
            if self._moving:
                self._point = self._advance()[0]
            self._moving = False
            self._route = ()
            self._route_m = 0.0
            self._speed_mps = 0.0

    def set_noise(self, enabled: bool) -> None:
        with self._lock:
            self._noise_on = enabled

    @property
    def noise_enabled(self) -> bool:
        return self._noise_on

    # -- reading --------------------------------------------------------------

    def read(self) -> Fix:
        """The current fix, advancing the drive to now if one is running."""
        with self._lock:
            if self._moving:
                self._point, self._bearing, finished = self._advance()
                if finished:
                    self._moving = False
                    self._route = ()
                    self._speed_mps = 0.0

            accuracy = self._accuracy_m if self._noise_on else 0.0
            return Fix(
                point=self._with_noise(self._point, accuracy),
                truth=self._point,
                bearing=self._bearing,
                speed_kph=self._speed_mps * 3.6,
                accuracy_m=accuracy,
                moving=self._moving,
                time_scale=self._time_scale if self._moving else 1.0,
                progress_m=self._progress_m,
                route_m=self._route_m,
                at=datetime.now(timezone.utc),
            )

    # -- internals ------------------------------------------------------------

    def _advance(self) -> tuple[Coord, float, bool]:
        """Where the vehicle is now, given how long it has been driving."""
        travelled = (self._clock() - self._started_at) * self._time_scale * self._speed_mps
        self._progress_m = min(travelled, self._route_m)
        return walk_polyline(self._route, travelled)

    def _with_noise(self, point: Coord, accuracy_m: float) -> Coord:
        if accuracy_m <= 0:
            return point
        # Gaussian in metres, converted to degrees at this latitude. A real
        # receiver's error is not circular, but it is not a step function
        # either, and this is enough to make matching do visible work.
        north = self._random.gauss(0.0, accuracy_m) / _M_PER_DEG_LAT
        east = self._random.gauss(0.0, accuracy_m) / _M_PER_DEG_LAT
        shrink = max(0.2, abs(math.cos(math.radians(point[1]))))
        return (point[0] + east / shrink, point[1] + north)
