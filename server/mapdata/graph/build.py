"""Road segments in, a routable graph out.

A published road segment and a routing edge are not the same thing, and the
difference is the whole job of this module. OSM publishes a *way*: one line
that may run for two kilometres through nine intersections. A router needs an
*edge*: a stretch between two junctions, with nothing to turn off onto in
between. Handing the way straight to the router would make every junction
along it invisible, and the route would sail past the turn it needed.

So the build has three steps:

1. **Find the junctions.** A coordinate that appears in more than one way is
   where two roads meet. Every way's own endpoints are junctions too, because
   that is where it can be left even if nothing crosses there.
2. **Split each way at its junctions.** The pieces between consecutive
   junctions become edges, each keeping its own slice of the polyline so the
   route can be drawn without the graph.
3. **Name everything stably.** A node id comes from its rounded coordinate, so
   two ways meeting at a point produce one node without any spatial join. An
   edge id is its way id plus its index along the way, so an edge keeps its
   name across rebuilds and a traffic reading attached to it still lands.

Coordinates flip here, and only here. Map data is longitude-first, because
every free source publishes GeoJSON; routing is latitude-first, because its
contract has always said so. One conversion at one boundary is a fact a reader
can hold; two would be a bug waiting for the third.

Inputs:  a sequence of :class:`mapdata.RoadSegment`
Outputs: a :class:`routing.InMemoryRoadGraph`, plus the index used to snap
Not here: cost, traffic, closures, or where the segments came from
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from domain import Coord, haversine_m
from routing import Access, Direction, Edge, InMemoryRoadGraph, LatLon, Node

__all__ = ["GraphBuild", "build_graph", "node_id_for", "NODE_PRECISION"]

#: Decimal places a coordinate is rounded to before it becomes a node id.
#: Six places is about 0.11 m at the equator -- finer than OSM's own
#: coordinate precision, so two ways that share a node in the source share one
#: here, and two that merely pass close do not.
NODE_PRECISION = 6

#: Minimum length of an edge, in meters. A split that produces something
#: shorter than this is folded into its neighbour: routing.Edge refuses a
#: self-loop, and a sub-centimetre edge is a coordinate artefact rather than a
#: piece of road.
MIN_EDGE_M = 0.5


@dataclass(frozen=True, slots=True)
class GraphBuild:
    """A built graph and what it took to build it.

    The counts are not decoration: a graph with far fewer junctions than ways
    means the source was asked for the wrong thing, and that is visible here
    before it becomes a mysteriously straight route.
    """

    graph: InMemoryRoadGraph
    node_coords: dict[str, Coord]
    source_count: int
    skipped: int

    @property
    def node_count(self) -> int:
        return len(self.node_coords)

    @property
    def edge_count(self) -> int:
        return sum(1 for _ in self.graph.edges())

    def summary(self) -> dict[str, int]:
        return {
            "sources": self.source_count,
            "nodes": self.node_count,
            "edges": self.edge_count,
            "skipped": self.skipped,
        }


def node_id_for(point: Coord) -> str:
    """The stable id of the junction at this coordinate.

    Derived from the rounded coordinate rather than assigned, so the same
    place gets the same id in every build, in every process, from every
    source. That is what lets a closure recorded yesterday still name a real
    node today.
    """
    lon, lat = point
    return f"n:{round(lon, NODE_PRECISION):.6f},{round(lat, NODE_PRECISION):.6f}"


def build_graph(segments: Sequence, *, min_edge_m: float = MIN_EDGE_M) -> GraphBuild:
    """Build a routable graph from published road segments.

    Args:
        segments: :class:`mapdata.RoadSegment` values, or anything with the
            same fields. Typed loosely so a caller may pass a fixture.
        min_edge_m: Splits shorter than this are folded into the next one.

    Returns:
        A :class:`GraphBuild`. The graph is safe to share and must not be
        mutated: routing treats it as read-only, and a live closure is a
        constraint rather than a graph edit.
    """
    junctions = _junctions(segments)

    graph = InMemoryRoadGraph()
    node_coords: dict[str, Coord] = {}
    skipped = 0

    for segment in segments:
        pieces = _split(segment.geometry, junctions, min_edge_m)
        if not pieces:
            skipped += 1
            continue
        for index, shape in enumerate(pieces):
            start_id = node_id_for(shape[0])
            end_id = node_id_for(shape[-1])
            if start_id == end_id:
                # A closed loop between the same junction: no routing meaning,
                # and routing.Edge refuses it outright.
                skipped += 1
                continue
            for node_id, point in ((start_id, shape[0]), (end_id, shape[-1])):
                if node_id not in node_coords:
                    node_coords[node_id] = point
                    graph.add_node(Node(id=node_id, latitude=point[1], longitude=point[0]))
            graph.add_edge(_edge(segment, index, shape, start_id, end_id))

    return GraphBuild(
        graph=graph,
        node_coords=node_coords,
        source_count=len(segments),
        skipped=skipped,
    )


# --- Steps -----------------------------------------------------------------


def _junctions(segments: Iterable) -> set[str]:
    """Ids of every coordinate two ways share, plus every way's endpoints."""
    seen: set[str] = set()
    shared: set[str] = set()
    for segment in segments:
        shape = tuple(segment.geometry)
        if len(shape) < 2:
            continue
        # Endpoints are always junctions: a way can be left where it ends.
        shared.add(node_id_for(shape[0]))
        shared.add(node_id_for(shape[-1]))
        for point in shape[1:-1]:
            key = node_id_for(point)
            if key in seen:
                shared.add(key)
            seen.add(key)
        for point in shape:
            seen.add(node_id_for(point))
    return shared


def _split(
    shape: Sequence[Coord], junctions: set[str], min_edge_m: float
) -> list[tuple[Coord, ...]]:
    """Cut a way's polyline at each junction it passes through."""
    if len(shape) < 2:
        return []

    pieces: list[tuple[Coord, ...]] = []
    current: list[Coord] = [shape[0]]
    for point in shape[1:]:
        current.append(point)
        if node_id_for(point) in junctions and len(current) >= 2:
            if _length(current) >= min_edge_m:
                pieces.append(tuple(current))
                current = [point]
            # Too short to be its own edge: keep accumulating, so the stub is
            # absorbed into the next piece rather than dropped.
    if len(current) >= 2 and _length(current) >= min_edge_m:
        if pieces:
            # A trailing remainder that never reached a junction belongs to the
            # previous edge, not to a dangling one.
            pieces[-1] = pieces[-1] + tuple(current[1:])
        else:
            pieces.append(tuple(current))
    return pieces


def _edge(segment, index: int, shape: tuple[Coord, ...], start_id: str, end_id: str) -> Edge:
    distance = _length(shape)
    speed_mps = max(segment.free_flow_kph, 1.0) / 3.6
    return Edge(
        id=f"{segment.id}#{index}",
        from_node=start_id,
        to_node=end_id,
        distance=distance,
        speed=speed_mps,
        road_class=segment.road_class,
        name=segment.name or "",
        direction=Direction.ONE_WAY if segment.oneway else Direction.BIDIRECTIONAL,
        access=Access.ALLOWED,
        geometry=tuple(LatLon(lat, lon) for lon, lat in shape),
        metadata={"road_id": segment.id, "free_flow_kph": segment.free_flow_kph},
    )


def _length(points: Sequence[Coord]) -> float:
    return sum(haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1))
