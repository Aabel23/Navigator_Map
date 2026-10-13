# api — Connector

## Responsibility

Own the server's external surface — HTTP transport, request validation,
response serialisation, error mapping, request logging — and the composition
root that wires every subsystem together at startup.

Own **no computation**. A handler parses a request, calls one application
service, and serialises the result. `api/routes/route.py` is three statements,
and the way to keep it that way is to be suspicious of any line added to it
that is not parsing or serialising.

## Inputs

| Name | Type | Source |
|---|---|---|
| HTTP requests | JSON bodies, `bbox=` query strings | clients and operators |
| `Settings` | frozen dataclass | `config.Settings.from_env()`, read once |
| every subsystem | their public surfaces | imported by `composition.py` only |

## Outputs

| Name | Type | Meaning |
|---|---|---|
| `create_app(services=None)` | factory | the Flask application |
| `build_services(settings)` | function | the wiring, separable from the app |
| `Services` | dataclass | everything the app was composed with |
| `API_PREFIX` | constant | `/api/v1` |
| HTTP responses | JSON | the published surface below |

## The published API

Everything is under `/api/v1` except health. Boxes are
`west,south,east,north`; points are `[lon, lat]` — **longitude first, in both
directions**.

| | |
|---|---|
| `POST /route` | compute a route between coordinates |
| `GET /mapdata/roads?bbox=` | the server's road network, as GeoJSON |
| `GET /mapdata/graph?bbox=` | how the routable graph came out — counts, not contents |
| `GET /traffic?bbox=` | current road speeds, with provenance |
| `GET /traffic/levels` | the level table: thresholds, labels, colours |
| `GET /roadstate?bbox=` | closures, flooding, works, incidents in force |
| `GET`/`DELETE /roadstate/{id}` | one condition; withdraw it |
| `POST /ingest/probes` | GPS position reports from clients |
| `POST /ingest/reports` | incident reports from an operator or a client |
| `POST /ingest/refresh` | pull the traffic feeds for an area now |
| `GET /health`, `/health/ready`, `/health/info` | alive, serviceable, and what it was composed with |

## Connectors

### `api → routing`, `→ mapdata`, `→ traffic`, `→ roadstate`, `→ ingest`, `→ storage`, `→ observability`, `→ config`

`composition.py` is **the only module that imports every subsystem**. Nothing
below it knows this layer exists.

### `api → client`

The public surface above. The client draws maps and follows a route; it does
not decide what the route is.

## Stable guarantees consumers may rely on

- **The status says whose problem it is.** One handler, in
  `middleware/errors.py`, one rule:

  | Situation | Status |
  |---|---|
  | malformed request, unknown profile | 400 — retrying unchanged will not help |
  | endpoint not near any road | 400 — moving the pin will help |
  | nothing legal connects the endpoints | 404 — a successful computation whose answer is "none" |
  | upstream unreadable | 502 — their problem, reported honestly |
  | upstream unavailable, storage down | 503 — temporary, retry later |
  | anything unexpected | 500 — logged with a traceback |

- **A 5xx body never carries the exception message.** A stack trace in a
  response is a gift to the wrong reader.
- **Longitude first, everywhere, in both directions.** Routing stores
  latitude-first internally and no client has to know that.
- **Stable ids are published** — node, edge, road, condition. A client
  genuinely needs them, and they are part of the contract rather than a leak.
- **`Route.total_cost` is not published.** The ETA is `duration_s`, from
  `Route.travel_time`, which is real seconds by construction.
- **Modelled traffic is labelled.** `simulated: true` means exactly that.
- Readiness reports **degraded** separately from **not ready**.

## Forbidden internal details

- `api.routes.*`, `api.schemas.*`, `api.middleware.*` as import paths.
- **`flask` must not be imported outside `api/`.**
  `tests/test_dependency_rules.py` fails the build if it is, which is what
  keeps every other block importable by a script, a test or a benchmark with
  no framework installed.
- **Routing algorithms must not appear in handlers.** If a change to
  `routes/` starts to look like an algorithm, it belongs one layer down.
- Database structures, internal classes, and the graph's contents.

## Inside the block

```text
api/
├── __init__.py        create_app, build_services, Services, API_PREFIX
├── app.py             the factory: blueprints, middleware, prefix
├── composition.py     the only module that imports every subsystem
├── services.py        application services: orchestration, no computation
├── routes/            one blueprint per thing exposed
│   ├── route.py         POST /route
│   ├── mapdata.py       GET /mapdata/roads, /mapdata/graph
│   ├── traffic.py       GET /traffic, /traffic/levels
│   ├── roadstate.py     GET/DELETE /roadstate
│   ├── ingest.py        POST /ingest/probes, /reports, /refresh
│   └── health.py        GET /health, /health/ready, /health/info
├── schemas/           request parsing and response shaping. No decisions
│   ├── geo.py           bbox strings, [lon, lat] points, GeoJSON
│   └── route.py         RouteQuery in, route JSON out
└── middleware/
    ├── errors.py        every exception -> a status, in one place
    └── logging.py       one line per request
```

**The three layers, and what each may do.**

| | |
|---|---|
| `routes/` | speaks HTTP. No loops over domain objects, no decisions |
| `services.py` | sequences subsystems. Knows *that* a refresh means collect-then-attach-then-classify, not *how* any of them work |
| subsystems | compute. Know nothing about the two layers above |

**The flow through the files**, for the central request:

```text
POST /api/v1/route
    │
    ▼  app.py                 routed to the blueprint
    ▼  middleware/logging.py  one line in
    ▼  routes/route.py        (1) schemas/route.py parses the body into a RouteQuery
    │                         (2) services.py -> routing.RoutingService.route()
    │                         (3) schemas/route.py shapes the Route into JSON
    │                             -- and drops total_cost, and flips to lon-first
    ▼  middleware/errors.py   anything raised becomes a status, here and only here
    ▼
JSON
```

**Why composition is a separate module from the app factory.** `create_app`
accepts `services=...`. That is what lets the test suite run the real HTTP
stack against a fake outside world by *construction* rather than by
monkey-patching — traffic feeds and the road source are the only things faked
anywhere in 796 tests.

**Startup.** `python main.py --check` builds every subsystem exactly as a real
start would — opens the database, runs the migration, wires the providers, runs
the health checks — and exits. A configuration mistake surfaces there rather
than as the first request failing.
