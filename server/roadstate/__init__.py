"""Road state -- what is temporarily true about the roads, and what it costs.

    from roadstate import RoadStateStore, RoadStateSource, classify_all

    store = RoadStateStore(backend.documents)
    store.record(classify_all(reports_from_ingest))
    conditions = RoadStateSource(store, graphs)   # graphs: mapdata provider

Owns:
    closures, flooding, construction, incidents and restrictions: classifying
    a report into one of them, attaching it to published roads, keeping it for
    as long as it is in force, answering what is in force in an area, and
    expressing all of that to routing as blocked edges and cost multipliers

Does not own:
    fetching reports (`ingest`), how fast traffic is moving (`traffic`), road
    geometry (`mapdata`), or the search itself (`routing`).

The distinction from `traffic` is the one to hold on to. Traffic is a
measurement that decays: a speed, true for minutes, replaced by the next
reading. A condition is a statement with a validity window: this street is
closed until Friday, and that is as true at 3 a.m. as at rush hour. They reach
routing by different paths for the same reason -- a jam is slower, a closure is
impassable, and a router that cannot tell them apart sends a driver twenty
kilometres around a queue or straight into a barrier.

This module is the block's entire public surface. Stdlib-only.
"""

from .attribute import DEFAULT_RADIUS_M, attribute
from .classify import CLASSIFIERS, classify, classify_all
from .models import (
    DEFAULT_MULTIPLIERS,
    ConditionKind,
    RoadCondition,
    RoadStateSnapshot,
    Severity,
)
from .provider import RoadEdgeIndex, RoadStateSource
from .store import DEFAULT_OPEN_ENDED_TTL, RoadStateStore

__all__ = [
    # What a condition is
    "RoadCondition",
    "RoadStateSnapshot",
    "ConditionKind",
    "Severity",
    "DEFAULT_MULTIPLIERS",
    # Getting one from a report
    "classify",
    "classify_all",
    "CLASSIFIERS",
    "attribute",
    "DEFAULT_RADIUS_M",
    # Keeping and asking
    "RoadStateStore",
    "DEFAULT_OPEN_ENDED_TTL",
    # The seam routing reads
    "RoadStateSource",
    "RoadEdgeIndex",
]
