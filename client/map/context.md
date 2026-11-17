# Block Context

MODULE: map
PURPOSE: Draw the basemap. Decode vector tiles, turn them into GPU geometry and labels, and render both at interactive frame rates on a phone-class device.
ENTRY: `main.py` (dev server) -> `ui/view.py` (Flask) -> `ui/static/app.js` (the page)

INPUT:
- vector tiles (Mapbox Vector Tile / OpenMapTiles schema) over HTTP, located by TileJSON
- SDF glyph ranges and a sprite sheet, over HTTP, from the same tile provider
- camera intent: pan, zoom, recentre

OUTPUT:
- pixels on a canvas
- a camera the rest of the system can read (`{worldX, worldY, zoom}`, world-Z0 pixels relative to a fixed origin)

READ FIRST:
- `ui/static/app.js` — the plan: camera, scheduler, worker pool, eviction. Computes *what* should exist, never *what it looks like*.
- `contract.md` — when anything crosses the block boundary.
- `config/style.py` — when the question is visual. It is the only place colours, widths and per-class zoom gates live.

COMMON TASKS:
- change a colour, a road width, or the zoom a class appears at → `config/style.py`, nothing else
- add a source layer or a feature class → a row in `config/style.py`'s `RULES`; the decoder and renderer need no change
- add or restyle a label (a new POI class, a bigger place name) → `config/style.py`'s `LABEL_STYLES` / `LABEL_RULES`
- tune caching, prefetch, simplification, label placement cadence → `config/config.py`
- change how a polygon becomes triangles → `ui/static/earcut.js` (+ `tests/test_earcut.mjs`)
- change how a road (or a label's line placement) becomes a ribbon or an anchor → `ui/static/lines.js` (+ `tests/test_lines.mjs`)
- change what is read out of a tile, geometry or labels → `ui/static/mvt.js` (+ `tests/test_mvt_decode.mjs`)
- change how a glyph range is decoded, or how the atlas is packed → `ui/static/glyphs.js` (+ `tests/test_glyphs.mjs`)
- change how text or icons are laid out, or which labels win a collision → `ui/static/labels.js` / `collision.js` / `placement.js` (+ `tests/test_labels.mjs`)
- change how geometry or labels reach the GPU, or how they are drawn → `ui/static/gl.js`

DEPENDENCIES:
- no imports from other blocks. The block talks to a tile source over HTTP and to WebGL2.
- the navigation server, over HTTP only: `/api/v1/*` is forwarded to `NAV_SERVER_URL` by `ui/view.py` (route, address, probes). The page follows the driver with `ui/static/gps.js` + `driver.js` + `overlay.js`; see README "The driver".

OPTIONAL CONTEXT:
- `README.md` — what is deliberately specialised here, and what is deliberately still missing.
- `ui/static/tile_math.js` — Web Mercator and tile arithmetic; stable, rarely the answer.

DO NOT READ BY DEFAULT:
- unrelated blocks
- sandbox
