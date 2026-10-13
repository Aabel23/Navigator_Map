"""LocationProcessor: the single stable boundary between raw position
sources and the rest of the application.

    RawPosition -> validate -> stale/accuracy check -> movement
    analysis -> filter -> derive heading/speed -> PositionUpdate

The processor knows nothing about routing, MapLibre, or traffic. It
only produces reliable position data and never crashes on malformed
input -- bad measurements are rejected and the last valid position is
kept.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable, Deque, List, Optional

from .config import LocationConfig
from .errors import RejectionReason, ValidationResult
from .filters import PositionFilter, SimplePositionFilter
from .geometry import bearing_degrees, distance_meters
from .models import PositionUpdate, RawPosition

Callback = Callable[[PositionUpdate], None]


class LocationProcessor:
    """Public API: ``process``, ``get_latest``, ``reset``, ``subscribe``."""

    def __init__(
        self,
        config: Optional[LocationConfig] = None,
        position_filter: Optional[PositionFilter] = None,
    ) -> None:
        self._config = config or LocationConfig()
        self._filter = position_filter or SimplePositionFilter()

        self._latest: Optional[PositionUpdate] = None
        self._history: Deque[PositionUpdate] = deque(maxlen=self._config.history_size)
        self._subscribers: List[Callback] = []

        # Observability
        self._accepted_count = 0
        self._rejected_count = 0
        self._last_rejection_reason: Optional[RejectionReason] = None
        self._last_update_timestamp: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self, raw: RawPosition, now_ms: Optional[int] = None
    ) -> Optional[PositionUpdate]:
        """Validate, filter, and normalize one raw measurement.

        Returns the accepted ``PositionUpdate``, or ``None`` if the
        measurement was rejected. On rejection, the previously accepted
        position (``get_latest()``) is left untouched.
        """
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)

        result = self._validate(raw, now_ms)
        if not result.is_valid:
            self._record_rejection(result.reason)
            return None

        previous = self._latest
        distance_from_previous: Optional[float] = None
        time_since_previous: Optional[float] = None

        if previous is not None:
            distance_from_previous = distance_meters(
                previous.latitude, previous.longitude, raw.latitude, raw.longitude
            )
            time_since_previous = (raw.timestamp - previous.timestamp) / 1000.0

            jump_result = self._check_impossible_jump(
                distance_from_previous, time_since_previous
            )
            if not jump_result.is_valid:
                self._record_rejection(jump_result.reason)
                return None

        # --- Filtering -------------------------------------------------
        prev_point = (previous.latitude, previous.longitude) if previous else None
        filtered_lat, filtered_lon = self._filter.apply(
            prev_point, (raw.latitude, raw.longitude), distance_from_previous, self._config
        )

        # --- Derived heading --------------------------------------------------
        heading = self._derive_heading(raw, previous, distance_from_previous)

        # --- Derived speed ------------------------------------------------
        calculated_speed = self._derive_speed(
            raw, distance_from_previous, time_since_previous
        )
        effective_speed = raw.speed if _is_valid_number(raw.speed) else calculated_speed

        age_s = max(0.0, (now_ms - raw.timestamp) / 1000.0)
        is_stale = age_s > self._config.stale_threshold_s

        update = PositionUpdate(
            latitude=filtered_lat,
            longitude=filtered_lon,
            accuracy=raw.accuracy,
            timestamp=raw.timestamp,
            altitude=raw.altitude,
            heading=heading,
            speed=effective_speed,
            age=age_s,
            is_stale=is_stale,
            is_valid=True,
            distance_from_previous=distance_from_previous,
            time_since_previous=time_since_previous,
            calculated_speed=calculated_speed,
            source=raw.source,
        )

        self._latest = update
        self._history.append(update)
        self._accepted_count += 1
        self._last_update_timestamp = raw.timestamp

        self._notify(update)
        return update

    def get_latest(self) -> Optional[PositionUpdate]:
        return self._latest

    def get_history(self) -> List[PositionUpdate]:
        """Bounded recent history (most recent last), for debugging/logging."""
        return list(self._history)

    def reset(self) -> None:
        self._latest = None
        self._history.clear()
        self._accepted_count = 0
        self._rejected_count = 0
        self._last_rejection_reason = None
        self._last_update_timestamp = None

    def subscribe(self, callback: Callback) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # --- Observability --------------------------------------------------

    @property
    def stats(self) -> dict:
        return {
            "accepted_count": self._accepted_count,
            "rejected_count": self._rejected_count,
            "last_rejection_reason": self._last_rejection_reason,
            "last_update_timestamp": self._last_update_timestamp,
            "current_accuracy": self._latest.accuracy if self._latest else None,
            "current_speed": self._latest.speed if self._latest else None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify(self, update: PositionUpdate) -> None:
        for callback in list(self._subscribers):
            callback(update)

    def _record_rejection(self, reason: Optional[RejectionReason]) -> None:
        self._rejected_count += 1
        self._last_rejection_reason = reason

    def _validate(self, raw: RawPosition, now_ms: int) -> ValidationResult:
        if raw.latitude is None or raw.longitude is None or raw.timestamp is None:
            return ValidationResult.reject(
                RejectionReason.MISSING_REQUIRED_FIELD, "latitude/longitude/timestamp required"
            )

        if not _is_valid_number(raw.latitude) or not (-90.0 <= raw.latitude <= 90.0):
            return ValidationResult.reject(
                RejectionReason.INVALID_COORDINATE, f"latitude={raw.latitude!r}"
            )
        if not _is_valid_number(raw.longitude) or not (-180.0 <= raw.longitude <= 180.0):
            return ValidationResult.reject(
                RejectionReason.INVALID_COORDINATE, f"longitude={raw.longitude!r}"
            )

        if not isinstance(raw.timestamp, (int, float)) or not _is_valid_number(
            float(raw.timestamp)
        ):
            return ValidationResult.reject(
                RejectionReason.INVALID_TIMESTAMP, f"timestamp={raw.timestamp!r}"
            )
        if raw.timestamp <= 0:
            return ValidationResult.reject(
                RejectionReason.INVALID_TIMESTAMP, "timestamp must be positive"
            )
        max_future_ms = self._config.max_future_skew_s * 1000.0
        if raw.timestamp - now_ms > max_future_ms:
            return ValidationResult.reject(
                RejectionReason.INVALID_TIMESTAMP, "timestamp is too far in the future"
            )

        age_s = (now_ms - raw.timestamp) / 1000.0
        if age_s > self._config.reject_stale_after_s:
            return ValidationResult.reject(
                RejectionReason.STALE_POSITION, f"age={age_s:.2f}s"
            )

        if raw.accuracy is not None:
            if not _is_valid_number(raw.accuracy) or raw.accuracy < 0:
                return ValidationResult.reject(
                    RejectionReason.INVALID_COORDINATE, f"accuracy={raw.accuracy!r}"
                )
            if raw.accuracy > self._config.reject_accuracy_m:
                return ValidationResult.reject(
                    RejectionReason.LOW_ACCURACY, f"accuracy={raw.accuracy}m"
                )

        return ValidationResult.ok()

    def _check_impossible_jump(
        self, distance_m: float, time_delta_s: float
    ) -> ValidationResult:
        if time_delta_s <= 0:
            # Non-increasing timestamps relative to the last accepted fix:
            # treat as an invalid/duplicate timestamp rather than a jump.
            return ValidationResult.reject(
                RejectionReason.INVALID_TIMESTAMP,
                "timestamp did not advance relative to previous position",
            )

        implied_speed = distance_m / time_delta_s
        max_speed = self._config.max_speed_for_current_mode()
        if implied_speed > max_speed:
            return ValidationResult.reject(
                RejectionReason.IMPOSSIBLE_JUMP,
                f"implied_speed={implied_speed:.2f}mps > max={max_speed}mps",
            )
        return ValidationResult.ok()

    def _derive_heading(
        self,
        raw: RawPosition,
        previous: Optional[PositionUpdate],
        distance_from_previous: Optional[float],
    ) -> Optional[float]:
        if _is_valid_number(raw.heading):
            return raw.heading % 360.0

        if (
            previous is not None
            and distance_from_previous is not None
            and distance_from_previous >= self._config.minimum_heading_distance_m
        ):
            return bearing_degrees(
                previous.latitude, previous.longitude, raw.latitude, raw.longitude
            )

        return None

    def _derive_speed(
        self,
        raw: RawPosition,
        distance_from_previous: Optional[float],
        time_since_previous: Optional[float],
    ) -> Optional[float]:
        if distance_from_previous is None or time_since_previous is None:
            return None
        if time_since_previous <= 0:
            return None
        return distance_from_previous / time_since_previous


def _is_valid_number(value: Optional[float]) -> bool:
    if value is None:
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(f) or math.isinf(f))
