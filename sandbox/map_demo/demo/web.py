"""The demo's HTTP layer: a page, the map's assets, and a way through to the API.

Deliberately thin. Everything the page asks for is either a static file or a
call the server answers, and this module makes no decision about navigation at
all — there is no routing here, no cost model, no traffic logic, no graph. If
this file ever grows one, the demo has stopped being a client.

Three things it serves:

* ``/`` and ``/demo/*`` -- the demo's own page and its two assets.
* ``/static/*`` and ``/api/config`` -- the **client map block**, unchanged.
  The renderer, the decode worker, the label engine and the style are the real
  ones, byte for byte, and the configuration endpoint is the map block's own
  view function rather than a copy.
* ``/api/v1/*`` -- passed to the server through :mod:`demo.link`.

The passthrough exists for one unglamorous reason: a page served from this
origin cannot call a server on another one without the server sending CORS
headers, and adding those to `server/api/` to satisfy a sandbox would be the
sandbox reaching into a block. Same origin, no headers, nothing touched.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

from .blocks import DEMO_ROOT, MAP_STATIC_DIR, load_map_config_view
from .link import LinkError, ServerLink

__all__ = ["create_app"]

_DEMO_STATIC = DEMO_ROOT / "demo" / "static"
_DEMO_TEMPLATES = DEMO_ROOT / "demo" / "templates"

#: Passed through verbatim. The list is short on purpose -- a demo that could
#: reach any path would stop documenting which six endpoints a client needs.
_ALLOWED = (
    "route",
    "mapdata/roads",
    "mapdata/graph",
    "traffic",
    "traffic/levels",
    "roadstate",
    "ingest/probes",
    "ingest/reports",
    "ingest/refresh",
)


def create_app(link: ServerLink, *, default_area: str) -> Flask:
    """Build the demo application over an already-chosen server link."""
    app = Flask(
        __name__,
        static_folder=str(MAP_STATIC_DIR),
        static_url_path="/static",
        template_folder=str(_DEMO_TEMPLATES),
    )

    # The map block's own configuration endpoint, borrowed rather than copied.
    app.add_url_rule("/api/config", "map_api_config", load_map_config_view())

    @app.get("/")
    def index() -> str:
        return render_template("index.html", page_title="Navigation demo")

    @app.get("/demo/<path:filename>")
    def demo_static(filename: str) -> Any:
        return send_from_directory(_DEMO_STATIC, filename)

    @app.get("/api/demo/info")
    def info() -> Any:
        """What this page is talking to, and where it should start looking."""
        status, health = _safe(link.get, "/health/info")
        return jsonify(
            {
                "link": link.describe(),
                "default_area": default_area,
                "health_status": status,
                "health": health,
            }
        )

    @app.route("/api/v1/<path:rest>", methods=["GET", "POST", "DELETE"])
    def passthrough(rest: str) -> Any:
        head = rest.split("/", 2)
        if rest not in _ALLOWED and head[0] != "roadstate":
            return jsonify({"status": "error", "error": f"/api/v1/{rest} is not exposed"}), 404

        path = f"/api/v1/{rest}"
        try:
            if request.method == "GET":
                status, body = link.get(path, request.args.to_dict())
            elif request.method == "POST":
                status, body = link.post(path, request.get_json(silent=True) or {})
            else:
                status, body = link.delete(path)
        except LinkError as err:
            # Not an error the server returned -- an error reaching it at all.
            return jsonify({"status": "error", "code": "link_down", "error": str(err)}), 502
        return jsonify(body if body is not None else {}), status

    return app


def _safe(call: Any, *args: Any) -> tuple[int, Any]:
    try:
        return call(*args)
    except LinkError as err:
        return 502, {"error": str(err)}
