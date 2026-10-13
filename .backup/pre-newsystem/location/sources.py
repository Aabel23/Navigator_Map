"""LocationSource abstraction.

The processor never talks to a browser, an OS location API, or hardware
directly. Every source implements the same tiny interface and produces
``RawPosition`` objects; the processor is agnostic to where they came
from.

    LocationSource
          |
          v
    RawPosition
          |
          v
    LocationProcessor

``BrowserGeolocationSource`` below documents the JS-side boundary. This
package is pure Python and does not itself call `navigator.geolocation`
(that API only exists inside a browser's JS runtime) -- in a real
browser-hosted app, a thin JS adapter calls `watchPosition`/`getCurrentPosition`
and converts each callback payload into the fields below, then hands
them to whatever runs this processor (e.g. via a bridge, a WASM build,
or a server-side ingestion endpoint). Keeping that conversion isolated
here means the core processor stays platform-independent, per the
compatibility requirement: swapping Browser GPS for Android/iOS GPS,
an external receiver, or vehicle telemetry never touches routing, map,
or navigation code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from .models import PositionSource, RawPosition

RawPositionCallback = Callable[[RawPosition], None]


class LocationSource(ABC):
    """Common interface every position source implements."""

    @abstractmethod
    def start(self, callback: RawPositionCallback) -> None:
        """Begin producing RawPosition updates, delivered via ``callback``."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Stop producing updates. Must be safe to call multiple times."""
        raise NotImplementedError


class BrowserGeolocationSource(LocationSource):
    """Adapter boundary for `navigator.geolocation.watchPosition`.

    This class does not itself talk to a browser -- it defines the
    conversion contract a thin JS/bridge layer should satisfy. Feed each
    raw `GeolocationPosition`-shaped payload (as a dict, e.g. from a JS
    bridge or a WebView message channel) into ``ingest()``; this class
    converts it into a ``RawPosition`` and forwards it to the
    subscribed callback. ``start``/``stop`` are provided so callers can
    treat this uniformly alongside other ``LocationSource`` implementations
    (e.g. a real integration would call `navigator.geolocation.watchPosition`
    on start() and `clearWatch` on stop(), from the JS side of the bridge).
    """

    def __init__(self) -> None:
        self._callback: Optional[RawPositionCallback] = None
        self._running = False

    def start(self, callback: RawPositionCallback) -> None:
        self._callback = callback
        self._running = True

    def stop(self) -> None:
        self._running = False
        self._callback = None

    def ingest(self, payload: Dict[str, Any]) -> None:
        """Convert one `GeolocationPosition`-shaped payload and forward it.

        Expected shape (mirrors the browser API's `coords` object):

            {
                "coords": {
                    "latitude": ...,
                    "longitude": ...,
                    "accuracy": ...,
                    "altitude": ...,          # nullable
                    "altitudeAccuracy": ...,  # nullable
                    "heading": ...,           # nullable
                    "speed": ...,             # nullable
                },
                "timestamp": ...,  # Unix milliseconds
            }
        """
        if not self._running or self._callback is None:
            return

        coords = payload.get("coords", {})
        raw = RawPosition(
            latitude=coords.get("latitude"),
            longitude=coords.get("longitude"),
            timestamp=payload.get("timestamp"),
            accuracy=coords.get("accuracy"),
            altitude=coords.get("altitude"),
            altitude_accuracy=coords.get("altitudeAccuracy"),
            heading=coords.get("heading"),
            speed=coords.get("speed"),
            source=PositionSource.BROWSER,
        )
        self._callback(raw)
