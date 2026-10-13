"""A small town, and the fakes that stand in for everything outside.

Every cross-subsystem test in this server runs over the same six streets. They
are laid out as a square with a diagonal, which is the smallest network where
the interesting questions have different answers: there is more than one way
across it, the ways differ in length and speed, and closing one changes the
result.

    (0,1) B ─────────── C (1,1)
          │ ╲           │
          │   ╲         │
          │     ╲       │
          │       ╲     │
    (0,0) A ─────────── D (1,0)

Nothing here touches the network, the clock or the disk. A fake road network
returns these six segments; a fake traffic source and a fake road-state source
return whatever a test hands them. That is what makes an integration test that
exercises the whole stack -- HTTP, service, engine, providers -- run in
milliseconds and give the same answer every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from domain import BBox, GeoPoint
from mapdata import RoadSegment

__all__ = [
    "TOWN",
    "TOWN_AREA",
    "CORNER",
    "town_roads",
    "FakeRoadNetwork",
    "FakeTrafficSource",
    "FakeRoadStateSource",
    "T0",
]

T0 = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)

#: The corners, in a real place so that coordinates behave like coordinates:
#: central District 1, Ho Chi Minh City. A square of 0.01 degrees is about
#: 1.1 km on a side, which is a realistic city block run.
CORNER = {
    "A": (106.700, 10.770),
    "B": (106.700, 10.780),
    "C": (106.710, 10.780),
    "D": (106.710, 10.770),
}

TOWN_AREA = BBox(106.690, 10.760, 106.720, 10.790)


def town_roads() -> tuple[RoadSegment, ...]:
    """The six streets. Distinct classes and speeds, so cost mode matters."""
    return (
        RoadSegment(
            id="way/AB",
            geometry=(CORNER["A"], CORNER["B"]),
            road_class="residential",
            free_flow_kph=30.0,
            name="Le Loi",
        ),
        RoadSegment(
            id="way/BC",
            geometry=(CORNER["B"], CORNER["C"]),
            road_class="primary",
            free_flow_kph=50.0,
            name="Nguyen Hue",
        ),
        RoadSegment(
            id="way/CD",
            geometry=(CORNER["C"], CORNER["D"]),
            road_class="residential",
            free_flow_kph=30.0,
            name="Hai Ba Trung",
        ),
        RoadSegment(
            id="way/AD",
            geometry=(CORNER["A"], CORNER["D"]),
            road_class="primary",
            free_flow_kph=50.0,
            name="Nam Ky Khoi Nghia",
        ),
        RoadSegment(
            id="way/BD",
            geometry=(CORNER["B"], CORNER["D"]),
            road_class="tertiary",
            free_flow_kph=40.0,
            name="Dong Khoi",
        ),
        # A stub hanging off A, so there is somewhere unreachable-ish and a
        # junction with an odd degree. Networks that are all cycles hide bugs.
        RoadSegment(
            id="way/A-stub",
            geometry=(CORNER["A"], (106.695, 10.770)),
            road_class="service",
            free_flow_kph=20.0,
            name="Alley",
        ),
    )


TOWN = town_roads()


@dataclass
class FakeRoadNetwork:
    """A road network that answers from a list. Records what it was asked.

    The call count is not decoration: several behaviours in this server exist
    only to avoid asking an upstream twice, and a test that cannot see the
    second call cannot check them.
    """

    segments: Sequence[RoadSegment] = TOWN
    calls: int = 0
    fail_with: Exception | None = None

    def roads(self, bbox: BBox) -> Sequence[RoadSegment]:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return tuple(
            segment for segment in self.segments if bbox.touches_any(segment.geometry)
        )


@dataclass
class FakeTrafficSource:
    """A ``routing.TrafficCostProvider`` over a fixed mapping."""

    multipliers: Mapping[str, float] = None  # type: ignore[assignment]
    calls: int = 0

    def multipliers_for(self, area: BBox) -> Mapping[str, float]:
        self.calls += 1
        return dict(self.multipliers or {})


@dataclass
class FakeRoadStateSource:
    """A ``routing.RoadStateProvider`` over fixed sets."""

    blocked: frozenset[str] = frozenset()
    multipliers: Mapping[str, float] = None  # type: ignore[assignment]
    fail_blocked_with: Exception | None = None

    def blocked_edges(self, area: BBox) -> frozenset[str]:
        if self.fail_blocked_with is not None:
            raise self.fail_blocked_with
        return frozenset(self.blocked)

    def multipliers_for(self, area: BBox) -> Mapping[str, float]:
        return dict(self.multipliers or {})


def point(corner: str) -> GeoPoint:
    """The named corner, as a routing-service endpoint."""
    lon, lat = CORNER[corner]
    return GeoPoint(lon, lat)
