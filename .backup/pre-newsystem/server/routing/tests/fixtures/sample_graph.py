"""A hand-built nine-junction town, small enough to reason about by hand.

Laid out as a three-by-three grid over central Ho Chi Minh City, so the
coordinates are plausible and the great-circle heuristic has real work to do:

    A --- B --- C        row streets run east-west
    |     |     |        column streets run north-south
    D ==> E --- F        ==> is one-way, eastbound only
    |     |     |
    G --- H -x- I        -x- is closed

Deliberate features, each the subject of at least one test:
    BC  unpaved, and slow, so a cost-mode change moves the route
    DE  one-way D to E
    HI  blocked, so reaching I from G must detour
    every edge is named, so manoeuvre steps have something to merge on

Edge distances are computed from the coordinates rather than invented. A
distance shorter than the straight line between its endpoints would make the
router's heuristic overestimate, and the resulting wrong routes would look
like a bug in the search rather than in the fixture.
"""

from __future__ import annotations

from routing import (
    Access,
    Direction,
    Edge,
    InMemoryRoadGraph,
    LatLon,
    Node,
    TurnKind,
    TurnRestriction,
)
from routing.geometry import haversine_m  # internal, but these fixtures are inside the block

# --- Layout ----------------------------------------------------------------

NODES: dict[str, tuple[float, float]] = {
    "A": (10.78, 106.68),
    "B": (10.78, 106.69),
    "C": (10.78, 106.70),
    "D": (10.77, 106.68),
    "E": (10.77, 106.69),
    "F": (10.77, 106.70),
    "G": (10.76, 106.68),
    "H": (10.76, 106.69),
    "I": (10.76, 106.70),
}

#: id, from, to, street name, road class, speed (m/s), direction, access
LAYOUT: tuple[tuple[str, str, str, str, str, float, Direction, Access], ...] = (
    ("AB", "A", "B", "Nguyen Hue", "primary", 14.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("BC", "B", "C", "Nguyen Hue", "unpaved", 5.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("DE", "D", "E", "Le Loi", "primary", 14.0, Direction.ONE_WAY, Access.ALLOWED),
    ("EF", "E", "F", "Le Loi", "primary", 14.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("GH", "G", "H", "Vo Van Kiet", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("HI", "H", "I", "Vo Van Kiet", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.BLOCKED),
    ("AD", "A", "D", "Pasteur", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("DG", "D", "G", "Pasteur", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("BE", "B", "E", "Nam Ky Khoi Nghia", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("EH", "E", "H", "Nam Ky Khoi Nghia", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("CF", "C", "F", "Hai Ba Trung", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
    ("FI", "F", "I", "Hai Ba Trung", "secondary", 11.0, Direction.BIDIRECTIONAL, Access.ALLOWED),
)


def small_town_graph() -> InMemoryRoadGraph:
    """The town as drawn above, with no turn restrictions."""
    graph = InMemoryRoadGraph()
    for node_id, (latitude, longitude) in NODES.items():
        graph.add_node(Node(node_id, latitude, longitude))
    for edge_id, start, end, name, road_class, speed, direction, access in LAYOUT:
        graph.add_edge(
            Edge(
                id=edge_id,
                from_node=start,
                to_node=end,
                distance=_span(start, end),
                speed=speed,
                road_class=road_class,
                name=name,
                direction=direction,
                access=access,
            )
        )
    return graph


def town_with_turn_restrictions() -> InMemoryRoadGraph:
    """The same town, plus two restrictions at the central junction E.

    - Arriving at E on Nam Ky Khoi Nghia (``BE``), the turn east into Le Loi
      (``EF``) is prohibited.
    - Arriving at E on Le Loi (``DE``), the only permitted exit is south on
      ``EH``, which forbids continuing straight onto ``EF``.
    """
    graph = small_town_graph()
    graph.add_turn_restriction(TurnRestriction("BE", "E", "EF", TurnKind.PROHIBITED))
    graph.add_turn_restriction(TurnRestriction("DE", "E", "EH", TurnKind.MANDATORY))
    return graph


def _span(start: str, end: str) -> float:
    """Great-circle distance between two named junctions, in meters."""
    return haversine_m(LatLon(*NODES[start]), LatLon(*NODES[end]))
