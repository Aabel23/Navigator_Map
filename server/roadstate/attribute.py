"""Working out which roads a condition is actually on.

Most free incident feeds publish geometry and no road reference. Digitraffic
gives a polyline; a citizen flood report gives a dropped pin; an operator
entering a closure by hand gives whatever the map let them draw. None of that
names a published road, and routing needs one -- a condition with no
``road_ids`` is drawable and reportable but cannot change a route.

So this module attaches conditions to roads the same way `traffic` attaches
measurements to them, over the same :class:`domain.SpatialIndex`, with one
difference that matters: a condition's geometry is matched *along its whole
length*, not at its midpoint. A closed stretch of road is a line covering
several published ways, and attributing it only to the way nearest its middle
would leave the rest of it open.

The radius is the other decision. It is wider than the traffic one, because an
incident is reported by a person at a place rather than measured by a sensor
bolted to a gantry, and a report pinned to the pavement beside the road is the
normal case rather than an error.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Sequence

from domain import index_of_polylines

from .models import RoadCondition

__all__ = ["attribute", "DEFAULT_RADIUS_M"]

#: How far a condition's geometry may be from a road and still be attributed
#: to it.
DEFAULT_RADIUS_M = 60.0


def attribute(
    conditions: Iterable[RoadCondition],
    roads: Sequence,
    *,
    radius_m: float = DEFAULT_RADIUS_M,
) -> tuple[RoadCondition, ...]:
    """Fill in ``road_ids`` for conditions that arrived without them.

    A condition that already names its roads is returned untouched: the source
    knew better than a proximity guess, and overriding it would discard the
    only reliable attribution in the system.

    A condition nothing could be attributed to keeps its empty ``road_ids``
    rather than being dropped. It still belongs on the map and in the API
    response -- "there is a crash here" is worth showing even when the server
    cannot say which way it blocks.
    """
    index = index_of_polylines(roads)
    if index.is_empty:
        return tuple(conditions)

    attributed: list[RoadCondition] = []
    for condition in conditions:
        if condition.road_ids:
            attributed.append(condition)
            continue
        road_ids = tuple(
            sorted(
                {
                    label
                    for label in (
                        index.nearest_label(point, within_m=radius_m)
                        for point in condition.geometry
                    )
                    if label is not None
                }
            )
        )
        attributed.append(replace(condition, road_ids=road_ids) if road_ids else condition)
    return tuple(attributed)
