"""GET /api/v1/roadstate -- what is closed, flooded, dug up or blocked.

Independently queryable, which is a requirement rather than a convenience: a
client needs to show a closure on the map whether or not the driver asked for
a route through it, and an operator needs to check that the closure they
entered five minutes ago is actually in force.

The response separates what blocks from what merely slows, because that is the
distinction a driver acts on and the one routing acts on. Everything active is
returned either way -- a works site a route avoided is still worth drawing.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..schemas import bbox_payload, parse_bbox

blueprint = Blueprint("roadstate", __name__)


@blueprint.get("/roadstate")
def get_road_state():
    """Conditions in force in a bounding box."""
    services = current_app.extensions["services"]
    area = parse_bbox(request.args.get("bbox"), default=services.default_area())
    snapshot = services.road_state.snapshot(area)

    return jsonify(
        {
            "status": "ok",
            **bbox_payload(area),
            **snapshot.meta(),
            "blocking": [c.to_payload() for c in snapshot.blocking],
            "conditions": [c.to_payload() for c in snapshot.conditions],
        }
    )


@blueprint.get("/roadstate/<path:condition_id>")
def get_condition(condition_id: str):
    """One condition by id, so a reporter can check what was recorded."""
    services = current_app.extensions["services"]
    condition = services.road_state.get(condition_id)
    if condition is None:
        return jsonify({"status": "error", "code": "not_found", "error": "no such condition"}), 404
    return jsonify({"status": "ok", "condition": condition.to_payload()})


@blueprint.delete("/roadstate/<path:condition_id>")
def withdraw_condition(condition_id: str):
    """Withdraw a condition -- the road reopened, the works finished."""
    services = current_app.extensions["services"]
    removed = services.road_state.withdraw(condition_id)
    return jsonify({"status": "ok", "withdrawn": removed}), (200 if removed else 404)
