"""The shape of a published road network.

This block's primary output is not a file, it is an answerable question: *what
roads are in this box?* :class:`RoadNetwork` is that question written down.

It is a :class:`~typing.Protocol` rather than a base class on purpose. A
consumer holds the interface, not this module; anything that can answer
``roads(bbox)`` is a road network, whether it reads Overpass, a PBF extract,
a fixture file, or an artifact this block published earlier. That is what lets
`mapdata` be swapped, tested or replaced without a single consumer changing.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .models import BBox, RoadSegment

__all__ = ["RoadNetwork"]


@runtime_checkable
class RoadNetwork(Protocol):
    """Supplies the reference road network for a bounding box."""

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        """Every routable road segment intersecting ``bbox``."""
        ...
