"""The map-graph provider: the server's answer to "what roads are here?".

This is the concrete side of :class:`routing.MapGraphProvider`. Routing holds
the protocol and never imports this module; this module imports routing's
types because building a graph means building *its* graph, which is the
ordinary direction for an adapter and a dependency routing itself never
returns.

    BBox ──▶ RoadNetwork (Overpass, a store, a fixture)
              │
              ▶ RoadSegment[] ──▶ build_graph ──▶ RoadGraph + node index
                                                    │
                                                    ▶ GraphView
                                                        .graph
                                                        .nearest_node()

Two things are cached, for different reasons. The segments are cached by the
source, because Overpass is shared volunteer infrastructure and asking it the
same question twice is impolite. The *built graph* is cached here, because
splitting several thousand ways at their junctions is the expensive half and
the result is identical for the same quantised area.

Snapping is a :class:`domain.SpatialIndex` over the built graph's node
coordinates. It is not a grid written here, because `traffic` and `roadstate`
need the same search over their own data and three copies of it is three
places for the ring-termination rule to be subtly different.

Inputs:  domain.BBox
Outputs: routing.GraphView
Not here: cost, traffic, closures, HTTP, SQL
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol, Sequence

from domain import BBox, Coord, GeoPoint, SpatialIndex
from routing import InMemoryRoadGraph, RoadGraph

from ..errors import MapDataError
from .build import GraphBuild, build_graph

__all__ = ["RoadGraphProvider", "NetworkGraphView"]

#: Decimal places the requested box is snapped to before it becomes a cache
#: key. Three places is roughly 100 m, so a small pan reuses one built graph.
AREA_PRECISION = 3

#: How many built graphs to keep. Each is a city-district-sized dictionary;
#: four covers a driver moving across a city without rebuilding on every
#: request, and bounds what an idle server holds.
DEFAULT_CACHE_SIZE = 4


class RoadNetwork(Protocol):
    """Anything that can answer "which roads are in this box?".

    Restated here rather than imported from ``mapdata.network`` so that this
    module reads on its own; they are the same shape and either satisfies the
    other.
    """

    def roads(self, bbox: BBox) -> Sequence: ...


@dataclass(frozen=True, slots=True)
class NetworkGraphView:
    """One built graph plus its snapping index. Satisfies ``routing.GraphView``."""

    _graph: InMemoryRoadGraph
    _index: SpatialIndex
    area: BBox
    build: GraphBuild

    @property
    def graph(self) -> RoadGraph:
        return self._graph

    def nearest_node(self, point: GeoPoint, *, within_m: float | None = None) -> str | None:
        """The junction closest to ``point``, or ``None`` if none is near enough.

        This is what turns a driver's coordinate into something routing will
        accept. Routing takes node ids and says in its contract that snapping
        is not its job; the nodes live here, so the snapping does too.
        """
        return self._index.nearest_label(point.as_tuple(), within_m=within_m)

    def summary(self) -> dict[str, int]:
        return self.build.summary()

    def road_edges(self) -> dict[str, tuple[str, ...]]:
        """Published road id to the edge ids built from it.

        Read off ``Edge.metadata["road_id"]``, which the builder writes, so
        this survives any change to how ids are spelled.
        """
        grouped: dict[str, list[str]] = {}
        for edge in self._graph.edges():
            road_id = edge.metadata.get("road_id")
            if road_id:
                grouped.setdefault(road_id, []).append(edge.id)
        return {road_id: tuple(sorted(ids)) for road_id, ids in grouped.items()}


class RoadGraphProvider:
    """Builds routable graphs for areas, and keeps the last few.

    Args:
        network: Where road segments come from -- an
            :class:`~mapdata.roads.overpass.OverpassRoadSource`, a store-backed
            source, or a fixture.
        cache_size: How many built graphs to keep.
        area_precision: Decimal places the requested box is snapped to.

    Thread-safe: a Flask development server handles requests on several
    threads, and two of them asking for overlapping areas at once must not
    each pay for a build. The lock is held across the build deliberately --
    building twice is worse than waiting once.
    """

    def __init__(
        self,
        network: RoadNetwork,
        *,
        cache_size: int = DEFAULT_CACHE_SIZE,
        area_precision: int = AREA_PRECISION,
    ) -> None:
        self._network = network
        self._cache_size = max(1, cache_size)
        self._precision = area_precision
        self._lock = threading.RLock()
        self._cache: dict[tuple[float, ...], NetworkGraphView] = {}

    def graph_for(self, area: BBox) -> NetworkGraphView:
        """The routable graph covering ``area``.

        Raises:
            MapDataError: the road network could not be read. Every other
                exception a source may raise is wrapped in this, so the
                routing service above sees one error type from map data.
        """
        snapped = area.quantized(self._precision)
        key = snapped.as_tuple()

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

            try:
                segments = list(self._network.roads(snapped))
            except MapDataError:
                raise
            except Exception as err:  # noqa: BLE001 - one error type leaves this block
                raise MapDataError(f"road network unavailable: {err}") from err

            build = build_graph(segments)
            view = NetworkGraphView(
                _graph=build.graph,
                _index=SpatialIndex(build.node_coords.items()),
                area=snapped,
                build=build,
            )
            self._remember(key, view)
            return view

    def road_edges(self, area: BBox) -> dict[str, tuple[str, ...]]:
        """Published road id to the edge ids built from it, for ``area``.

        This is what `traffic` and `roadstate` ask for. Both are keyed by road
        -- a sensor and a closure notice both name a way, not a stretch
        between two junctions -- and routing is keyed by edge. Publishing the
        mapping here means the ``way#index`` convention stays private to the
        builder: a consumer that reconstructed it would work today and break
        silently the first time splitting changed.
        """
        return self.graph_for(area).road_edges()

    def invalidate(self) -> None:
        """Drop every built graph. Used when the underlying data changes."""
        with self._lock:
            self._cache.clear()

    def _remember(self, key: tuple[float, ...], view: NetworkGraphView) -> None:
        self._cache[key] = view
        while len(self._cache) > self._cache_size:
            # Plain insertion order: the oldest build goes first. A true LRU
            # would need touch-on-read, and at four entries it would not
            # change which one is evicted often enough to justify the state.
            self._cache.pop(next(iter(self._cache)))
