"""The composition root: the one place that knows every subsystem exists.

Everything else in this server is written against an interface and handed what
it needs. This file is where "what it needs" is decided -- once, from
configuration, at startup -- and it is the only module that imports `routing`,
`mapdata`, `traffic`, `roadstate`, `ingest` and `storage` together.

That concentration is the point rather than a smell. The alternative is each
subsystem constructing its own dependencies, and then swapping the database,
turning off the traffic feed, or running a test without the network means
editing five files instead of one.

    Settings
       │
       ▶ StorageBackend ────────────────────┐
       │                                    │
       ▶ RoadNetwork (Overpass + store) ──▶ RoadGraphProvider ─┐
       │                                                       │
       ▶ TrafficState ──▶ TrafficCostSource ───────────────────┤
       │                                                       │
       ▶ RoadStateStore ──▶ RoadStateSource ───────────────────┤
       │                                                       │
       ▶ TrafficCollector ──▶ IngestService ──▶ TrafficService │
       │                                                       ▼
       └───────────────────────────────────────────▶ RoutingService

Nothing above reaches down past what it was handed, and nothing below knows
this file exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import Settings
from domain import BBox
from ingest import TrafficCollector
from mapdata import (
    NominatimAddressSource,
    OverpassRoadSource,
    PersistingRoadNetwork,
    RoadGraphProvider,
    StoredRoadNetwork,
)
from observability import HealthRegistry, get_logger
from roadstate import RoadStateSource, RoadStateStore
from routing import RoutingPolicy, RoutingService
from storage import InMemoryStorage, JsonFileCache, SqliteStorage, StorageBackend
from traffic import TrafficCostSource, TrafficState

from .services import IngestService, TrafficService

__all__ = ["Services", "build_services"]

log = get_logger("composition")


@dataclass(frozen=True, slots=True)
class Services:
    """Everything the handlers are allowed to reach.

    A handler is given this and nothing else. What is absent from this list is
    absent from the API's vocabulary -- there is no way for a route handler to
    obtain a database connection, because nothing here exposes one.
    """

    settings: Settings
    storage: StorageBackend
    roads: Any
    graphs: RoadGraphProvider
    traffic_state: TrafficState
    routing: RoutingService
    ingest: IngestService
    traffic: TrafficService
    road_state: RoadStateStore
    health: HealthRegistry
    #: Reverse geocoding. Optional so a test that has no use for it does not
    #: have to build one; the endpoint answers 503 when it is absent.
    addresses: Any = None

    def default_area(self) -> BBox:
        return self.settings.area()

    def describe(self) -> dict[str, Any]:
        return {
            "settings": self.settings.describe(),
            "routing": self.routing.describe(),
            "traffic": self.traffic.stats(),
            "ingest": self.ingest.describe(),
            "road_state": self.road_state.stats(),
            "storage": {"backend": self.storage.name},
        }

    def close(self) -> None:
        self.storage.close()


def build_services(settings: Settings | None = None) -> Services:
    """Wire the whole server from settings. Called once, by the app factory."""
    settings = settings or Settings.from_env()
    settings.validate()

    storage = _storage(settings)
    storage.migrate()

    roads = _road_network(settings, storage)
    graphs = RoadGraphProvider(roads, cache_size=settings.graph_cache_size)

    traffic_state = TrafficState(max_age_s=settings.traffic_max_age_s)
    road_state_store = RoadStateStore(
        storage.documents,
        open_ended_ttl=_seconds(settings.roadstate_open_ended_ttl_s),
    )

    ingest_service = IngestService(
        collector=_collector(settings),
        traffic=traffic_state,
        road_state=road_state_store,
        roads=roads,
    )
    traffic_service = TrafficService(
        ingest=ingest_service,
        state=traffic_state,
        enabled=settings.traffic_enabled,
    )

    routing_service = RoutingService(
        graphs=graphs,
        traffic=(
            TrafficCostSource(traffic_state, graphs) if settings.traffic_enabled else None
        ),
        road_state=(
            RoadStateSource(road_state_store, graphs) if settings.roadstate_enabled else None
        ),
        policy=RoutingPolicy(
            pad_degrees=settings.route_pad_degrees,
            snap_radius_m=settings.route_snap_radius_m,
        ),
    )

    services = Services(
        settings=settings,
        storage=storage,
        roads=roads,
        graphs=graphs,
        traffic_state=traffic_state,
        routing=routing_service,
        ingest=ingest_service,
        traffic=traffic_service,
        road_state=road_state_store,
        health=HealthRegistry(),
        addresses=_addresses(settings),
    )
    _register_health(services)
    return services


# --- Pieces ----------------------------------------------------------------


def _storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "memory":
        return InMemoryStorage(cache_ttl_s=settings.cache_ttl_s)
    return SqliteStorage(settings.database_file(), cache_ttl_s=settings.cache_ttl_s)


def _road_network(settings: Settings, storage: StorageBackend):
    """Overpass in front, the database behind it.

    The disk cache is separate from the database on purpose: an Overpass
    response is a raw upstream payload that is cheap to lose and awkward to
    query, while the parsed segments in the document store are what the server
    falls back to when Overpass is unreachable. Two different jobs, two
    different places.
    """
    cache = JsonFileCache(settings.cache_path(), ttl_s=settings.cache_ttl_s)
    upstream = OverpassRoadSource(
        endpoint=settings.overpass_endpoint,
        cache=cache,
        timeout_s=settings.overpass_timeout_s,
    )
    return PersistingRoadNetwork(upstream, storage.documents)


def _addresses(settings: Settings) -> NominatimAddressSource:
    """OSM's own reverse geocoder, rate-limited and cached on disk.

    Same disk cache as the road source: a reverse lookup is an upstream payload
    that is cheap to lose and that a public volunteer service would rather not
    be asked for twice.
    """
    return NominatimAddressSource(
        endpoint=settings.nominatim_endpoint,
        cache=JsonFileCache(settings.cache_path(), ttl_s=settings.cache_ttl_s),
        min_interval_s=settings.nominatim_interval_s,
    )


def _collector(settings: Settings) -> TrafficCollector:
    """The free traffic sources, chosen by configuration.

    Both are free and keyless, which is a project rule rather than an
    accident. Digitraffic measures, and covers Finland only. The simulated
    provider models, covers anywhere, and labels every record it makes so
    nothing downstream -- and no driver -- can mistake it for a measurement.
    """
    providers = []
    if settings.digitraffic_enabled:
        from ingest.external_sources.digitraffic import DigitrafficProvider

        providers.append(DigitrafficProvider())

    fallback = None
    if settings.traffic_simulated:
        from ingest.external_sources.simulated import SimulatedTrafficProvider

        fallback = SimulatedTrafficProvider(_SimulatedRoads(settings))

    return TrafficCollector(providers, fallback=fallback)


class _SimulatedRoads:
    """A road network for the modelled provider, built lazily.

    Lazy because constructing it eagerly would make starting the server depend
    on Overpass being up, and a server that will not start because a volunteer
    API is slow is worse than one that starts and reports a degraded traffic
    source.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._source = None

    def roads(self, bbox):
        if self._source is None:
            self._source = OverpassRoadSource(
                endpoint=self._settings.overpass_endpoint,
                cache=JsonFileCache(
                    self._settings.cache_path(), ttl_s=self._settings.cache_ttl_s
                ),
                timeout_s=self._settings.overpass_timeout_s,
            )
        return self._source.roads(bbox)


def _register_health(services: Services) -> None:
    """What this particular server should be able to do.

    Storage is critical: without it nothing can be persisted or read back.
    Map data is critical: without roads there is no graph and no route.
    Traffic and road state are not -- a server routing on free-flow speeds
    with no closures loaded is degraded, not broken, and taking it out of
    rotation over that would be the wrong call every time.
    """
    services.health.register(
        "storage",
        lambda: (services.storage.healthy(), {"backend": services.storage.name}),
    )
    services.health.register(
        "mapdata",
        lambda: _check_graph(services),
    )
    services.health.register(
        "traffic",
        lambda: (True, services.traffic.stats()),
        critical=False,
    )
    services.health.register(
        "roadstate",
        lambda: (True, services.road_state.stats()),
        critical=False,
    )


def _check_graph(services: Services) -> tuple[bool, Any]:
    """Whether a graph can be built for the default area.

    Reads through the graph cache, so after the first call this is free and
    the health endpoint is not a way to hammer Overpass.
    """
    view = services.graphs.graph_for(services.default_area())
    summary = view.summary()
    return summary["edges"] > 0, summary


def _seconds(value: float):
    from datetime import timedelta

    return timedelta(seconds=value)
