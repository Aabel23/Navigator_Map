"""Flask application: the page shell and its one configuration endpoint.

This block draws a map and nothing else -- there is no ``/api/position`` and
no ``/api/route`` here. Everything the page needs, including the entire visual
style, is served from :mod:`config`, so the renderer ships no opinion about
what a road looks like.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template

from config import config, style

__all__ = ["create_app"]


def create_app() -> Flask:
    """Build the Flask application.

    Returns:
        A configured Flask app.
    """
    app = Flask(__name__)
    # Resolved once at start-up so a bad style rule fails loudly here rather
    # than silently dropping a road class on every tile.
    style_payload = style.style_payload()

    @app.get("/")
    def index() -> str:
        return render_template("index.html", page_title=config.PAGE_TITLE)

    @app.get("/api/config")
    def api_config() -> Any:
        return jsonify(
            {
                "page": {"title": config.PAGE_TITLE, "attribution": config.ATTRIBUTION},
                "source": {
                    "tilejson_url": config.TILEJSON_URL,
                    "min_zoom": config.DATA_MIN_ZOOM,
                    "max_zoom": config.DATA_MAX_ZOOM,
                    "max_camera_overzoom": config.MAX_CAMERA_OVERZOOM,
                },
                "map": {
                    "center": [config.MAP_CENTER[1], config.MAP_CENTER[0]],
                    "zoom": config.MAP_ZOOM,
                },
                "pipeline": {
                    "resident_tile_cap": config.RESIDENT_TILE_CAP,
                    "prefetch_ring_tiles": config.PREFETCH_RING_TILES,
                    "prefetch_min_speed_px_s": config.PREFETCH_MIN_SPEED_PX_S,
                    "simplify_tolerance_units": config.SIMPLIFY_TOLERANCE_UNITS,
                    "placement_interval_ms": config.LABEL_PLACEMENT_INTERVAL_MS,
                },
                "labels": {
                    "glyphs_url": config.GLYPHS_URL,
                    "sprite_url": config.SPRITE_URL,
                    "font": config.LABEL_FONT,
                    "preload_ranges": config.GLYPH_PRELOAD_RANGES,
                },
                "style": style_payload,
            }
        )

    return app
