"""The graph abstraction the search is written against.

The search calls only the methods declared on :class:`RoadGraph`. That is the
seam letting the real system swap this block's in-memory graph for one backed
by OSM, a PBF extract, PostGIS, SQLite, a binary tile cache, or a remote
service, without :mod:`routing.search` changing at all.

Inputs:  Node, Edge, TurnRestriction, however the implementation obtains them
Outputs: read-only lookups and adjacency
Not here: cost (routing.costs), request-time rules (routing.constraints)

Main types:
    RoadGraph          the interface; implement this to bring your own data
    InMemoryRoadGraph  dictionaries, the only implementation shipped here
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator

from .errors import UnknownEdge, UnknownNode
from .models import Direction, Edge, Node, TurnKind, TurnRestriction


class RoadGraph(ABC):
    """Read-only view of a road network.

    Implementations may load data however they like, but must answer every
    method below without the search needing to know which.
    """

    # --- Required ----------------------------------------------------------

    @abstractmethod
    def get_node(self, node_id: str) -> Node:
        """Return the node with this id, or raise :class:`UnknownNode`."""

    @abstractmethod
    def get_edge(self, edge_id: str) -> Edge:
        """Return the edge with this id, or raise :class:`UnknownEdge`."""

    @abstractmethod
    def get_outgoing_edges(self, node_id: str) -> Iterable[Edge]:
        """Return every edge traversable starting from this node.

        A bidirectional edge whose ``to_node`` is ``node_id`` is included
        (traversable in reverse); a one-way edge only when
        ``node_id == from_node``. Blocked edges are still returned -- deciding
        whether a block applies to *this* request is the cost model's and the
        constraint layer's job, not the graph's.
        """

    @abstractmethod
    def get_neighbors(self, node_id: str) -> Iterable[str]:
        """Return node ids reachable by one traversable edge from this node."""

    @abstractmethod
    def get_edge_between(self, node_a: str, node_b: str) -> Edge | None:
        """Return a traversable edge from ``node_a`` to ``node_b``, if any.

        Where several exist an implementation may return any of them; callers
        that need all of them filter :meth:`get_outgoing_edges` themselves.
        """

    @abstractmethod
    def nodes(self) -> Iterator[Node]:
        """Iterate over every node in the graph."""

    @abstractmethod
    def edges(self) -> Iterator[Edge]:
        """Iterate over every edge in the graph, in its stored direction."""

    # --- Optional, with working defaults -----------------------------------

    def get_turn_restrictions(self, via_node: str) -> Iterable[TurnRestriction]:
        """Return every restriction whose ``via_node`` is this node.

        Empty by default, so a graph carrying no turn data is still a valid
        graph -- the contract promises legality *as reported by the graph*.
        """
        return ()

    def is_turn_allowed(self, from_edge_id: str, via_node: str, to_edge_id: str) -> bool:
        """Whether ``from_edge -> to_edge`` may be taken through ``via_node``.

        A mandatory restriction is read as the full set of permitted exits for
        that ``from_edge``, so it implicitly prohibits every other turn;
        prohibitions are then subtracted from that set.
        """
        relevant = [r for r in self.get_turn_restrictions(via_node) if r.from_edge == from_edge_id]
        if not relevant:
            return True
        prohibited = {r.to_edge for r in relevant if r.kind is TurnKind.PROHIBITED}
        mandatory = {r.to_edge for r in relevant if r.kind is TurnKind.MANDATORY}
        if mandatory:
            return to_edge_id in mandatory - prohibited
        return to_edge_id not in prohibited

    def has_node(self, node_id: str) -> bool:
        """Convenience default built on :meth:`get_node`."""
        try:
            self.get_node(node_id)
        except UnknownNode:
            return False
        return True

    def max_speed(self) -> float:
        """Highest edge speed in the graph, in m/s.

        The router needs this to build an admissible time heuristic. The
        default scans every edge, which a lazily-backed implementation should
        override with a stored value rather than pay per Router construction.

        Raises:
            ValueError: if the graph has no edges.
        """
        speeds = [edge.speed for edge in self.edges()]
        if not speeds:
            raise ValueError("graph has no edges")
        return max(speeds)


class InMemoryRoadGraph(RoadGraph):
    """A :class:`RoadGraph` backed by plain dictionaries.

    The only concrete graph shipped here. It exists so the router has
    something to run against; a production system adds a sibling
    implementation satisfying the same interface.
    """

    def __init__(
        self,
        nodes: Iterable[Node] = (),
        edges: Iterable[Edge] = (),
        turn_restrictions: Iterable[TurnRestriction] = (),
    ) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        # node id -> ids of edges traversable starting from that node.
        self._outgoing: dict[str, list[str]] = {}
        # (via node, from edge) -> restrictions on leaving that edge there.
        self._turns: dict[tuple[str, str], list[TurnRestriction]] = {}
        self._max_speed: float | None = None
        for node in nodes:
            self.add_node(node)
        for edge in edges:
            self.add_edge(edge)
        for restriction in turn_restrictions:
            self.add_turn_restriction(restriction)

    # --- Construction ------------------------------------------------------

    def add_node(self, node: Node) -> None:
        self._nodes[node.id] = node
        self._outgoing.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        """Register an edge.

        Rejects a duplicate id rather than overwriting: replacing an edge in
        place would leave the previous endpoints' adjacency lists pointing at
        an edge that no longer touches them, and the corruption would only
        surface later, as an error from somewhere else entirely.
        """
        if edge.id in self._edges:
            raise ValueError(f"duplicate edge id {edge.id!r}")
        if edge.from_node not in self._nodes:
            raise UnknownNode(edge.from_node)
        if edge.to_node not in self._nodes:
            raise UnknownNode(edge.to_node)
        self._edges[edge.id] = edge
        self._outgoing[edge.from_node].append(edge.id)
        if edge.direction is Direction.BIDIRECTIONAL:
            self._outgoing[edge.to_node].append(edge.id)
        self._max_speed = None

    def add_turn_restriction(self, restriction: TurnRestriction) -> None:
        from_edge = self.get_edge(restriction.from_edge)
        to_edge = self.get_edge(restriction.to_edge)
        if restriction.via_node not in self._nodes:
            raise UnknownNode(restriction.via_node)
        for edge in (from_edge, to_edge):
            if restriction.via_node not in (edge.from_node, edge.to_node):
                raise ValueError(
                    f"turn restriction via {restriction.via_node!r} names edge {edge.id!r}, "
                    "which does not touch that node"
                )
        key = (restriction.via_node, restriction.from_edge)
        self._turns.setdefault(key, []).append(restriction)

    # --- RoadGraph interface -----------------------------------------------

    def get_node(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise UnknownNode(node_id) from None

    def get_edge(self, edge_id: str) -> Edge:
        try:
            return self._edges[edge_id]
        except KeyError:
            raise UnknownEdge(edge_id) from None

    def get_outgoing_edges(self, node_id: str) -> Iterable[Edge]:
        if node_id not in self._nodes:
            raise UnknownNode(node_id)
        return [self._edges[eid] for eid in self._outgoing[node_id]]

    def get_neighbors(self, node_id: str) -> Iterable[str]:
        return [edge.other_end(node_id) for edge in self.get_outgoing_edges(node_id)]

    def get_edge_between(self, node_a: str, node_b: str) -> Edge | None:
        for edge in self.get_outgoing_edges(node_a):
            if edge.other_end(node_a) == node_b:
                return edge
        return None

    def nodes(self) -> Iterator[Node]:
        return iter(self._nodes.values())

    def edges(self) -> Iterator[Edge]:
        return iter(self._edges.values())

    def get_turn_restrictions(self, via_node: str) -> Iterable[TurnRestriction]:
        return [r for rules in self._turns.values() for r in rules if r.via_node == via_node]

    def is_turn_allowed(self, from_edge_id: str, via_node: str, to_edge_id: str) -> bool:
        """Indexed override of the base implementation, hit once per expansion."""
        relevant = self._turns.get((via_node, from_edge_id))
        if not relevant:
            return True
        prohibited = {r.to_edge for r in relevant if r.kind is TurnKind.PROHIBITED}
        mandatory = {r.to_edge for r in relevant if r.kind is TurnKind.MANDATORY}
        if mandatory:
            return to_edge_id in mandatory - prohibited
        return to_edge_id not in prohibited

    def max_speed(self) -> float:
        if self._max_speed is None:
            self._max_speed = super().max_speed()
        return self._max_speed

    def __len__(self) -> int:
        """Node count, so ``len(graph)`` reads naturally in benchmarks."""
        return len(self._nodes)
