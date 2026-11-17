# map — the basemap renderer

A vector-tile map drawn by this project's own decoder and WebGL2 renderer, not
by a general-purpose map library. Real tiles, filled polygons, real road
widths, street names and points of interest in Vietnamese, and a handful of
draw calls per frame.

```bash
cd map
python -m pip install -r requirements.txt
python main.py
```

Then open <http://127.0.0.1:1520/>. Drag to pan, scroll or pinch to zoom, `i`
for the pipeline HUD. No API key: it reads the free, keyless OpenFreeMap tiles,
glyphs and sprite sheet, over endpoints fetched at start-up rather than baked
in — OpenFreeMap's tile path carries a build timestamp that changes over time,
and the TileJSON it publishes is the mechanism that exists to say what the
current one is.

## What "specialised" means here, concretely

Six switches, each real:

| Switch | What it looks like in this block |
|---|---|
| **Flat arrays, not per-feature objects** | [`ui/static/mvt.js`](ui/static/mvt.js) walks the protobuf once and writes straight into typed arrays already in world space — no per-feature dictionary, no intermediate GeoJSON, no command list handed to a second consumer. |
| **Decode *and geometry* on a worker, not the frame** | [`ui/static/decode_worker.js`](ui/static/decode_worker.js) fetches the bytes, decodes them, triangulates every polygon and extrudes every road — all off the thread that owns the canvas. What the main thread receives is a typed array and an index array; the only work left on the frame thread is one add per index. |
| **One GPU buffer per bucket, not per tile** | [`ui/static/gl.js`](ui/static/gl.js)'s `Bucket` is one vertex buffer and one index buffer shared by `land`, `water`, `waterway`, `building` or `road` across the *entire* map. |
| **Attribute-driven styling, not a pass per layer** | Every vertex carries a style index; the shader reads colour and width out of a uniform block indexed by it. A motorway, a service road and a building outline share one buffer and one pass while looking nothing alike. Five buckets cost seven draw calls — the three fill buckets once each, and the two line buckets (`waterway`, `road`) twice each, casings for the whole network then fills for the whole network, which is what makes a junction read as a junction. |
| **LOD before the parse, not after** | A class below its configured zoom is not decoded, not uploaded and not drawn. `landuse` is gated at the layer level and is never even walked; `building` and `service` are gated per class. A tile's identity therefore includes the zoom it was decoded at. |
| **Dirty-range updates, not whole-buffer rebuilds** | `Bucket.setStyleRange` restyles a contiguous run of vertices and re-uploads only the bytes that run covers. Nothing in the base map uses it — the base map is static — but it is the port `traffic`, `road_condition` and `navigation` restyle segments through. |

Two more from the same family: **directional prefetch**
([`ui/static/app.js`](ui/static/app.js) tracks the camera's recent movement and,
above `PREFETCH_MIN_SPEED_PX_S`, requests a ring of tiles ahead of that heading),
and **generation eviction** — at most two tile generations are resident, and the
older one is dropped the moment the newer one covers the viewport, so the same
street is never drawn at two zoom levels at once.

## Labels: text and icons, from the same free tile provider

Street names, place names and points of interest were already in every tile
this block was fetching — OpenFreeMap's tiles carry a `name` field on `place`,
`poi`, `transportation_name` and `water_name`, already localised, no
translation lookup needed. The map/version1.0 project rule is free-only data
sources, and the label engine is built entirely on that constraint:

| Piece | Where it comes from | What it costs |
|---|---|---|
| **Names** | Already in the vector tiles, decoded by [`mvt.js`](ui/static/mvt.js) alongside geometry, in the same pass | free — no new source |
| **Glyphs** | `https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf` — the standard SDF glyph-PBF protocol, same host as the tiles | free, keyless |
| **Icons** | `https://tiles.openfreemap.org/sprites/ofm_f384/ofm.json` + `.png` — a plain Mapbox-format sprite sheet, same host | free, keyless |

Four switches make this a batched, worker-driven pipeline rather than the
browser drawing text the way a web page does:

| Switch | What it looks like in this block |
|---|---|
| **Labels decided on the worker, shaped on the frame thread** | [`mvt.js`](ui/static/mvt.js) decides, per feature, whether it has a label, what it says, where its anchor is, and how hard it should fight for space — a plain object, not geometry. [`labels.js`](ui/static/labels.js) turns that decision into quads once the glyphs it needs have arrived, and caches the result forever: panning back to a place already shaped costs nothing. |
| **Signed-distance-field text, one atlas for the whole map** | [`glyphs.js`](ui/static/glyphs.js) decodes 256-code-point glyph ranges into one shared texture. A distance field lets the same bitmap be thresholded crisp at any zoom, and a halo is a second threshold on the same value — not a second bitmap. |
| **A uniform grid for collision, not a tree** | [`collision.js`](ui/static/collision.js) sorts every on-screen label by priority and places it greedily: if its box is clear it is drawn, otherwise it is dropped whole. Labels are screen-sized and roughly evenly spread, which is exactly what a grid handles well and a tree only complicates. |
| **Two draw calls for every label on the map** | Icons in one `drawElements`, text halos and text fills in two more — regardless of how many thousand label records are resident, because what reaches the GPU is only the few hundred that won the collision pass. |

Priority is tuned for a driver, not a reference atlas: a street name outranks
the name of the administrative block it runs through, because only one of
those is something you can be told to turn onto. See `LABEL_STYLES` in
[`config/style.py`](config/style.py) for the exact order.

Vietnamese needs three glyph blocks beyond Basic Latin — Latin-1 Supplement,
Latin Extended-A (for `Đ`/`đ`), and Latin Extended Additional (every
tone-marked vowel) — and all three are free from the same host, preloaded at
start-up (`GLYPH_PRELOAD_RANGES`) so labels don't arrive in visible waves.

## The style is data

`config/style.py` holds the whole visual language, geometry and text alike: a
background colour, two zoom stops, the bucket draw order, an ordered fill
table, an ordered line table, a rule per source layer, an ordered label style
table, and a label rule per name-bearing layer.

Nothing in the renderer knows what a motorway looks like, or what size a place
name should be. Adding a road class, restyling one, or changing which POI
classes get icons is a table row — no shader change, no extra draw call. Style
names are resolved to indices once at start-up, so a typo is a start-up error
rather than a silently missing class or label.

## The driver: real GPS, address, route, probes

The basemap is the bulk of this block, but the page also follows the driver:

| What | How | Where |
|---|---|---|
| **Position** | `navigator.geolocation.watchPosition`, high accuracy. Fixes worse than `NAV_GPS_MAX_ACCURACY_M` are held back; a missing speed or heading is derived from two fixes only when they are further apart than the receiver's own error | [`gps.js`](ui/static/gps.js) |
| **Address** | `GET /api/v1/mapdata/address?point=lon,lat` on the server (OSM Nominatim, cached, ≤ 1 req/s upstream). Asked again only after moving `NAV_ADDRESS_MIN_MOVE_M` | [`driver.js`](ui/static/driver.js) |
| **Route** | Tap the map: `POST /api/v1/route` from the current fix to the tapped point. Double-tap still zooms | [`driver.js`](ui/static/driver.js), [`app.js`](ui/static/app.js) |
| **Probes** | Anonymous `POST /api/v1/ingest/probes`, batched every 15 s, one per 2 s at most. A checkbox on the page turns it off per device | [`gps.js`](ui/static/gps.js) `ProbeUploader` |
| **Drawing** | Position dot, accuracy circle, heading arrow, route and destination pin on a 2D canvas over the WebGL one | [`overlay.js`](ui/static/overlay.js) |

The page never calls the server directly: `/api/v1/*` on this block is
forwarded to `NAV_SERVER_URL` (default `http://127.0.0.1:8000`) by
[`ui/view.py`](ui/view.py). One origin is what makes the next section one
command.

### On a phone, through Cloudflare Tunnel

A browser only hands out GPS to a **secure** page — HTTPS, or `localhost`. A
phone opening `http://192.168.x.x:1520` gets no prompt and no position. A free
Cloudflare quick tunnel gives the page an HTTPS address with no account:

```bash
# terminal 1 — the navigation server
cd server && python main.py

# terminal 2 — this page (proxies /api/v1 to the server)
cd client/map && python main.py

# terminal 3 — HTTPS for the phone
cloudflared tunnel --url http://127.0.0.1:1520
```

`cloudflared` prints `https://<random-words>.trycloudflare.com`. Open that on
the phone, tap the locate button (bottom of the right-hand column), allow
location, and the address appears under the map. Tap anywhere to route there.
`cloudflared` is a single binary — `brew install cloudflared`, `winget install
Cloudflare.cloudflared`, or the `.deb` from Cloudflare's releases page.

The quick-tunnel address changes on every run and anyone with it can reach the
page; for a fixed name, use a named tunnel on a domain in your Cloudflare
account. The server's API has no authentication — keep the tunnel pointed at
this page, not at the server, and stop it when you are done.

## What is deliberately not here

**No pitch, no bearing, no 3D buildings.** The camera is flat and
north-up. Buildings are footprints, not extrusions.

**No traffic.** Roads are coloured by class, not by how they are flowing. The
mechanism for a live per-segment colour exists (`setStyleRange`), but the feed
belongs to the `traffic` block and there is nothing to plug into it yet.

**One shared coordinate origin, chosen once.** Every vertex is `float32` world
pixels relative to the initial camera position, which is what lets one bucket
hold vertices from many tiles and zoom levels without a per-tile transform.
Panning very far from the start point is not handled — the numbers still work,
they just carry less precision than at the origin. Camera-relative coordinates
are a planned milestone.

**Eviction compacts immediately.** Dropping tiles rebuilds the buffer without
them in one pass rather than tracking dead space and compacting later. Eviction
is already infrequent, and this way a frame can never draw a tile that was
supposed to be gone. A slab allocator that avoids the rebuild entirely is a
planned milestone.

## Verifying it

Six offline, deterministic suites — no network, no browser:

```bash
node tests/test_earcut.mjs      # triangulation
node tests/test_lines.mjs       # polyline extrusion, label line-anchors
node tests/test_mvt_decode.mjs  # decode, classify, LOD, projection, label records
node tests/test_glyphs.mjs      # SDF glyph-range decoding
node tests/test_labels.mjs      # text/icon shaping, vertex emission, collision
node tests/test_gps.mjs         # positions -> fixes -> probes, derived speed, upload retry
```

They assert properties rather than recorded numbers. The triangulator is
checked against the triangle-count ceiling, an independently computed polygon
area, and index bounds — a triangulator that drops or overlaps triangles fails
at least one. The extruder is checked against the geometry that makes a corner
meet: the mitre at a right angle must be exactly `1/cos(45°)` long. The decoder
is checked against counts worked out by hand from the four features in
`tests/fixtures/tiny.pbf`, not copied from a prior run. The glyph decoder is
checked against a range this suite encodes by hand from the published schema,
not a vendored font file, so what is tested is the wire format rather than one
font's specific bytes. The label engine is checked against derivable geometry:
a right-angle mitre, a centred and vertically-balanced line of text, a
collision grid that finds a box from any cell it spans.

## Layout

```
main.py                     entry point: host, port, debug
config/
├── config.py                tile source, cache, prefetch, simplification, glyph/sprite endpoints
└── style.py                 colours, widths, per-class zoom gates, layer rules, label styles/rules
ui/
├── view.py                  Flask: /, /api/config, and /api/v1/* forwarded to the server
├── templates/index.html     the page shell -- one canvas, one HUD, no inline script or style
└── static/
    ├── app.css              page chrome only; it cannot change what the map looks like
    ├── app.js               camera, input, worker pool, scheduler, eviction, label placement, HUD
    ├── tile_math.js         Web Mercator and tile arithmetic
    ├── pbf.js                the three protobuf primitives every decoder here shares
    ├── mvt.js               protobuf -> classify -> LOD -> geometry + label records, in one pass
    ├── earcut.js            flat-array polygon triangulation
    ├── lines.js             polyline -> ribbon; also the label line-anchor (position + angle)
    ├── decode_worker.js     the worker: fetch, decode, triangulate, extrude
    ├── glyphs.js            SDF glyph-range decoding and atlas packing
    ├── sprite.js            the icon sheet: fetch, index lookup
    ├── labels.js            text/icon shaping into quads; vertex emission
    ├── collision.js         the placement grid and rotated-box bounds
    ├── placement.js         per-frame: cull, measure, prioritise, collide, shape, upload
    ├── gps.js               Geolocation -> fixes; probe batching and upload
    ├── driver.js            follow, address lookup, tap-to-route, probe opt-out
    ├── overlay.js           position, accuracy, route and destination, on a 2D canvas
    └── gl.js                buckets + label meshes, uniform-block styling, append/evict, the draw
tests/
├── fixtures/tiny.pbf
├── test_earcut.mjs
├── test_lines.mjs
├── test_mvt_decode.mjs
├── test_glyphs.mjs
├── test_labels.mjs
└── test_gps.mjs
```
