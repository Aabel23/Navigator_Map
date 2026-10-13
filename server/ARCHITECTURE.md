# Server Architecture

This describes the server as it is built, not as it might be. Every component
named here exists, and everything that does not exist is called out as absent.

---

## 1. What the server is for

The server is the navigation backend. It answers one central question — *how
should this driver get from here to there, right now* — and the four
subsidiary ones that make the answer useful: what roads are there, how fast is
traffic moving, what is closed, and what has the outside world told us
lately.

**Routing is server-side.** The client sends two coordinates and gets back a
route. It does not hold a road graph, a cost model, or a search. That is not a
performance decision; it is an ownership one. A route computed on the device
would be computed from whatever data that device happened to have, and two
clients would answer the same question differently.

The server owns: the API, routing, traffic processing, road-state processing,
map-data access, ingestion, persistence, health, observability, configuration.

The server does not own: the mobile UI, or the rendering of the map the driver
looks at. It supplies the data those need.

---

## 2. The blocks

Ten top-level modules under `server/`. `server/` is a path root, not a
package — `import routing` works with nothing but that directory on the path,
which is what keeps each block independently runnable.

| Block | Owns | Does not own |
|---|---|---|
| `domain` | the shared geographic vocabulary and proximity search | anything with a policy in it |
| `config` | every deployment decision, read once from the environment | any decision those values feed |
| `observability` | log shape, log destination, what "working" means | what is worth logging |
| `storage` | how bytes are kept and found again, and which engine does it | what any of those bytes mean |
| `routing` | path search, cost models, constraints, manoeuvres, geometry | where data comes from, what a road costs |
| `mapdata` | the road network, its persistence, the routable graph, snapping | how fast anything is moving; rendering |
| `traffic` | attaching measurements to roads, classifying, holding, pricing | fetching; closures |
| `roadstate` | closures, flooding, construction, incidents; their validity | fetching; how fast traffic moves |
| `ingest` | receiving, validating, normalising, and surviving sources | what any of it means |
| `api` | HTTP, serialisation, error mapping, and composition | any computation |

---

## 3. Dependency direction

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

`routing` sits below `mapdata`, `traffic` and `roadstate`, not beside them.
Each of the three *builds or feeds something routing consumes* — a graph, a
cost multiplier, a constraint — so each may import routing's types, and
routing imports none of them. That is the ordinary direction for an adapter
and its port, and it is what keeps the engine benchmarkable, contract-testable
and replaceable on its own.

The exact table is in `tests/test_dependency_rules.py`, which reads every
production module with `ast` and fails the build on a violation, a cycle,
`sqlite3` outside `storage/sqlite/`, or `flask` outside `api/`.

---

## 4. Routing

### Where it lives

`routing/` — 21 modules, 207 tests, contract v1.0 with its own suite at
`routing/tests/contract/test_v1.py`. The engine predates this migration and
was preserved intact; what was added is the service layer above it.

```text
routing/
├── service.py     RouteQuery -> Route.  The application-level entry point
├── providers.py   what the service needs, as three Protocols
├── router.py      validation, cost-model and heuristic choice
├── search.py      A* over (via_edge, node) states
├── assemble.py    a path -> geometry, manoeuvre steps, distance, time
├── graph.py       RoadGraph interface + InMemoryRoadGraph
├── costs.py       CostModel family, VehicleProfile, CostContext
├── constraints.py per-request avoid rules
├── models.py      Node, Edge, TurnRestriction, RouteRequest, Route
├── heuristics.py  admissible bounds (internal)
└── geometry.py    haversine, bearings, turn angles
```

### API → Routing → providers

```text
POST /api/v1/route
    │
    ▼  api/routes/route.py      parse, call, serialise. Three statements
RoutingService.route(RouteQuery)
    │
    ├── 1. area      = BBox.covering(endpoints, pad)
    ├── 2. view      = MapGraphProvider.graph_for(area)
    ├── 3. nodes     = view.nearest_node(point) for each endpoint
    ├── 4. costs     = DynamicCostModel(static, combine(traffic, roadstate))
    ├── 5. blocked   = RoadStateProvider.blocked_edges(area)  -> constraint
    │
    ▼
Router.find(RouteRequest)        node ids, a loaded graph, a cost model
    │
    ▼
Route                            geometry, steps, distance, travel_time
    │
    ▼  api/schemas/route.py      -> JSON, longitude first
```

Two input contracts, on purpose. `RouteQuery` is coordinates, waypoints, a
profile, preferences — what a client actually has. `RouteRequest` is node ids
and a loaded graph — what the engine needs. The service is the only thing that
converts one into the other, and neither knows HTTP exists.

### The three provider protocols

`routing/providers.py` states what routing needs in terms of what it needs,
not of who supplies it. All three are `typing.Protocol`, so `mapdata`,
`traffic` and `roadstate` satisfy them structurally and routing imports none
of them.

| Protocol | Method | Returns | Satisfied by |
|---|---|---|---|
| `MapGraphProvider` | `graph_for(area)` | a `GraphView`: `.graph`, `.nearest_node()` | `mapdata.RoadGraphProvider` |
| `TrafficCostProvider` | `multipliers_for(area)` | `{edge_id: float}`, each ≥ 1.0 | `traffic.TrafficCostSource` |
| `RoadStateProvider` | `blocked_edges(area)` | `frozenset[edge_id]` | `roadstate.RoadStateSource` |
| | `multipliers_for(area)` | `{edge_id: float}`, each ≥ 1.0 | |

This is also the answer to "the engine must not know whether the data came
from SQLite, PostgreSQL, Redis, HTTP, a file or memory": none of that is
expressible in any of those signatures.

### Cost model

Cost is not baked into the graph. An `Edge` stores facts — distance, speed,
class, name, shape; a `CostModel` decides what those are worth for this
vehicle at this moment. `StaticCostModel` covers `fastest` and `shortest`;
`DynamicCostModel` wraps it with a per-edge multiplier map.

Live conditions reach the search as that map. Two rules make it safe:

- **Never below 1.0.** A condition may slow a road, never speed it past
  free flow. Below 1.0 makes the A* heuristic inadmissible, which does not
  fail — it silently returns a worse route.
- **Capped.** Standstill is capped at 8× (traffic) and 12× (combined). A jam
  is not a closure.

Where traffic and road state both report on an edge, the **worse** value wins
rather than the product. A flooded road is slow *because* it is flooded;
multiplying charges the driver twice for one event observed twice.

### Waypoints

Each leg is searched separately and the legs are joined — the duplicated
junction dropped from `nodes`, the duplicated coordinate from `geometry`,
distances and times summed. Steps are left as they are: each leg ends with an
arrival and the next begins with a departure, which is what stopping at a
waypoint actually is. A one-leg trip is returned byte-identical to what the
engine produced, because the contract's determinism guarantee is stated about
that object.

---

## 5. Traffic

### Where it lives

`traffic/` — processing and state only. It does **no I/O at all**.

```text
traffic/
├── levels.py             ratio -> level, thresholds, colours
├── models.py             RoadSpeed, TrafficSnapshot
├── processing/
│   ├── attach.py         measurement -> published road
│   └── cost.py           ratio -> multiplier
└── state/
    ├── store.py          TrafficState: the current picture, expiring
    └── provider.py       TrafficCostSource: road ids -> edge ids
```

### How it feeds routing

```text
providers ──▶ ingest ──▶ Observations
                             │
                             ▼  traffic.processing.attach
                        RoadSpeed  (road_id, speed, free_flow, source, confidence)
                             │
                             ▼  traffic.state.TrafficState
                        the current picture, expiring after 10 minutes
                             │
                             ▼  traffic.state.TrafficCostSource
                        {edge_id: multiplier}
                             │
                             ▼
                        routing.DynamicCostModel
```

Traffic is not hidden inside routing. Routing *consumes* traffic information;
traffic *computes* it. The seam is a plain mapping and neither block imports
the other.

### The judgements this block makes

Three, and all of them are judgements rather than lookups, which is why none
of them is in `ingest`:

1. **Which road a measurement is about.** A record naming its `road_id` wins.
   A point snaps to the nearest road within 120 m; past that the answer is
   "no road", because a motorway sensor attributed to a side street invents a
   jam on a street that is fine.
2. **Which reading to believe when two disagree.** Measured beats modelled,
   then confidence, then recency — ranked, never averaged. An average of a
   sensor and a model is a number with no honest source to put on it.
3. **What a ratio means.** The level table in `levels.py`, in one place, for
   every provider at once. It is *served* at `/api/v1/traffic/levels` so no
   renderer ships its own opinion of what "heavy" looks like.

### Road ids and edge ids

Traffic is keyed by *road* (`osm:way/12345`) — what a sensor and a driver both
recognise. Routing is keyed by *edge* (`osm:way/12345#2`) — one stretch
between two junctions. `TrafficCostSource` bridges them by asking map data for
`road_edges(area)` rather than reconstructing the `way#index` convention.
Guessing would work today and break silently the first time splitting changed,
with the only symptom being routes that ignore traffic.

---

## 6. MapData

### What the server-side block contains

`mapdata/` owns the road network the server computes with, and the routable
graph built from it.

```text
sources (Overpass) ──▶ RoadSegment[]  ──▶ build_graph ──▶ RoadGraph + node index
        │                     │                                 │
        │                     ▼                                 ▼
        │              storage (documents)               GraphView
        │                                                  .graph
        └── PersistingRoadNetwork: fetch, save, fall back    .nearest_node()
                                                             .road_edges()
```

A `RoadSegment` carries geometry, road class, a free-flow reference, a name
and a one-way flag. Nothing about cost, traffic or conditions.

### Ways are not edges

The most consequential thing this block does. OSM publishes a *way*: one line
that may run two kilometres through nine intersections. A router needs an
*edge*: a stretch between two junctions with nothing to turn off onto in
between. `graph/build.py`:

1. finds the junctions — any coordinate two ways share, plus every way's own
   endpoints;
2. splits each way there, each piece keeping its own slice of the polyline so
   a route is drawable without the graph;
3. names everything stably — a node id from its rounded coordinate, an edge id
   from `way#index`, so a closure recorded yesterday still names a real edge
   today.

Handing a way straight to the router makes every junction along it invisible,
and the route sails past the turn it needed. That is not a crash and no test
that merely checks a route came back would catch it — hence
`mapdata/tests/test_graph.py`.

### Snapping

Coordinates become node ids here, over a `domain.SpatialIndex` of the built
graph's junctions. Routing's contract is explicit that this is not routing's
job; the nodes live here, so the snapping does too, and doing it in two places
would give the system two ways to disagree about where the driver is.

### Coordinate order

Map data is longitude-first (GeoJSON, which is what every free source
publishes). Routing is latitude-first (its contract says so). The single
conversion is in `mapdata/graph/build.py` and nowhere else.

### What remains on the client

Rendering. The client fetches its own vector tiles and draws the basemap, the
route line and the UI. The server never sends a tile, a style or a sprite.
"MapData" and "the map the driver looks at" are different things that share a
word.

`GET /api/v1/mapdata/roads` exists for what a tile cannot give a client: the
*server's* view of the network, so a client can highlight one segment, put a
closure on the right street, or explain why a route went the way it did.

---

## 7. RoadState

### What it represents

Something temporarily true about a road, with a validity window: a closure,
flooding, construction, an incident, a restriction, a hazard.

The distinction from traffic is the block's reason to exist. Traffic is a
measurement that decays — true for minutes, replaced by the next reading. A
condition *ends* rather than decaying, and until it does it is as true at 3
a.m. as at rush hour.

### How a condition reaches routing

```text
report (operator, client, or a feed's incident)
    │
    ▼  ingest.incidents.normalize_report      shape only; no judgement
    │
    ▼  roadstate.classify                     closure -> flooding -> construction -> incident
    │
    ▼  roadstate.attribute                    geometry -> road ids, along the whole length
    │
    ▼  roadstate.RoadStateStore               persisted, with its validity window
    │
    ├──▶ blocking?  ──▶ blocked_edges(area) ──▶ RouteConstraints.blocked_edges
    └──▶ otherwise   ──▶ multipliers_for(area) ──▶ DynamicCostModel
```

### The two paths, and why they must stay two

A closure is a **constraint**, never a cost. Expressing it as a very large
number is the classic navigation defect: when nothing else connects the two
ends of a trip, the search happily "uses" the expensive road and returns a
route down a flooded street, with an unusually long ETA as the only symptom. A
constraint cannot be traded off, so the honest answer — no route — is what
comes back.

Everything else is a cost. Roadworks, a crash, shallow water: worse, not gone.
A driver would rather crawl past a works site than be sent five kilometres
around it.

`RoadStateSource.blocked_edges` therefore does **not** degrade on a failure
reading the road-to-edge mapping — it raises, the routing service turns that
into an error, and the request fails safely. `multipliers_for` does degrade,
because a route priced without knowing about a works site is merely a worse
route.

### Classification order

`closure → flooding → construction → incident`, and it is not alphabetical.
Reports overlap: "flooded street closed to traffic" matches two rules, and
which wins decides whether a driver is routed around it or merely slowed.
Closure first because it is the strongest claim in the system and the most
expensive to get wrong permissively. Incident last, as the catch-all that
never declines.

### Flooding

The condition this project's home city produces most, and where the blocking
threshold matters most. Standing water at or past **30 cm** blocks; the
threshold is deliberately below where a car actually fails, because the cost
of an unnecessary detour is minutes and the cost of the other error is the
vehicle. Where no depth is published — the common case — severity falls back
to what the source declared and only an explicitly impassable report blocks.

### Ageing out

A condition with an end time is honoured as given. One without — several free
feeds publish an incident and withdraw it once it clears — stops being
believed after six hours. A crash nobody withdrew must not divert traffic for
a week.

---

## 8. Ingest

### The flow in

```text
  external feed          GPS probe            incident report
  (Digitraffic,          (client)             (operator, client)
   simulated)                │                       │
       │                     │                       │
       ▼                     ▼                       ▼
  TrafficCollector      gps.parse_probe      incidents.normalize_report
   coverage routing      strict validation     shape validation
   measured > modelled   implausible dropped   provenance stamped
   failures isolated     stationary excluded
       │                     │                       │
       └──────────┬──────────┘                       │
                  ▼                                  ▼
             Observations                   normalized report (a mapping)
                  │                                  │
                  ▼                                  ▼
          traffic.TrafficState               roadstate.classify
```

### What ingest does and does not do

It receives, validates, normalises, timestamps, attributes a source, and
survives a feed that is down. It makes **no judgement about meaning**: records
carry no traffic level, reports carry no condition kind. What leaves is what
the source *said* — a speed, a free-flow reference, a title, a window. The
interpretation happens one block downstream, in one place, for every provider
at once. That is what lets a second provider be added without a second opinion
arriving with it.

### The collector's three policies

- **Coverage routing.** A provider declaring a region is only asked about
  boxes inside it. A Finnish sensor network asked about Ho Chi Minh City says
  "not mine" rather than returning an empty result that reads like a
  free-flowing city.
- **Measured before modelled.** The fallback is consulted only where no
  measuring provider produced anything. The simulated provider never competes
  with a sensor.
- **A failure is not fatal.** A provider that raises is dropped from that
  refresh and recorded *by name*, and the failures are returned rather than
  logged and forgotten. A map that quietly shows an empty city because a feed
  timed out is worse than one that says so.

### GPS probes

The cheapest traffic source in existence, and the most easily turned into
nonsense. The gate is strict: coordinates in range, speeds plausible
(≤ 250 kph), timestamps aware, recent, and not in the future, and a
stationary probe contributes no speed — a car park full of parked cars is not
a traffic jam. Rejections are counted and returned with reasons, because a
client whose submissions silently vanish has no way to discover its field
names are wrong.

### When the refresh happens

Lazily, debounced per area, triggered by a route request for that area — not
by a background worker. A worker is a second thing to deploy, supervise and
shut down cleanly, and it would poll areas nobody is looking at. The area that
needs to be fresh is the one being routed across, and that is known at the
moment a route is requested. `POST /api/v1/ingest/refresh` exists for an
operator who wants to warm a city before rush hour without faking a route.

---

## 9. Storage

### The abstraction

```text
     routing   mapdata   traffic   roadstate   ingest   api
                            │
                            ▼
                   storage.StorageBackend
                    .documents  -> DocumentStore
                    .cache      -> Cache
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        InMemoryStorage  SqliteStorage  (PostgresStorage)
                                          not written
```

Nothing above `storage/` names SQLite, a table, or SQL. The backend is chosen
once, in `api/composition.py`, from configuration.

### One row shape

A stored document is an opaque payload with three things the server can query
on: which collection it belongs to, which piece of the world it covers, and
when it was true.

```python
StoredDocument(collection, key, west, south, east, north,
               payload, recorded_at, valid_from, valid_to)
```

Storage is not allowed to know what a road, an observation or a closure *is*.
A `road_class` column would be a piece of map-data policy living in the
database layer, and the next change to that dataclass would become a schema
migration. Each domain block converts its own types to and from a payload,
next to the type it converts. What storage *does* know is the two axes
everything queries on — an area and a moment — because those are indexable and
a JSON blob is not.

Collections in use: `roads`, `observations`, `road_conditions`.

### SQLite today

`storage/sqlite/` is the only module in the server that imports `sqlite3`, and
`tests/test_dependency_rules.py` fails the build if that changes. Three engine
decisions:

- timestamps are ISO-8601 text, always UTC, always aware — enforced at the
  `StoredDocument` boundary, because SQLite has no instant type;
- payloads are JSON text, never read by the block;
- one connection with `check_same_thread=False` behind a lock, because a Flask
  dev server serves on several threads and SQLite tolerates serialised access.

### PostgreSQL/PostGIS tomorrow

`storage/postgres/schema.sql` is the target DDL; `storage/postgres/MIGRATION.md`
is the plan. **No adapter is written**, because nothing in the project
currently requires one, and adding infrastructure without a requirement is
what the lock forbids.

What differs: four indexed `REAL` columns become one `GEOMETRY(POLYGON, 4326)`
with a GiST index; ISO text becomes `TIMESTAMPTZ`; JSON text becomes `JSONB`;
the single locked connection becomes a pool. The upsert spelling is already
the PostgreSQL one — SQLite adopted it — so the write path transfers almost
verbatim.

What does not differ: the `DocumentStore` interface, and therefore every line
of routing, traffic, road-state, map-data and API code.

The migration is one file plus one entry in `storage/tests/test_conformance.py`,
which is parameterised over backends and currently runs 78 tests against three
configurations — in-memory, a SQLite file, and a SQLite memory database. That
suite is what makes "replaceable" a demonstrated property rather than a design
intention: when the in-memory cache accepted a payload the SQLite one refused,
the suite said so, and the in-memory backend was corrected rather than the
test relaxed.

---

## 10. The API boundary

A handler parses, calls one application service, and serialises. `api/routes/route.py`
is three statements, and the way to keep it that way is to be suspicious of
any line added to it that is not parsing or serialising.

Layers:

| | |
|---|---|
| `api/routes/` | speaks HTTP. No loops over domain objects, no decisions |
| `api/services.py` | sequences subsystems. Knows *that* a refresh means collect-then-attach-then-classify, not *how* any of them work |
| subsystems | compute. Know nothing about the two layers above |

### What is not published

`Route.total_cost` — it is what the search minimised, possibly
penalty-weighted, and a client that found it in the response would eventually
show it to someone as a duration. The ETA is `duration_s`, from
`Route.travel_time`, which is real seconds by construction.

Internal geometry order — routing stores latitude-first; the API publishes
GeoJSON longitude-first, so no client has to remember to flip it.

Database structures, internal classes, and the graph's contents. Stable ids
(node, edge, road, condition) *are* published: a client genuinely needs them,
and they are part of the contract rather than a leak.

### Error mapping

One handler, in `api/middleware/errors.py`, and one rule: **the status says
whose problem it is.**

| Situation | Status | Why |
|---|---|---|
| malformed request, unknown profile | 400 | retrying unchanged will not help |
| endpoint not near any road | 400 | moving the pin will help |
| nothing legal connects the endpoints | 404 | a successful computation whose answer is "none" |
| upstream unreadable | 502 | their problem, reported honestly |
| upstream unavailable, storage down | 503 | temporary, retry later |
| anything unexpected | 500 | logged with a traceback; the body says nothing about the internals |

A 5xx body never carries the exception message. A stack trace in a response is
a gift to the wrong reader.

---

## 11. Testing

```bash
python -m pytest              # 796 tests
```

| Suite | Count | What it covers |
|---|---|---|
| `routing/tests` | 207 | the engine, its contract (v1.0), and the service over mock providers |
| `tests/test_dependency_rules.py` | 280 | the architecture, read off the source with `ast` |
| `storage/tests` | 78 | one conformance suite, three backend configurations |
| `api/tests` | 36 | the real HTTP stack, fake outside world |
| `traffic/tests` | 35 | attaching, ranking, expiry, pricing |
| `roadstate/tests` | 34 | classification, windows, the constraint/cost split |
| `mapdata/tests` | 28 | way-splitting, snapping, persistence, the offline fallback |
| `ingest/tests` | 27 | refusal, and the collector's three policies |
| `domain/tests`, `config/tests`, `observability/tests` | 54 | the shared vocabulary and the edges |
| `tests/test_integration.py` | 17 | the seams: real storage, real graph, real engine |

Nothing in the suite touches the network or the clock. Traffic feeds and the
road source are the only things faked, and they are faked by construction
(`create_app(services=...)`) rather than by monkey-patching — which is why
composition is a separate module from the app factory.

---

## 12. Startup and deployment

```bash
python main.py --check    # wire everything, run the health checks, exit 0 or 1
python main.py            # development server
```

`--check` builds every subsystem exactly as a real start would — opens the
database, runs the migration, wires the providers, runs the health checks —
and exits. A configuration mistake surfaces there rather than as the first
request failing.

For production, hand `api.create_app()` to a WSGI server. Flask's own server
is single-process and not meant for it; `main.py` says so rather than leaving
it to be discovered.

Health has three endpoints and the distinction between the first two matters:
`/health` is alive and checks nothing; `/health/ready` runs every registered
check and returns 503 when a critical one fails; `/health/info` reports what
the server was composed with. Readiness reports *degraded* separately from
*not ready* — a missing traffic feed is degraded, routes still compute on
free-flow speeds, and treating it as a hard failure would take a serving
process out of rotation over a feature that gracefully does without.

---

## 13. Known limits

Stated rather than smoothed over.

- **No live traffic for Vietnam.** No free source publishes it. The simulated
  provider fills the gap and labels every record; `simulated: true` on the
  traffic response means exactly that.
- **A* is roughly a wash in `fastest` mode.** The bound divides by the graph's
  single fastest speed, which is loose where speeds vary. It always settles
  fewer states and it is reliably faster in `shortest` mode. Tightening it
  needs per-region speed bounds or landmarks. See `routing/contract.md`.
- **No PostgreSQL adapter.** Documented and planned, not written.
- **No background worker.** Traffic refreshes lazily, per area, on demand.
- **One route, no alternatives.** `find()` returns one.
- **Proximity is a grid, not a k-d tree**, and a polyline is indexed as
  densified points rather than segments — error bounded at 25 m, which is
  inside every snap radius here and inside the position error of the readings.
- **The road-source fallback is by area, not by age.** If Overpass is down and
  an area was never imported, the answer is no roads rather than a stale graph
  from a neighbouring area.
