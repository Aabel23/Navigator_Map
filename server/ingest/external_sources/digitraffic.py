"""Fintraffic Digitraffic -- real, live, free, and keyless.

This is the reference provider of the block, and the reason it is the
reference is that it is the only traffic source found that is genuinely open
on every axis at once: no API key, no registration, no quota, no paid tier
waiting behind the free one, JSON rather than DATEX II XML, and measurements
rather than estimates. Around 490 roadside stations across Finland publish a
five-minute rolling average speed per direction, refreshed every minute, and
the station metadata publishes a free-flow reference speed for the same
direction -- so the congestion ratio comes from one source that measured both
halves of it, instead of a measured speed divided by a legal speed limit.

    https://www.digitraffic.fi/en/road-traffic/

Three upstream endpoints, three very different refresh rates, which is why
each is cached separately:

* ``/api/tms/v1/stations`` -- where the stations are. Changes a few times a
  year; cached for a day.
* ``/api/tms/v1/stations/{id}`` -- the free-flow reference speeds, which are
  only on the per-station document. Fetched lazily for the stations actually
  inside the requested box and then kept, because fetching all 519 up front
  to draw a dozen would be rude and slow.
* ``/api/tms/v1/stations/data`` -- every current reading in one 145 kB
  response. One request beats twenty; cached for a minute, which is the rate
  the data itself moves at.
* ``/api/traffic-message/v1/messages`` -- incidents and road works, with real
  geometry. Cached for five minutes, the publisher-side update interval.

What this provider cannot do is cover anywhere else. Finland publishes this;
Vietnam does not, and neither does most of the world. :meth:`coverage` says
so out loud rather than returning an empty batch that reads like a
free-flowing city.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from ..errors import BadResponse, OutsideCoverage
from domain import Coord
from ..http import HttpClient
from ..models import (
    BBox,
    IncidentKind,
    Observations,
    Severity,
    TrafficIncident,
    TrafficObservation,
    coords_of,
)
from ..provider import TrafficProvider

__all__ = ["DigitrafficProvider", "FINLAND"]

#: Finland plus its territorial waters, generously rounded. Used to skip this
#: provider entirely for a box it cannot answer for.
FINLAND = BBox(west=19.0, south=59.5, east=31.7, north=70.2)

BASE_URL = "https://tie.digitraffic.fi"

#: Average speed over the last five minutes, per direction. Direction 1 is the
#: increasing road-address direction; direction 2 is the opposite one.
SPEED_SENSORS = {
    1: "KESKINOPEUS_5MIN_LIUKUVA_SUUNTA1",
    2: "KESKINOPEUS_5MIN_LIUKUVA_SUUNTA2",
}

#: Vehicles per hour over the same window. Not used for the level -- flow and
#: congestion are not the same thing, and a jammed road can be nearly empty --
#: but useful next to a speed when judging whether a reading means anything.
FLOW_SENSORS = {
    1: "OHITUKSET_5MIN_LIUKUVA_SUUNTA1",
    2: "OHITUKSET_5MIN_LIUKUVA_SUUNTA2",
}

#: Message classes worth showing a driver, mapped onto this block's kinds.
MESSAGE_TYPES = {
    "TRAFFIC_ANNOUNCEMENT": IncidentKind.OTHER,
    "ROAD_WORK": IncidentKind.ROADWORKS,
}

#: Words in a Finnish or English announcement that mean the road is shut. A
#: keyword test is crude, but the feed has no structured "closed" flag, and
#: getting this wrong in the safe direction only downgrades a closure to a
#: warning.
BLOCKING_WORDS = ("suljettu", "closed", "poikkeusreitti", "kielletty")

STATION_TTL_S = 24 * 3600.0
DETAIL_TTL_S = 24 * 3600.0
DATA_TTL_S = 60.0
MESSAGE_TTL_S = 300.0


@dataclass(slots=True)
class _Cached:
    value: Any
    fetched_at: float


class DigitrafficProvider(TrafficProvider):
    """Live Finnish road measurements and incidents.

    Args:
        client: HTTP client. Injected so tests can serve recorded responses
            without touching the network.
        base_url: Override for a mirror or a local replay proxy.
        include_incidents: Turn off to skip the two message requests when
            only speeds are wanted.
        clock: Monotonic seconds, injected so cache expiry is testable.
    """

    name = "digitraffic"

    def __init__(
        self,
        *,
        client: HttpClient | None = None,
        base_url: str = BASE_URL,
        include_incidents: bool = True,
        clock: Any = time.monotonic,
    ) -> None:
        self._client = client or HttpClient()
        self._base = base_url.rstrip("/")
        self._include_incidents = include_incidents
        self._clock = clock
        self._stations: _Cached | None = None
        self._data: _Cached | None = None
        self._messages: dict[str, _Cached] = {}
        self._details: dict[int, dict[str, Any]] = {}

    def coverage(self) -> BBox:
        return FINLAND

    def fetch(self, bbox: BBox) -> Observations:
        if not self.covers(bbox):
            raise OutsideCoverage(f"{self.name} covers Finland only, not {bbox.as_tuple()}")

        stations = self._station_index(bbox)
        observations: list[TrafficObservation] = []
        if stations:
            readings = self._readings()
            for station_id, station in stations.items():
                observations.extend(self._observations_for(station, readings.get(station_id, {})))

        incidents = self._incidents(bbox) if self._include_incidents else []
        return Observations(
            bbox=bbox,
            source=self.name,
            observed_at=datetime.now(timezone.utc),
            observations=tuple(observations),
            incidents=tuple(incidents),
        )

    # -- stations ------------------------------------------------------------

    def _station_index(self, bbox: BBox) -> dict[int, dict[str, Any]]:
        """The stations inside ``bbox``, each merged with its detail document.

        The list endpoint has positions but no free-flow speeds; the detail
        endpoint has free-flow speeds but is one request per station. So the
        list is fetched wholesale and the details only for what is on screen.
        """
        index: dict[int, dict[str, Any]] = {}
        for feature in self._stations_geojson().get("features", []):
            point = _point_of(feature.get("geometry"))
            if point is None or not bbox.contains(point):
                continue
            properties = feature.get("properties") or {}
            if properties.get("collectionStatus") == "REMOVED_PERMANENTLY":
                continue
            station_id = int(properties.get("id", feature.get("id", -1)))
            if station_id < 0:
                continue
            index[station_id] = {"id": station_id, "point": point, **properties, **self._detail(station_id)}
        return index

    def _stations_geojson(self) -> dict[str, Any]:
        if self._fresh(self._stations, STATION_TTL_S):
            return self._stations.value  # type: ignore[union-attr]
        payload = self._client.get_json(f"{self._base}/api/tms/v1/stations?lastUpdated=false")
        if not isinstance(payload, dict):
            raise BadResponse("tms station list was not an object")
        self._stations = _Cached(payload, self._clock())
        return payload

    def _detail(self, station_id: int) -> dict[str, Any]:
        """Free-flow speeds and names for one station. Fetched once, kept.

        A station that will not load is remembered as an empty detail rather
        than retried on every refresh: its readings are still usable, they
        just have no free-flow reference, so their ratio is None and `roadstate`
        classifies them as unknown rather than as free-flowing.
        """
        cached = self._details.get(station_id)
        if cached is not None:
            return cached
        try:
            payload = self._client.get_json(f"{self._base}/api/tms/v1/stations/{station_id}")
            detail = (payload or {}).get("properties") or {}
        except Exception:
            detail = {}
        self._details[station_id] = detail
        return detail

    def _readings(self) -> dict[int, dict[str, float]]:
        """Every station reading, as ``{station id: {sensor name: value}}``."""
        if self._fresh(self._data, DATA_TTL_S):
            return self._data.value  # type: ignore[union-attr]
        payload = self._client.get_json(f"{self._base}/api/tms/v1/stations/data")
        if not isinstance(payload, dict):
            raise BadResponse("tms station data was not an object")
        readings: dict[int, dict[str, float]] = {}
        for station in payload.get("stations", []):
            values = {
                sensor["name"]: sensor["value"]
                for sensor in station.get("sensorValues", [])
                if sensor.get("value") is not None
            }
            values["_measuredTime"] = _newest_measured_time(station.get("sensorValues", []))
            readings[int(station["id"])] = values
        self._data = _Cached(readings, self._clock())
        return readings

    def _observations_for(
        self, station: dict[str, Any], values: dict[str, Any]
    ) -> list[TrafficObservation]:
        """Up to two observations per station -- one per direction of travel."""
        if not values:
            return []
        observed_at = values.get("_measuredTime") or datetime.now(timezone.utc)
        bearing = station.get("bearing")
        out: list[TrafficObservation] = []
        for direction in (1, 2):
            speed = values.get(SPEED_SENSORS[direction])
            if speed is None:
                continue
            out.append(
                TrafficObservation(
                    id=f"digitraffic:{station['id']}:{direction}",
                    point=station["point"],
                    observed_at=observed_at,
                    source=self.name,
                    speed_kph=float(speed),
                    free_flow_kph=_free_flow(station, direction),
                    flow_vph=_optional_float(values.get(FLOW_SENSORS[direction])),
                    # Direction 2 runs against the road address direction, so
                    # its heading is the station bearing turned around.
                    bearing=_direction_bearing(bearing, direction),
                    road_name=_station_name(station),
                )
            )
        return out

    # -- incidents -----------------------------------------------------------

    def _incidents(self, bbox: BBox) -> list[TrafficIncident]:
        out: list[TrafficIncident] = []
        for situation_type, kind in MESSAGE_TYPES.items():
            for feature in self._messages_geojson(situation_type).get("features", []):
                incident = _incident_from_feature(feature, kind, self.name)
                if incident is None:
                    continue
                if not bbox.touches_any(incident.geometry):
                    continue
                out.append(incident)
        return out

    def _messages_geojson(self, situation_type: str) -> dict[str, Any]:
        cached = self._messages.get(situation_type)
        if self._fresh(cached, MESSAGE_TTL_S):
            return cached.value  # type: ignore[union-attr]
        url = (
            f"{self._base}/api/traffic-message/v1/messages"
            f"?inactiveHours=0&includeAreaGeometry=false&situationType={situation_type}"
        )
        payload = self._client.get_json(url)
        if not isinstance(payload, dict):
            raise BadResponse(f"{situation_type} messages were not an object")
        self._messages[situation_type] = _Cached(payload, self._clock())
        return payload

    # -- cache ---------------------------------------------------------------

    def _fresh(self, cached: _Cached | None, ttl_s: float) -> bool:
        if cached is None:
            return False
        return (self._clock() - cached.fetched_at) < ttl_s


# -- parsing -----------------------------------------------------------------


def _point_of(geometry: Any) -> Coord | None:
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        return None
    return (float(coordinates[0]), float(coordinates[1]))


def _free_flow(station: dict[str, Any], direction: int) -> float | None:
    value = station.get(f"freeFlowSpeed{direction}")
    if not value:
        return None
    return float(value)


def _direction_bearing(bearing: Any, direction: int) -> float | None:
    if bearing is None:
        return None
    return (float(bearing) + (180.0 if direction == 2 else 0.0)) % 360.0


def _station_name(station: dict[str, Any]) -> str | None:
    names = station.get("names") or {}
    return names.get("en") or names.get("fi") or station.get("name")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _newest_measured_time(sensor_values: Iterable[dict[str, Any]]) -> datetime | None:
    stamps = [
        _parse_time(sensor.get("measuredTime"))
        for sensor in sensor_values
        if sensor.get("measuredTime")
    ]
    real = [s for s in stamps if s is not None]
    if not real:
        return None
    return max(real)


def _parse_time(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _incident_from_feature(
    feature: dict[str, Any], kind: IncidentKind, source: str
) -> TrafficIncident | None:
    properties = feature.get("properties") or {}
    geometry = _incident_geometry(feature.get("geometry"))
    if not geometry:
        return None

    announcement = _first_announcement(properties.get("announcements"))
    title = (announcement.get("title") or "").strip() or None
    window = announcement.get("timeAndDuration") or {}
    starts_at = _parse_time(window.get("startTime"))
    ends_at = _parse_time(window.get("endTime"))
    blocking = _looks_blocking(title, announcement.get("additionalInformation"))

    return TrafficIncident(
        id=f"{source}:{properties.get('situationId', id(feature))}",
        kind=IncidentKind.CLOSURE if blocking else kind,
        severity=_severity_for(kind, blocking),
        geometry=geometry,
        source=source,
        reported_at=_parse_time(properties.get("releaseTime")) or datetime.now(timezone.utc),
        title=title,
        description=(announcement.get("additionalInformation") or None),
        starts_at=starts_at,
        ends_at=ends_at,
        road_name=_road_name_of(announcement),
        blocking=blocking,
        speed_limit_kph=_speed_limit_of(announcement),
    )


def _incident_geometry(geometry: Any) -> tuple[Coord, ...]:
    """Flatten whatever GeoJSON the feed used into one coordinate run.

    A multi-part incident becomes one polyline. That is a simplification, but
    the parts of a single situation are consecutive stretches of the same
    road, so drawing them as one line is what a reader expects anyway.
    """
    if not isinstance(geometry, dict):
        return ()
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Point":
        return coords_of([coordinates]) if len(coordinates) >= 2 else ()
    if kind == "LineString":
        return coords_of(coordinates)
    if kind == "MultiLineString":
        return coords_of([point for part in coordinates for point in part])
    if kind == "Polygon":
        return coords_of(coordinates[0]) if coordinates else ()
    return ()


def _first_announcement(announcements: Any) -> dict[str, Any]:
    if not isinstance(announcements, list) or not announcements:
        return {}
    for announcement in announcements:
        if announcement.get("language") == "EN":
            return announcement
    return announcements[0]


def _road_name_of(announcement: dict[str, Any]) -> str | None:
    location = announcement.get("locationDetails") or {}
    road = (location.get("roadAddressLocation") or {}).get("primaryPoint") or {}
    alert_c = road.get("alertCLocation") or {}
    return alert_c.get("name") or road.get("municipality")


def _speed_limit_of(announcement: dict[str, Any]) -> float | None:
    for item in announcement.get("features") or []:
        if item.get("unit") == "km/h" and item.get("quantity"):
            return float(item["quantity"])
    return None


def _looks_blocking(*texts: Any) -> bool:
    joined = " ".join(t.lower() for t in texts if isinstance(t, str))
    return any(word in joined for word in BLOCKING_WORDS)


def _severity_for(kind: IncidentKind, blocking: bool) -> Severity:
    if blocking:
        return Severity.CRITICAL
    if kind is IncidentKind.ROADWORKS:
        return Severity.MEDIUM
    return Severity.LOW


def bounding_stations(features: Sequence[dict[str, Any]], bbox: BBox) -> list[int]:
    """Station ids inside ``bbox``. Exposed for tests and diagnostics."""
    out: list[int] = []
    for feature in features:
        point = _point_of(feature.get("geometry"))
        if point and bbox.contains(point):
            out.append(int((feature.get("properties") or {}).get("id", -1)))
    return out
