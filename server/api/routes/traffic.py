"""GET /api/v1/traffic -- how fast the network is moving, and how sure we are.

Two things this endpoint does that a naive one would not, both because the
alternative misleads a driver:

* **It says where the numbers came from.** ``simulated: true`` means every
  reading in the response is modelled rather than measured, and a client is
  expected to show that. There is no free live traffic feed for Vietnam; a
  server that returned a plausible-looking model with no label would be
  inventing measurements.
* **It reports which sources failed.** A city that looks free-flowing because
  a feed timed out is worse than one that says the feed timed out.

The level table is served rather than documented -- ``GET /api/v1/traffic/levels``
-- so a renderer ships no opinion of its own about what "heavy" looks like and
cannot drift from the server that decides it.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from traffic import level_payload

from ..schemas import bbox_payload, parse_bbox

blueprint = Blueprint("traffic", __name__)


@blueprint.get("/traffic")
def get_traffic():
    """Current road speeds for a bounding box."""
    services = current_app.extensions["services"]
    area = parse_bbox(request.args.get("bbox"), default=services.default_area())

    roads = services.roads.roads(area)
    snapshot = services.traffic.snapshot(area, roads)

    return jsonify(
        {
            "status": "ok",
            **bbox_payload(area),
            **snapshot.meta(),
            "roads": [speed.to_payload() for speed in snapshot.worst_first()],
        }
    )


@blueprint.get("/traffic/levels")
def get_levels():
    """The level table: thresholds, labels and colours."""
    return jsonify({"status": "ok", **level_payload()})
