"""What published map data is made of.

One type: a :class:`RoadSegment`, which is what came back when this block was
asked about an area. The area itself is a :class:`domain.BBox` -- shared
rather than redefined here, because `ingest`, `roadstate` and the API all name
the same rectangle and three spellings of it is how a server starts
disagreeing with itself about what it was asked.

A segment is frozen. A published artifact is a statement about the source data
at a moment; anything that would change one returns a new one instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from domain import BBox, Coord, bounds_of, polyline_length_m

__all__ = ["Coord", "BBox", "RoadSegment", "coords_of"]


@dataclass(frozen=True, slots=True)
class RoadSegment:
    """One piece of the published reference road network.

    This is the block's primary output and the shape every consumer sees. It
    is deliberately thin: geometry, a class, a free-flow reference and a name.
    What a segment *costs*, how fast traffic is actually moving on it, and
    which graph edges it becomes are all decisions belonging to other blocks.

    Attributes:
        id: Stable identifier, carrying its provenance (``osm:way/12345``).
            Consumers key on this and it is part of the published contract.
        geometry: The shape, longitude first, at least two points.
        road_class: The source's own classification (``motorway``,
            ``residential``, ...), passed through rather than reinterpreted.
        free_flow_kph: Speed when nothing is in the way. From the source's
            posted limit where it publishes one, from a class default
            otherwise -- never a measurement, and never presented as one.
        name: Street name where the source has one.
        oneway: Whether the source tags the way as one-directional.
    """

    id: str
    geometry: tuple[Coord, ...]
    road_class: str
    free_flow_kph: float
    name: str | None = None
    oneway: bool = False

    def __post_init__(self) -> None:
        if len(self.geometry) < 2:
            raise ValueError(f"road segment {self.id!r} needs at least 2 points")
        if self.free_flow_kph <= 0:
            raise ValueError(f"road segment {self.id!r} has non-positive free flow")

    @property
    def length_m(self) -> float:
        return polyline_length_m(self.geometry)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return bounds_of(self.geometry)


def coords_of(pairs: Iterable[Sequence[float]]) -> tuple[Coord, ...]:
    """Normalise any iterable of lon/lat pairs into a coordinate tuple."""
    return tuple((float(p[0]), float(p[1])) for p in pairs)
