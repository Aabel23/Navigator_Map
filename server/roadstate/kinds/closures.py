"""Road closures: the only condition that is blocking by definition.

A closure is the simplest condition to describe and the most consequential to
get wrong. If a closed road is merely expensive, the search will use it when
nothing else connects, and the driver arrives at a barrier. If an open road is
recorded as closed, a whole district can become unreachable from one bad
report. So the rule here is narrow on purpose: a report becomes a closure only
when the source said the road is closed or impassable, not when it said the
road is bad.

Everything softer -- a lane closure, a weight limit, a temporary one-way --
is a restriction, which slows a route without forbidding it.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..models import ConditionKind, RoadCondition, Severity

__all__ = ["as_closure", "CLOSURE_WORDS", "PARTIAL_WORDS"]

#: Words that mean the road cannot be driven at all. Matched against the
#: report's own kind field first and its text second, because a feed that
#: publishes a structured kind is more trustworthy than one that publishes
#: prose.
CLOSURE_WORDS = (
    "closed",
    "closure",
    "impassable",
    "blocked",
    "road_closed",
)

#: Words that look like a closure but are not one. Checked first: "partially
#: closed" contains "closed", and treating it as impassable would route a
#: driver around a road they could have used.
PARTIAL_WORDS = ("partial", "partly", "lane closed", "one lane", "single lane")


def as_closure(report: Mapping[str, Any]) -> RoadCondition | None:
    """Read a normalized incident report as a closure, or return ``None``."""
    kind = str(report.get("kind", "")).lower()
    text = f"{report.get('title', '')} {report.get('description', '')}".lower()

    if any(word in text for word in PARTIAL_WORDS):
        return None
    if kind not in CLOSURE_WORDS and not any(word in text for word in CLOSURE_WORDS):
        if not report.get("blocking"):
            return None

    return RoadCondition(
        id=report["id"],
        kind=ConditionKind.CLOSURE,
        severity=_severity(report),
        geometry=tuple(tuple(p) for p in report["geometry"]),
        source=report.get("source", "unknown"),
        road_ids=tuple(report.get("road_ids", ())),
        reported_at=report["reported_at"],
        starts_at=report.get("starts_at"),
        ends_at=report.get("ends_at"),
        blocking=True,
        description=report.get("description") or report.get("title"),
        metadata=dict(report.get("metadata", {})),
    )


def _severity(report: Mapping[str, Any]) -> Severity:
    """A closure is at least high: the road is gone either way.

    The source's own severity may raise it to critical but never lower it,
    because "how bad is it" and "can I drive down it" are different questions
    and only the second one decides a route.
    """
    declared = str(report.get("severity", "")).lower()
    if declared == Severity.CRITICAL.value:
        return Severity.CRITICAL
    return Severity.HIGH
