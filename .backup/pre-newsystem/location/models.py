"""Input (``RawPosition``) and output (``PositionUpdate``) contracts.

Units are explicit and fixed for the whole subsystem:

    latitude / longitude   -> degrees
    accuracy                -> meters (1-sigma radius, provider-defined)
    altitude                -> meters
    altitude_accuracy       -> meters
    heading                 -> degrees, 0=North, 90=East, 180=South, 270=West
    speed                   -> meters/second
    timestamp               -> Unix milliseconds (int)

All optional fields are nullable (``None``). Only ``latitude``,
``longitude`` and ``timestamp`` are required on ``RawPosition``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PositionSource(str, Enum):
    BROWSER = "browser"
    SIMULATOR = "simulator"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RawPosition:
    """A single, unvalidated measurement from a location source."""

    latitude: float
    longitude: float
    timestamp: int  # Unix milliseconds

    accuracy: Optional[float] = None            # meters
    altitude: Optional[float] = None            # meters
    altitude_accuracy: Optional[float] = None   # meters
    heading: Optional[float] = None             # degrees
    speed: Optional[float] = None               # meters/second
    source: PositionSource = PositionSource.UNKNOWN


@dataclass(frozen=True)
class PositionUpdate:
    """Normalized, accepted position state handed to consumers.

    This is the only contract that routing, map rendering, navigation
    state, and tracking/logging should depend on.
    """

    latitude: float
    longitude: float
    accuracy: Optional[float]
    timestamp: int  # Unix milliseconds

    altitude: Optional[float]
    heading: Optional[float]
    speed: Optional[float]

    age: float                 # seconds, current_time - timestamp at process() call
    is_stale: bool
    is_valid: bool

    distance_from_previous: Optional[float]   # meters
    time_since_previous: Optional[float]      # seconds
    calculated_speed: Optional[float]         # meters/second, derived if provider speed absent

    source: PositionSource
