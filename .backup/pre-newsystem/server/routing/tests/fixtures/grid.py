"""A seeded synthetic grid, for benchmarking and for scale-sensitive tests.

Bigger than the hand-built town and reproducible from a seed, but carrying the
same features -- diagonals, closures, one-ways, turn restrictions -- so a
measurement on a large graph is measuring the same work the small one does,
not a simplified version of it.

Distances come from the coordinates. A synthetic graph whose distances did not
match its geometry would quietly break the heuristic's lower bound and make
the benchmark compare A* against a broken A*.
"""

from __future__ import annotations

import random

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

#: Roughly 110 m of latitude, so a 100x100 grid spans about 11 km.
SPACING_DEGREES = 0.001
ORIGIN_LAT = 10.70
ORIGIN_LON = 106.60

ROAD_CLASSES = ("primary", "secondary", "residential")
SPEEDS = {"primary": 16.0, "secondary": 11.0, "residential": 7.0}

BLOCKED_SHARE = 0.02
ONE_WAY_SHARE = 0.08
DIAGONAL_SHARE = 0.10
RESTRICTED_JUNCTION_SHARE = 0.03


def random_grid_graph(rows: int, columns: int | None = None, *, seed: int = 0) -> InMemoryRoadGraph:
    """Build a ``rows x columns`` grid, reproducible for a given seed.

    Args:
        rows: Number of grid rows.
        columns: Number of grid columns; defaults to ``rows``, so
            ``random_grid_graph(50)`` is a 50x50 grid.
        seed: Anything derived from randomness is drawn from this, so two
            calls with the same arguments produce identical graphs.
    """
    columns = rows if columns is None else columns
    rng = random.Random(seed)
    graph = InMemoryRoadGraph()

    for row in range(rows):
        for column in range(columns):
            graph.add_node(
                Node(
                    _node_id(row, column),
                    ORIGIN_LAT + row * SPACING_DEGREES,
                    ORIGIN_LON + column * SPACING_DEGREES,
                )
            )

    for row in range(rows):
        for column in range(columns):
            if column + 1 < columns:
                _add(graph, rng, row, column, row, column + 1, "h")
            if row + 1 < rows:
                _add(graph, rng, row, column, row + 1, column, "v")
            if row + 1 < rows and column + 1 < columns and rng.random() < DIAGONAL_SHARE:
                _add(graph, rng, row, column, row + 1, column + 1, "d")

    _add_turn_restrictions(graph, rng, rows=rows, columns=columns)
    return graph


# --- Internal --------------------------------------------------------------


def _node_id(row: int, column: int) -> str:
    return f"{row}_{column}"


def _add(
    graph: InMemoryRoadGraph,
    rng: random.Random,
    row_a: int,
    column_a: int,
    row_b: int,
    column_b: int,
    kind: str,
) -> None:
    start, end = _node_id(row_a, column_a), _node_id(row_b, column_b)
    road_class = rng.choice(ROAD_CLASSES)
    direction = Direction.ONE_WAY if rng.random() < ONE_WAY_SHARE else Direction.BIDIRECTIONAL
    access = Access.BLOCKED if rng.random() < BLOCKED_SHARE else Access.ALLOWED
    graph.add_edge(
        Edge(
            id=f"{kind}{start}-{end}",
            from_node=start,
            to_node=end,
            distance=haversine_m(
                LatLon(*_coordinate(row_a, column_a)), LatLon(*_coordinate(row_b, column_b))
            ),
            speed=SPEEDS[road_class],
            road_class=road_class,
            name=f"{kind}{row_a if kind == 'h' else column_a}",
            direction=direction,
            access=access,
        )
    )


def _coordinate(row: int, column: int) -> tuple[float, float]:
    return ORIGIN_LAT + row * SPACING_DEGREES, ORIGIN_LON + column * SPACING_DEGREES


def _add_turn_restrictions(
    graph: InMemoryRoadGraph, rng: random.Random, *, rows: int, columns: int
) -> None:
    """Forbid one arbitrary turn at a scattering of interior junctions.

    Restrictions are only added where the junction keeps at least three
    traversable edges, so the grid never gets cut into pieces by them and a
    benchmark run stays comparable to one without them.
    """
    for row in range(1, rows - 1):
        for column in range(1, columns - 1):
            if rng.random() >= RESTRICTED_JUNCTION_SHARE:
                continue
            node = _node_id(row, column)
            edges = list(graph.get_outgoing_edges(node))
            if len(edges) < 3:
                continue
            from_edge, to_edge = rng.sample(edges, 2)
            graph.add_turn_restriction(
                TurnRestriction(from_edge.id, node, to_edge.id, TurnKind.PROHIBITED)
            )
