"""Incident reports: what a person or a feed says is wrong with a road.

This is the narrowest module in the block and the one with the most at stake,
because an incident report is the only input that can make a road unusable. A
bad traffic reading makes a route slightly wrong; a bad closure report makes a
district unreachable.

So what leaves here is deliberately *not* a decision. This module validates
shape -- there is an id, there is geometry, the timestamps are aware and in
order -- normalises field names across sources, and stamps provenance. What
kind of condition the report describes, how severe it is, and whether it
blocks are all judgements, and they belong to `roadstate`, which makes them in
one place for every source at once.

The report that leaves is a plain mapping rather than a class. That is the
connector between the two blocks: `ingest` and `roadstate` do not import each
other, and a shape travels between them where a type would be a dependency
edge.

Inputs:  raw report dictionaries, from the API or from a feed's incidents
Outputs: normalized report mappings, ready for roadstate.classify
Not here: classification, severity policy, blocking policy
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..errors import BadResponse
from ..models import TrafficIncident, coords_of

__all__ = ["normalize_report", "normalize_reports", "report_of_incident", "REPORT_SOURCE"]

#: Source stamped on a report that arrived through the API rather than from a
#: named feed. Kept distinct so an operator entry is never mistaken for a
#: measurement from a road authority.
REPORT_SOURCE = "report"


def normalize_report(
    raw: Mapping[str, Any], *, source: str = REPORT_SOURCE, now: datetime | None = None
) -> dict[str, Any]:
    """Validate and normalise one raw incident report.

    Args:
        raw: Whatever arrived. Accepts ``geometry`` as a list of ``[lon, lat]``
            pairs, or a single ``lon``/``lat`` pair for a point report.
        source: Provenance, stamped on the result.
        now: Injected clock, for tests.

    Raises:
        BadResponse: the report cannot be used. Reporting why matters here --
            an operator whose closure silently vanished has no way to find out
            it was malformed.
    """
    moment = now or datetime.now(timezone.utc)

    report_id = str(raw.get("id") or "").strip()
    if not report_id:
        raise BadResponse("incident report has no id")

    geometry = _geometry(raw)
    if not geometry:
        raise BadResponse(f"incident report {report_id!r} has no usable geometry")

    reported_at = _moment(raw.get("reported_at")) or moment
    starts_at = _moment(raw.get("starts_at"))
    ends_at = _moment(raw.get("ends_at"))
    for name, value in (("reported_at", reported_at), ("starts_at", starts_at), ("ends_at", ends_at)):
        if value is not None and value.tzinfo is None:
            raise BadResponse(f"incident report {report_id!r} has a naive {name}")
    if starts_at and ends_at and ends_at < starts_at:
        raise BadResponse(f"incident report {report_id!r} ends before it starts")

    return {
        "id": f"{source}:{report_id}" if ":" not in report_id else report_id,
        "kind": str(raw.get("kind", "")).lower(),
        "severity": str(raw.get("severity", "")).lower(),
        "geometry": [list(point) for point in geometry],
        "source": source,
        "road_ids": tuple(str(r) for r in raw.get("road_ids", ()) if r),
        "reported_at": reported_at,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "blocking": bool(raw.get("blocking", False)),
        "title": raw.get("title"),
        "description": raw.get("description"),
        "metadata": dict(raw.get("metadata", {})),
    }


def normalize_reports(
    raws: Iterable[Mapping[str, Any]], *, source: str = REPORT_SOURCE
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalise many reports.

    Returns:
        The reports that passed, and one message per report that did not. Both
        halves are returned rather than the failures being logged and dropped:
        a client submitting a batch needs to know which rows were refused, and
        one bad row must not cost it the others.
    """
    good: list[dict[str, Any]] = []
    bad: list[str] = []
    for raw in raws:
        try:
            good.append(normalize_report(raw, source=source))
        except BadResponse as err:
            bad.append(str(err))
    return good, bad


def report_of_incident(incident: TrafficIncident) -> dict[str, Any]:
    """Turn a feed's :class:`~ingest.models.TrafficIncident` into a report.

    This is the second entrance to the same door. Digitraffic's road-works and
    accident messages arrive as incidents inside an observations batch; they
    are the same thing an operator types into the API, and they must end up
    classified by the same rules rather than by a second code path that drifts.
    """
    return {
        "id": incident.id,
        "kind": incident.kind.value,
        "severity": incident.severity.value,
        "geometry": [list(point) for point in incident.geometry],
        "source": incident.source,
        "road_ids": incident.road_ids,
        "reported_at": incident.reported_at,
        "starts_at": incident.starts_at,
        "ends_at": incident.ends_at,
        "blocking": incident.blocking,
        "title": incident.title,
        "description": incident.description,
        "metadata": {"speed_limit_kph": incident.speed_limit_kph},
    }


def _geometry(raw: Mapping[str, Any]) -> tuple[tuple[float, float], ...]:
    if raw.get("geometry"):
        try:
            return coords_of(raw["geometry"])
        except (TypeError, ValueError, IndexError):
            return ()
    if raw.get("lon") is not None and raw.get("lat") is not None:
        try:
            return ((float(raw["lon"]), float(raw["lat"])),)
        except (TypeError, ValueError):
            return ()
    return ()


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
