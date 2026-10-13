"""Which kind a report is, decided once, in a stated order.

The order is the whole content of this module, and it is not alphabetical.
Reports overlap: a feed describing a flooded street closed to traffic matches
both the closure rule and the flooding rule, and which one wins decides
whether a driver is routed around it or merely slowed. So:

    closure  ->  flooding  ->  construction  ->  incident

**Closure first**, because "you cannot go this way" is the strongest claim in
the system and the most expensive to get wrong in the permissive direction.
**Flooding second**, because it is the condition that turns into a closure on
its own and the one this project's home city produces most of.
**Construction third**, because it is scheduled and therefore distinguishable
by its window rather than its wording. **Incident last**, as the catch-all
that never declines.

Each classifier reads the same normalized report shape and decides for itself
whether the report is its business, which is what keeps the four rule sets
independently readable and independently wrong.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .kinds import as_closure, as_construction, as_flooding, as_incident
from .models import RoadCondition

__all__ = ["classify", "classify_all", "CLASSIFIERS"]

#: Tried in order; the first that returns a condition wins. ``as_incident``
#: is last and never returns ``None``.
CLASSIFIERS = (as_closure, as_flooding, as_construction, as_incident)


def classify(report: Mapping[str, Any]) -> RoadCondition:
    """Turn one normalized incident report into a road condition.

    Args:
        report: A mapping carrying at least ``id``, ``geometry`` and
            ``reported_at``; optionally ``kind``, ``severity``, ``title``,
            ``description``, ``road_ids``, ``blocking``, ``starts_at``,
            ``ends_at`` and ``metadata``. This is deliberately a plain mapping
            rather than an ingest type: `ingest` and `roadstate` do not import
            each other, and the connector between them is a shape, not a
            class.

    Raises:
        KeyError: the report is missing a required field. Not caught -- a
            report the ingest layer let through without an id or geometry is a
            bug upstream, and silently dropping it would hide it.
    """
    for classifier in CLASSIFIERS:
        condition = classifier(report)
        if condition is not None:
            return condition
    raise AssertionError("the incident classifier must not decline")  # pragma: no cover


def classify_all(reports: Iterable[Mapping[str, Any]]) -> tuple[RoadCondition, ...]:
    """Classify many reports, skipping ones that are structurally unusable.

    A malformed report is dropped rather than failing the batch: one bad row
    in a feed of four hundred must not cost the server the other 399.
    """
    conditions: list[RoadCondition] = []
    for report in reports:
        try:
            conditions.append(classify(report))
        except (KeyError, ValueError, TypeError):
            continue
    return tuple(conditions)
