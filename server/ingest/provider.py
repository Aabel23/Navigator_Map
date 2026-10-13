"""The seam every traffic source plugs into.

One method, :meth:`TrafficProvider.fetch`, and one declaration,
:meth:`TrafficProvider.coverage`. That second one is what makes a world made
of national open-data feeds workable: free traffic data is published by road
authorities, one country at a time, so a provider that only knows Finland has
to be able to *say* so and be skipped everywhere else, rather than answering
an unanswerable question with an empty result.

:class:`RoadNetwork` is the other half, and the way it is written is the
mapdata boundary being respected rather than crossed. A provider that derives
traffic rather than measuring it needs a reference network to attach numbers
to, and this block does not own road geometry. So this is a structural
:class:`~typing.Protocol`: anything that can answer a roads query satisfies
it, and no import passes between the two blocks in either direction. Whoever
composes the server hands one in.

The bounding box is :class:`domain.BBox` on both sides now -- the shared
geographic vocabulary, so the two blocks name the same rectangle rather than
each defining their own and relying on them having the same four fields.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, Sequence, runtime_checkable

from domain import BBox

from .models import Observations

__all__ = ["TrafficProvider", "RoadNetwork", "RoadLike"]


@runtime_checkable
class RoadLike(Protocol):
    """The shape a provider needs a published road to have.

    Structural on purpose: this names the fields of the mapdata block's
    RoadSegment without importing it, so a modelled provider can attach
    numbers to a road network it is handed without either block depending on
    the other.
    """

    id: str
    geometry: tuple[tuple[float, float], ...]
    road_class: str
    free_flow_kph: float
    name: str | None
    oneway: bool


@runtime_checkable
class RoadNetwork(Protocol):
    """Supplies the reference road network for a bounding box.

    Satisfied today by the mapdata block's OverpassRoadSource. When the client
    can hand over geometry it has already decoded, that becomes a second
    implementation and nothing in this block changes.

    """

    def roads(self, bbox: BBox) -> Sequence[RoadLike]:
        """Every routable road segment intersecting the box."""
        ...


class TrafficProvider(ABC):
    """One source of traffic observations.

    Subclasses do the network I/O and the schema translation, and return the
    result in this block's own vocabulary. Nothing above a provider knows
    whether it read a sensor feed, a modelled estimate, or a file on disk --
    only the source recorded on each record says so, and that string is what
    an honest UI shows the driver.
    """

    #: Short, stable identifier. Ends up on every record this provider makes
    #: and on the batch it returns, so it is part of the wire format.
    name: str = "unnamed"

    def coverage(self) -> BBox | None:
        """The area this provider can answer for. None means anywhere.

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
    def fetch(self, bbox: BBox) -> Observations:
        """Normalized observations inside the box, now.

        Raises:
            ingest.errors.ProviderUnavailable: upstream unreachable.
            ingest.errors.BadResponse: upstream answered unreadably.
            ingest.errors.OutsideCoverage: the box is outside
                :meth:`coverage`.

        An area this provider covers but has no data for is not an error --
        that is an empty batch.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"
