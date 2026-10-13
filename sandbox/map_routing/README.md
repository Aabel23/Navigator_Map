# map_routing — three blocks, wired together and driven by hand

A sandbox that makes the `map`, `routing` and `traffic` blocks talk to each
other, so their connectors can be exercised rather than read about.

```text
Fake GPS
   │
   │ origin      (a coordinate → map matching → a graph node id)
   ▼
 Routing ◄──── Traffic      ({edge_id: multiplier}, plus blocking incidents)
   │
   │ route       (Route.geometry — a coordinate sequence, nothing else)
   ▼
  Map           (the real renderer, plus an overlay above it)
```

```bash
cd sandbox/map_routing
python -m pip install -r requirements.txt
python main.py
```

Then open <http://127.0.0.1:1530/>. Click the map to drop a destination,
watch two routes appear, and press **Drive route** to send the fake vehicle
along one.

The first start fetches the region's roads from Overpass and caches them under
`.cache/overpass/`; give it a few seconds. Everything after that is local.

---

## What this is for

Each of the three blocks is verified on its own. What no block can verify on
its own is the join: routing insists on node ids and refuses coordinates, map
insists on a coordinate sequence and refuses road data, traffic insists on
producing a plain dict and refuses to know routing exists. Those refusals are
the architecture working — and they mean nothing in the repository actually
demonstrates that the three fit.

This does. Every arrow above is a documented connector, crossed here with
plain data.

| Arrow | Connector | Where it is crossed |
|---|---|---|
| GPS → routing | `map_matching → routing`: "Routing takes graph node ids, never coordinates" | [`sim/matching.py`](sim/matching.py) |
| traffic → routing | "a `Mapping[edge_id, float]` of multipliers, wrapped in `DynamicCostModel`" | [`sim/traffic_link.py`](sim/traffic_link.py) |
| blocking incident → routing | "expressed by the graph's `Access.BLOCKED` or by a request constraint, not by an enormous multiplier" | [`sim/traffic_link.py`](sim/traffic_link.py) → `RouteConstraints` |
| routing → map | `Route.geometry`, "the single field that keeps `map` independent of the graph" | [`static/sim.js`](static/sim.js) |
| roads → graph | traffic's `RoadSource`, "this block does not own road geometry — it borrows it" | [`sim/graph_build.py`](sim/graph_build.py) |

No block imports another. The sandbox imports each one only through the
interface it publishes, and that is confined to [`sim/blocks.py`](sim/blocks.py)
so it can be audited in one screen.

---

## Two routes, always

Every request is routed twice over the same graph, from the same origin to the
same destination: once under free-flow costs, once under live traffic. The
panel shows both, and the difference between them *is* the traffic connector —
a simulator that drew one line could not tell you whether the connector was
doing anything at all.

Measured in Ho Chi Minh City on 2026-09-13, District 1, modelled traffic:

```text
free flow :   5601 m   6.6 min   93 edges   4475 settled
w/ traffic:   6622 m   9.0 min   62 edges   7012 settled
same road : False
```

A different road, 18% longer, and still the faster of the two once congestion
is priced. That is the whole point, on one line.

---

## What the sandbox owns, and why

Three things sit here rather than in a block, each because no existing block
claims them:

**The road graph.** Routing says it does not decide "where road data comes
from". Traffic says it "does not own road geometry — it borrows it", and
publishes what it borrowed as `RoadSegment`. So
[`sim/graph_build.py`](sim/graph_build.py) turns one into the other. The work
is mostly one idea: *a way is not an edge*. An OSM way runs through junctions;
a routing edge runs between them. Every coordinate two ways share becomes a
junction, and each way is cut there.

**Map matching.** There is no `map_matching` block yet, so
[`sim/matching.py`](sim/matching.py) supplies the crudest honest version:
nearest routable junction, no path history, no heading filter. Naming it here
keeps the gap visible instead of letting it dissolve into routing.

**The traffic cost adapter.** The traffic block's README lists
`traffic/cost.py` as the next thing to write. Until it exists,
[`sim/traffic_link.py`](sim/traffic_link.py) does the same job in the sandbox —
which is where it can be written without either block learning about the
other.

None of the three is a block, and none should become one by accident. They are
here to be deleted the day a real one exists.

---

## The camera tap

The map block's `ports.md` declares `camera_state` — `{worldX, worldY, zoom}` —
as an output port, and records that nothing consumes it yet. Nothing publishes
it yet either: `camera` is a local inside `app.js`'s `main()`.

The overlay needs exactly that one value, and publishing it would be a change
to another block. So [`static/sim.js`](static/sim.js) taps it where it already
crosses a published seam instead: `Renderer.draw(camera)` is called once per
frame with the camera object, and the sandbox wraps that method to record it
and call straight through. Nothing in `server/map/` is modified.

**This is the one piece of the sandbox that should not outlive its cause.**
The clean fix is one line in `map/ui/static/app.js` publishing the documented
port, plus the matching line in `map/ports.md` — an ordinary change *inside*
the map block, fulfilling a contract it already wrote. When that lands, delete
the wrapper at the top of `sim.js` and read the published value.

Everything else on the page is the map block untouched: `/static` is served
straight out of `server/map/ui/static`, and `/api/config` is the map block's
own view function, registered on the sandbox's app rather than copied into it.
The overlay projects with the map's own `lonLatToWorldZ0`, so the route and
the basemap agree on where a coordinate is by construction.

---

## The two regions

The traffic block's honest answer to "is there free live traffic data" is "in
some countries". Both answers are here, because a simulator that only showed
one would hide the more interesting half.

| Region | Traffic | Source |
|---|---|---|
| **Ho Chi Minh City**, District 1 | modelled | `SimulatedTrafficProvider` over free OSM geometry. Every record is labelled `simulated` and the panel says so. |
| **Helsinki**, central | measured | Fintraffic's Digitraffic — free, keyless, real roadside sensors, and free-flow references measured by the same operator. |

Verified against the live feed on 2026-09-13:

```text
region : helsinki    measured
graph  : 9699 ways → 8619 nodes, 9922 edges, 8231 routable
traffic: sources ['digitraffic']   simulated False
         26 observations, 12 incidents, 0 segments
link   : 26/26 observations matched → 13 edges priced, worst ×2.86
```

Switching region re-queries Overpass and rebuilds the graph. The camera
follows, but the map block's world origin does not: it is fixed at start-up
from `MAP_CENTER`, and the renderer's `float32` world coordinates lose
precision far from it. Helsinki is about 58 world-pixels from the Ho Chi Minh
City default, which is harmless at the zoom the region opens at and visible as
sub-pixel wobble past z16. For a long session in Helsinki, start the simulator
with the origin moved:

```bash
MAP_CENTER_LAT=60.1699 MAP_CENTER_LON=24.9384 python main.py --region helsinki
```

---

## The fake GPS

It is deliberately *wrong*. A position with a few metres of Gaussian noise on
it is what makes the matching step visibly do something; a perfect coordinate
would make routing-from-node-ids look like pointless ceremony. Noise is applied
to the reported fix and never to the tracked position, so error cannot
accumulate.

Driving walks the traffic-aware route at the speed the route itself implies —
its distance over the travel time the cost model reported. The speedometer
stays honest and the **clock** runs fast (×8) instead, so a nine-minute route
can be watched in about a minute while still taking longer than the free-flow
one it is being compared against.

---

## What is deliberately not here

**No navigation.** The route is not recomputed as the vehicle moves, progress
along it is not tracked as manoeuvres, and nothing is spoken. That is the
`navigation` block's responsibility and this sandbox does not pretend to it.

**No turn restrictions.** Overpass `out geom` is queried for ways only, so the
graph carries no `restriction` relations. Routing's legality guarantee is
"legality *as reported by the graph*", and this graph reports none.

**One-way `-1` is flattened.** The traffic block's Overpass reader maps
`oneway=-1` to a plain `True` without reversing the geometry, so a handful of
reverse-tagged ways point the wrong way here. It shows up as an occasional odd
detour, not a wrong answer.

**Traffic is not drawn on the basemap.** The map block offers
`Bucket.setStyleRange` for exactly that, and it is the right port for colouring
roads the basemap already holds. This sandbox draws traffic on its own 2D
overlay instead, because the overlay had to exist for the route anyway and one
drawing path is easier to trust than two. Using `setStyleRange` properly is a
map-side milestone, not a sandbox one.

---

## Layout

```text
main.py                     entry point: host, port, region
requirements.txt            flask, and nothing else
sim/
├── blocks.py               the only place the three blocks are imported
├── settings.py             regions, cache location, the judgement-call numbers
├── geodesy.py              haversine, bearings, walking a polyline
├── graph_build.py          RoadSegment[] → InMemoryRoadGraph (a way is not an edge)
├── matching.py             coordinate → node id; coordinate → edge ids
├── traffic_link.py         TrafficSnapshot → {edge_id: multiplier} + blocked edges
├── gps.py                  the fake receiver: place it, or drive it
├── world.py                the simulator: holds all of it, computes both routes
└── web.py                  Flask: the page, /api/config, /api/sim/*
templates/index.html        the map block's DOM, plus the overlay and the panel
static/
├── sim.css                 panel chrome; nothing here can restyle the map
└── sim.js                  camera tap, overlay, picking, panel
```

## Attribution

Road geometry and modelled traffic derive from OpenStreetMap, © OpenStreetMap
contributors under ODbL. Measured traffic is published by Fintraffic under
CC BY 4.0. Both are credited in the panel, which is a condition of using them.
