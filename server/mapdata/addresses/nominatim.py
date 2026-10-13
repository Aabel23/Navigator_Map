"""Reverse geocoding: a coordinate in, a street address out.

Nominatim is OpenStreetMap's own geocoder -- free, keyless, and built over the
same data the road network and the client's basemap come from, so the street
it names is the street the driver sees drawn under the position dot.

Its public instance has a usage policy, and staying free means keeping to it:

* **At most one request per second.** Enforced here with a lock and a clock,
  not left to the client. A phone reporting a position every second would
  otherwise be the whole budget on its own.
* **Identify the application.** The block's `HttpClient` sends a User-Agent.
* **Cache.** A coordinate is rounded to about 11 m before it becomes a cache
  key, which is inside the accuracy of a phone fix -- two readings from the
  same doorstep are the same question.

Inputs:  a point, ``(lon, lat)``
Outputs: an :class:`Address`
Not here: forward search (text to coordinate), which nothing needs yet.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from storage import Cache, JsonFileCache, cache_key

from ..errors import BadResponse
from ..http import HttpClient
from ..models import Coord

__all__ = ["Address", "NominatimAddressSource", "parse_nominatim", "DEFAULT_ENDPOINT"]

DEFAULT_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"

#: The public instance's published limit.
MIN_INTERVAL_S = 1.0

#: Decimal places a coordinate keeps in the cache key. Four is about 11 m.
KEY_PRECISION = 4

#: Answers kept in process, in front of the disk cache. A driver crossing a
#: city passes a few thousand ~11 m cells; this holds a long drive's worth.
MEMORY_ENTRIES = 4096

ATTRIBUTION = "© OpenStreetMap contributors, ODbL. Geocoding by Nominatim."

#: Nominatim's ``address`` keys, coarsest last, grouped by the role each plays
#: in a Vietnamese address: số nhà, đường, phường, quận, thành phố.
_STREET_KEYS = ("road", "pedestrian", "footway", "path", "residential")
_WARD_KEYS = ("quarter", "suburb", "village", "neighbourhood", "hamlet")
_DISTRICT_KEYS = ("city_district", "district", "county", "town")
_CITY_KEYS = ("city", "state", "province")


@dataclass(frozen=True, slots=True)
class Address:
    """What a coordinate is called.

    Attributes:
        point: The coordinate that was asked about, ``(lon, lat)``.
        label: A short, readable line built from the parts below -- what a
            driver is shown.
        display_name: The geocoder's own full string, unedited.
        house_number, street, ward, district, city, country: Parts, each
            ``None`` where OSM has nothing.
        place_name: The name of the thing at the point, when it has one --
            a shop, a building, a park.
        source, attribution: Where it came from and how it must be credited.
    """

    point: Coord
    label: str
    display_name: str
    house_number: str | None = None
    street: str | None = None
    ward: str | None = None
    district: str | None = None
    city: str | None = None
    country: str | None = None
    place_name: str | None = None
    source: str = "nominatim"
    attribution: str = ATTRIBUTION

    def as_dict(self) -> dict[str, Any]:
        return {
            "point": list(self.point),
            "label": self.label,
            "display_name": self.display_name,
            "house_number": self.house_number,
            "street": self.street,
            "ward": self.ward,
            "district": self.district,
            "city": self.city,
            "country": self.country,
            "place_name": self.place_name,
            "source": self.source,
            "attribution": self.attribution,
        }


@dataclass
class NominatimAddressSource:
    """Reverse-geocodes points through Nominatim, politely.

    Args:
        client: HTTP client, injected so tests never hit the network.
        endpoint: The ``/reverse`` URL. A self-hosted instance drops the rate
            limit by setting ``min_interval_s`` to zero.
        cache: Any :class:`storage.Cache`.
        language: ``Accept-Language`` for the names returned.
        min_interval_s: Shortest gap between two upstream requests.
        clock, sleep: Injected so the rate limit is testable without waiting.
    """

    client: HttpClient = field(default_factory=lambda: HttpClient(timeout_s=10.0))
    endpoint: str = DEFAULT_ENDPOINT
    cache: Cache = field(default_factory=lambda: JsonFileCache(None))
    language: str = "vi,en"
    min_interval_s: float = MIN_INTERVAL_S
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_request: float | None = field(default=None, init=False, repr=False)
    _memory: OrderedDict = field(default_factory=OrderedDict, init=False, repr=False)
    _memory_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def reverse(self, point: Coord) -> Address:
        """The address at ``point``. Raises the block's errors on failure."""
        lon = round(float(point[0]), KEY_PRECISION)
        lat = round(float(point[1]), KEY_PRECISION)
        key = cache_key("nominatim-reverse", lon, lat, self.language)

        with self._memory_lock:
            payload = self._memory.get(key)
        if payload is None:
            payload = self.cache.get(key)
        if payload is None:
            payload = self._fetch(lon, lat)
            self.cache.put(key, payload)
        self._remember(key, payload)
        return parse_nominatim(payload, (float(point[0]), float(point[1])))

    def _remember(self, key: str, payload: Any) -> None:
        with self._memory_lock:
            self._memory[key] = payload
            self._memory.move_to_end(key)
            while len(self._memory) > MEMORY_ENTRIES:
                self._memory.popitem(last=False)

    def _fetch(self, lon: float, lat: float) -> Any:
        query = urllib.parse.urlencode(
            {
                "format": "jsonv2",
                "lat": f"{lat:.{KEY_PRECISION}f}",
                "lon": f"{lon:.{KEY_PRECISION}f}",
                "zoom": 18,
                "addressdetails": 1,
            }
        )
        with self._lock:
            if self._last_request is not None:
                wait = self.min_interval_s - (self.clock() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            try:
                return self.client.get_json(
                    f"{self.endpoint}?{query}", {"Accept-Language": self.language}
                )
            finally:
                self._last_request = self.clock()


def parse_nominatim(payload: Any, point: Coord) -> Address:
    """Turn a ``format=jsonv2`` reverse response into an :class:`Address`."""
    if not isinstance(payload, dict):
        raise BadResponse("nominatim response was not an object")
    if "error" in payload:
        # Nominatim answers 200 with an error body for a point in the sea or
        # outside its coverage. That is an answer, not an outage.
        return Address(point=point, label="Không xác định được địa chỉ", display_name="")

    parts = payload.get("address") or {}
    if not isinstance(parts, dict):
        raise BadResponse("nominatim address was not an object")

    house = parts.get("house_number")
    street = _first(parts, _STREET_KEYS)
    ward = _first(parts, _WARD_KEYS)
    district = _first(parts, _DISTRICT_KEYS)
    city = _first(parts, _CITY_KEYS)
    name = payload.get("name") or None
    if name in (street, ward, district, city):
        name = None

    street_line = " ".join(p for p in (house, street) if p)
    pieces = [p for p in (name, street_line, ward, district, city) if p]
    display = str(payload.get("display_name") or "")
    label = ", ".join(_dedupe(pieces)) or display or "Không xác định được địa chỉ"

    return Address(
        point=point,
        label=label,
        display_name=display,
        house_number=house,
        street=street,
        ward=ward,
        district=district,
        city=city,
        country=parts.get("country"),
        place_name=name,
    )


def _first(parts: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = parts.get(key)
        if value:
            return str(value)
    return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [item for item in items if not (item in seen or seen.add(item))]
