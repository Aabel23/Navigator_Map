"""Application services: the orchestration between HTTP and the subsystems.

A route handler should read like a sentence -- parse, call, serialise -- and
everything it calls should already exist. These are the things it calls.

The division of labour this file exists to keep:

* A **handler** (``api/routes/``) speaks HTTP. It reads a query string, calls
  one method here, and turns the result into JSON. It contains no loops over
  domain objects and no decisions.
* A **service** (this file) sequences subsystems. It knows that a traffic
  refresh means collect, then attach, then classify the incidents that came
  with it -- and it knows nothing about how any of those three work.
* A **subsystem** computes. It knows nothing about the other two layers.

Nothing here is an algorithm. If a method in this file starts to contain
domain reasoning -- what a severity means, how a speed becomes a cost -- that
reasoning belongs in the subsystem that owns it, and having it here is the
beginning of the API becoming the place where the real logic lives.

Inputs:  domain values from the handlers
Outputs: domain values and plain summary dicts
Not here: HTTP, JSON, Flask, SQL
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from domain import BBox
from ingest import (
    TrafficCollector,
    normalize_reports,
    parse_probe,
    probes_to_observations,
    report_of_incident,
)
from ingest.errors import BadResponse
from observability import get_logger
from roadstate import RoadStateStore, attribute, classify_all
from traffic import TrafficState

__all__ = ["IngestService", "TrafficService", "DEFAULT_REFRESH_INTERVAL_S"]

#: How long a collected traffic picture is reused before the providers are
#: asked again. Sixty seconds matches the fastest free feed's own publishing
#: rate; asking faster than the data changes is impolite to volunteer
#: infrastructure and buys nothing.
DEFAULT_REFRESH_INTERVAL_S = 60.0

log = get_logger("services")


class IngestService:
    """Everything arriving from outside, and where each kind of it goes.

    One object rather than three because the three paths share a shape --
    receive, validate, hand to the subsystem that interprets it -- and because
    the traffic path produces incidents, which means a refresh feeds both
    `traffic` and `roadstate`. Splitting them would put that fact somewhere
    that could forget it.

    Args:
        collector: The traffic feeds.
        traffic: Where speed readings are merged.
        road_state: Where conditions are kept.
        roads: The published road network, needed to attach both kinds of
            record to roads.
    """

    def __init__(
        self,
        *,
        collector: TrafficCollector,
        traffic: TrafficState,
        road_state: RoadStateStore,
        roads,
    ) -> None:
        self._collector = collector
        self._traffic = traffic
        self._road_state = road_state
        self._roads = roads

    # --- Feeds -------------------------------------------------------------

    def refresh(self, area: BBox) -> dict[str, Any]:
        """Pull every covering feed for ``area`` and distribute what comes back.

        Speed records go to `traffic`; incidents go to `roadstate` through the
        same classifier an operator's report goes through, so a Digitraffic
        road-works message and a typed-in one end up judged identically.

        A feed that failed is recorded on the traffic state and reported here,
        not raised: the rest of the picture is still worth having.
        """
        collection = self._collector.collect(area)

        for name, error in collection.failures:
            self._traffic.record_failure(name, error)
            log.warning("traffic source failed", extra={"source": name, "error": error})
        for batch in collection.batches:
            self._traffic.clear_failures(batch.source)

        roads = self._roads_in(area)
        attached = self._traffic.apply(collection.batches, roads)

        reports = [report_of_incident(incident) for incident in collection.incidents()]
        recorded = self._record_reports(reports, roads)

        return {
            **collection.meta(),
            "roads_with_speed": attached,
            "conditions_recorded": recorded,
        }

    # --- Clients -----------------------------------------------------------

    def accept_probes(self, raws: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Take GPS position reports from clients.

        Rejected probes are counted and their reasons returned rather than
        logged and dropped. A client sending malformed probes has no other way
        to find out, and silently discarding them is how a feature is believed
        to work for months while contributing nothing.
        """
        probes = []
        rejected: list[str] = []
        for raw in raws:
            try:
                probes.append(parse_probe(raw))
            except BadResponse as err:
                rejected.append(str(err))

        if not probes:
            return {"accepted": 0, "rejected": len(rejected), "reasons": rejected[:10]}

        batch = probes_to_observations(probes)
        area = batch.bbox.expanded(0.005)
        attached = self._traffic.apply([batch], self._roads_in(area))

        return {
            "accepted": len(probes),
            "moving": len(batch.observations),
            "rejected": len(rejected),
            "reasons": rejected[:10],
            "roads_with_speed": attached,
        }

    def accept_reports(self, raws: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Take incident reports -- a closure, a flood, a crash."""
        reports, rejected = normalize_reports(raws)
        if not reports:
            return {"accepted": 0, "rejected": len(rejected), "reasons": rejected[:10]}

        area = _area_of_reports(reports)
        recorded = self._record_reports(reports, self._roads_in(area))
        return {
            "accepted": recorded,
            "rejected": len(rejected),
            "reasons": rejected[:10],
        }

    # --- Shared ------------------------------------------------------------

    def _record_reports(self, reports: Sequence[Mapping[str, Any]], roads) -> int:
        if not reports:
            return 0
        conditions = classify_all(reports)
        conditions = attribute(conditions, roads)
        return self._road_state.record(conditions)

    def _roads_in(self, area: BBox):
        try:
            return self._roads.roads(area)
        except Exception as err:  # noqa: BLE001 - a missing road source degrades, never fails
            log.warning("road network unavailable during ingest", extra={"error": str(err)})
            return ()

    def describe(self) -> dict[str, Any]:
        return self._collector.describe()


class TrafficService:
    """Reads the traffic picture, refreshing it when it has gone stale.

    The refresh is lazy and debounced per area rather than run by a background
    worker. That is a deliberate choice for the current shape of this project:
    a worker is a second thing to deploy, supervise and shut down cleanly, and
    it would poll areas nobody is looking at. When a route is requested, the
    data for that area is what needs to be fresh, and this is where that is
    known.

    The debounce is per quantised area and holds a lock across the fetch, so
    two simultaneous requests for the same city do not both call Overpass and
    Digitraffic.
    """

    def __init__(
        self,
        *,
        ingest: IngestService,
        state: TrafficState,
        interval_s: float = DEFAULT_REFRESH_INTERVAL_S,
        enabled: bool = True,
        clock=time.monotonic,
    ) -> None:
        self._ingest = ingest
        self._state = state
        self._interval_s = interval_s
        self._enabled = enabled
        self._clock = clock
        self._lock = threading.RLock()
        self._last: dict[tuple[float, ...], float] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def ensure_fresh(self, area: BBox) -> bool:
        """Refresh ``area`` if it has not been refreshed recently.

        Returns whether a refresh actually ran. Never raises: traffic is an
        improvement to a route, not a precondition for one.
        """
        if not self._enabled:
            return False

        key = area.quantized(2).as_tuple()
        with self._lock:
            last = self._last.get(key)
            if last is not None and (self._clock() - last) < self._interval_s:
                return False
            self._last[key] = self._clock()
            try:
                self._ingest.refresh(area)
            except Exception as err:  # noqa: BLE001 - never fail a route over this
                log.warning("traffic refresh failed", extra={"error": str(err)})
                return False
        return True

    def snapshot(self, area: BBox, roads=None):
        """The current picture for ``area``, refreshed first if stale."""
        self.ensure_fresh(area)
        return self._state.snapshot(area, roads)

    def stats(self) -> dict[str, Any]:
        return {"enabled": self._enabled, "interval_s": self._interval_s, **self._state.stats()}


def _area_of_reports(reports: Sequence[Mapping[str, Any]]) -> BBox:
    points = [tuple(point) for report in reports for point in report["geometry"]]
    return BBox.covering(points, pad_degrees=0.005)
