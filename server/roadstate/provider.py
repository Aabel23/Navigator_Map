"""The road-state provider: conditions expressed the two ways routing needs.

Routing asks two separate questions, and the whole design of this module is
that it must never answer them with the same mechanism:

    blocked_edges(area)   ->  frozenset[edge_id]   a constraint
    multipliers_for(area) ->  {edge_id: float}     a cost

A closure goes down the first path. Expressing it as a very large cost instead
is the classic navigation defect: when nothing else connects the two ends of a
trip, the search "uses" the expensive road and returns a route down a flooded
street, and the only visible symptom is an unusually long ETA. A constraint
cannot be traded off, so the honest answer -- no route -- is what comes back.

Everything else goes down the second. Roadworks, a crash, shallow water: the
road is worse, not gone, and a driver would rather crawl past a works site
than be sent five kilometres around it.

Like the traffic cost provider, this converts road ids to edge ids by asking
map data for the mapping rather than reconstructing the ``way#index``
convention. Two blocks guessing the same private convention is one refactor
away from routes that quietly ignore every closure.

Inputs:  a RoadStateStore, and something that maps road ids to edge ids
Outputs: blocked edge ids, and edge cost multipliers
Not here: classification, ingestion, persistence mechanics
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from domain import BBox

from .models import DEFAULT_MULTIPLIERS, RoadCondition
from .store import RoadStateStore

__all__ = ["RoadEdgeIndex", "RoadStateSource"]


@runtime_checkable
class RoadEdgeIndex(Protocol):
    """Maps a published road id to the routing edges built from it.

    Satisfied by :class:`mapdata.RoadGraphProvider`. Structural, so neither
    block imports the other.
    """

    def road_edges(self, area: BBox) -> Mapping[str, tuple[str, ...]]: ...


class RoadStateSource:
    """Answers routing's two road-condition questions for an area.

    Args:
        store: Where conditions are kept.
        edges: Where the road-to-edge mapping comes from.
        multipliers: The kind/severity cost table. Injectable so that a
            deployment can be more or less cautious about flooding without
            editing the models.
    """

    def __init__(
        self,
        store: RoadStateStore,
        edges: RoadEdgeIndex,
        *,
        multipliers: Mapping = DEFAULT_MULTIPLIERS,
    ) -> None:
        self._store = store
        self._edges = edges
        self._table = multipliers

    def blocked_edges(self, area: BBox) -> frozenset[str]:
        """Edge ids that may not be traversed in ``area`` right now."""
        conditions = [c for c in self._store.active_in(area) if c.blocking]
        if not conditions:
            return frozenset()

        # Deliberately not degraded: if the road-to-edge mapping cannot be
        # read, the honest answer is that we do not know what is closed, and
        # returning an empty set would route a driver through a closure. The
        # exception reaches the routing service, which turns it into "no
        # route" -- the safe failure.
        by_road = self._edges.road_edges(area)
        return frozenset(
            edge_id
            for condition in conditions
            for road_id in condition.road_ids
            for edge_id in by_road.get(road_id, ())
        )

    def multipliers_for(self, area: BBox) -> Mapping[str, float]:
        """Edge id to multiplier for conditions that slow rather than block.

        Where two conditions affect the same road the worse one wins. Adding
        or multiplying them would charge a driver twice for what is usually
        one event reported by two sources -- a crash and the queue behind it.
        """
        conditions = [c for c in self._store.active_in(area) if not c.blocking]
        if not conditions:
            return {}

        by_road = self._road_edges(area)
        worst: dict[str, float] = {}
        for condition in conditions:
            value = condition.multiplier(self._table)
            if value <= 1.0:
                continue
            for road_id in condition.road_ids:
                for edge_id in by_road.get(road_id, ()):
                    if value > worst.get(edge_id, 1.0):
                        worst[edge_id] = value
        return worst

    def describe(self) -> dict[str, object]:
        return {"source": "roadstate-store", **self._store.stats()}

    def _road_edges(self, area: BBox) -> Mapping[str, tuple[str, ...]]:
        """The mapping, or nothing, for the advisory path only.

        Costs degrade: a route priced without knowing about a works site is a
        worse route, and a request that failed over it would be no route at
        all. :meth:`blocked_edges` deliberately does not use this -- see the
        comment there.
        """
        try:
            return self._edges.road_edges(area)
        except Exception:
            return {}
