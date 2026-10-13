"""Position filtering.

Goal is NOT perfect GPS estimation -- it is removing obvious jitter
while staying responsive to real movement. The interface is designed
so a more sophisticated filter (e.g. a future Kalman filter) can be
swapped in without touching the processor.

    PositionProcessor
            |
            v
    PositionFilter (interface)
            |
            +--> SimplePositionFilter   (this module)
            |
            +--> FutureKalmanFilter     (not implemented here)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from .config import LocationConfig


class PositionFilter(ABC):
    """Interface for smoothing an accepted (lat, lon) candidate."""

    @abstractmethod
    def apply(
        self,
        previous: Optional[Tuple[float, float]],
        candidate: Tuple[float, float],
        distance_m: Optional[float],
        config: LocationConfig,
    ) -> Tuple[float, float]:
        """Return the (possibly smoothed) latitude/longitude to emit.

        ``previous`` is the last accepted (lat, lon), or None if this is
        the first accepted position. ``distance_m`` is the Haversine
        distance between previous and candidate, or None if there is no
        previous position.
        """
        raise NotImplementedError


class SimplePositionFilter(PositionFilter):
    """Deterministic, dependency-free filter.

    Behavior:
    * No previous position -> pass the candidate through unchanged.
    * Movement below ``config.min_jitter_distance_m`` -> treat as GPS
      jitter and blend toward the candidate using ``filter_strength``
      (higher strength = more smoothing, more weight on the previous
      point).
    * Movement at or above the jitter threshold -> pass the candidate
      through unchanged, so real movement is never laggy.

    Large, physically-impossible jumps are rejected upstream by the
    processor's movement analysis and never reach this filter.
    """

    def apply(
        self,
        previous: Optional[Tuple[float, float]],
        candidate: Tuple[float, float],
        distance_m: Optional[float],
        config: LocationConfig,
    ) -> Tuple[float, float]:
        if previous is None or distance_m is None:
            return candidate

        if distance_m >= config.min_jitter_distance_m:
            return candidate

        strength = min(max(config.filter_strength, 0.0), 1.0)
        prev_lat, prev_lon = previous
        cand_lat, cand_lon = candidate

        smoothed_lat = prev_lat * strength + cand_lat * (1.0 - strength)
        smoothed_lon = prev_lon * strength + cand_lon * (1.0 - strength)
        return smoothed_lat, smoothed_lon
