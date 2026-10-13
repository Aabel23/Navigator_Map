# Server Flow — how the blocks and their files work together

`ARCHITECTURE.md` says what each block *is*. Each block's `connector.md` says
what crosses its boundary. This document is the third view: **what actually
happens, in order, through named files**, when the server starts and when each
kind of request arrives.

Read it when you need to know where a change lands.

---

## 1. The blocks, at a glance

| Block | One sentence | Depends on |
|---|---|---|
| `domain` | the geographic vocabulary and the proximity index | nothing |
| `config` | every deployment decision, read once from the environment | nothing |
| `observability` | log shape, log destination, what "working" means | nothing |
| `storage` | how bytes are kept and found again | `domain` |
| `routing` | path search, costs, constraints, manoeuvres | `domain` |
| `mapdata` | the road network and the routable graph built from it | `domain`, `storage`, `routing` |
| `traffic` | what a speed means and what it costs a route | `domain`, `ingest`, `routing` |
| `roadstate` | what is closed, flooded, under works — and for how long | `domain`, `storage`, `ingest`, `routing` |
| `ingest` | the only door outside data comes through | `domain`, `storage` |
| `api` | HTTP, serialisation, error mapping, composition | all of them |

`routing` sits **below** `mapdata`, `traffic` and `roadstate` rather than
beside them: each of those three builds or feeds something routing consumes,
so each imports routing's types and routing imports none of them.

```text
                              api
                               │
                    ┌──────────┼──────────┬───────────┐
                    ▼          ▼          ▼           ▼
                mapdata    traffic    roadstate    ingest
                    │          │          │           │
                    └────┬─────┴────┬─────┴─────┬─────┘
                         ▼          ▼           ▼
                     routing     storage   observability
                         │          │           │
                         └──────────┴───────────┘
                                    ▼
                                 domain
```

---

## 2. Startup

```text
main.py
  │
  ▼  config/settings.py        Settings.from_env()
  │      the only reader of os.environ. A bad value fails here, naming it
  │
  ▼  observability/logging.py  configure(level, as_json)
  │
  ▼  api/composition.py        build_services(settings)
  │      the only module that imports every subsystem
  │
  │   ┌─ storage/sqlite/backend.py    SqliteStorage(path).migrate()
  │   │      applies storage/sqlite/schema.sql
  │   │
  │   ├─ mapdata/roads/overpass.py    OverpassRoadSource(cache=backend.cache)
  │   ├─ mapdata/store.py             PersistingRoadNetwork(source, RoadStore(docs))
  │   ├─ mapdata/graph/provider.py    RoadGraphProvider(network)
  │   │
  │   ├─ ingest/external_sources/digitraffic.py   DigitrafficProvider()      [if enabled]
  │   ├─ ingest/external_sources/simulated.py     SimulatedTrafficProvider() [if enabled]
  │   ├─ ingest/traffic/collector.py              TrafficCollector(providers, fallback)
  │   │
  │   ├─ traffic/state/store.py       TrafficState()
  │   ├─ traffic/state/provider.py    TrafficCostSource(state, graphs)
  │   │
  │   ├─ roadstate/store.py           RoadStateStore(backend.documents)
  │   ├─ roadstate/provider.py        RoadStateSource(store, graphs)
  │   │
  │   ├─ routing/service.py           RoutingService(graphs, traffic, roadstate)
  │   └─ observability/health.py      HealthRegistry, one check per subsystem
  │
  ▼  api/app.py                create_app(services)
  │      registers routes/*, middleware/errors.py, middleware/logging.py
  ▼
serving on /api/v1
```

`python main.py --check` runs exactly this and exits, so a configuration
mistake surfaces at startup rather than as the first request failing.

Every provider above is passed **in**, never constructed where it is used.
That is what lets `create_app(services=...)` run the real HTTP stack against a
fake outside world by construction rather than by monkey-patching.

---

## 3. The central flow: `POST /api/v1/route`

This is the one request the whole server exists to answer, and it touches
every block.

```text
   client: {"origin": [lon, lat], "destination": [lon, lat]}
      │
      ▼  api/middleware/logging.py         one line in
      ▼  api/routes/route.py               three statements, no decisions
      ▼  api/schemas/route.py              body -> RouteQuery (validates lon/lat)
      │
      ▼  api/services.py                   sequences, does not compute
      │      may first trigger a lazy traffic refresh for this area (§4)
      │
      ▼  routing/service.py  RoutingService.route(RouteQuery)
      │
      │  ┌── 1. area = BBox.covering(endpoints, pad)            domain/geo.py
      │  │
      │  ├── 2. MapGraphProvider.graph_for(area)
      │  │        mapdata/graph/provider.py
      │  │          └─ mapdata/store.py  PersistingRoadNetwork.roads(area)
      │  │               ├─ mapdata/roads/overpass.py  -> mapdata/http.py -> Overpass
      │  │               │    (storage/files.py or storage cache short-circuits)
      │  │               ├─ saved via storage/interface/store.py -> sqlite/backend.py
      │  │               └─ on failure: StoredRoadNetwork, what was saved before
      │  │          └─ mapdata/graph/build.py  build_graph(RoadSegment[])
      │  │               ways -> junctions -> edges; ids; lat-first flip
      │  │          => GraphView: .graph, .nearest_node(), .road_edges()
      │  │
      │  ├── 3. nodes = view.nearest_node(point) for each endpoint
      │  │        mapdata/graph/provider.py over domain/spatial.py SpatialIndex
      │  │        -- coordinates become node ids HERE, never inside routing
      │  │
      │  ├── 4. costs:
      │  │        traffic/state/provider.py    TrafficCostSource.multipliers_for(area)
      │  │          traffic/state/store.py     the current picture, expiring
      │  │          traffic/processing/cost.py ratio -> multiplier, capped at 8x
      │  │          mapdata road_edges(area)   road_id -> edge_ids
      │  │        roadstate/provider.py        RoadStateSource.multipliers_for(area)
      │  │        combine: the WORSE of the two per edge, never the product
      │  │        => routing/costs.py DynamicCostModel(StaticCostModel, multipliers)
      │  │
      │  └── 5. blocked = roadstate/provider.py  RoadStateSource.blocked_edges(area)
      │           => routing/constraints.py RouteConstraints(blocked_edges=...)
      │           a closure is a CONSTRAINT, never a cost
      │
      ▼  RouteRequest  (node ids, a loaded graph, a cost model, constraints)
      │
      ▼  routing/router.py     validates; picks cost model and heuristic
      ▼  routing/search.py     A* over (via_edge, node) states
      │      routing/heuristics.py supplies the admissible bound
      │      routing/graph.py answers adjacency and turn legality
      ▼  routing/assemble.py   path -> geometry, merged manoeuvre steps, distance, time
      ▼  Route
      │
      ▼  api/schemas/route.py  -> JSON: lon-first, duration_s from travel_time,
      │                           total_cost dropped
      ▼  api/middleware/errors.py   anything raised became a status, here only
      ▼
   {"status": "ok", "distance_m": ..., "duration_s": ..., "geometry": ..., "steps": [...]}
```

### Three things this flow is shaped to prevent

**Coordinates reaching the engine.** `RouteQuery` (coordinates) and
`RouteRequest` (node ids) are two contracts on purpose, and `routing/service.py`
is the only converter. Snapping lives in `mapdata` because the nodes do.

**A closure priced as a cost.** Step 5 is a separate path from step 4. A very
large multiplier lets the search "use" a closed road when nothing else
connects, and the only symptom is an unusually long ETA. A constraint cannot
be traded off, so the honest answer — no route — comes back instead.

**A multiplier below 1.0.** It makes the A\* heuristic inadmissible, which does
not fail; it silently returns a worse route. Both providers guarantee ≥ 1.0.

---

## 4. Traffic: from a sensor to a cost

Refresh is **lazy, debounced per area, and triggered by a route request** for
that area — not by a background worker. A worker is a second thing to deploy
and supervise, and it would poll areas nobody is looking at.

```text
  api/services.py  refresh(area)         (or POST /api/v1/ingest/refresh)
      │
      ▼  ingest/traffic/collector.py  TrafficCollector.collect(area)
      │     coverage routing: a Finnish feed asked about Vietnam says "not mine"
      │     measured before modelled: the fallback only fills genuine gaps
      │     failures isolated and returned BY NAME, not logged and forgotten
      │
      │     ├─ ingest/external_sources/digitraffic.py -> ingest/http.py -> Fintraffic
      │     │     gzip mandatory (406 without it); free-flow from the per-station doc
      │     └─ ingest/external_sources/simulated.py
      │           deterministic model over the roads mapdata handed in
      │           source == "simulated" on every record it makes
      ▼
  ingest.Observations          speeds, free-flow references, ratios.
      │                        NO LEVEL -- that judgement is not ingest's
      │
      ▼  traffic/processing/attach.py    attach(observations, roads)
      │     a record naming its road_id wins outright
      │     a point snaps to the nearest road within 120 m; past that, no road
      ▼
  traffic.RoadSpeed(road_id, speed, free_flow, source, confidence, at)
      │
      ▼  traffic/state/store.py  TrafficState.apply()
      │     ranked, never averaged: measured > confidence > recency
      │     entries expire after 10 minutes
      ▼
  the current picture
      │
      ├──▶ traffic/models.py TrafficSnapshot ──▶ api/routes/traffic.py
      │       traffic/levels.py classifies each ratio into a TrafficLevel
      │       GET /api/v1/traffic?bbox=       (with provenance, simulated flag)
      │       GET /api/v1/traffic/levels      (the table itself, so no renderer
      │                                        ships its own idea of "heavy")
      │
      ▼  traffic/state/provider.py  TrafficCostSource.multipliers_for(area)
      │     traffic/processing/cost.py    ratio -> multiplier, capped
      │     mapdata road_edges(area)      road_id -> edge_ids
      ▼
  {edge_id: multiplier}  ──▶ routing/costs.py DynamicCostModel   (step 4 above)
```

**Road ids versus edge ids.** Traffic is keyed by *road* (`osm:way/12345`) —
what a sensor and a driver both recognise. Routing is keyed by *edge*
(`osm:way/12345#2`) — one stretch between two junctions. `TrafficCostSource`
bridges them by **asking** `mapdata` for `road_edges(area)`. Reconstructing the
`way#index` convention would work today and break silently the first time
splitting changed, with the only symptom being routes that ignore traffic.

---

## 5. Road conditions: from a report to a blocked edge

```text
  POST /api/v1/ingest/reports        (or an incident inside a feed's batch)
      │
      ▼  api/routes/ingest.py  ->  api/services.py
      │
      ▼  ingest/incidents/reports.py  normalize_report()
      │     shape only: id, geometry, kind hint, severity, window, provenance
      │     NO condition kind -- that judgement is not ingest's
      │
      ▼  roadstate/classify.py  classify()
      │     closures.py -> flooding.py -> construction.py -> incidents.py
      │     the order IS the policy: "flooded street closed to traffic" matches
      │     two rules, and which wins decides detour-or-slowdown
      │
      ▼  roadstate/attribute.py  attribute()
      │     geometry -> road ids, along the whole length,
      │     over domain/spatial.py against the roads mapdata published
      │
      ▼  roadstate/store.py  RoadStateStore.record()
      │     storage/interface/store.py -> storage/sqlite/backend.py
      │     collection "road_conditions", with its validity window
      │     an open-ended condition stops being believed after 6 hours
      ▼
  in force in this area, now
      │
      ▼  roadstate/provider.py  RoadStateSource
      │     mapdata road_edges(area): road_id -> edge_ids
      │
      ├──▶ blocked_edges(area)    frozenset[edge_id]     -> RouteConstraints
      │      DOES NOT DEGRADE. If the mapping cannot be read it raises, the
      │      request fails safely, and no closure is silently dropped.
      │
      └──▶ multipliers_for(area)  {edge_id: float} >= 1  -> DynamicCostModel
             DOES degrade to {}. A route priced without knowing about a works
             site is merely a worse route.
```

**Flooding blocks at 30 cm**, deliberately below where a car actually fails:
the cost of an unnecessary detour is minutes, and the cost of the other error
is the vehicle.

---

## 6. GPS probes: the cheapest traffic source

```text
  POST /api/v1/ingest/probes     [{lon, lat, speed_kph, at, ...}, ...]
      │
      ▼  api/routes/ingest.py -> api/services.py
      ▼  ingest/gps/probes.py  parse_probe()
      │     coordinates in range; speed <= 250 kph; timestamp aware, recent,
      │     not in the future; a stationary probe contributes no speed --
      │     a car park full of parked cars is not a traffic jam
      │     rejections COUNTED and RETURNED WITH REASONS
      ▼  ingest/gps/probes.py  probes_to_observations()
      ▼
  ingest.Observations  ──▶ traffic/processing/attach.py   (§4, from here on identical)
```

A client whose submissions silently vanish has no way to discover its field
names are wrong — hence the reasons in the response.

---

## 7. Where a change lands

| If you are changing… | Go to |
|---|---|
| a colour, a threshold, what "heavy" means | `traffic/levels.py` |
| what a jam costs a route | `traffic/processing/cost.py` |
| which road a measurement belongs to | `traffic/processing/attach.py` |
| which reading wins when two disagree | `traffic/state/store.py` |
| whether a report is a closure or an incident | `roadstate/classify.py` + `roadstate/kinds/` |
| when flooding blocks | `roadstate/kinds/flooding.py` |
| how a way becomes edges, or an edge id | `mapdata/graph/build.py` |
| how a coordinate becomes a node id | `mapdata/graph/provider.py` |
| which roads are fetched, and from where | `mapdata/roads/overpass.py` |
| the search itself, or the heuristic | `routing/search.py`, `routing/heuristics.py` |
| how a path becomes steps and geometry | `routing/assemble.py` |
| what a vehicle profile costs | `routing/costs.py` |
| the order subsystems are called in for a request | `routing/service.py`, `api/services.py` |
| a URL, a status code, a response field | `api/routes/`, `api/schemas/`, `api/middleware/errors.py` |
| what is wired at startup | `api/composition.py` |
| a configurable value | `config/settings.py` (add a field; nothing else) |
| the database engine or schema | `storage/sqlite/`, `storage/postgres/` |
| a new external feed | a module in `ingest/external_sources/` |

---

## 8. The rules that are enforced rather than remembered

`tests/test_dependency_rules.py` reads every production module with `ast` and
fails the build if:

- a block imports one it may not depend on (the layering is a table in that file)
- `sqlite3` appears outside `storage/sqlite/`
- `flask` appears outside `api/`
- the block import graph has a cycle
- a block has no `__all__`

So "routing does not know about the database" is a property of the repository,
not a claim in a document.

```bash
python -m pytest                          # 796 tests
python -m pytest tests/test_dependency_rules.py
python main.py --check                    # wire everything, health-check, exit
```

---

## 9. What is deliberately not in any of these flows

Naming these stops a later reader from assuming they exist.

- **A background worker.** Traffic refreshes lazily, per area, on demand.
- **Live rerouting and map matching over time.** Routing takes node ids;
  snapping a *moving* driver to the network is not built.
- **Alternative routes.** `find()` returns one.
- **A PostgreSQL adapter.** `storage/postgres/` holds the DDL and the plan, no
  code.
- **Authentication.** The API is unauthenticated.
- **A tile server.** The client fetches its own tiles; the server never sends
  a tile, a style or a sprite.
- **Live traffic for Vietnam.** No free source publishes it — the simulated
  provider fills the gap and labels every record.
