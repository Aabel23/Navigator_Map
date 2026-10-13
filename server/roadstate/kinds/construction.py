"""Road works: the condition that is almost never blocking and always slow.

Works differ from the other three in a way that matters for routing: they are
scheduled. A feed publishes them with a start and an end, often weeks ahead,
and a server that ignored the window would route around a roadworks site for a
fortnight before it appeared and for a fortnight after it cleared. The window
is therefore carried through unchanged and enforced by
:meth:`~roadstate.models.RoadCondition.active_at`, not flattened into "there
are works here".

Severity follows how much of the road is left. Where a feed says how many
lanes are closed, that is the best signal available; where it does not, a
declared severity is used, and the default is medium rather than low because a
works site that a feed bothered to publish is rarely nothing.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..models import ConditionKind, RoadCondition, Severity

__all__ = ["as_construction", "WORKS_WORDS"]

WORKS_WORDS = (
    "roadwork",
    "road work",
    "construction",
    "works",
    "maintenance",
    "resurfacing",
    "repair",
)


def as_construction(report: Mapping[str, Any]) -> RoadCondition | None:
    """Read a normalized incident report as construction, or return ``None``."""
    kind = str(report.get("kind", "")).lower()
    text = f"{report.get('title', '')} {report.get('description', '')}".lower()
    if kind not in ("roadworks", "construction") and not any(
        word in text for word in WORKS_WORDS
    ):
        return None

    return RoadCondition(
        id=report["id"],
        kind=ConditionKind.CONSTRUCTION,
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
    lanes_closed = report.get("lanes_closed", report.get("metadata", {}).get("lanes_closed"))
    lanes_total = report.get("lanes_total", report.get("metadata", {}).get("lanes_total"))
    if lanes_closed is not None and lanes_total:
        try:
            share = float(lanes_closed) / float(lanes_total)
        except (TypeError, ValueError, ZeroDivisionError):
            share = None
        if share is not None:
            if share >= 1.0:
                return Severity.CRITICAL
            if share >= 0.5:
                return Severity.HIGH
            if share > 0.0:
                return Severity.MEDIUM
            return Severity.LOW

    declared = str(report.get("severity", "")).lower()
    try:
        return Severity(declared)
    except ValueError:
        return Severity.MEDIUM
