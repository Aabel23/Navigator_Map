"""GPS probes: the one kind of data this server is given rather than fetches.

A client posts where it is, how fast it is going, and which way it is facing.
That is the cheapest traffic source in existence -- it costs nothing, it covers
exactly where drivers are, and unlike every free feed it works in Ho Chi Minh
City -- and it is also the one most easily turned into nonsense, because it
arrives unvalidated from an untrusted device.

So the gate is here, at the boundary, and it is deliberately strict:

* **Coordinates must be real.** A swapped lat/lon pair lands in the Gulf of
  Guinea and would otherwise sit in the database looking like a road.
* **Speeds must be plausible.** A phone that briefly thinks it is doing
  900 kph is a GPS artefact, not a measurement, and one of them is enough to
  make a street look clear that is not.
* **Timestamps must be aware, recent, and not in the future.** A probe from
  next Tuesday poisons every freshness check downstream.
* **A stationary probe is not congestion.** A parked car reports zero, and
  treating that as a standstill would make every car park a traffic jam. Only
  probes that are moving contribute a speed.

What leaves is an :class:`~ingest.models.Observations` batch exactly like the
one a national sensor feed produces, with a low confidence and its own source
name -- so everything downstream treats it as one more provider rather than
as a special case.

Inputs:  raw probe dictionaries, from the API
Outputs: Observations
Not here: matching a probe to a road (`traffic` does that), storing it
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from domain import BBox, Coord

from ..errors import BadResponse
from ..models import Observations, TrafficObservation

__all__ = [
    "GpsProbe",
    "PROBE_SOURCE",
    "PROBE_CONFIDENCE",
    "MAX_PLAUSIBLE_KPH",
    "MIN_MOVING_KPH",
    "MAX_PROBE_AGE",
    "parse_probe",
    "probes_to_observations",
]

#: Source name every probe-derived record carries.
PROBE_SOURCE = "gps-probe"

#: Low, but above the simulated provider's. A crowd of real devices beats a
#: model and loses to a calibrated roadside sensor, which is the right order.
PROBE_CONFIDENCE = 0.5

#: Above this, the reading is a GPS artefact rather than a vehicle.
MAX_PLAUSIBLE_KPH = 250.0

#: Below this, the vehicle is stopped or crawling in a car park, and its speed
#: says nothing about the road.
MIN_MOVING_KPH = 3.0

#: How old a probe may be and still be accepted.
MAX_PROBE_AGE = timedelta(minutes=10)

#: How far into the future a probe's timestamp may be before it is refused.
#: A minute of tolerance, because client clocks drift and refusing every
#: slightly-fast phone would drop a lot of usable data.
MAX_CLOCK_SKEW = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class GpsProbe:
    """One validated position report.

    Attributes:
        device_id: Opaque, supplied by the client. Used only to keep one
            device from dominating a road's average; never resolved to a
            person by this block.
        point: Where, ``(lon, lat)``.
        observed_at: When, timezone-aware.
        speed_kph: Ground speed, or ``None`` when the device did not report
            one.
        bearing: Degrees from north, or ``None``.
        accuracy_m: Reported horizontal accuracy, or ``None``.
    """

    device_id: str
    point: Coord
    observed_at: datetime
    speed_kph: float | None = None
    bearing: float | None = None
    accuracy_m: float | None = None

    @property
    def is_moving(self) -> bool:
        return self.speed_kph is not None and self.speed_kph >= MIN_MOVING_KPH


def parse_probe(raw: Mapping[str, Any], *, now: datetime | None = None) -> GpsProbe:
    """Validate and normalise one raw probe.

    Raises:
        BadResponse: the probe is unusable. The message says which rule it
            broke, because a client sending malformed probes needs to be able
            to find out why rather than watch them vanish.
    """
    moment = now or datetime.now(timezone.utc)

    try:
        lon = float(raw["lon"])
        lat = float(raw["lat"])
    except (KeyError, TypeError, ValueError) as err:
        raise BadResponse(f"probe has no usable position: {err}") from err

    if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
        raise BadResponse(f"probe position ({lon}, {lat}) is out of range")

    observed_at = _moment(raw.get("observed_at"))
    if observed_at is None:
        raise BadResponse("probe has no usable timestamp")
    if observed_at.tzinfo is None:
        raise BadResponse(
            "probe timestamp has no timezone; the server will not guess one, "
            "because a guess is wrong by whole hours with nothing looking broken"
        )
    if observed_at > moment + MAX_CLOCK_SKEW:
        raise BadResponse("probe timestamp is in the future")
    if moment - observed_at > MAX_PROBE_AGE:
        raise BadResponse("probe is too old to be useful")

    speed = _optional_float(raw.get("speed_kph"))
    if speed is not None and (speed < 0 or speed > MAX_PLAUSIBLE_KPH):
        # Dropped rather than rejected: the position is still good, and a
        # single implausible speed reading should not cost the whole probe.
        speed = None

    device_id = str(raw.get("device_id") or "anonymous")

    return GpsProbe(
        device_id=device_id,
        point=(lon, lat),
        observed_at=observed_at,
        speed_kph=speed,
        bearing=_optional_float(raw.get("bearing")),
        accuracy_m=_optional_float(raw.get("accuracy_m")),
    )


def probes_to_observations(
    probes: Sequence[GpsProbe], area: BBox | None = None
) -> Observations:
    """Turn validated probes into one observations batch.

    Only moving probes become observations. A stationary one is still a valid
    probe -- it may be stored, and it tells a fleet view where a vehicle is --
    but it is not evidence about how fast the road is moving.

    ``free_flow_kph`` is left unset. A probe knows its own speed and nothing
    about what the road is capable of; supplying the reference is `traffic`'s
    job, from the published road the probe is attached to.
    """
    moving = [probe for probe in probes if probe.is_moving]
    box = area or (
        BBox.covering([p.point for p in probes], pad_degrees=0.0)
        if probes
        else BBox(0.0, 0.0, 0.0, 0.0)
    )

    observations = tuple(
        TrafficObservation(
            id=f"{PROBE_SOURCE}:{probe.device_id}:{int(probe.observed_at.timestamp())}",
            point=probe.point,
            observed_at=probe.observed_at,
            source=PROBE_SOURCE,
            speed_kph=probe.speed_kph,
            bearing=probe.bearing,
            confidence=PROBE_CONFIDENCE,
        )
        for probe in moving
    )

    return Observations(
        bbox=box,
        source=PROBE_SOURCE,
        observed_at=max((p.observed_at for p in probes), default=datetime.now(timezone.utc)),
        observations=observations,
    )


def _moment(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    return None


def _optional_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
