# Navigation Server

The computation platform behind the driver app. It owns the road network, the
routing engine, the traffic picture, the state of the roads, everything coming
in from outside, and everything kept on disk. The client draws maps and
follows a route; it does not decide what the route is.

```text
                         MOBILE APP
                             │  HTTPS / JSON
                             ▼
                    ┌──────────────────┐
                    │    SERVER API    │   api/
                    └────────┬─────────┘
                             │
                ┌────────────┼────────────┐
                ▼            ▼            ▼
         ┌───────────┐ ┌───────────┐ ┌───────────┐
         │  ROUTING  │ │  MAPDATA  │ │ ROADSTATE │
         └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
               │             │             │
               └─────────────┼─────────────┘
                             │
                         ┌───▼────┐
                         │TRAFFIC │
                         └───┬────┘
                             ▼
                         DATA LAYER
                   ┌─────────┴─────────┐
                   ▼                   ▼
                STORAGE              INGEST
                   │                   ▲
                   ▼                   │
             SQLite / (Postgres)   External sources
```

`ARCHITECTURE.md` is the full picture — what each block owns, the contracts
between them, the dependency rules, and the database strategy.
`ARCHITECTURE_LOCK.md` is what a future agent must not undo.

## Running it

```bash
pip install -r requirements.txt

python main.py --check          # wire everything, run health checks, exit
python main.py                  # development server on 127.0.0.1:8000
python -m pytest                # 815 tests
```

A fresh checkout with no configuration starts: it fetches central District 1,
Ho Chi Minh City from Overpass, builds a routable graph, models traffic over
it, and answers a route request. Every data source is free and keyless.

```bash
curl -s localhost:8000/api/v1/route -H 'Content-Type: application/json' -d '{
  "origin":      [106.6985, 10.7770],
  "destination": [106.7180, 10.7730]
}'
```

```json
{ "status": "ok", "distance_m": 4796.2, "duration_s": 423.8,
  "geometry": { "type": "LineString", "coordinates": [[106.6985, 10.777], ...] },
  "steps": [ { "maneuver": "depart", "name": "Nam Kỳ Khởi Nghĩa", "distance_m": 159.0 },
             { "maneuver": "left",   "name": "Lý Tự Trọng",       "distance_m": 322.0 }, ... ] }
```

## The API

Six things, deliberately. Everything is under `/api/v1` except health.

| | |
|---|---|
| `POST /route` | Compute a route between coordinates |
| `GET /mapdata/roads?bbox=` | The server's road network, as GeoJSON |
| `GET /mapdata/graph?bbox=` | How the routable graph came out — counts, not contents |
| `GET /mapdata/address?point=lon,lat` | Reverse geocoding: the street address at a point |
| `GET /traffic?bbox=` | Current road speeds, with provenance |
| `GET /traffic/levels` | The level table: thresholds, labels, colours |
| `GET /roadstate?bbox=` | Closures, flooding, works, incidents in force |
| `GET`/`DELETE /roadstate/{id}` | One condition; withdraw it |
| `POST /ingest/probes` | GPS position reports from clients |
| `POST /ingest/reports` | Incident reports from an operator or a client |
| `POST /ingest/refresh` | Pull the traffic feeds for an area now |
| `GET /health`, `/health/ready`, `/health/info` | Alive, serviceable, and what it was composed with |

Boxes are `west,south,east,north`; points are `[lon, lat]`. Longitude first,
everywhere, in both directions — the routing engine stores latitude-first
internally and the single conversion happens at the map-data boundary.

## Layout

```text
server/
├── api/              HTTP, serialisation, error mapping, composition root
│   ├── routes/       one blueprint per thing exposed
│   ├── schemas/      request parsing and response shaping. No decisions
│   ├── middleware/   errors in one place, request logging in another
│   ├── services.py   application services: orchestration, no computation
│   └── composition.py  the only module that imports every subsystem
│
├── routing/          A*/Dijkstra over a road graph. Contract v1.0
│   ├── service.py      RouteQuery -> Route: area, snapping, costs, constraints
│   ├── providers.py    what routing needs from the rest, as protocols
│   ├── bench/          A* against Dijkstra
│   └── tests/          207 tests, contract suite included
│
├── mapdata/          the road network, and the graph built from it
│   ├── roads/          sources. One shipped: OpenStreetMap via Overpass
│   ├── graph/          ways -> edges, and nearest-junction snapping
│   └── store.py        roads through the storage interface
│
├── traffic/          what a speed means, and what it costs a route
│   ├── levels.py       ratio -> level, colours, thresholds
│   ├── processing/     attaching measurements to roads; pricing them
│   └── state/          the current picture, and the seam routing reads
│
├── roadstate/        closures, flooding, construction, incidents
│   ├── kinds/          one module per kind, each with its own rules
│   ├── classify.py     which kind a report is, decided in a stated order
│   └── provider.py     blocked edges (a constraint) and costs (not the same)
│
├── ingest/           the door everything outside comes through
│   ├── gps/            client position reports, validated strictly
│   ├── traffic/        fetching feeds, and surviving them
│   ├── incidents/      normalising reports from anywhere
│   └── external_sources/  Digitraffic (measured), and a model
│
├── storage/          persistence, and the interface that makes it replaceable
│   ├── interface/      what a backend must do
│   ├── memory/         in-process
│   ├── sqlite/         the only module that imports sqlite3
│   └── postgres/       the migration target: DDL and MIGRATION.md
│
├── domain/           the shared vocabulary. Imports nothing
├── config/           every deployment decision, read once from the environment
├── observability/    logging and health
└── tests/            cross-subsystem, plus the architecture rules
```

## The rules that are enforced rather than remembered

`tests/test_dependency_rules.py` reads every production module with `ast` and
fails the build if:

- a block imports one it may not depend on (the layering is a table in that file)
- `sqlite3` appears outside `storage/sqlite/`
- `flask` appears outside `api/`
- the block import graph has a cycle
- a block has no `__all__`

So "routing does not know about the database" is a property of the repository,
not a claim in a document.

## Configuration

Environment variables, all prefixed `MAP_`, all with working defaults. The
full list is the field list of `config/settings.py`. The ones that matter
most:

```bash
MAP_STORAGE_BACKEND=sqlite      # or memory
MAP_DATABASE_PATH=data/server.db
MAP_DEFAULT_AREA=106.675,10.758,106.725,10.798
MAP_TRAFFIC_ENABLED=1           # price routes with live traffic
MAP_TRAFFIC_SIMULATED=1         # model traffic where no feed covers the area
MAP_DIGITRAFFIC_ENABLED=1       # Finland's free, keyless sensor feed
MAP_ROADSTATE_ENABLED=1         # let closures affect routes
```

An unreadable value fails at startup with a message naming the variable, not
at the first request.

## Data sources

Everything is free and keyless. That is a project rule, not a coincidence.

| Source | What | Coverage |
|---|---|---|
| [Overpass / OpenStreetMap](https://overpass-api.de/) | road geometry, classes, `maxspeed`, one-ways | worldwide |
| [Digitraffic](https://www.digitraffic.fi/en/road-traffic/) (Fintraffic) | measured speeds, incidents, roadworks | Finland |
| [Nominatim](https://nominatim.org/) (OSM) | reverse geocoding — the address at a point; ≤ 1 request/s, cached | worldwide |
| GPS probes | speeds where drivers actually are | wherever clients are |
| `SimulatedTrafficProvider` | a deterministic model over OSM geometry | anywhere |

There is no free live traffic API for Vietnam, which is where this project
centres its map. The simulated provider fills that gap and labels every record
it produces, so nothing downstream and no driver can mistake a model for a
measurement — `simulated: true` on the traffic response means exactly that.

OSM data is © OpenStreetMap contributors under ODbL; Digitraffic data is
published by Fintraffic under CC BY 4.0. Both must be credited wherever this
server's output is displayed.
