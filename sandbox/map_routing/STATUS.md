# Status: superseded by the server, and currently not runnable

**As of 2026-09-13 this sandbox does not start.** The server migration moved
and renamed everything it imports. Nothing here has been rewritten, because the
instruction for that migration was to leave the sandbox alone and record its
situation instead. This file is that record.

---

## What this sandbox was for

It existed to answer one question that no block could answer on its own:
*do `map`, `routing` and `traffic` actually fit together?* Each block was
verified in isolation, and each deliberately refused the others' work — routing
insisted on node ids, map insisted on a coordinate sequence, traffic insisted
on producing a plain dict. Those refusals were the architecture working, and
they meant nothing in the repository demonstrated that the three joined up.

So it wired them by hand, with a fake GPS for an origin, a click for a
destination, and two routes drawn at once — free-flow and traffic-priced — so
the difference the traffic connector made was visible on screen.

It worked. Measured in District 1, Ho Chi Minh City on 2026-09-13:

```text
free flow :   5601 m   6.6 min    93 edges   4475 settled
w/ traffic:   6622 m   9.0 min    62 edges   7012 settled
same road : False
```

---

## Why it is superseded

Everything it hand-rolled is now a real, tested part of the server.

| The sandbox wrote | The server now has |
|---|---|
| `sim/graph_build.py` — ways into edges | `mapdata/graph/build.py`, with `tests/test_graph.py` |
| `sim/matching.py` — coordinate to node id | `mapdata/graph/provider.py`, over `domain.SpatialIndex` |
| `sim/traffic_link.py` — snapshot to multipliers | `traffic/processing/` + `traffic/state/provider.py` |
| `sim/world.py` — two routes, one with traffic | `routing/service.py`, and `MAP_TRAFFIC_ENABLED` |
| the whole wiring | `api/composition.py` |

And the demonstration itself is now a single request:

```bash
curl -s localhost:8000/api/v1/route -H 'Content-Type: application/json' \
  -d '{"origin": [106.6985, 10.7770], "destination": [106.7180, 10.7730]}'
```

`server/ARCHITECTURE_LOCK.md` §6 records the same comparison the sandbox used
to draw: 423.8 s with traffic, 307.1 s without, over a live Overpass graph.

---

## Exactly what is broken

All of it is in one file by design — [`sim/blocks.py`](sim/blocks.py) is the
only module that reaches a block — plus the call sites of the three things that
changed shape.

| Import | Then | Now |
|---|---|---|
| `ui.view.create_app` | `server/map/ui/view.py` | `client/map/ui/view.py` |
| map static assets | `server/map/ui/static` | `client/map/ui/static` |
| `routing` | `server/routing/routing/` | `server/routing/` — add `server/` to the path, not `server/routing/` |
| `BBox` | `traffic.BBox` | `domain.BBox` |
| `RoadSegment` | `traffic.RoadSegment` | `mapdata.RoadSegment` |
| `OverpassRoadSource` | `traffic.sources.overpass`, `cache_dir=` | `mapdata.OverpassRoadSource`, `cache=JsonFileCache(...)` |
| `DigitrafficProvider` | `traffic.providers.digitraffic` | `ingest.external_sources.digitraffic` |
| `SimulatedTrafficProvider` | `traffic.providers.simulated` | `ingest.external_sources.simulated` |
| `TrafficStore` | `traffic.TrafficStore` | **gone.** Collecting is `ingest.TrafficCollector`; holding is `traffic.TrafficState` |
| `TrafficSnapshot` | records with levels and `edge_id` | `traffic.TrafficSnapshot` over `RoadSpeed`; levels come from `traffic/levels.py` |

The first five are one-line repairs. `TrafficStore` is not: collecting and
holding are two blocks now, which is the split that lets a second provider be
added without a second opinion arriving with it — so
[`sim/world.py`](sim/world.py) and [`sim/traffic_link.py`](sim/traffic_link.py)
would have to follow, and that is a rewrite rather than a repair.

---

## The two ways forward

**Repoint it.** Roughly an hour: fix `sim/blocks.py`, replace `TrafficStore`
with `TrafficCollector` + `TrafficState` in `sim/world.py`, and rewrite
`sim/traffic_link.py` against `RoadSpeed`. The result would be a sandbox that
duplicates four tested subsystems, which is the thing it was built to make
unnecessary.

**Retarget it at the API — recommended.** Delete `sim/graph_build.py`,
`sim/matching.py`, `sim/traffic_link.py` and most of `sim/world.py`, and have
the page call `POST /api/v1/route`, `GET /api/v1/traffic?bbox=` and
`GET /api/v1/traffic/levels` over HTTP. What survives is the genuinely useful
part and the part nothing else in the repository does:

- the **fake GPS** ([`sim/gps.py`](sim/gps.py)) — a position with real noise on
  it, drivable along a route, which is what makes matching visibly do work;
- the **map overlay** ([`static/sim.js`](static/sim.js)) — the only code that
  draws a server route on the client's real renderer, including the camera tap
  described below;
- the **two-route comparison**, which would become two requests with
  `traffic` on and off rather than two routers.

That version would exercise the server as a client does, rather than as a
library, which is the more useful thing to have now that the server has a
public API.

---

## One thing worth keeping either way

The map block still declares `camera_state` as an output port and still does
not publish it — `camera` is a local inside `app.js`'s `main()`. The overlay
needs exactly that value, so [`static/sim.js`](static/sim.js) taps it by
wrapping `Renderer.prototype.draw`, which already receives it once per frame.
Nothing in the map block is modified.

The clean fix remains one line in `client/map/ui/static/app.js` publishing the
documented port, plus the matching line in `client/map/ports.md`. When that
lands, the wrapper at the top of `sim.js` is the one thing to delete.

---

## Scope note

`sandbox/` is not a block. It owns no domain rule, nothing in `server/` may
import it, and it is outside the single-block rule — working on it is not
working on a block. See `agent-system-server/TREE.md`.
