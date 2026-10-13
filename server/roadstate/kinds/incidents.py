"""Accidents, obstructions and hazards: the catch-all, and the shortest-lived.

Everything a feed reports that is not a closure, a flood or a works site lands
here. That makes this the module where being permissive is right: a crash, a
broken-down lorry, debris and an unspecified "traffic event" all slow a road
down by an amount nobody can measure from a report, and the useful thing for
routing is to know that something is wrong there at all.

Unlike works, incidents usually arrive without an end time. Several free feeds
publish an incident and withdraw it once it clears rather than predicting how
long it will take -- which is honest, and means an open-ended window here is
normal rather than missing data. The store ages them out instead; see
:class:`~roadstate.store.RoadStateStore`.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..models import ConditionKind, RoadCondition, Severity

__all__ = ["as_incident", "HAZARD_WORDS"]

#: Words that make a report a hazard -- a condition of the road surface or its
#: surroundings -- rather than an incident involving vehicles. The distinction
#: is only for what a driver is shown; both cost the same.
HAZARD_WORDS = ("debris", "ice", "snow", "fog", "landslide", "fallen", "animal", "oil")


def as_incident(report: Mapping[str, Any]) -> RoadCondition:
    """Read any remaining report as an incident or a hazard.

    Never returns ``None``: this is the last classifier tried, and a report
    nothing else recognised still describes something wrong with a road.
    """
    text = f"{report.get('title', '')} {report.get('description', '')}".lower()
    kind = (
        ConditionKind.HAZARD
        if any(word in text for word in HAZARD_WORDS)
        else ConditionKind.INCIDENT
    )

    return RoadCondition(
        id=report["id"],
        kind=kind,
        severity=_severity(report),
        geometry=tuple(tuple(p) for p in report["geometry"]),
        source=report.get("source", "unknown"),
        road_ids=tuple(report.get("road_ids", ())),
        reported_at=report["reported_at"],
        starts_at=report.get("starts_at"),
        ends_at=report.get("ends_at"),
        blocking=bool(report.get("blocking")),
        description=report.get("description") or report.get("title"),
        metadata=dict(report.get("metadata", {})),
    )


def _severity(report: Mapping[str, Any]) -> Severity:
    declared = str(report.get("severity", "")).lower()
    try:
        return Severity(declared)
    except ValueError:
        return Severity.MEDIUM
