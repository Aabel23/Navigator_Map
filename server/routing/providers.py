"""What routing needs from the rest of the server, stated as three questions.

Routing computes paths. It does not read a database, call Overpass, decide
what congestion means, or know whether a street is flooded. But it needs all
of those answers, and this module is where it says so -- in terms of what it
needs, not of who provides it.

Every one is a :class:`~typing.Protocol`, which is the whole point. `mapdata`,
`traffic` and `roadstate` satisfy these by shape and never import this module;
routing depends on the protocols and never imports those blocks. So there is
no import edge in either direction, nothing below routing can pull routing in,
and a test substitutes a dict-backed fake in two lines::

    class FakeTraffic:
        def multipliers_for(self, area): return {"seg_1": 2.0}

That is also the answer to "the routing engine must not know whether the data
came from SQLite, PostgreSQL, Redis, HTTP, a file or memory": it cannot,
because none of that is expressible in any of these three signatures.

Inputs:  a :class:`domain.BBox` -- the area a route may touch
Outputs: a graph, a multiplier map, a set of blocked edge ids
Not here: how any of them are obtained
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from domain import BBox, GeoPoint

from .graph import RoadGraph

__all__ = ["GraphView", "MapGraphProvider", "TrafficCostProvider", "RoadStateProvider"]


@runtime_checkable
class GraphView(Protocol):
    """A road graph for one area, plus the snapping that area makes possible.

    Snapping lives with the graph rather than in routing because the graph is
    what holds the nodes. Routing takes node ids and says so in its contract;
    turning a coordinate into one is a map-data question, and answering it in
    two places would give the system two ways to disagree about where the
    driver is.
    """

    @property
    def graph(self) -> RoadGraph:
        """The searchable network. Shared and read-only."""
        ...

    def nearest_node(self, point: GeoPoint, *, within_m: float | None = None) -> str | None:
        """Id of the closest junction, or ``None`` when nothing is near enough."""
        ...


@runtime_checkable
class MapGraphProvider(Protocol):
    """Supplies the road graph covering an area."""

    def graph_for(self, area: BBox) -> GraphView:
        """Build or fetch the routable graph for ``area``.

        Raises:
            Exception: implementation-specific. The routing service converts
                a failure here into a routing error rather than letting a
                provider's exception type reach the API.
        """
        ...


@runtime_checkable
class TrafficCostProvider(Protocol):
    """Supplies how much slower than free flow each edge currently is."""

    def multipliers_for(self, area: BBox) -> Mapping[str, float]:
        """Edge id to multiplier, for edges with a current reading.

        Every value must be at least 1.0. Conditions may slow a road down,
        never speed it past its free-flow speed -- that is what keeps the A*
        heuristic admissible, and
        :class:`~routing.costs.DynamicCostModel` rejects anything lower.
        An edge with no reading is simply absent.
        """
        ...


@runtime_checkable
class RoadStateProvider(Protocol):
    """Supplies temporary road conditions: closures, flooding, works, incidents."""

    def blocked_edges(self, area: BBox) -> frozenset[str]:
        """Edges that may not be traversed at all right now.

        A closure is a constraint, not an enormous cost. Expressing it as a
        multiplier would let the search "use" a closed road when nothing else
        connects, and return a route down a flooded street rather than
        reporting that there is none.
        """
        ...

    def multipliers_for(self, area: BBox) -> Mapping[str, float]:
        """Edge id to multiplier for conditions that slow rather than block.

        Same rule as :class:`TrafficCostProvider`: at least 1.0, absent when
        there is nothing to say.
        """
        ...
