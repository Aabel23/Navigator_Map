"""Coordinates in, graph ids out -- the piece the routing block refuses to do.

The routing connector is explicit about this: "Routing takes graph node ids,
never coordinates: converting a GPS fix to a position on the network is map
matching's responsibility, and doing it in both places would give the system
two ways to disagree about where the driver is."

There is no ``map_matching`` block yet, so the simulator supplies the crudest
honest version of one: nearest junction, and nearest road. It is nearest-point
matching with no path history and no heading filter, which is exactly what a
real map matcher improves on -- and naming it here, in the sandbox, keeps that
gap visible instead of letting it dissolve into the routing block.

Both indexes are plain degree grids. A city holds tens of thousands of
vertices, a lookup touches a handful of cells, and nothing here is on a hot
path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from .blocks import InMemoryRoadGraph
from .geodesy import Coord, haversine_m, point_to_segment_m

__all__ = ["Match", "NodeIndex", "EdgeIndex"]

#: Grid cell size in degrees of latitude: roughly 220 m, a couple of city
#: blocks. Big enough that cells stay populated, small enough that a radius
#: query walks only a few of them.
_CELL_DEG = 0.002

#: Metres in one degree of latitude. Longitude is this times cos(latitude),
#: which is why every span below is widened before it is turned into cells --
#: at Helsinki's latitude a degree of longitude is barely half as long as a
#: degree of latitude, and a grid search that forgot would quietly miss roads.
_M_PER_DEG_LAT = 111_320.0


def _cells_around(point: Coord, radius_deg: float) -> Iterator[tuple[int, int]]:
    """Every grid cell that can hold a point within ``radius_deg`` (as latitude)."""
    lat_span = max(1, math.ceil(radius_deg / _CELL_DEG))
    shrink = max(0.2, math.cos(math.radians(point[1])))
    lon_span = max(1, math.ceil(radius_deg / (_CELL_DEG * shrink)))
    cx, cy = int(point[0] // _CELL_DEG), int(point[1] // _CELL_DEG)
    for dx in range(-lon_span, lon_span + 1):
        for dy in range(-lat_span, lat_span + 1):
            yield (cx + dx, cy + dy)


@dataclass(frozen=True, slots=True)
class Match:
    """Where a coordinate was decided to be, on the network.

    Attributes:
        node_id: The junction the position was snapped to.
        distance_m: How far the snap moved. Reported rather than hidden: a
            large number is the difference between "on this street" and "the
            nearest street the graph happens to know about".
        point: The junction's own coordinate, ``(lon, lat)``.
    """

    node_id: str
    distance_m: float
    point: Coord


class NodeIndex:
    """Nearest routable junction to a coordinate.

    Args:
        graph: The built graph.
        node_ids: Which nodes may be matched to. The builder passes the
            mutually-reachable set, so a picked point can never land somewhere
            the router would then refuse to route from.
    """

    def __init__(self, graph: InMemoryRoadGraph, node_ids: Iterable[str]) -> None:
        self._points: dict[str, Coord] = {}
        self._cells: dict[tuple[int, int], list[str]] = {}
        for node_id in node_ids:
            node = graph.get_node(node_id)
            point = (node.longitude, node.latitude)
            self._points[node_id] = point
            cell = (int(point[0] // _CELL_DEG), int(point[1] // _CELL_DEG))
            self._cells.setdefault(cell, []).append(node_id)

    def __len__(self) -> int:
        return len(self._points)

    def nearest(self, point: Coord, max_distance_m: float) -> Match | None:
        """The closest indexed junction within ``max_distance_m``, or ``None``.

        The search widens ring by ring rather than scanning every node. Once a
        candidate is found the rings are walked once more, out to that
        candidate's own distance plus a cell, because a nearer junction can sit
        just over a boundary the first ring stopped at.
        """
        limit_deg = max_distance_m / _M_PER_DEG_LAT
        radius_deg = _CELL_DEG
        while True:
            best = self._scan(point, radius_deg, max_distance_m)
            if best is not None:
                confirm_deg = best.distance_m / _M_PER_DEG_LAT + _CELL_DEG
                if confirm_deg > radius_deg:
                    best = self._scan(point, confirm_deg, max_distance_m) or best
                return best
            if radius_deg > limit_deg:
                return None
            radius_deg += _CELL_DEG

    def _scan(self, point: Coord, radius_deg: float, max_distance_m: float) -> Match | None:
        best: Match | None = None
        for cell in _cells_around(point, radius_deg):
            for node_id in self._cells.get(cell, ()):
                distance = haversine_m(point, self._points[node_id])
                if distance <= max_distance_m and (best is None or distance < best.distance_m):
                    best = Match(node_id, distance, self._points[node_id])
        return best


class EdgeIndex:
    """Which road edges run near a coordinate.

    This is what turns a point measurement into something routing can price: a
    roadside sensor reports a speed at a position, and the cost model needs it
    keyed by edge id.
    """

    def __init__(self, graph: InMemoryRoadGraph) -> None:
        self._geometry: dict[str, tuple[Coord, ...]] = {}
        self._cells: dict[tuple[int, int], set[str]] = {}
        for edge in graph.edges():
            shape = tuple((c.longitude, c.latitude) for c in edge.geometry)
            if len(shape) < 2:
                # A graph may leave geometry empty to mean "a straight line
                # between the endpoints"; the routing block substitutes that
                # when it assembles a route, and so does this index.
                node_a = graph.get_node(edge.from_node)
                node_b = graph.get_node(edge.to_node)
                shape = (
                    (node_a.longitude, node_a.latitude),
                    (node_b.longitude, node_b.latitude),
                )
            self._geometry[edge.id] = shape
            for point in shape:
                cell = (int(point[0] // _CELL_DEG), int(point[1] // _CELL_DEG))
                self._cells.setdefault(cell, set()).add(edge.id)

    def __len__(self) -> int:
        return len(self._geometry)

    def near(self, point: Coord, radius_m: float) -> list[tuple[str, float]]:
        """Every edge whose shape passes within ``radius_m``, nearest first."""
        radius_deg = radius_m / _M_PER_DEG_LAT
        candidates: set[str] = set()
        for cell in _cells_around(point, radius_deg):
            candidates |= self._cells.get(cell, set())

        hits: list[tuple[str, float]] = []
        for edge_id in candidates:
            distance = self._distance_to(point, self._geometry[edge_id])
            if distance <= radius_m:
                hits.append((edge_id, distance))
        hits.sort(key=lambda pair: pair[1])
        return hits

    def nearest(self, point: Coord, radius_m: float) -> tuple[str, float] | None:
        hits = self.near(point, radius_m)
        return hits[0] if hits else None

    @staticmethod
    def _distance_to(point: Coord, shape: Sequence[Coord]) -> float:
        best = float("inf")
        for i in range(len(shape) - 1):
            distance, _ = point_to_segment_m(point, shape[i], shape[i + 1])
            if distance < best:
                best = distance
        return best
