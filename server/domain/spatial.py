"""Nearest-thing-to-a-point, over a uniform grid.

Three subsystems need the same question answered and would otherwise each
grow their own index: `mapdata` snapping a coordinate to a junction, `traffic`
attaching a sensor reading to a road, `roadstate` attaching a flood report to
one. The question is identical -- "which of these labelled positions is
closest, and is it close enough?" -- and it carries no policy at all, which is
why it can live down here with the geographic types.

A uniform grid, not a k-d tree. The sets here are thousands of points, not
millions; a grid has no build cost worth measuring, and the search is exact
because it widens its ring until the ring's own inner edge is further away
than the best candidate already found. What a k-d tree would buy at this size
is unmeasurable, and what it would cost is a page of code that has to be right.

Positions are ``(lon, lat)`` degrees. Labels need not be unique -- a polyline
is indexed by adding one entry per vertex under the same label, which is what
makes "nearest road" the same call as "nearest junction".
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .geo import BBox, Coord, haversine_m

__all__ = ["SpatialIndex", "index_of_polylines", "densify", "DEFAULT_CELL_DEGREES", "DEFAULT_STEP_M"]

#: Grid cell size in degrees. About 1.1 km at the equator -- comfortably
#: larger than any snap radius this server uses, so a typical query reads one
#: cell and the ring around it.
DEFAULT_CELL_DEGREES = 0.01

#: Meters per degree of latitude. Used only to decide when to stop widening
#: the ring, where a constant is not merely adequate but conservative: a
#: degree of longitude is shorter than this away from the equator, so the
#: search stops no earlier than it should.
METERS_PER_DEGREE = 111_320.0

#: Rings to widen before the ring search gives up. 64 rings is about 70 km.
#: A bounded search stops there and reports nothing found, which is correct:
#: the caller said how close was close enough. An unbounded one falls back to
#: a full scan instead, because "nearest, no limit" returning nothing while
#: the index holds points would be a lie the caller cannot detect.
MAX_RINGS = 64

#: Largest gap left between indexed points along a polyline. Fifty metres
#: bounds the approximation error at twenty-five, which is well inside every
#: snap radius this server uses.
DEFAULT_STEP_M = 50.0


class SpatialIndex:
    """Labelled positions, searchable by proximity.

    Args:
        entries: ``(label, (lon, lat))`` pairs. A label may repeat.
        cell_degrees: Grid resolution.

    Immutable once built. Rebuilding is cheap and sharing a mutable index
    across request threads is not worth the lock.
    """

    __slots__ = ("_cells", "_cell_degrees", "_size")

    def __init__(
        self,
        entries: Iterable[tuple[str, Coord]],
        *,
        cell_degrees: float = DEFAULT_CELL_DEGREES,
    ) -> None:
        self._cell_degrees = cell_degrees
        self._cells: dict[tuple[int, int], list[tuple[str, Coord]]] = {}
        size = 0
        for label, point in entries:
            self._cells.setdefault(self._cell(point), []).append((label, point))
            size += 1
        self._size = size

    def __len__(self) -> int:
        """How many positions are indexed, not how many distinct labels."""
        return self._size

    @property
    def is_empty(self) -> bool:
        return self._size == 0

    def nearest(self, point: Coord, *, within_m: float | None = None) -> tuple[str, float] | None:
        """The closest label and its distance, or ``None`` if none qualifies.

        With ``within_m``, ``None`` means nothing is that close -- which is an
        answer, not a failure, and usually the right one: a GPS fix 800 m from
        every road should not be attributed to the least distant of them.

        Without it, the answer is the nearest point in the index, whatever the
        distance. Ties are broken by label, ascending, so the answer is
        deterministic when two positions coincide -- which they do, at a
        junction shared by two ways.
        """
        if self._size == 0:
            return None

        limit = float("inf") if within_m is None else float(within_m)
        cx, cy = self._cell(point)
        best: tuple[str, float] | None = None
        ring = 0

        while True:
            for label, position in self._ring(cx, cy, ring):
                distance = haversine_m(point, position)
                if distance > limit:
                    continue
                if best is None or distance < best[1] or (
                    distance == best[1] and label < best[0]
                ):
                    best = (label, distance)

            # Nothing in a further ring can be closer than this ring's own
            # inner edge, so once that edge is beyond both the best found and
            # the caller's limit, widening cannot change the answer.
            inner_edge_m = ring * self._cell_degrees * METERS_PER_DEGREE
            if best is not None and inner_edge_m > best[1]:
                return best
            if inner_edge_m > limit:
                return best
            if ring >= MAX_RINGS:
                if best is not None or within_m is not None:
                    return best
                # Unbounded, and nothing within 70 km. Rather than widen the
                # ring across an empty ocean one square at a time, scan.
                return self._scan(point)
            ring += 1

    def nearest_label(self, point: Coord, *, within_m: float | None = None) -> str | None:
        """:meth:`nearest`, without the distance."""
        found = self.nearest(point, within_m=within_m)
        return found[0] if found else None

    def within(self, area: BBox) -> tuple[str, ...]:
        """Every distinct label with at least one position inside ``area``.

        Sorted, so a caller iterating it gets a stable order.
        """
        labels: set[str] = set()
        for bucket in self._cells.values():
            for label, position in bucket:
                if area.contains(position):
                    labels.add(label)
        return tuple(sorted(labels))

    # --- Internals ---------------------------------------------------------

    def _scan(self, point: Coord) -> tuple[str, float] | None:
        """Every entry, compared. The fallback for a far unbounded search."""
        best: tuple[str, float] | None = None
        for bucket in self._cells.values():
            for label, position in bucket:
                distance = haversine_m(point, position)
                if best is None or distance < best[1] or (
                    distance == best[1] and label < best[0]
                ):
                    best = (label, distance)
        return best

    def _cell(self, point: Coord) -> tuple[int, int]:
        step = self._cell_degrees
        return (int(point[0] // step), int(point[1] // step))

    def _ring(self, cx: int, cy: int, ring: int) -> list[tuple[str, Coord]]:
        if ring == 0:
            return self._cells.get((cx, cy), [])
        found: list[tuple[str, Coord]] = []
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                found.extend(self._cells.get((cx + dx, cy + dy), ()))
        return found


def index_of_polylines(
    items: Iterable,
    *,
    cell_degrees: float = DEFAULT_CELL_DEGREES,
    step_m: float = DEFAULT_STEP_M,
) -> SpatialIndex:
    """Build an index from anything with an ``id`` and a ``geometry``.

    Every vertex is indexed under its owner's id, and long spans between
    vertices are filled in at ``step_m`` intervals. The filling matters: a road
    is a line, but a grid indexes points, and a sensor beside the middle of a
    kilometre of straight motorway with no vertex near it would otherwise
    measure as a kilometre away and be attributed to nothing.

    Interpolating is the cheap way to make a point index behave like a line
    index. The alternative -- real point-to-segment distance -- is exact and
    needs a different structure; at fifty-metre steps the error here is at most
    twenty-five metres, which is well inside the snap radii this server uses
    and inside the position error of the readings themselves.
    """
    return SpatialIndex(
        (
            (item.id, point)
            for item in items
            for point in densify(item.geometry, step_m=step_m)
        ),
        cell_degrees=cell_degrees,
    )


def densify(points: Sequence[Coord], *, step_m: float = DEFAULT_STEP_M) -> list[Coord]:
    """Every vertex, plus interpolated points so no gap exceeds ``step_m``.

    Linear interpolation in degrees. Over the tens of metres involved the
    difference from a great-circle interpolation is far below the precision
    anything here needs, and a spherical interpolation per road vertex would
    be paid on every index build.
    """
    if len(points) < 2:
        return list(points)

    filled: list[Coord] = [points[0]]
    for start, end in zip(points, points[1:]):
        span = haversine_m(start, end)
        steps = int(span // step_m)
        for i in range(1, steps + 1):
            fraction = (i * step_m) / span
            if fraction >= 1.0:
                break
            filled.append(
                (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
            )
        filled.append(end)
    return filled
