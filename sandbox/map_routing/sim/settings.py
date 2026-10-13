"""What the simulator is allowed to know without asking a block.

Two regions, because the traffic block's honest answer to "is there free live
traffic data" is "in some countries": Helsinki has measured sensor data and Ho
Chi Minh City does not, and a simulator that only ever showed one of them would
hide the most interesting half of the traffic connector.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .blocks import SANDBOX_ROOT

__all__ = ["Region", "REGIONS", "DEFAULT_REGION", "CACHE_DIR", "HOST", "PORT", "DEBUG", "Tuning"]

HOST: str = os.getenv("SIM_HOST", "127.0.0.1")
PORT: int = int(os.getenv("SIM_PORT", "1530"))
DEBUG: bool = os.getenv("SIM_DEBUG", "").strip().lower() in {"1", "true", "yes"}

#: Overpass is a shared volunteer service. Everything it answers is cached to
#: disk so restarting the simulator does not re-ask for the same city.
CACHE_DIR: Path = Path(os.getenv("SIM_CACHE_DIR", str(SANDBOX_ROOT / ".cache" / "overpass")))

#: Every road class the graph builder will accept. Service roads, tracks and
#: footways are already excluded by the traffic block's own road source.
ALL_CLASSES: tuple[str, ...] = (
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "residential", "unclassified",
)

#: Major roads only. Used where the region is large enough that asking for
#: every residential street would make the Overpass query the slow part of
#: starting the simulator.
MAJOR_CLASSES: tuple[str, ...] = (
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary",
)


@dataclass(frozen=True, slots=True)
class Tuning:
    """Numbers the simulator uses that are judgement calls, not facts."""

    #: How far a traffic reading may be from a graph edge and still be taken
    #: to describe it. A sensor mast stands beside the carriageway, and OSM
    #: geometry is a centreline, so zero is the wrong answer.
    traffic_match_radius_m: float = 45.0

    #: Ceiling on a congestion multiplier. The traffic block promises every
    #: multiplier is at least 1.0; this end is the sandbox's own guard against
    #: one implausible reading swamping a route.
    max_multiplier: float = 6.0

    #: How far a blocking incident reaches when it is turned into avoided edges.
    incident_block_radius_m: float = 60.0

    #: A picked point further than this from any routable junction is refused
    #: rather than silently snapped halfway across town.
    max_snap_distance_m: float = 400.0

    #: GPS noise, one standard deviation. Small, but large enough that the
    #: snap to a junction is visibly doing something.
    gps_accuracy_m: float = 5.0

    #: How much faster than real time a drive runs. The vehicle keeps the
    #: route's own speed -- only the clock is sped up -- so a nine-minute route
    #: still reports the 35 km/h it is being driven at, and still takes longer
    #: than the free-flow one it is being compared against.
    drive_time_scale: float = 8.0


@dataclass(frozen=True, slots=True)
class Region:
    """One place the simulator can be pointed at.

    Attributes:
        key: Stable identifier used on the wire.
        label: What the panel calls it.
        bbox: West, south, east, north. Bounds the road graph, the Overpass
            query and the traffic snapshot -- one box for all three, so the
            three blocks are always talking about the same area.
        center: Where the fake GPS starts, ``(lon, lat)``.
        zoom: Camera zoom the page opens at.
        road_classes: Which OSM highway classes the graph is built from.
        measured: Whether a measuring traffic provider covers this region.
            Purely informational -- the store decides for itself.
        utc_offset_hours: Local time, for the simulated provider's rush hours.
    """

    key: str
    label: str
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    zoom: float
    road_classes: tuple[str, ...] = ALL_CLASSES
    measured: bool = False
    utc_offset_hours: float = 7.0
    note: str = ""


REGIONS: dict[str, Region] = {
    "hcmc": Region(
        key="hcmc",
        label="Ho Chi Minh City -- District 1",
        bbox=(106.675, 10.758, 106.725, 10.798),
        center=(106.7009, 10.7769),
        zoom=15.0,
        road_classes=ALL_CLASSES,
        measured=False,
        utc_offset_hours=7.0,
        note="No free live feed for Vietnam. Traffic here is modelled, and every "
             "record says so.",
    ),
    "helsinki": Region(
        key="helsinki",
        label="Helsinki -- central",
        bbox=(24.83, 60.14, 25.07, 60.25),
        center=(24.9384, 60.1699),
        zoom=13.0,
        road_classes=MAJOR_CLASSES,
        measured=True,
        utc_offset_hours=2.0,
        note="Fintraffic's Digitraffic publishes measured speeds and incidents "
             "here, free and keyless.",
    ),
}

DEFAULT_REGION: str = os.getenv("SIM_REGION", "hcmc")

TUNING = Tuning()
