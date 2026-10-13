"""Traffic block: dynamic traffic state for the navigation system.

The public interface of the block. Nothing outside `traffic/` should reach
past this module into a submodule -- import what is re-exported here, and the
internals stay free to move.

    from traffic import BBox, TrafficStore
    from traffic.providers.digitraffic import DigitrafficProvider

    store = TrafficStore([DigitrafficProvider()])
    result = store.snapshot(BBox(24.7, 60.1, 25.1, 60.3))

Everything in the core is stdlib-only, so the routing engine or a test can
import it without installing anything.
"""

from __future__ import annotations

from .errors import BadResponse, OutsideCoverage, ProviderUnavailable, TrafficError
from .geo import Coord
from .http import HttpClient
from .levels import (
    LEVEL_COLORS,
    LEVEL_THRESHOLDS,
    TrafficLevel,
    level_for_ratio,
    level_for_speed,
    level_payload,
)
from .models import (
    SIMULATED_SOURCE,
    BBox,
    IncidentKind,
    RoadSegment,
    Severity,
    TrafficIncident,
    TrafficObservation,
    TrafficSegment,
    TrafficSnapshot,
)
from .provider import RoadSource, TrafficProvider
from .store import StoreResult, TrafficStore

__all__ = [
    "BBox",
    "BadResponse",
    "Coord",
    "HttpClient",
    "IncidentKind",
    "LEVEL_COLORS",
    "LEVEL_THRESHOLDS",
    "OutsideCoverage",
    "ProviderUnavailable",
    "RoadSegment",
    "RoadSource",
    "SIMULATED_SOURCE",
    "Severity",
    "StoreResult",
    "TrafficError",
    "TrafficIncident",
    "TrafficLevel",
    "TrafficObservation",
    "TrafficProvider",
    "TrafficSegment",
    "TrafficSnapshot",
    "TrafficStore",
    "level_for_ratio",
    "level_for_speed",
    "level_payload",
]
