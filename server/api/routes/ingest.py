"""POST /api/v1/ingest/... -- the two doors data comes in through.

Probes and reports are separate endpoints because they are separate kinds of
claim, with different consequences and different trust. A probe says "I was
here doing this speed"; the worst a bad one does is make a street look slightly
wrong for ten minutes. A report says "this road is closed"; a bad one can make
a district unreachable. Giving them one endpoint would invite one validation
path, and the strict one would lose.

Both answer with what was accepted *and* what was refused, with reasons. A
client whose submissions silently vanish has no way to discover that its field
names are wrong, and a feature believed to work while contributing nothing is
worse than one that visibly fails.

Neither endpoint interprets anything. The probe becomes an observation and
goes to `traffic`; the report goes through `roadstate`'s classifier, the same
one a Digitraffic message goes through, so a closure typed by an operator and
one published by a road authority are judged by identical rules.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..schemas import ApiError, parse_bbox

blueprint = Blueprint("ingest", __name__)

#: Most records one submission may carry. A client with more should send
#: several requests; an unbounded body is an unbounded amount of parsing.
MAX_BATCH = 500


@blueprint.post("/ingest/probes")
def post_probes():
    """Accept GPS position reports from clients."""
    services = current_app.extensions["services"]
    return jsonify({"status": "ok", **services.ingest.accept_probes(_batch("probes"))})


@blueprint.post("/ingest/reports")
def post_reports():
    """Accept incident reports -- a closure, a flood, a crash, roadworks."""
    services = current_app.extensions["services"]
    return jsonify({"status": "ok", **services.ingest.accept_reports(_batch("reports"))})


@blueprint.post("/ingest/refresh")
def post_refresh():
    """Pull every covering traffic feed for an area, now.

    Exposed because the lazy refresh is driven by route requests, and an
    operator warming a city before a rush hour -- or checking that a feed
    works at all -- should not have to fake one.
    """
    services = current_app.extensions["services"]
    body = request.get_json(silent=True) or {}
    area = parse_bbox(body.get("bbox") or request.args.get("bbox"), default=services.default_area())
    return jsonify({"status": "ok", **services.ingest.refresh(area)})


def _batch(field: str) -> list:
    body = request.get_json(silent=True)
    records = body.get(field) if isinstance(body, dict) else body
    if records is None:
        raise ApiError(f"expected a JSON body with a {field!r} list", field=field)
    if not isinstance(records, list):
        raise ApiError(f"{field} must be a list", field=field)
    if len(records) > MAX_BATCH:
        raise ApiError(f"{field}: at most {MAX_BATCH} per request", field=field)
    return records
