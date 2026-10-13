"""The seam every traffic source plugs into.

One method, :meth:`TrafficProvider.fetch`, and one declaration,
:meth:`TrafficProvider.coverage`. That second one is what makes a world made
of national open-data feeds workable: free traffic data is published by road
authorities, one country at a time, so a provider that only knows Finland has
to be able to *say* so and be skipped everywhere else, rather than answering
an unanswerable question with an empty result.

:class:`RoadSource` is the other half. A provider that derives traffic rather
than measuring it needs a reference network to attach numbers to, and this
block does not own road geometry -- it asks for it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, Sequence, runtime_checkable

from .models import BBox, RoadSegment, TrafficSnapshot

__all__ = ["TrafficProvider", "RoadSource"]


@runtime_checkable
class RoadSource(Protocol):
    """Supplies the reference road network for a bounding box.

    Implemented today by :class:`traffic.sources.overpass.OverpassRoadSource`
    against free OpenStreetMap data. When the map or map_matching block can
    hand over the geometry it has already decoded, that becomes a second
    implementation and nothing else in this block changes.
    """

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        """Every routable road segment intersecting ``bbox``."""
        ...


class TrafficProvider(ABC):
    """One source of traffic state.

    Subclasses do the network I/O and the schema translation, and return the
    result in this block's own vocabulary. Nothing above a provider knows
    whether it read a sensor feed, a modelled estimate, or a file on disk --
    only the ``source`` recorded on each record says so, and that string is
    what an honest UI shows the driver.
    """

    #: Short, stable identifier. Ends up on every record this provider makes
    #: and in the snapshot ``sources`` tuple, so it is part of the wire format.
    name: str = "unnamed"

    def coverage(self) -> BBox | None:
        """The area this provider can answer for. ``None`` means anywhere.

        A provider that returns a box will only ever be asked about boxes that
        intersect it.
        """
        return None

    def covers(self, bbox: BBox) -> bool:
        area = self.coverage()
        if area is None:
            return True
        return area.intersects(bbox)

    @abstractmethod
    def fetch(self, bbox: BBox) -> TrafficSnapshot:
        """Traffic state inside ``bbox``, now.

        Raises:
            traffic.errors.ProviderUnavailable: upstream unreachable.
            traffic.errors.BadResponse: upstream answered unreadably.
            traffic.errors.OutsideCoverage: ``bbox`` is outside
                :meth:`coverage`.

        An area this provider covers but has no data for is not an error --
        that is an empty snapshot.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"
