"""Health, readiness, and what this server was composed with.

Three endpoints, and the distinction between the first two is the one that
stops a working server from being restarted:

* ``GET /health`` -- the process is alive and can answer. Nothing is checked.
* ``GET /health/ready`` -- every critical check passes. Returns 503 when one
  does not, so a load balancer stops sending traffic without anything killing
  the process.
* ``GET /health/info`` -- what is wired up: which storage backend, which
  traffic sources, what the routing policy is. This is what someone reads
  first when a deployment behaves unlike the one next to it.

``ready`` deliberately reports *degraded* separately from *not ready*. A
missing traffic feed is degraded -- routes still compute, on free-flow speeds
-- and treating it as a hard failure would take a serving process out of
rotation over a feature that gracefully does without.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

blueprint = Blueprint("health", __name__)


@blueprint.get("/health")
def live():
    """Alive. Checks nothing, on purpose."""
    return jsonify({"status": "ok", "live": True})


@blueprint.get("/health/ready")
def ready():
    """Every critical check, run now."""
    services = current_app.extensions["services"]
    ok, report = services.health.ready()
    return jsonify({"status": "ok" if ok else "degraded", **report}), (200 if ok else 503)


@blueprint.get("/health/info")
def info():
    """What this server was composed with."""
    services = current_app.extensions["services"]
    return jsonify({"status": "ok", **services.describe()})
