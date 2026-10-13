# Server Connections

Every cross-block connection is one row in the table below. Each is a
`typing.Protocol` or a plain mapping; **no pair of domain blocks imports each
other.** Changing a row is an architectural change, not a refactor, and every
consumer must be checked.

## The contracts

| Contract | Declared in | Input | Output | Provider | Consumer |
|---|---|---|---|---|---|
| `MapGraphProvider` | `routing/providers.py` | `domain.BBox` | `GraphView` (`.graph`, `.nearest_node`) | `mapdata.RoadGraphProvider` | `routing.RoutingService` |
| `TrafficCostProvider` | `routing/providers.py` | `domain.BBox` | `{edge_id: float}`, each ≥ 1.0 | `traffic.TrafficCostSource` | `routing.RoutingService` |
| `RoadStateProvider.blocked_edges` | `routing/providers.py` | `domain.BBox` | `frozenset[edge_id]` | `roadstate.RoadStateSource` | `routing.RoutingService` |
| `RoadStateProvider.multipliers_for` | `routing/providers.py` | `domain.BBox` | `{edge_id: float}`, each ≥ 1.0 | `roadstate.RoadStateSource` | `routing.RoutingService` |
| `RoadEdgeIndex` | `traffic/state/provider.py`, `roadstate/provider.py` | `domain.BBox` | `{road_id: (edge_id, …)}` | `mapdata.RoadGraphProvider` | traffic, roadstate |
| `RoadNetwork` | `mapdata/network.py`, `ingest/provider.py` | `domain.BBox` | `Sequence[RoadSegment]` | `mapdata` sources and stores | ingest, traffic, roadstate, api |
| `TrafficProvider` | `ingest/provider.py` | `domain.BBox` | `Observations` | `ingest.external_sources.*` | `ingest.TrafficCollector` |
| normalized report | `ingest/incidents/reports.py` | raw mapping | a mapping: id, geometry, kind, severity, window, provenance | `ingest` | `roadstate.classify` |
| `DocumentStore` | `storage/interface/store.py` | `StoredDocument`, area, instant | `StoredDocument` | `storage.{memory,sqlite}` | mapdata, roadstate |
| `Cache` | `storage/interface/store.py` | key, JSON payload | payload or `None` | `storage.{memory,sqlite}`, `JsonFileCache` | mapdata sources |
| `RouteQuery` → `Route` | `routing/service.py` | coordinates, waypoints, profile, preferences | `Route` | `routing.RoutingService` | `api` |

## Main data flow

```text
External sources                     Client
(Digitraffic, a model)          (probes, reports)
      │                                │
      └──────────────┬─────────────────┘
                     ▼
                  ingest                     normalized, provider-independent,
                     │                       and deliberately meaning-free
        ┌────────────┴────────────┐
        ▼                         ▼
     traffic                  roadstate      the judgements: what a ratio means,
        │                         │          what a report is
        └────────────┬────────────┘
                     ▼
                  routing                    consumes multipliers + constraints;
                     │                       imports neither block
                     ▼
                    api
                     ▼
                  client
```

## Static map-data flow

```text
Map sources (Overpass / OpenStreetMap)
    ▼
 mapdata     roads -> RoadSegment[] -> build_graph -> RoadGraph + node index
    │
    ├──▶ storage        persisted, and read back when the source is down
    ├──▶ routing        the graph, and the coordinate -> node id snap
    ├──▶ traffic        road_id -> edge_ids
    ├──▶ roadstate      road_id -> edge_ids
    └──▶ api            GET /api/v1/mapdata/roads, /mapdata/graph
```

## Persistence connections

```text
mapdata   → storage      the "roads" collection, and the source cache
roadstate → storage      the "road_conditions" collection, with validity windows
ingest    → storage      where a raw or normalized record must be kept
api       → storage      only to choose and open the backend, and migrate
```

## Direction rules

- `api` may consume documented outputs from every block. It is the only module
  set that imports every subsystem, and `api/composition.py` is the only module
  that does so at once.
- `mapdata`, `traffic` and `roadstate` may import `routing`'s **types**.
  `routing` imports none of them. The direction is deliberate and is the
  opposite of what it looks like from the data flow: they are adapters, routing
  is the port.
- `roadstate` and `traffic` may consume documented outputs from `ingest`.
- `ingest`, `roadstate` and `mapdata` may use documented storage interfaces.
- `storage` must not depend on domain blocks.
- `domain` depends on nothing, and nothing may ever be added to it that does.
- No circular block dependency is allowed.
- External providers must not be called directly from domain blocks. `ingest`
  is the only door in, and `mapdata` is the only reader of a map source.

## The two pairs that must never be merged

**A jam and a closure.** Traffic reaches routing as a cost multiplier;
road state reaches it as a cost multiplier *and* as a constraint. A closure
expressed as a very large number lets the search use a closed road when nothing
else connects, with an unusually long ETA as the only symptom. Blocking goes
through `blocked_edges`, always.

**A road id and an edge id.** Traffic and road state are keyed by *road*
(`osm:way/12345`); routing is keyed by *edge* (`osm:way/12345#2`). The bridge is
`mapdata.RoadGraphProvider.road_edges(area)` and it must be **asked for**, never
reconstructed. Guessing the `way#index` convention works today and breaks
silently the first time splitting changes.

## Connector rule

Every cross-block connection is represented by the relevant blocks'
`connector.md` files, which live beside their code at
`server/<block>/connector.md`. This document describes the system-level
relationship; each block's connector file describes the block-local interface
and how that block's own files work together.

`server/FLOW.md` is the third view: what happens, in order, through named
files, for each kind of request.
