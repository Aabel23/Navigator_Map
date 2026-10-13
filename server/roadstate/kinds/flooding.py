"""Flooding: the condition this project exists in a city famous for.

Ho Chi Minh City floods on a schedule -- tidal, seasonal, and after any heavy
rain -- and a navigation system there that cannot route around water is not
much of one. Which makes this the condition where getting the blocking
threshold right matters most.

The rule is depth, where a report gives it. Motor vehicles stop being able to
drive through standing water somewhere around 30 cm, and are genuinely at risk
of being carried well before a metre; the threshold here is deliberately below
where a car actually fails, because the cost of an unnecessary detour is
minutes and the cost of the other error is the vehicle.

Where no depth is published -- the common case, since most reports are a human
saying a street is flooded -- severity falls back to what the source declared,
and only an explicitly impassable report blocks.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..models import ConditionKind, RoadCondition, Severity

__all__ = ["as_flooding", "BLOCKING_DEPTH_CM", "FLOOD_WORDS"]

#: Standing water at or past this depth makes the road blocking rather than
#: merely slow. Conservative on purpose -- see the module docstring.
BLOCKING_DEPTH_CM = 30.0

#: Depth at which a report is treated as critical even if it is passable.
SEVERE_DEPTH_CM = 20.0

FLOOD_WORDS = ("flood", "flooded", "flooding", "water", "ngập", "submerged", "inundat")


def as_flooding(report: Mapping[str, Any]) -> RoadCondition | None:
    """Read a normalized incident report as flooding, or return ``None``."""
    kind = str(report.get("kind", "")).lower()
    text = f"{report.get('title', '')} {report.get('description', '')}".lower()
    if "flood" not in kind and not any(word in text for word in FLOOD_WORDS):
        return None

    depth_cm = _depth_cm(report)
    blocking = bool(report.get("blocking")) or (
        depth_cm is not None and depth_cm >= BLOCKING_DEPTH_CM
    )

    return RoadCondition(
        id=report["id"],
        kind=ConditionKind.FLOODING,
        severity=_severity(report, depth_cm),
        geometry=tuple(tuple(p) for p in report["geometry"]),
        source=report.get("source", "unknown"),
        road_ids=tuple(report.get("road_ids", ())),
        reported_at=report["reported_at"],
        starts_at=report.get("starts_at"),
        ends_at=report.get("ends_at"),
        blocking=blocking,
        description=report.get("description") or report.get("title"),
        metadata={**dict(report.get("metadata", {})), "depth_cm": depth_cm},
    )


def _depth_cm(report: Mapping[str, Any]) -> float | None:
    raw = report.get("depth_cm", report.get("metadata", {}).get("depth_cm"))
    if raw is None:
        return None
    try:
        depth = float(raw)
    except (TypeError, ValueError):
        return None
    return depth if depth >= 0 else None


def _severity(report: Mapping[str, Any], depth_cm: float | None) -> Severity:
    if depth_cm is not None:
        if depth_cm >= BLOCKING_DEPTH_CM:
            return Severity.CRITICAL
        if depth_cm >= SEVERE_DEPTH_CM:
            return Severity.HIGH
        return Severity.MEDIUM
    declared = str(report.get("severity", "")).lower()
    try:
        return Severity(declared)
    except ValueError:
        return Severity.MEDIUM
