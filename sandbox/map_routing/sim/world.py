"""The simulator: one object holding the three blocks and the wires between them.

The data flow this exists to exercise, in the order it happens:

    Fake GPS ---- origin ------> [ map matching ] --+
                                                     |
    picked point - destination -> [ map matching ] --+--> routing --> Map
                                                     |
    Traffic ---- {edge: multiplier} -----------------+

Every arrow is a documented connector of one of the three blocks, and every
one of them is crossed here with plain data -- a coordinate, an id, a dict of
floats. No block imports another, and the sandbox imports each one only
through the interface it publishes.

Two routes are computed for every request, not one: the same origin and
destination under free-flow costs and under live traffic costs. A simulator
whose job is to prove a connector works should show the difference the
connector makes, and one route on its own cannot.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .blocks import (
    BBox,
    CostMode,
    DigitrafficProvider,
    DynamicCostModel,
    OverpassRoadSource,
    Route,
    RouteConstraints,
    RouteRequest,
    Router,
    RoutingError,
    SimulatedTrafficProvider,
    StaticCostModel,
    TrafficStore,
)
from .geodesy import Coord
from .gps import FakeGps
from .graph_build import BuiltGraph, build_graph
from .matching import EdgeIndex, Match, NodeIndex
from .settings import CACHE_DIR, REGIONS, TUNING, Region
from .traffic_link import TrafficLink, link_traffic_to_edges

__all__ = ["Simulator"]

#: How often the background thread asks the traffic store for a new snapshot.
#: The store's own TTL is 60 s, so asking more often than that mostly costs
#: nothing; asking on this cadence keeps the overlay from ageing out.
_TRAFFIC_REFRESH_S = 45.0


@dataclass(frozen=True, slots=True)
class Leg:
    """One of the two routes computed for a request."""

    key: str
    label: str
    route: Route | None
    error: str | None

    def as_json(self) -> dict[str, Any]:
        if self.route is None:
            return {"key": self.key, "label": self.label, "ok": False, "error": self.error}
        route = self.route
        return {
            "key": self.key,
            "label": self.label,
            "ok": True,
            "error": None,
            "geometry": [[c.longitude, c.latitude] for c in route.geometry],
            "distance_m": round(route.distance, 1),
            "travel_time_s": round(route.travel_time, 1),
            "total_cost": round(route.total_cost, 1),
            "cost_mode": route.cost_mode,
            "edges": route.edge_count,
            "nodes_expanded": route.nodes_expanded,
            "steps": [
                {
                    "maneuver": step.maneuver.value,
                    "name": step.name,
                    "distance_m": round(step.distance, 1),
                    "travel_time_s": round(step.travel_time, 1),
                }
                for step in route.steps
            ],
        }


class Simulator:
    """Holds a region's graph, its traffic, and one fake vehicle.

    Thread-safe by one coarse lock. The work that takes real time -- the
    Overpass query, the graph build, the traffic refresh -- happens on a
    background thread so that no browser request ever waits on the network.
    """

    def __init__(self, region_key: str) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._region: Region = REGIONS[region_key]
        self._generation = 0

        self._status = "idle"
        self._error: str | None = None
        self._built: BuiltGraph | None = None
        self._nodes: NodeIndex | None = None
        self._edges: EdgeIndex | None = None

        self._store: TrafficStore | None = None
        self._traffic: Any = None  # StoreResult, once one has arrived
        self._traffic_link = TrafficLink()
        self._traffic_at: float = 0.0

        self._gps = FakeGps(self._region.center, accuracy_m=TUNING.gps_accuracy_m)
        self._origin: Match | None = None
        self._destination_point: Coord | None = None
        self._destination: Match | None = None
        self._legs: tuple[Leg, ...] = ()
        self._route_note: str | None = None

        self._worker = threading.Thread(target=self._background, name="sim-worker", daemon=True)
        self._worker.start()

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        self._stop.set()

    # -- region ---------------------------------------------------------------

    @property
    def region(self) -> Region:
        return self._region

    def set_region(self, key: str) -> None:
        """Point the simulator at another city, discarding everything built."""
        if key not in REGIONS:
            raise KeyError(key)
        with self._lock:
            if key == self._region.key:
                return
            self._region = REGIONS[key]
            self._generation += 1
            self._status = "idle"
            self._error = None
            self._built = None
            self._nodes = None
            self._edges = None
            self._store = None
            self._traffic = None
            self._traffic_link = TrafficLink()
            self._traffic_at = 0.0
            self._legs = ()
            self._route_note = None
            self._origin = None
            self._destination = None
            self._destination_point = None
            self._gps.place(self._region.center)

    # -- the fake GPS ---------------------------------------------------------

    def place_gps(self, point: Coord) -> dict[str, Any]:
        """Drop the vehicle at a coordinate and re-match it to the network."""
        with self._lock:
            self._gps.place(point)
            self._match_origin()
            self._recompute()
            return self.state()

    def set_noise(self, enabled: bool) -> None:
        self._gps.set_noise(enabled)

    def drive(self, on: bool) -> dict[str, Any]:
        """Start or stop driving the traffic-aware route.

        The speed comes from the route itself: distance over the travel time
        the cost model reported. Driving the congested route is therefore
        visibly slower than driving the free-flow one, which is the traffic
        connector showing up in the one place a driver would feel it. The
        clock, not the speedometer, is what gets sped up so the drive can be
        watched rather than waited out.
        """
        with self._lock:
            if not on:
                self._gps.stop()
                self._match_origin()
                return self.state()

            leg = self._leg("traffic") or self._leg("free_flow")
            if leg is None or leg.route is None or leg.route.travel_time <= 0:
                return self.state()
            shape = [(c.longitude, c.latitude) for c in leg.route.geometry]
            speed_kph = (leg.route.distance / leg.route.travel_time) * 3.6
            self._gps.follow(shape, speed_kph, TUNING.drive_time_scale)
            return self.state()

    # -- destination and routing ---------------------------------------------

    def set_destination(self, point: Coord) -> dict[str, Any]:
        """Pick a spot on the map: match it, then route to it."""
        with self._lock:
            self._destination_point = point
            self._match_origin()
            self._recompute()
            return self.state()

    def clear_destination(self) -> dict[str, Any]:
        with self._lock:
            self._destination_point = None
            self._destination = None
            self._legs = ()
            self._route_note = None
            self._gps.stop()
            return self.state()

    def rebuild(self) -> dict[str, Any]:
        """Throw the graph away and fetch the region again.

        The only way back from a failed Overpass query, which is a thing that
        happens: it is a free volunteer service and it is sometimes busy.
        """
        with self._lock:
            self._generation += 1
            self._status = "idle"
            self._error = None
            self._built = None
            self._nodes = None
            self._edges = None
            self._store = None
            self._traffic = None
            self._traffic_link = TrafficLink()
            self._traffic_at = 0.0
            self._legs = ()
            return self.state()

    def recompute(self) -> dict[str, Any]:
        with self._lock:
            self._match_origin()
            self._recompute()
            return self.state()

    # -- what the page reads --------------------------------------------------

    def state(self) -> dict[str, Any]:
        with self._lock:
            fix = self._gps.read()
            if fix.moving:
                # While driving, the origin follows the vehicle so the panel
                # shows where the matcher currently thinks the driver is. It is
                # matched on the *reported* fix, noise and all, because that is
                # the only thing a receiver would hand over. The route is not
                # recomputed -- that is navigation's job, and this sandbox
                # deliberately does not pretend to do it.
                self._match_origin(fix.point)

            return {
                "region": {
                    "key": self._region.key,
                    "label": self._region.label,
                    "bbox": list(self._region.bbox),
                    "center": list(self._region.center),
                    "zoom": self._region.zoom,
                    "measured": self._region.measured,
                    "note": self._region.note,
                },
                "graph": {
                    "status": self._status,
                    "error": self._error,
                    **(self._built.stats if self._built else {}),
                },
                "gps": {
                    **fix.as_json(),
                    "noise": self._gps.noise_enabled,
                    "match": _match_json(self._origin),
                },
                "destination": {
                    "picked": list(self._destination_point) if self._destination_point else None,
                    "match": _match_json(self._destination),
                },
                "traffic": self._traffic_json(),
                "routes": [leg.as_json() for leg in self._legs],
                "note": self._route_note,
            }

    def traffic_geojson(self) -> dict[str, Any]:
        with self._lock:
            if self._traffic is None:
                return {"type": "FeatureCollection", "features": []}
            return self._traffic.snapshot.to_geojson()

    # -- internals ------------------------------------------------------------

    def _traffic_json(self) -> dict[str, Any]:
        if self._traffic is None:
            return {"ready": False, "link": dict(self._traffic_link.stats)}
        return {
            "ready": True,
            **self._traffic.meta(),
            "age_s": round(time.monotonic() - self._traffic_at, 1),
            "link": dict(self._traffic_link.stats),
        }

    def _leg(self, key: str) -> Leg | None:
        for leg in self._legs:
            if leg.key == key:
                return leg
        return None

    def _match_origin(self, point: Coord | None = None) -> None:
        """Snap the vehicle to a junction. Needs the graph; silent without it."""
        if self._nodes is None:
            self._origin = None
            return
        where = point if point is not None else self._gps.read().point
        self._origin = self._nodes.nearest(where, TUNING.max_snap_distance_m)

    def _recompute(self) -> None:
        self._legs = ()
        self._route_note = None

        if self._nodes is None or self._built is None:
            self._route_note = "The road graph is still being built."
            return
        if self._destination_point is None:
            return

        self._destination = self._nodes.nearest(
            self._destination_point, TUNING.max_snap_distance_m
        )
        if self._origin is None:
            self._route_note = "No routable junction near the vehicle."
            return
        if self._destination is None:
            self._route_note = (
                f"No routable junction within {TUNING.max_snap_distance_m:.0f} m of that point."
            )
            return
        if self._origin.node_id == self._destination.node_id:
            self._route_note = "Origin and destination matched to the same junction."
            return

        graph = self._built.graph
        link = self._traffic_link

        free_flow = Router(graph=graph)
        traffic_aware = Router(
            graph=graph,
            costs=DynamicCostModel(StaticCostModel(CostMode.FASTEST), link.multipliers),
        )
        # A blocking incident is a request constraint, not a large multiplier.
        # The routing connector is specific about that, and it is the right
        # call: an infinite cost would poison the A* heuristic's bound, while
        # a constraint simply removes the edge from consideration.
        constraints = (
            RouteConstraints(blocked_edges=link.blocked_edges) if link.blocked_edges else None
        )

        self._legs = (
            self._run(
                free_flow,
                "free_flow",
                "Free flow",
                self._origin.node_id,
                self._destination.node_id,
                None,
            ),
            self._run(
                traffic_aware,
                "traffic",
                "With traffic",
                self._origin.node_id,
                self._destination.node_id,
                constraints,
            ),
        )

    @staticmethod
    def _run(
        router: Router,
        key: str,
        label: str,
        origin: str,
        destination: str,
        constraints: RouteConstraints | None,
    ) -> Leg:
        request = RouteRequest(
            origin=origin,
            destination=destination,
            profile="car",
            cost_mode=CostMode.FASTEST,
            constraints=constraints,
        )
        try:
            return Leg(key=key, label=label, route=router.find(request), error=None)
        except RoutingError as err:
            # The routing contract promises nothing but RoutingError escapes a
            # routing call, so this one clause is the whole failure surface.
            return Leg(key=key, label=label, route=None, error=f"{type(err).__name__}: {err}")

    # -- background work ------------------------------------------------------

    def _background(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as err:  # noqa: BLE001 - a worker that dies takes the sim with it
                with self._lock:
                    self._status = "error"
                    self._error = f"{type(err).__name__}: {err}"
            self._stop.wait(1.0)

    def _tick(self) -> None:
        with self._lock:
            region, generation, status = self._region, self._generation, self._status

        if status == "idle":
            self._build(region, generation)
            return
        if status != "ready":
            return

        with self._lock:
            due = (time.monotonic() - self._traffic_at) >= _TRAFFIC_REFRESH_S
        if due:
            self._refresh_traffic(region, generation)

    def _build(self, region: Region, generation: int) -> None:
        """Fetch the region's roads and turn them into a graph."""
        with self._lock:
            if self._generation != generation:
                return
            self._status = "building"
            self._error = None

        source = OverpassRoadSource(
            road_classes=region.road_classes,
            cache_dir=CACHE_DIR,
        )
        bbox = BBox(*region.bbox)
        try:
            segments = source.roads(bbox)
            built = build_graph(segments)
        except Exception as err:  # noqa: BLE001 - reported to the page, not raised
            with self._lock:
                if self._generation == generation:
                    self._status = "error"
                    self._error = f"{type(err).__name__}: {err}"
            return

        store = TrafficStore(
            providers=[DigitrafficProvider()] if region.measured else [],
            fallback=SimulatedTrafficProvider(
                source,
                utc_offset_hours=region.utc_offset_hours,
            ),
        )

        with self._lock:
            if self._generation != generation:
                return
            self._built = built
            self._nodes = NodeIndex(built.graph, built.routable_nodes)
            self._edges = EdgeIndex(built.graph)
            self._store = store
            self._status = "ready"
            self._match_origin()
            self._recompute()

        self._refresh_traffic(region, generation)

    def _refresh_traffic(self, region: Region, generation: int) -> None:
        with self._lock:
            store, edges, built = self._store, self._edges, self._built
        if store is None or edges is None or built is None:
            return

        bbox = BBox(*region.bbox)
        try:
            result = store.snapshot(bbox)
        except Exception as err:  # noqa: BLE001 - traffic is allowed to be missing
            with self._lock:
                if self._generation == generation:
                    self._traffic_at = time.monotonic()
                    self._route_note = f"Traffic refresh failed: {err}"
            return

        link = link_traffic_to_edges(
            result.snapshot.active(),
            way_edges=built.way_edges,
            edge_index=edges,
            tuning=TUNING,
        )
        with self._lock:
            if self._generation != generation:
                return
            self._traffic = result
            self._traffic_link = link
            self._traffic_at = time.monotonic()
            self._recompute()


def _match_json(match: Match | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "node_id": match.node_id,
        "distance_m": round(match.distance_m, 1),
        "lon": round(match.point[0], 7),
        "lat": round(match.point[1], 7),
    }
