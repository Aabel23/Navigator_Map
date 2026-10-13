"""
Location / Positioning Block
=============================

Converts raw device/browser position measurements into a clean,
normalized ``PositionUpdate`` stream.

This package is intentionally independent from routing, map rendering,
and traffic logic. Consumers depend only on the ``PositionUpdate``
contract produced by ``LocationProcessor`` -- never on browser
geolocation objects or a specific position source.

Public API
----------

    from location import LocationProcessor, LocationConfig, RawPosition
    from location.simulator import SimulatorLocationSource

    processor = LocationProcessor(LocationConfig())
    update = processor.process(raw_position)   # -> PositionUpdate | None
    processor.get_latest()                     # -> PositionUpdate | None
    processor.subscribe(callback)
    processor.reset()

See README.md in this package's parent directory for the full data-flow
description, configuration reference, and integration guide.
"""

from .models import RawPosition, PositionUpdate
from .errors import RejectionReason, ValidationResult
from .config import LocationConfig
from .processor import LocationProcessor
from .filters import PositionFilter, SimplePositionFilter
from .sources import LocationSource, BrowserGeolocationSource
from . import geometry

__all__ = [
    "RawPosition",
    "PositionUpdate",
    "RejectionReason",
    "ValidationResult",
    "LocationConfig",
    "LocationProcessor",
    "PositionFilter",
    "SimplePositionFilter",
    "LocationSource",
    "BrowserGeolocationSource",
    "geometry",
]
