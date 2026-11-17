# Block Ports

BLOCK: map
CONTRACT: v1

## Inputs

- port: tile_source
  type: TileJSON URL -> `{z}/{x}/{y}.pbf` (Mapbox Vector Tile, OpenMapTiles schema)
  source: `config.config.TILEJSON_URL`, resolved by the page at start-up
  semantics: read-only, cacheable, may 404 for coordinates the source does not cover
  lifecycle: resolved once per page load; individual tiles fetched on demand by the scheduler

- port: style
  type: `config.style.style_payload()` dict, served inside `GET /api/config`
  source: `config/style.py`
  semantics: complete visual definition. Ordered tables; indices are the wire format
  lifecycle: read once at start-up, pushed to every worker before any tile is requested

- port: camera_intent
  type: pointer, wheel and button events on the canvas and controls
  source: the browser
  semantics: pan, zoom about a point, recentre
  lifecycle: continuous

- port: glyphs_and_sprite
  type: SDF glyph-range protobuf (`{fontstack}/{range}.pbf`) and a sprite sheet
    (`.json` index + `.png`/`@2x.png`)
  source: `config.config.GLYPHS_URL` / `SPRITE_URL`, same provider as the tiles
  semantics: read-only. Glyph ranges are fetched lazily per code point and
    cached forever in one atlas texture; four ranges covering Latin and
    Vietnamese are preloaded at start-up so labels do not arrive in visible
    waves
  lifecycle: sprite loaded once at start-up; glyph ranges loaded on first use

- port: device_position
  type: `GeolocationPosition` from `navigator.geolocation.watchPosition`
  source: the device's receiver, via the browser. Secure context only
  semantics: turned into `{lon, lat, accuracy, speedKph, heading, timestamp}` by `gps.js`;
    fixes worse than `NAV_GPS_MAX_ACCURACY_M` are dropped
  lifecycle: continuous once the person allows location

- port: navigation_server
  type: JSON over HTTP, `/api/v1/*` on this origin, forwarded to `NAV_SERVER_URL`
  source: the server block -- `POST /route`, `GET /mapdata/address`, `POST /ingest/probes`
  semantics: this block computes no route and no address; it asks and draws
  lifecycle: on a tap (route), on moving 25 m (address), every 15 s (probes)

## Outputs

- port: frame
  type: pixels on `<canvas id="gl">`
  destination: the screen
  semantics: the basemap for the current camera; painter's order is `style.buckets`
  lifecycle: one per `requestAnimationFrame`

- port: camera_state
  type: `{worldX, worldY, zoom}` in world-Z0 Mercator pixels relative to the configured origin
  destination: `driver.js`, which moves it to follow the vehicle until the person drags the map
  semantics: authoritative view state; written only by input handling
  lifecycle: continuous

- port: restyle_range
  type: `Bucket.setStyleRange(startVertex, count, styleIndex) -> bytesUploaded`
  destination: not yet consumed. `traffic`, `road_condition` and `navigation` will
    call it to recolour segments -- traffic level, a closure, the active route --
    without rebuilding a buffer
  semantics: rewrites the style attribute of a contiguous vertex run and uploads
    only the bytes that run covers
  lifecycle: on demand

- port: draw_statistics
  type: per-bucket triangle and byte counts, resident and in-flight tile counts,
    fps, labels drawn / on-screen / resident
  destination: the HUD today; a benchmark harness later
  semantics: measured values, never targets
  lifecycle: sampled twice a second
