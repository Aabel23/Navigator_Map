# map_demo — what the server can already do, shown as a map

A working navigation client. The client map block draws the basemap; the
**server** decides everything else, and the demo asks it over `/api/v1` the
same way a phone would.

```bash
cd sandbox/map_demo
python -m pip install -r ../../server/requirements.txt
python main.py
```

Open <http://127.0.0.1:1540/>. Click the map for a start point, click again for
a destination.

**The first request for an area is slow, and only the first.** The server
fetches that piece of the world from OpenStreetMap and builds a routable graph
from it, lazily, per area — tens of seconds. Everything after that is
milliseconds, and the fetch is cached to disk, so it survives a restart. The
panel says what it is waiting for rather than just sitting there.

Measured, same box, cold then warm:

```text
                cold      warm
roads          28.3 s    0.20 s
traffic         0.2 s    0.10 s
road state      0.0 s    0.00 s
route           1.2 s    0.03 s
graph summary      —     0.00 s   (free: the route already built it)
```

Areas the page asks for are snapped outward to a 0.01° grid, so ordinary
panning keeps asking the same question and keeps hitting the cache. Closing a
road is the other cold path: the server derives the report's area from its
geometry, and the first closure in a district pays one fetch for it.

---

## What you see

| On screen | Where it comes from |
|---|---|
| the basemap, labels, Vietnamese street names | the client's own vector tiles — the server never sends a tile |
| the blue route line | `POST /api/v1/route` |
| the turn list, with real street names | `route.steps` — maneuver, name, distance, duration |
| ETA and distance | `duration_s` (real seconds) and `distance_m` |
| the grey dashed route beside it | the same trip with `use_traffic: false` |
| roads coloured green→red | `GET /api/v1/traffic` joined to `GET /api/v1/mapdata/roads` by `road_id` |
| the legend | `GET /api/v1/traffic/levels` — the server's table, not the page's |
| closures and flooding | `GET /api/v1/roadstate` |
| node and edge counts | `GET /api/v1/mapdata/graph` |
| the moving vehicle | the demo, animating along `route.geometry` |

Nothing on that list is computed here. There is no graph in this directory, no
cost model, no snapping and no search — which is the point: if a demo can build
a navigation UI out of the API alone, so can a phone.

---

## The four things worth trying

**1. Watch traffic change the answer.** Route anywhere in District 1 at a
rush hour. The panel shows both numbers and what the difference bought:

```text
with traffic:   3012.9 m   575.6 s
free flow:      2905.0 m   198.3 s
traffic costs   377.3 s  (+190%)
```

Sometimes the two lines sit on top of each other — same road, priced
differently. Sometimes they diverge, and the server picked a different road
*because* of the traffic. The panel says which.

**2. Close a road and watch it reroute.** Press **Close a road**, then click a
street the route uses. That posts an incident report:

```text
POST /api/v1/ingest/reports   {"reports": [{"id": …, "kind": "closure",
                                            "blocking": true, "geometry": [[lon, lat]]}]}
```

The server normalises it in `ingest`, classifies it in `roadstate` (closure
first, ahead of flooding, construction and incident), attaches it to the road,
stores it with a validity window, and hands routing a **blocked edge** — not a
large cost. The next route goes around it. Verified:

```text
report -> accepted=1   roadstate: 1 condition, 1 blocking, kind=closure
re-route: 2920.8 m     route changed = True
```

**Reopen all** withdraws only the closures this page reported
(`DELETE /api/v1/roadstate/{id}`).

**3. Start the drive.** The vehicle follows the route at the speed the route
implies — its own distance over the duration the cost model reported — with the
clock run 8× so a ten-minute trip is watchable. The speedometer stays honest.
The guidance bar shows the next manoeuvre and the distance to it, and the turn
list highlights where you are.

**4. Look at the provenance.** The traffic panel says `modelled` or
`measured`, names the sources, and names any that failed. There is no free
live traffic feed for Vietnam; the server models it and labels every reading,
and this page shows the label rather than hiding it.

---

## Two ways to run it

```bash
python main.py                                      # server in-process
python main.py --server-url http://127.0.0.1:8000   # against a running server
```

**In-process** (the default) composes the server inside this process and calls
it through Flask's test client. Every blueprint, middleware and error handler
runs exactly as under a real server; what is skipped is the socket. One
command, no ports, nothing else to start.

**Over HTTP** is the honest answer to "does this work over the wire". Start the
server yourself first:

```bash
cd server && python main.py --port 8000
```

Both were verified. The page cannot tell which is underneath: it calls
`/api/v1/...` on its own origin either way.

---

## Why there is a passthrough

A page served from `127.0.0.1:1540` cannot call a server on `127.0.0.1:8000`
without the server sending CORS headers, and adding those to `server/api/` to
satisfy a sandbox would be the sandbox reaching into a block. So the demo
forwards `/api/v1/*` from its own origin. Same origin, no headers, nothing in
the server touched.

The forwarded paths are listed explicitly in `demo/web.py`. A demo that could
reach any path would stop documenting which endpoints a client actually needs.

---

## The one shim

The client map block's `ports.md` declares `camera_state` —
`{worldX, worldY, zoom}` — as an output port and records that nothing consumes
it. Nothing publishes it either: `camera` is a local inside `app.js`'s
`main()`.

The overlay needs exactly that value to draw a route line that lines up with
the basemap. So [`demo/static/demo.js`](demo/static/demo.js) taps it where it
already crosses a published seam: `Renderer.draw(camera)` is called once per
frame with the object, and the wrapper records it and calls straight through.
Nothing in `client/map/` is modified.

The clean fix is one line in `client/map/ui/static/app.js` publishing the
documented port, plus the matching line in `client/map/ports.md`. When that
lands, the wrapper at the top of `demo.js` is the one thing to delete.

Everything else on the page is the map block untouched: `/static` is served
straight out of `client/map/ui/static`, and `/api/config` is the map block's
own view function registered on the demo's app rather than copied into it.

---

## Layout

```text
main.py                  entry point: port, area, which link
demo/
├── blocks.py            locates the server and the client map block
├── link.py              InProcessLink and HttpLink -- one interface, two ways
├── web.py               the page, the map's assets, the /api/v1 passthrough
├── templates/index.html the map block's DOM, plus the panel and the overlay
└── static/
    ├── demo.css         panel chrome; nothing here can restyle the map
    └── demo.js          camera tap, overlay, API calls, guidance, drive
```

`blocks.py` is worth one paragraph. `client/map/` and `server/` both contain a
top-level `config`, and Python resolves a regular package before a namespace
one whatever the path order — so simply putting the map block on `sys.path`
would hand it the *server's* configuration. The map block is therefore imported
inside a window where its two configuration modules are loaded by file and
installed under the name it expects, and the window closes immediately.

---

## Scope

`sandbox/` is not a block. It owns no domain rule, nothing in `server/` may
import it, and it is outside the single-block rule. See
`agent-system-server/TREE.md`.

The older `sandbox/map_routing/` predates the server having an API and wired
the blocks together as libraries. It is superseded and does not run; see its
[`STATUS.md`](../map_routing/STATUS.md).

## Attribution

Road geometry and modelled traffic derive from OpenStreetMap, © OpenStreetMap
contributors under ODbL. Measured traffic, where a feed covers the area, is
published by Fintraffic under CC BY 4.0. Both are credited in the panel, which
is a condition of using them.
