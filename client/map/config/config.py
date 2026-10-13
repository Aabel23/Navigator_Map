"""Central configuration for the map block.

Two files configure this block and they divide cleanly:

* ``config.py`` -- *how the pipeline runs*: where tiles come from, how many
  stay resident, how far ahead to prefetch, how hard to simplify.
* ``style.py`` -- *what the map looks like*: colours, widths, and the zoom at
  which each feature class starts existing.

Nothing is hard-coded into the page. Both arrive over ``/api/config``, so a
restyle or a retune is a server-side change with no JavaScript edit.
"""

from __future__ import annotations

import os

__all__ = [
    "HOST",
    "PORT",
    "DEBUG",
    "PAGE_TITLE",
    "TILEJSON_URL",
    "DATA_MIN_ZOOM",
    "DATA_MAX_ZOOM",
    "MAX_CAMERA_OVERZOOM",
    "MAP_CENTER",
    "MAP_ZOOM",
    "RESIDENT_TILE_CAP",
    "PREFETCH_RING_TILES",
    "PREFETCH_MIN_SPEED_PX_S",
    "SIMPLIFY_TOLERANCE_UNITS",
    "GLYPHS_URL",
    "SPRITE_URL",
    "LABEL_FONT",
    "GLYPH_PRELOAD_RANGES",
    "LABEL_PLACEMENT_INTERVAL_MS",
    "ATTRIBUTION",
]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


# -- Server ------------------------------------------------------------------

HOST: str = os.getenv("MAP_HOST", "127.0.0.1")
PORT: int = _env_int("MAP_PORT", 1520)
DEBUG: bool = os.getenv("MAP_DEBUG", "").strip().lower() in {"1", "true", "yes"}

PAGE_TITLE: str = os.getenv("MAP_TITLE", "Map")

# -- Tile source ---------------------------------------------------------
# Free, keyless OpenFreeMap vector tiles, read with this project's own decoder
# and renderer rather than MapLibre GL JS. The TileJSON is fetched by the page
# at start-up instead of a raw tile URL being baked in here: OpenFreeMap's tile
# path carries a build timestamp that changes over time, and TileJSON is the
# mechanism that exists to say what the current one is.

TILEJSON_URL: str = os.getenv("MAP_TILEJSON", "https://tiles.openfreemap.org/planet")

#: Fallback zoom bounds, used only until the fetched TileJSON supplies its own.
DATA_MIN_ZOOM: int = _env_int("MAP_MIN_ZOOM", 0)
DATA_MAX_ZOOM: int = _env_int("MAP_MAX_ZOOM", 14)

#: How far past the deepest available tile zoom the camera may still go. The
#: source stops at z14; a driver needs to see the street they are on, so those
#: tiles are drawn scaled up rather than the zoom being refused.
MAX_CAMERA_OVERZOOM: int = _env_int("MAP_MAX_OVERZOOM", 5)

#: Initial view: Ho Chi Minh City, District 1.
MAP_CENTER: tuple[float, float] = (
    _env_float("MAP_CENTER_LAT", 10.7769),
    _env_float("MAP_CENTER_LON", 106.7009),
)
MAP_ZOOM: float = _env_float("MAP_ZOOM", 16.0)

# -- Pipeline ----------------------------------------------------------------

#: Tiles kept resident (decoded and uploaded) before the least-recently-seen
#: ones are evicted and their buckets compacted. A downtown z14 tile decoded
#: with buildings costs roughly 0.7 MB of GPU memory, so this cap is a memory
#: budget as much as a cache size.
RESIDENT_TILE_CAP: int = _env_int("MAP_RESIDENT_CAP", 48)

#: How many extra tiles beyond the visible rectangle are requested ahead of
#: the camera's recent direction of travel.
PREFETCH_RING_TILES: int = _env_int("MAP_PREFETCH_RING", 2)

#: Below this camera speed (screen pixels per second) the direction estimate is
#: too noisy to trust, and prefetch falls back to the plain surrounding margin.
PREFETCH_MIN_SPEED_PX_S: float = _env_float("MAP_PREFETCH_MIN_SPEED", 40.0)

#: Vertices closer than this, in tile-local units on a 4096 extent, are dropped
#: from *lines* during decode. Polygons are never simplified: moving a shared
#: boundary vertex opens a gap between two fills that used to touch.
SIMPLIFY_TOLERANCE_UNITS: float = _env_float("MAP_SIMPLIFY_TOLERANCE", 2.0)

# -- Labels ------------------------------------------------------------------
# Glyphs and icons come from the same keyless, open service as the tiles.
# Unlike the tiles, their locations are not advertised anywhere machine
# readable, so they are configured rather than discovered.

#: Signed-distance-field glyph ranges, 256 code points per request.
GLYPHS_URL: str = os.getenv(
    "MAP_GLYPHS_URL", "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
)

#: The icon sheet, without its `.json` / `.png` suffix.
SPRITE_URL: str = os.getenv("MAP_SPRITE_URL", "https://tiles.openfreemap.org/sprites/ofm_f384/ofm")

LABEL_FONT: str = os.getenv("MAP_LABEL_FONT", "Noto Sans Regular")

#: Fetched at start-up rather than discovered tile by tile, so labels do not
#: arrive in visible waves. Between them these four blocks cover Latin,
#: Vietnamese (both the D-with-stroke and every tone-marked vowel), and the
#: combining marks a decomposed name would use.
GLYPH_PRELOAD_RANGES: list[str] = [
    r.strip()
    for r in os.getenv("MAP_GLYPH_RANGES", "0-255,256-511,768-1023,7680-7935").split(",")
    if r.strip()
]

#: Label placement is redone whenever the camera moves, but no more often than
#: this. Below roughly 60 ms the work stops being free on a phone; above
#: roughly 150 ms the labels visibly lag the map.
LABEL_PLACEMENT_INTERVAL_MS: int = _env_int("MAP_PLACEMENT_INTERVAL_MS", 90)

ATTRIBUTION: str = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    " contributors &middot; tiles by"
    ' <a href="https://openfreemap.org/">OpenFreeMap</a>'
)
