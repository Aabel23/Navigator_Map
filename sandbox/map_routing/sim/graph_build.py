"""Turn borrowed road geometry into a road graph the routing block can search.

Neither of the two blocks involved owns this step, and that is not an
oversight. The routing block states that it does not decide "where road data
comes from"; the traffic block states that it "does not own road geometry -- it
borrows it", and publishes what it borrowed as :class:`RoadSegment`. So
something has to stand between a pile of OSM ways and a routable graph, and in
this simulator that something is the sandbox.

The conversion is mostly one idea: **a way is not an edge**. An OSM way runs
through junctions; a routing edge runs between them. So the builder finds every
coordinate two ways share, calls it a junction, and cuts each way there.

Junction detection is by exact coordinate, quantised to six decimal places
(~0.1 m). That works because two OSM ways that meet genuinely share the same
node, and therefore the same coordinate, rather than merely passing close by.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Sequence

from .blocks import Access, Direction, Edge, InMemoryRoadGraph, LatLon, Node, RoadSegment
from .geodesy import Coord, polyline_length_m

__all__ = ["BuiltGraph", "build_graph"]

#: Decimal places coordinates are rounded to before two ways are said to meet.
#: Six places is about 0.1 m -- finer than OSM's own precision, coarse enough
#: that float formatting cannot split one junction into two.
_PLACES = 6

#: Shorter than this and a split is an artefact of the source geometry rather
#: than a piece of road. Keeping them would add nodes the search has to settle
#: for no benefit.
_MIN_EDGE_M = 0.5


@dataclass(frozen=True, slots=True)
class BuiltGraph:
    """A road graph plus the two lookups the rest of the sandbox needs.

    Attributes:
        graph: Handed to :class:`routing.Router` and never mutated afterwards.
        way_edges: OSM way id -- the ``RoadSegment.id`` the traffic block uses,
            and the value it puts in ``TrafficSegment.edge_id`` -- mapped to
            the routing edge ids cut from it. This is the join between the two
            blocks' vocabularies.
        routable_nodes: The largest set of nodes mutually reachable from one
            another. Snapping only to these is what stops a picked point
            landing on a slip-road fragment nothing connects to.
        stats: Counts, for the panel and for judging whether a region is sane.
    """

    graph: InMemoryRoadGraph
    way_edges: dict[str, tuple[str, ...]]
    routable_nodes: frozenset[str]
    stats: dict[str, int]


def build_graph(segments: Sequence[RoadSegment]) -> BuiltGraph:
    """Build a routable graph from the traffic block's reference road network."""
    junctions = _junction_keys(segments)

    nodes: dict[tuple[float, float], Node] = {}
    edges: list[Edge] = []
    way_edges: dict[str, list[str]] = {}
    dropped = 0

    for segment in segments:
        if len(segment.geometry) < 2:
            continue
        speed = max(segment.free_flow_kph, 1.0) / 3.6
        for index, piece in enumerate(_cut_at(segment.geometry, junctions)):
            start_key, end_key = _key(piece[0]), _key(piece[-1])
            if start_key == end_key:
                # A way that leaves a junction and returns to it -- a
                # roundabout drawn as one closed way, most often. Routing
                # rejects a self-loop, and rightly: it has no meaning.
                dropped += 1
                continue
            distance = polyline_length_m(piece)
            if distance < _MIN_EDGE_M:
                dropped += 1
                continue
            from_node = _node_for(nodes, start_key, piece[0])
            to_node = _node_for(nodes, end_key, piece[-1])
            edge_id = f"{segment.id}#{index}"
            edges.append(
                Edge(
                    id=edge_id,
                    from_node=from_node.id,
                    to_node=to_node.id,
                    distance=distance,
                    speed=speed,
                    road_class=segment.road_class,
                    name=segment.name or "",
                    # The traffic block's Overpass reader flattens `oneway=-1`
                    # to a plain True without reversing the geometry, so a
                    # handful of reverse-tagged ways point the wrong way here.
                    # Rare, and it shows up as a route taking an odd detour
                    # rather than as a wrong answer.
                    direction=Direction.ONE_WAY if segment.oneway else Direction.BIDIRECTIONAL,
                    access=Access.ALLOWED,
                    geometry=tuple(LatLon(lat, lon) for lon, lat in piece),
                    metadata={
                        "way_id": segment.id,
                        "free_flow_kph": segment.free_flow_kph,
                        "oneway": segment.oneway,
                    },
                )
            )
            way_edges.setdefault(segment.id, []).append(edge_id)

    graph = InMemoryRoadGraph(nodes=nodes.values(), edges=edges)
    routable = _largest_mutually_reachable(graph)

    return BuiltGraph(
        graph=graph,
        way_edges={way: tuple(ids) for way, ids in way_edges.items()},
        routable_nodes=routable,
        stats={
            "ways": len(segments),
            "nodes": len(nodes),
            "edges": len(edges),
            "routable_nodes": len(routable),
            "dropped_pieces": dropped,
        },
    )


# --- cutting ways into edges -------------------------------------------------


def _key(point: Coord) -> tuple[float, float]:
    return (round(point[0], _PLACES), round(point[1], _PLACES))


def _junction_keys(segments: Iterable[RoadSegment]) -> set[tuple[float, float]]:
    """Coordinates where a cut must happen: a shared vertex, or a way's end."""
    seen_in: dict[tuple[float, float], int] = {}
    junctions: set[tuple[float, float]] = set()
    for segment in segments:
        if len(segment.geometry) < 2:
            continue
        junctions.add(_key(segment.geometry[0]))
        junctions.add(_key(segment.geometry[-1]))
        # Counted once per way, so a way that touches its own vertex twice
        # does not masquerade as two ways meeting.
        for key in {_key(point) for point in segment.geometry}:
            seen_in[key] = seen_in.get(key, 0) + 1
    junctions.update(key for key, count in seen_in.items() if count > 1)
    return junctions


def _cut_at(
    geometry: Sequence[Coord], junctions: set[tuple[float, float]]
) -> list[tuple[Coord, ...]]:
    """Split a way's polyline into the pieces running between junctions."""
    pieces: list[tuple[Coord, ...]] = []
    current: list[Coord] = [geometry[0]]
    for point in geometry[1:]:
        current.append(point)
        if _key(point) in junctions and len(current) > 1:
            pieces.append(tuple(current))
            current = [point]
    if len(current) > 1:
        pieces.append(tuple(current))
    return pieces


def _node_for(
    nodes: dict[tuple[float, float], Node], key: tuple[float, float], point: Coord
) -> Node:
    node = nodes.get(key)
    if node is None:
        node = Node(id=f"n{len(nodes)}", latitude=point[1], longitude=point[0])
        nodes[key] = node
    return node


# --- connectivity ------------------------------------------------------------


def _largest_mutually_reachable(graph: InMemoryRoadGraph) -> frozenset[str]:
    """Nodes that can all reach each other, taking one-ways seriously.

    The set returned is the strongly connected component of whichever of the
    busiest few junctions sits in the biggest one. It is not a full Tarjan
    pass: a city road network has one giant component containing essentially
    every through road, and a handful of seeds finds it with two breadth-first
    walks each rather than a full traversal carrying a stack of state.
    """
    forward: dict[str, list[str]] = {}
    backward: dict[str, list[str]] = {}
    for node in graph.nodes():
        forward.setdefault(node.id, [])
        backward.setdefault(node.id, [])
    for node in graph.nodes():
        for edge in graph.get_outgoing_edges(node.id):
            other = edge.other_end(node.id)
            forward[node.id].append(other)
            backward[other].append(node.id)

    seeds = sorted(forward, key=lambda n: len(forward[n]), reverse=True)[:5]
    best: frozenset[str] = frozenset()
    for seed in seeds:
        if seed in best:
            continue
        component = _reach(forward, seed) & _reach(backward, seed)
        if len(component) > len(best):
            best = frozenset(component)
    return best


def _reach(adjacency: dict[str, list[str]], start: str) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in adjacency[node]:
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen
