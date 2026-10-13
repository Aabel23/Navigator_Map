"""The HTTP surface of the simulator.

Two things here are worth knowing.

**The map block's page assets are served unchanged.** ``/static`` points
straight at ``server/map/ui/static``, so the renderer, the decode worker, the
label engine and the style are the real ones, byte for byte. If the simulator
draws a road in the wrong place, that is the simulator's fault and nowhere
else.

**The map block's own configuration endpoint is reused, not copied.** The
sandbox borrows the view function out of the map block's Flask app and
registers it on its own. A copied ``/api/config`` would be a second opinion
about the tile source and the style, and it would drift the first time either
changed.

Everything the simulator itself adds lives under ``/api/sim``.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

from .blocks import MAP_STATIC_DIR, SANDBOX_ROOT, create_map_app, level_payload
from .settings import DEFAULT_REGION, REGIONS, TUNING
from .world import Simulator

__all__ = ["create_app"]

_SANDBOX_STATIC = SANDBOX_ROOT / "static"


def create_app(region_key: str = DEFAULT_REGION) -> Flask:
    """Build the sandbox Flask application and start its simulator."""
    if region_key not in REGIONS:
        raise KeyError(f"unknown region {region_key!r}; known: {sorted(REGIONS)}")

    app = Flask(
        __name__,
        static_folder=str(MAP_STATIC_DIR),
        static_url_path="/static",
        template_folder=str(SANDBOX_ROOT / "templates"),
    )

    # The map block's app is constructed only to lift one view out of it. It
    # is never served; nothing else on it is registered here.
    map_app = create_map_app()
    app.add_url_rule("/api/config", "map_api_config", map_app.view_functions["api_config"])

    simulator = Simulator(region_key)
    app.extensions["simulator"] = simulator

    # -- the page -------------------------------------------------------------

    @app.get("/")
    def index() -> str:
        return render_template("index.html", page_title="map + routing + traffic simulator")

    @app.get("/sim-static/<path:filename>")
    def sandbox_static(filename: str) -> Any:
        return send_from_directory(_SANDBOX_STATIC, filename)

    # -- what the page needs once ---------------------------------------------

    @app.get("/api/sim/boot")
    def boot() -> Any:
        """Everything that does not change while the simulator is running."""
        return jsonify(
            {
                "regions": [
                    {
                        "key": region.key,
                        "label": region.label,
                        "bbox": list(region.bbox),
                        "center": list(region.center),
                        "zoom": region.zoom,
                        "measured": region.measured,
                        "note": region.note,
                    }
                    for region in REGIONS.values()
                ],
                # The level table is served rather than hard-coded, exactly as
                # the map block serves its style: the page ships no opinion
                # about what "heavy" looks like.
                **level_payload(),
                "tuning": {
                    "traffic_match_radius_m": TUNING.traffic_match_radius_m,
                    "max_multiplier": TUNING.max_multiplier,
                    "max_snap_distance_m": TUNING.max_snap_distance_m,
                    "gps_accuracy_m": TUNING.gps_accuracy_m,
                    "drive_time_scale": TUNING.drive_time_scale,
                },
            }
        )

    # -- state ----------------------------------------------------------------

    @app.get("/api/sim/state")
    def state() -> Any:
        return jsonify(simulator.state())

    @app.get("/api/sim/traffic")
    def traffic() -> Any:
        """The current snapshot as GeoJSON, straight from the traffic block.

        ``TrafficSnapshot.to_geojson()`` is the traffic block's own published
        rendering of itself. The overlay draws that and nothing else, so what
        is on screen is what the block said, not the sandbox's paraphrase.
        """
        return jsonify(simulator.traffic_geojson())

    # -- controls -------------------------------------------------------------

    @app.post("/api/sim/region")
    def set_region() -> Any:
        key = str(_body().get("key", ""))
        if key not in REGIONS:
            return jsonify({"error": f"unknown region {key!r}"}), 400
        simulator.set_region(key)
        return jsonify(simulator.state())

    @app.post("/api/sim/gps")
    def set_gps() -> Any:
        body = _body()
        if "noise" in body:
            simulator.set_noise(bool(body["noise"]))
            return jsonify(simulator.state())
        point = _point(body)
        if point is None:
            return jsonify({"error": "expected lon and lat, or noise"}), 400
        return jsonify(simulator.place_gps(point))

    @app.post("/api/sim/destination")
    def set_destination() -> Any:
        point = _point(_body())
        if point is None:
            return jsonify({"error": "expected lon and lat"}), 400
        return jsonify(simulator.set_destination(point))

    @app.delete("/api/sim/destination")
    def clear_destination() -> Any:
        return jsonify(simulator.clear_destination())

    @app.post("/api/sim/drive")
    def drive() -> Any:
        return jsonify(simulator.drive(bool(_body().get("on", True))))

    @app.post("/api/sim/rebuild")
    def rebuild() -> Any:
        return jsonify(simulator.rebuild())

    return app


def _body() -> dict[str, Any]:
    return request.get_json(silent=True) or {}


def _point(body: dict[str, Any]) -> tuple[float, float] | None:
    """Read a ``(lon, lat)`` out of a request body.

    Longitude first, because that is the order every lon/lat pair already
    crossing this project's wire uses -- the map block's ``map.center``, the
    traffic block's GeoJSON, and Overpass' output all agree on it.
    """
    try:
        lon, lat = float(body["lon"]), float(body["lat"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    return (lon, lat)
