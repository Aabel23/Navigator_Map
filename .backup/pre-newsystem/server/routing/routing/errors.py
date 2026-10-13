"""Exceptions raised by the routing block.

Every error escaping the public surface derives from :class:`RoutingError`, so
a caller who only wants to know "routing did not work" needs one ``except``
clause while a caller who cares why can catch the specific subclass. This is a
contract guarantee, not a convention: :meth:`routing.router.Router.find` lets
nothing else out.
"""

from __future__ import annotations


class RoutingError(Exception):
    """Base class for every error this block raises."""


class InvalidRequest(RoutingError):
    """Raised when a :class:`~routing.models.RouteRequest` is malformed.

    Covers a naive (timezone-less) departure time, an unknown vehicle profile
    name, and an unknown cost mode -- all caller mistakes that are cheaper to
    reject up front than to discover halfway through a search.
    """


class UnknownNode(RoutingError):
    """Raised when a request or an edge refers to a node the graph lacks."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"unknown node: {node_id!r}")


class UnknownEdge(RoutingError):
    """Raised when something asks the graph for an edge it lacks."""

    def __init__(self, edge_id: str) -> None:
        self.edge_id = edge_id
        super().__init__(f"unknown edge: {edge_id!r}")


class NoRouteFound(RoutingError):
    """Raised when both endpoints exist but nothing legal connects them.

    Covers a genuinely disconnected graph and a graph connected only through
    edges the current profile, constraints, or turn restrictions rule out.
    """

    def __init__(self, origin: str, destination: str) -> None:
        self.origin = origin
        self.destination = destination
        super().__init__(f"no route from {origin!r} to {destination!r}")
