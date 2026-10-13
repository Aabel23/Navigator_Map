"""The traffic cost provider: road speeds expressed as edge multipliers.

This is the concrete side of :class:`routing.TrafficCostProvider`, and the one
place the two id spaces meet. Traffic is keyed by *road* -- ``osm:way/12345``,
the thing a sensor and a driver both recognise. Routing is keyed by *edge* --
``osm:way/12345#2``, one stretch between two junctions, because a long way
carries several. The mapping between them is map data's, so this module asks
for it rather than reconstructing the naming convention:

    TrafficState        RoadEdgeIndex (mapdata)
    road_id -> speed    road_id -> (edge_id, ...)
            \\              /
             ▶ {edge_id: multiplier} ──▶ routing.DynamicCostModel

Doing it by convention instead -- ``f"{road_id}#0"`` -- would work today and
break silently the first time map data changed how it splits ways, with the
only symptom being routes that ignore traffic. Asking is cheap; guessing is a
defect waiting for a refactor.

A road's every edge gets the same multiplier. The reading describes the whole
way and the block has nothing finer, so pretending otherwise would be
inventing precision.

Inputs:  a TrafficState, and something that maps road ids to edge ids
Outputs: Mapping[edge_id, float], every value >= 1.0
Not here: HTTP, providers, levels, or what the router does with it
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from domain import BBox

from ..processing.cost import MAX_MULTIPLIER, multiplier_for
from .store import TrafficState

__all__ = ["RoadEdgeIndex", "TrafficCostSource"]


@runtime_checkable
class RoadEdgeIndex(Protocol):
    """Maps a published road id to the routing edges built from it.

    Satisfied by :class:`mapdata.RoadGraphProvider`. Structural, so neither
    block imports the other.
    """

    def road_edges(self, area: BBox) -> Mapping[str, tuple[str, ...]]: ...


class TrafficCostSource:
    """Answers "how much slower than free flow is each edge right now?".

    Args:
        state: The current traffic picture.
        edges: Where the road-to-edge mapping comes from.
        ceiling: Largest multiplier produced. Standstill is capped rather than
            infinite -- a jam is not a closure, and `roadstate` is what says a
            road cannot be used at all.
    """

    def __init__(
        self,
        state: TrafficState,
        edges: RoadEdgeIndex,
        *,
        ceiling: float = MAX_MULTIPLIER,
    ) -> None:
        self._state = state
        self._edges = edges
        self._ceiling = ceiling

    def multipliers_for(self, area: BBox) -> Mapping[str, float]:
        """Edge id to multiplier, for edges whose road has a fresh reading.

        An edge with no reading is absent rather than present as 1.0. Absent
        means "nothing known", which is what
        :class:`routing.DynamicCostModel` already treats as free flow, and a
        map holding an entry for every edge in the city would be paid for on
        every request to say nothing.
        """
        readings = self._state.fresh()
        if not readings:
            return {}

        try:
            by_road = self._edges.road_edges(area)
        except Exception:
            # Without the mapping there is nothing honest to return. Routing
            # on free-flow speeds is a worse route; failing the request would
            # be no route at all.
            return {}

        multipliers: dict[str, float] = {}
        for road_id, speed in readings.items():
            value = multiplier_for(speed, ceiling=self._ceiling)
            if value <= 1.0:
                continue
            for edge_id in by_road.get(road_id, ()):
                multipliers[edge_id] = value
        return multipliers

    def describe(self) -> dict[str, object]:
        return {"source": "traffic-state", **self._state.stats()}
