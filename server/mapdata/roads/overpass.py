"""The reference road network, from OpenStreetMap via the Overpass API.

Free, keyless, worldwide, and the same data the client's basemap is already
drawing, which is the point: anything derived from OSM geometry lands on top
of an OSM-derived basemap instead of a hundred metres beside it.

Free-flow speed comes from the OSM ``maxspeed`` tag where a way carries one,
and from a per-class default where it does not. Both are labelled as what
they are: a posted limit is not a measurement of how fast traffic actually
moves when the road is clear, and in a dense city it is usually optimistic.
It is, however, the only free worldwide reference that exists.

Overpass is a shared volunteer service with no quota but a real cost per
query, so this source caches through the `storage` block and asks for a
padded box, so a small pan does not re-query.
"""

from __future__ import annotations

from typing import Any, Sequence

from storage import Cache, JsonFileCache, cache_key

from ..errors import BadResponse
from ..http import HttpClient
from ..models import BBox, RoadSegment, coords_of

__all__ = [
    "OverpassRoadSource",
    "parse_overpass",
    "free_flow_for",
    "parse_maxspeed",
    "DEFAULT_ENDPOINT",
    "FREE_FLOW_BY_CLASS",
    "ROAD_CLASSES",
]

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

#: The classes worth publishing. Service roads, tracks and footways are left
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
#: where there is no measured feed and therefore where a default actually has
#: to carry the weight.
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
    """Fetches and publishes drivable OSM ways for a bounding box.

    Args:
        client: HTTP client, injected so tests never hit the network.
        endpoint: Overpass instance. Several public mirrors exist; the
            default is the main one.
        road_classes: Which ``highway`` values to ask for.
        cache: Where responses are kept between runs. Any
            :class:`storage.Cache` -- the backend's own, or a
            :class:`storage.JsonFileCache`. The default is one with no
            directory, which caches in memory only.
        pad_degrees: How far outside the requested box to fetch, so panning
            a little reuses the same cache entry.
        timeout_s: Passed to Overpass in the query itself as well as used for
            the socket, so the service can give up before the client does.
    """

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        road_classes: Sequence[str] = ROAD_CLASSES,
        cache: Cache | None = None,
        pad_degrees: float = 0.004,
        timeout_s: int = 30,
    ) -> None:
        self._client = client or HttpClient(timeout_s=float(timeout_s) + 10)
        self._endpoint = endpoint
        self._road_classes = tuple(road_classes)
        self._cache = cache if cache is not None else JsonFileCache(None)
        self._pad = pad_degrees
        self._timeout_s = timeout_s
        self._memory: dict[str, list[RoadSegment]] = {}

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        """Every drivable way intersecting ``bbox``, padded and cached.

        This is the method the `RoadNetwork` connector names. A consumer that
        can answer it is a road network as far as this project is concerned,
        whether it reads Overpass, a PBF extract or a fixture file.
        """
        area = bbox.expanded(self._pad).quantized(3)
        key = cache_key(area.as_tuple(), ",".join(self._road_classes))

        cached = self._memory.get(key)
        if cached is not None:
            return cached

        payload = self._cache.get(key)
        if payload is None:
            payload = self._client.post_json(
                self._endpoint,
                _query(area, self._road_classes, self._timeout_s).encode("utf-8"),
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            self._cache.put(key, payload)

        segments = parse_overpass(payload)
        self._memory[key] = segments
        return segments


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
