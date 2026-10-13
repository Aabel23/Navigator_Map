"""The reference road network, from OpenStreetMap via the Overpass API.

Free, keyless, worldwide, and the same data the map block is already drawing,
which is the point: a traffic segment derived from OSM geometry lands on top
of an OSM-derived basemap instead of a hundred metres beside it.

Free flow speed comes from the OSM ``maxspeed`` tag where a way carries one,
and from a per-class default where it does not. Both are labelled as what
they are: a posted limit is not a measurement of how fast traffic actually
moves when the road is clear, and in a dense city it is usually optimistic.
It is, however, the only free worldwide reference that exists.

Overpass is a shared volunteer service with no quota but a real cost per
query, so this source caches to disk by default and asks for a padded box, so
a small pan does not re-query.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Sequence

from ..errors import BadResponse
from ..http import HttpClient
from ..models import BBox, RoadSegment, coords_of

__all__ = ["OverpassRoadSource", "DEFAULT_ENDPOINT", "FREE_FLOW_BY_CLASS", "ROAD_CLASSES"]

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

#: The classes worth colouring. Service roads, tracks and footways are left
#: out: they carry no through traffic and would triple the geometry.
ROAD_CLASSES: tuple[str, ...] = (
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "residential",
    "unclassified",
)

#: Fallback free-flow speed in km/h for a way with no ``maxspeed``. Tuned for
#: dense Asian city traffic rather than European motorways, because that is
#: where this block has no measured feed and therefore actually needs a
#: default.
FREE_FLOW_BY_CLASS: dict[str, float] = {
    "motorway": 80.0,
    "motorway_link": 60.0,
    "trunk": 70.0,
    "trunk_link": 50.0,
    "primary": 50.0,
    "primary_link": 40.0,
    "secondary": 45.0,
    "secondary_link": 35.0,
    "tertiary": 40.0,
    "tertiary_link": 30.0,
    "residential": 30.0,
    "unclassified": 30.0,
}

DEFAULT_FREE_FLOW_KPH = 40.0


class OverpassRoadSource:
    """Fetches drivable OSM ways for a bounding box.

    Args:
        client: HTTP client, injected so tests never hit the network.
        endpoint: Overpass instance. Several public mirrors exist; the
            default is the main one.
        road_classes: Which ``highway`` values to ask for.
        cache_dir: Where to keep responses. ``None`` disables the disk cache.
        cache_ttl_s: How long a cached response stays usable. A day by
            default -- road geometry is not what changes minute to minute.
        pad_degrees: How far outside the requested box to fetch, so panning
            a little reuses the same cache entry.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        road_classes: Sequence[str] = ROAD_CLASSES,
        cache_dir: Path | str | None = None,
        cache_ttl_s: float = 24 * 3600.0,
        pad_degrees: float = 0.004,
        timeout_s: int = 30,
    ) -> None:
        self._client = client or HttpClient(timeout_s=float(timeout_s) + 10)
        self._endpoint = endpoint
        self._road_classes = tuple(road_classes)
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._cache_ttl_s = cache_ttl_s
        self._pad = pad_degrees
        self._timeout_s = timeout_s
        self._memory: dict[str, list[RoadSegment]] = {}

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        """Every drivable way intersecting ``bbox``, padded and cached."""
        area = bbox.expanded(self._pad).quantized(3)
        key = _cache_key(area, self._road_classes)
        cached = self._memory.get(key)
        if cached is not None:
            return cached

        payload = self._read_disk(key)
        if payload is None:
            payload = self._client.post_json(
                self._endpoint,
                _query(area, self._road_classes, self._timeout_s).encode("utf-8"),
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            self._write_disk(key, payload)

        segments = parse_overpass(payload)
        self._memory[key] = segments
        return segments

    def _read_disk(self, key: str) -> Any | None:
        if self._cache_dir is None:
            return None
        path = self._cache_dir / f"{key}.json"
        if not path.exists():
            return None
        if (time.time() - path.stat().st_mtime) > self._cache_ttl_s:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_disk(self, key: str, payload: Any) -> None:
        if self._cache_dir is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"{key}.json"
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            # A cache that cannot be written is a slower source, not a broken
            # one. The caller already has its answer.
            pass


def parse_overpass(payload: Any) -> list[RoadSegment]:
    """Turn an Overpass ``out geom`` response into road segments."""
    if not isinstance(payload, dict) or "elements" not in payload:
        raise BadResponse("overpass response had no elements")

    segments: list[RoadSegment] = []
    for element in payload["elements"]:
        if element.get("type") != "way":
            continue
        geometry = element.get("geometry") or []
        if len(geometry) < 2:
            continue
        tags = element.get("tags") or {}
        road_class = tags.get("highway", "unclassified")
        segments.append(
            RoadSegment(
                id=f"osm:way/{element['id']}",
                geometry=coords_of((point["lon"], point["lat"]) for point in geometry),
                road_class=road_class,
                free_flow_kph=free_flow_for(tags, road_class),
                name=tags.get("name"),
                oneway=tags.get("oneway") in ("yes", "1", "-1", "true"),
            )
        )
    return segments


def free_flow_for(tags: dict[str, Any], road_class: str) -> float:
    """Free-flow speed for a way: its ``maxspeed`` tag, or a class default."""
    parsed = parse_maxspeed(tags.get("maxspeed"))
    if parsed is not None:
        return parsed
    return FREE_FLOW_BY_CLASS.get(road_class, DEFAULT_FREE_FLOW_KPH)


def parse_maxspeed(value: Any) -> float | None:
    """Read an OSM ``maxspeed`` tag. Handles bare km/h and ``N mph``.

    Returns ``None`` for the tag values that are not a number at all --
    ``walk``, ``none``, ``signals`` and the national-default codes -- because
    guessing a speed from those is how a free-flow reference silently becomes
    fiction.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text.endswith("mph"):
        number = text.removesuffix("mph").strip()
        try:
            return float(number) * 1.609344
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _query(bbox: BBox, road_classes: Sequence[str], timeout_s: int) -> str:
    classes = "|".join(road_classes)
    # Overpass takes bbox as south,west,north,east -- the opposite order to
    # the GeoJSON one used everywhere else in this block.
    south_west_north_east = f"{bbox.south},{bbox.west},{bbox.north},{bbox.east}"
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'way["highway"~"^({classes})$"]({south_west_north_east});'
        f"out geom;"
    )


def _cache_key(bbox: BBox, road_classes: Sequence[str]) -> str:
    raw = f"{bbox.as_tuple()}|{','.join(road_classes)}"
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=10).hexdigest()
