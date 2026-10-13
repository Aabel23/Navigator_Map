"""Configuration for the location subsystem.

All thresholds live here so nothing is scattered as magic numbers
through the processor/filter implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict


class TransportMode(str, Enum):
    WALKING = "walking"
    CYCLING = "cycling"
    DRIVING = "driving"
    UNKNOWN = "unknown"


# Conservative per-mode ceilings (meters/second). "unknown" is deliberately
# generous (~190 km/h) so mode is not required for the first implementation
# while still catching genuinely impossible jumps (e.g. teleportation).
DEFAULT_MAX_SPEED_MPS: Dict[TransportMode, float] = {
    TransportMode.WALKING: 2.5,
    TransportMode.CYCLING: 12.0,
    TransportMode.DRIVING: 45.0,
    TransportMode.UNKNOWN: 52.0,
}


@dataclass(frozen=True)
class LocationConfig:
    # Staleness
    # A measurement older than stale_threshold_s is still accepted but is
    # flagged (PositionUpdate.is_stale = True) so consumers can decide how
    # to treat it. Only once age exceeds reject_stale_after_s is it
    # rejected outright (STALE_POSITION) instead of emitted.
    stale_threshold_s: float = 5.0
    reject_stale_after_s: float = 30.0

    # Accuracy handling
    max_accuracy_m: float = 100.0          # above this: low-confidence
    reject_accuracy_m: float = 1000.0      # above this: reject outright

    # Movement / jump detection
    transport_mode: TransportMode = TransportMode.UNKNOWN
    max_speed_mps: Dict[TransportMode, float] = field(
        default_factory=lambda: dict(DEFAULT_MAX_SPEED_MPS)
    )

    # Heading derivation
    minimum_heading_distance_m: float = 2.0

    # Filtering
    filter_strength: float = 0.35          # 0 = no smoothing, 1 = ignore new point
    min_jitter_distance_m: float = 1.0     # movement below this is treated as noise

    # Bounded history (do not store unlimited GPS history)
    history_size: int = 20

    # Timestamp sanity
    max_future_skew_s: float = 2.0  # tolerance for clock drift on "future" timestamps

    def max_speed_for_current_mode(self) -> float:
        return self.max_speed_mps.get(
            self.transport_mode, DEFAULT_MAX_SPEED_MPS[TransportMode.UNKNOWN]
        )
