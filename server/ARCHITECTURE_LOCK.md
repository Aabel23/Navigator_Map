# Server Architecture Lock

```text
STATUS          LOCKED
LOCKED          2026-09-13
SCOPE           server/ only. The client is out of scope for this document.
SUPERSEDES      the pre-migration layout preserved at .backup/pre-newsystem/
VERIFIED BY     python -m pytest   ->  796 passed
                python main.py --check  ->  exit 0, against live OpenStreetMap
```

This document exists so that a later agent does not have to re-derive the
boundaries, and does not undo them by accident. It is not a description — that
is `ARCHITECTURE.md`. It is the list of things that are settled.

---

## 1. Ownership

```text
SERVER OWNS ROUTING
SERVER OWNS TRAFFIC PROCESSING
SERVER OWNS ROAD STATE
SERVER OWNS SERVER-SIDE MAP DATA ACCESS
SERVER OWNS INGEST
SERVER OWNS STORAGE
MOBILE OWNS MAP RENDERING / UI
```

Expanded, because each line has been got wrong somewhere before:

**Routing is server-side.** The client sends two coordinates and receives a
route. It holds no road graph, no cost model and no search. A route computed
on the device would be computed from whatever data that device happened to
have, and two clients would answer the same question differently.

**Traffic processing is server-side.** Attaching a measurement to a road,
deciding which of two readings to believe, and deciding what a speed ratio
means are judgements. They are made once, on the server, for every provider at
once.

**Road state is server-side, and separate from traffic.** A jam is slower; a
closure is impassable. They reach routing by different mechanisms and must
keep doing so.

**Map data is server-side; map *rendering* is not.** The server owns road
geometry, classes, speed limits, connectivity and the routable graph. The
client owns tiles, styles, sprites and everything the driver looks at. These
are different things that share a word.

**Ingest is the only door.** Nothing enters the server's domain state without
passing validation and normalisation there.

**Storage is behind an interface.** Choosing an engine is a configuration
decision made in one file.

---

## 2. The boundaries, as they now stand

| Block | Path | Public surface | Tests |
|---|---|---|---|
| domain | `server/domain/` | `domain/__init__.py` | 24 |
| config | `server/config/` | `config/__init__.py` | 20 |
| observability | `server/observability/` | `observability/__init__.py` | 10 |
| storage | `server/storage/` | `storage/__init__.py` | 78 |
| routing | `server/routing/` | `routing/__init__.py`, contract v1.0 | 207 |
| mapdata | `server/mapdata/` | `mapdata/__init__.py` | 28 |
| traffic | `server/traffic/` | `traffic/__init__.py` | 35 |
| roadstate | `server/roadstate/` | `roadstate/__init__.py` | 34 |
| ingest | `server/ingest/` | `ingest/__init__.py` | 27 |
| api | `server/api/` | `api/__init__.py` | 36 |
| cross-subsystem | `server/tests/` | — | 297 |

`server/` is a path root, not a package. There is no `server/__init__.py`, and
adding one would make every block a submodule of one package and break the
property that `import routing` works with nothing but that directory on the
path.

---

## 3. The contracts between subsystems

Each is a `typing.Protocol` or a plain mapping. No pair of domain blocks
imports each other.

| Contract | Declared in | Input | Output | Errors | Provider | Consumer |
|---|---|---|---|---|---|---|
| `MapGraphProvider` | `routing/providers.py` | `domain.BBox` | `GraphView` (`.graph`, `.nearest_node`) | `MapDataError` | `mapdata.RoadGraphProvider` | `routing.RoutingService` |
| `TrafficCostProvider` | `routing/providers.py` | `domain.BBox` | `{edge_id: float}`, each ≥ 1.0 | none; degrades to `{}` | `traffic.TrafficCostSource` | `routing.RoutingService` |
| `RoadStateProvider.blocked_edges` | `routing/providers.py` | `domain.BBox` | `frozenset[edge_id]` | propagates; fails the request | `roadstate.RoadStateSource` | `routing.RoutingService` |
| `RoadStateProvider.multipliers_for` | `routing/providers.py` | `domain.BBox` | `{edge_id: float}`, each ≥ 1.0 | none; degrades to `{}` | `roadstate.RoadStateSource` | `routing.RoutingService` |
| `RoadEdgeIndex` | `traffic/state/provider.py`, `roadstate/provider.py` | `domain.BBox` | `{road_id: (edge_id, …)}` | propagates | `mapdata.RoadGraphProvider` | traffic, roadstate |
| `RoadNetwork` | `mapdata/network.py`, `ingest/provider.py` | `domain.BBox` | `Sequence[RoadSegment]` | `MapDataError` | `mapdata` sources and stores | ingest, traffic, roadstate, api |
| `TrafficProvider` | `ingest/provider.py` | `domain.BBox` | `Observations` | `IngestError` family | `ingest.external_sources.*` | `ingest.TrafficCollector` |
| normalized report | `ingest/incidents/reports.py` | raw mapping | a mapping: id, geometry, kind, severity, window, provenance | `BadResponse` | `ingest` | `roadstate.classify` |
| `DocumentStore` | `storage/interface/store.py` | `StoredDocument`, area, instant | `StoredDocument` | `StorageError` | `storage.{memory,sqlite}` | mapdata, roadstate |
| `Cache` | `storage/interface/store.py` | key, JSON payload | payload or `None` | none; every failure is a miss | `storage.{memory,sqlite}`, `JsonFileCache` | mapdata sources |
| `RouteQuery` → `Route` | `routing/service.py` | coordinates, waypoints, profile, preferences | `Route` | `InvalidRequest`, `NoRouteFound`, `RoutingError` | `routing.RoutingService` | `api` |

Changing any row above is an architectural change, not a refactor. Every
consumer must be checked.

---

## 4. Rules for future agents

These are enforced by `server/tests/test_dependency_rules.py`, which reads
every production module with `ast`. A violation fails the build.

1. **Do not move routing into the client.** The client may display, animate,
   track position and provide navigation UI. The authoritative route is the
   server's.
2. **Do not put routing algorithms into API handlers.** A handler parses,
   calls one service, and serialises. If a change to `api/routes/` starts to
   look like an algorithm, it belongs one layer down.
3. **Do not import a database driver outside `storage/sqlite/`.** Not
   `sqlite3`, not `psycopg`, not an ORM.
4. **Do not import a web framework outside `api/`.** Every other block must
   stay importable by a script, a test or a benchmark with no framework
   installed.
5. **Do not duplicate traffic logic.** One place decides what a speed ratio
   means: `traffic/levels.py`.
6. **Do not duplicate road-state logic.** One place decides what a report is:
   `roadstate/classify.py`, in its stated order.
7. **Do not duplicate map-data ownership.** One place owns road geometry and
   the graph built from it: `mapdata/`. Nothing else may hold a second road
   network.
8. **Do not reconstruct the `way#index` edge-id convention.** Ask
   `mapdata.RoadGraphProvider.road_edges(area)`. Guessing works today and
   breaks silently the first time splitting changes.
9. **Do not silently change a public contract.** The table in §3 is the list.
10. **Do not couple a subsystem to a database.** Application code holds
    `DocumentStore`, never a connection.
11. **Do not add infrastructure without a concrete requirement.** No queue, no
    worker, no cache tier, no ORM until something needs one.
12. **Do not modify another subsystem's implementation without explicit
    scope.** Its `connector.md` is the interface; its internals are not.
13. **Do not express a closure as a cost.** Blocking goes through
    `blocked_edges`. A large multiplier lets the search use a closed road when
    nothing else connects.
14. **Do not let a multiplier fall below 1.0.** It makes the A* heuristic
    inadmissible, which does not fail — it silently returns a worse route.
15. **Do not publish `Route.total_cost`.** It may be penalty-weighted. The ETA
    is `duration_s`, from `travel_time`.
16. **Do not present modelled traffic as measured.** Records from
    `SimulatedTrafficProvider` carry `source: "simulated"` and the API reports
    it. Keep it that way.
17. **Do not propose a paid or freemium data source.** Every source in this
    project is free and keyless, by standing rule.

---

## 5. What the lock does not freeze

Internals. Any block may be reorganised, optimised or rewritten as long as its
documented contract stays compatible and its tests pass. Specifically:

- the search algorithm, its state representation, its heuristic
  (`routing/search.py`, `routing/heuristics.py`)
- how a way is split into edges (`mapdata/graph/build.py`), provided edge ids
  stay stable and `road_edges()` keeps reporting the mapping
- the proximity index (`domain/spatial.py`)
- the SQLite schema, provided `DocumentStore` is satisfied and
  `storage/tests/test_conformance.py` passes
- the level thresholds and the condition multiplier tables — these are product
  decisions and are expected to move
- which of several equal-cost routes is returned

Adding a **new** block is allowed when a genuinely new responsibility appears
that cannot belong to an existing one. Adding one to avoid touching an
existing block is not.

---

## 6. Verification behind this lock

Not claims. These were run.

```text
python -m pytest
    796 passed in 3.50s

python -m pytest tests/test_dependency_rules.py
    280 passed   -- layering, no cycles, no sqlite3 outside storage/sqlite,
                    no flask outside api, every block declares __all__

python -m pytest storage/tests
    78 passed    -- one conformance suite against three backend configurations

python -m pytest routing/tests/contract
    contract v1.0 suite passes unchanged after the migration

python main.py --check
    exit 0.  Live Overpass fetch of central District 1, Ho Chi Minh City:
    5140 road segments -> 6182 nodes, 8062 edges, 3 skipped.

POST /api/v1/route over that live graph
    4796.2 m, 423.8 s, 46 segments, turn-by-turn steps with real street names.
    With traffic disabled: 307.1 s. The difference is the modelled congestion.
```

---

## 7. What is deliberately absent

Naming these stops a later agent from assuming they exist, and from
"restoring" something that was never there.

- **A PostgreSQL adapter.** `storage/postgres/` holds the DDL and
  `MIGRATION.md`, no code. Nothing currently requires it.
- **A background worker.** Traffic refreshes lazily, per area, on demand.
- **Alternative routes.** `find()` returns one.
- **Live rerouting and map matching.** Routing takes node ids; snapping a
  moving driver to the network over time is not built.
- **Authentication.** The API is unauthenticated. Adding it is an API-layer
  change and does not touch any subsystem.
- **A tile server.** The client fetches its own tiles.
- **Live traffic for Vietnam.** No free source publishes it.
