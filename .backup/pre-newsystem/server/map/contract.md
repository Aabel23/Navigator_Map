# Block Contract

BLOCK: map
VERSION: 1

PURPOSE:
Turn a tile source and a camera into a drawn basemap, at a frame rate a moving
vehicle can be navigated from.

INPUTS:
- name: tile source
  type: TileJSON URL, resolving to `{z}/{x}/{y}.pbf` Mapbox Vector Tiles in the
    OpenMapTiles schema
  meaning: where the geometry comes from. Supplied by configuration, fetched at
    start-up rather than baked in, because the tile path can change under a
    stable TileJSON URL.

- name: style
  type: the payload of `config/style.py:style_payload()` -- background colour,
    zoom stops, bucket draw order, an ordered fill style table, an ordered line
    style table, a rule per source layer, an ordered label style table, and a
    label rule per name-bearing source layer
  meaning: the entire visual language, geometry and text alike. Style indices
    are positions in the ordered tables and are carried on vertices, so the
    tables may be appended to but never reordered without re-decoding every
    resident tile.

- name: glyphs and sprite
  type: an SDF glyph-range endpoint (`{fontstack}/{range}.pbf`) and a sprite
    sheet (`.json` index + `.png`/`@2x.png` bitmap), both from
    `config/config.py`
  meaning: the second supply chain text and icons come from, independent of
    the tile source. Neither is required for the basemap to draw -- if this
    service is unreachable the map still renders, only without labels.

- name: camera
  type: `{worldX: number, worldY: number, zoom: number}`
  meaning: world-Z0 Mercator pixels relative to the configured origin, plus a
    fractional zoom. Written by input handling; readable by anything that needs
    to know what the driver is looking at.

OUTPUTS:
- name: rendered frame
  type: pixels on the supplied `<canvas>`
  meaning: the basemap for the current camera and the currently resident tiles.

- name: draw statistics
  type: per-bucket triangle counts and byte counts, resident and in-flight tile
    counts, frames per second
  meaning: measured, not asserted. The HUD prints these; a benchmark could read
    the same values.

SEMANTICS:
- guarantees:
  - Decoding, triangulation and line extrusion happen on worker threads. No
    tile, however large, can block a frame.
  - Every resident polygon is drawn in one `drawElements` call per bucket, and
    every resident line in two (casing, then fill), regardless of how many
    tiles or feature classes are resident.
  - A feature class below its configured zoom is not decoded, not uploaded and
    not drawn -- the LOD gate is applied before the layer is parsed, not after.
  - At most two tile generations (tile zoom paired with LOD zoom) are resident
    at once. The older one is dropped as soon as the newer one covers the
    viewport, so the same street is never drawn at two zoom levels.
  - Restyling a contiguous run of vertices (`Bucket.setStyleRange`) re-uploads
    only the bytes that run covers.
  - Label placement is a greedy, priority-ordered pass over resident label
    records, redone on camera movement but throttled to
    `LABEL_PLACEMENT_INTERVAL_MS`. It never partially draws a label: a name
    either gets its full box clear of every previously-placed label, or it is
    dropped for that frame entirely.
  - A label's text is measured and shaped from glyph metrics alone, off the
    tile's geometry. A tile whose glyphs have not arrived yet contributes no
    labels until they do, but its polygons and lines draw immediately.

ERRORS:
- name: WebGL2 unavailable
  meaning: the renderer cannot be constructed; the page reports the failure
    instead of drawing. There is no 2D fallback.

- name: tile fetch failed
  meaning: logged and skipped. The tile is not marked resident, so the next
    scheduler tick retries it. A 404 is not a failure -- it means the source
    has no tile there, and it is recorded as an empty tile so it is not
    requested again.

- name: unknown style name in a rule
  meaning: raised at start-up by `style_payload()`, not at tile-decode time, so
    a typo cannot silently drop a feature class.

SIDE EFFECTS:
- HTTP GETs against the configured tile source.

PERFORMANCE:
- requirement: 7 draw calls per frame for the full basemap -- one per fill
  bucket (`land`, `water`, `building`) and two per line bucket (`waterway`,
  `road`: casing, then fill) -- plus up to 3 more for labels (icons, then
  text halo, then text fill). All independent of resident tile count; only
  the bucket and label-style tables change these numbers, never tile count.
- requirement: resident GPU geometry stays under the memory implied by
  `RESIDENT_TILE_CAP`; a dense downtown z14 tile decoded with buildings costs
  roughly 0.7 MB.
- requirement: performance-affecting changes are measured against the HUD's
  per-bucket triangle and byte counts before and after.

COMPATIBILITY:
- requirements:
  - Vertex layouts are fixed per bucket kind: fill is `[x, y, style]`, line is
    `[x, y, extrudeX, extrudeY, side, style]`. `Bucket.setStyleRange` assumes
    the style index is the last float of both.
  - Style indices are ordinal. Appending to `FILL_STYLES` or `LINE_STYLES` is
    compatible; inserting or reordering is not.
  - World coordinates are float32 relative to a fixed origin chosen at
    start-up. Precision degrades far from that origin; nothing in this version
    re-centres it.
  - Label vertices are `[anchorX, anchorY, offsetX, offsetY, angle, u, v,
    style]`. The anchor is world space; the offset is a screen-pixel vector
    rotated by `angle` in the vertex shader, which is what keeps text a
    constant size and a rotated street name pivoting about its own centre
    rather than shearing as the camera zooms.
