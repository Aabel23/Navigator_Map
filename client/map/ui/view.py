"""Flask application: the page shell, its configuration, and a door to the server.

This block computes nothing about roads. Routes, addresses and traffic belong
to the navigation server; ``/api/v1/...`` here forwards to it unchanged, so the
page has one origin. That is what lets a phone reach everything through a
single HTTPS tunnel -- and a browser only reports GPS to a secure page.

Everything else the page needs, including the entire visual style, is served
from :mod:`config`, so the renderer ships no opinion about what a road looks
like.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

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
                "driver": {
                    "api_base": "/api/v1",
                    "max_accuracy_m": config.GPS_MAX_ACCURACY_M,
                    "follow_zoom": config.FOLLOW_ZOOM,
                    "address_min_move_m": config.ADDRESS_MIN_MOVE_M,
                    "address_min_interval_ms": config.ADDRESS_MIN_INTERVAL_MS,
                    "probes_enabled": config.PROBES_ENABLED,
                    "probe_flush_ms": config.PROBE_FLUSH_MS,
                    "probe_min_interval_ms": config.PROBE_MIN_INTERVAL_MS,
                },
            }
        )

    @app.route("/api/v1/<path:subpath>", methods=["GET", "POST", "DELETE"])
    def api_proxy(subpath: str) -> Any:
        return _forward(f"{config.SERVER_URL}/api/v1/{subpath}")

    return app


#: Request headers worth passing on. Everything else -- cookies, the tunnel's
#: own headers, Host -- describes the hop to this page, not the request.
_FORWARDED_HEADERS = ("Content-Type", "Accept", "Accept-Language")


def _forward(url: str) -> Response:
    """Send the current request to the server and relay its answer verbatim.

    The server's error bodies are already JSON with a reason; relaying them
    unchanged is what lets the page show "no road within 250 m" rather than a
    generic failure. Only an unreachable server is answered here, as a 502.
    """
    if request.query_string:
        url = f"{url}?{request.query_string.decode('latin-1')}"
    body = request.get_data() if request.method in ("POST", "DELETE") else None
    upstream = urllib.request.Request(url, data=body, method=request.method)
    for name in _FORWARDED_HEADERS:
        if name in request.headers:
            upstream.add_header(name, request.headers[name])

    try:
        with urllib.request.urlopen(upstream, timeout=config.PROXY_TIMEOUT_S) as reply:
            return _relay(reply.status, reply.headers, reply.read())
    except urllib.error.HTTPError as err:
        return _relay(err.code, err.headers, err.read())
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        payload = {
            "status": "error",
            "code": "server_unreachable",
            "error": f"không kết nối được máy chủ dẫn đường ({config.SERVER_URL}): {err}",
        }
        return Response(json.dumps(payload, ensure_ascii=False), 502, mimetype="application/json")


def _relay(status: int, headers: Any, body: bytes) -> Response:
    return Response(body, status, content_type=headers.get("Content-Type", "application/json"))
