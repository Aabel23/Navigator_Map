"""Per-request rules about which edges a route may use.

These sit on top of what the graph and the vehicle profile already rule out
(``Access.BLOCKED``, ``allowed_road_classes``, turn restrictions).
Constraints are for what is true of *this request* -- "avoid this segment on
this trip", "no tolls today" -- and they are evaluated during the search
rather than by pre-filtering, so one shared graph serves concurrent requests
carrying different rules without ever being mutated.

Inputs:  Edge
Outputs: a yes/no per edge
Not here: anything permanent about the road (that belongs on the Edge) or
    about the vehicle (that belongs on the VehicleProfile)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import Edge


class Constraint(Protocol):
    """A predicate an edge must satisfy to be usable in a particular route.

    Returns ``True`` if the edge is allowed, ``False`` if it must be excluded.
    """

    def __call__(self, edge: Edge) -> bool: ...


def avoid_edges(edge_ids: set[str]) -> Constraint:
    """Reject a specific set of edge ids."""

    def constraint(edge: Edge) -> bool:
        return edge.id not in edge_ids

    return constraint


def avoid_nodes(node_ids: set[str]) -> Constraint:
    """Reject any edge touching one of these nodes."""

    def constraint(edge: Edge) -> bool:
        return edge.from_node not in node_ids and edge.to_node not in node_ids

    return constraint


def avoid_road_classes(road_classes: set[str]) -> Constraint:
    """Reject edges of the given road classes."""

    def constraint(edge: Edge) -> bool:
        return edge.road_class not in road_classes

    return constraint


def max_metadata_value(key: str, limit: float) -> Constraint:
    """Reject edges whose numeric metadata value exceeds a limit.

    An edge that does not carry ``key`` at all passes: absence of a toll is
    not a toll. Example: ``max_metadata_value("toll_usd", 0)`` rejects every
    edge with a positive toll.
    """

    def constraint(edge: Edge) -> bool:
        value = edge.metadata.get(key)
        return value is None or value <= limit

    return constraint


def avoid_tolls() -> Constraint:
    """Reject edges flagged as tolled, by ``metadata["toll"]`` or a positive fare."""

    def constraint(edge: Edge) -> bool:
        if edge.metadata.get("toll"):
            return False
        fare = edge.metadata.get("toll_usd")
        return not (fare is not None and fare > 0)

    return constraint


@dataclass(frozen=True, slots=True)
class RouteConstraints:
    """A bundle of :class:`Constraint` predicates for one request.

    Every rule must pass for an edge to be usable: this is an AND of
    ``blocked_edges``, ``blocked_nodes``, and every entry in ``rules``. The
    first two are kept as plain sets rather than closures so a caller or a
    test can inspect what is blocked without evaluating anything.

    Attributes:
        blocked_edges: Edge ids that may not be used.
        blocked_nodes: Node ids that may not be routed through. Blocking the
            origin or destination makes the request unroutable, by design --
            it is the caller's statement, not a mistake to paper over.
        rules: Further predicates, from the helpers above or the caller's own.
    """

    blocked_edges: frozenset[str] = frozenset()
    blocked_nodes: frozenset[str] = frozenset()
    rules: tuple[Constraint, ...] = field(default_factory=tuple)

    def allows(self, edge: Edge) -> bool:
        if edge.id in self.blocked_edges:
            return False
        if edge.from_node in self.blocked_nodes or edge.to_node in self.blocked_nodes:
            return False
        return all(rule(edge) for rule in self.rules)

    def with_blocked_edge(self, edge_id: str) -> "RouteConstraints":
        """Return a copy with one more edge blocked.

        Useful for asking "what if this segment were closed?" without touching
        the original constraints or the graph.
        """
        return RouteConstraints(
            blocked_edges=self.blocked_edges | {edge_id},
            blocked_nodes=self.blocked_nodes,
            rules=self.rules,
        )
