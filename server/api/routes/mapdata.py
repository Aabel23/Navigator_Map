"""GET /api/v1/mapdata/roads -- the server-side road network, as data.

This is map *data*, not a map. It returns the road segments the server
computes with -- geometry, class, free-flow reference, one-way flag -- and it
is not a tile endpoint, a style, or anything a renderer consumes directly. The
client draws its basemap from vector tiles it fetches itself; what it cannot
get from a tile is the server's own view of the network, which is what a
client needs to highlight one segment, show a closure on the right street, or
explain why a route went the way it did.

GeoJSON, because it is the one format every mapping client already reads.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from mapdata import MapDataError, SourceUnavailable

from ..schemas import bbox_payload, parse_bbox

blueprint = Blueprint("mapdata", __name__)

#: Most segments one response may carry. A city-wide box is several tens of
#: thousands of ways and tens of megabytes; a client that wants that much
#: should ask for it in pieces, and one that asked by accident should get a
#: clear answer rather than a timeout.
MAX_SEGMENTS = 5000


@blueprint.get("/mapdata/roads")
def get_roads():
    """Road segments intersecting a bounding box."""
    services = current_app.extensions["services"]
    area = parse_bbox(request.args.get("bbox"), default=services.default_area())

    segments = list(_roads(services, area))
    truncated = len(segments) > MAX_SEGMENTS

    return jsonify(
        {
            "status": "ok",
            **bbox_payload(area),
            "count": min(len(segments), MAX_SEGMENTS),
            "truncated": truncated,
            "type": "FeatureCollection",
            "features": [_feature(segment) for segment in segments[:MAX_SEGMENTS]],
        }
    )


@blueprint.get("/mapdata/graph")
def get_graph_summary():
    """How the routable graph for an area came out.

    Counts, not contents. The graph is an internal structure and publishing it
    would make every consumer depend on how ways are split; what is useful
    outside is whether it built and how big it is, which is what a client or
    an operator checks when a route looks wrong.
    """
    services = current_app.extensions["services"]
    area = parse_bbox(request.args.get("bbox"), default=services.default_area())
    view = services.graphs.graph_for(area)
    return jsonify({"status": "ok", **bbox_payload(view.area), **view.summary()})


def _roads(services, area):
    """Ask the road network, and let one error type out.

    A road source is an adapter over something external -- Overpass, a file, a
    database -- and each has its own exception type. Translating them here is
    what lets the error middleware map "upstream is down" to 503 without
    knowing which upstream, and keeps a socket timeout from surfacing as a 500
    that says this server is broken when it is not.
    """
    try:
        return services.roads.roads(area)
    except MapDataError:
        raise
    except Exception as err:  # noqa: BLE001 - one error type leaves this boundary
        raise SourceUnavailable(f"road network unavailable: {err}") from err


def _feature(segment) -> dict:
    return {
        "type": "Feature",
        "id": segment.id,
        "geometry": {
            "type": "LineString",
            "coordinates": [list(point) for point in segment.geometry],
        },
        "properties": {
            "id": segment.id,
            "road_class": segment.road_class,
            "free_flow_kph": segment.free_flow_kph,
            "name": segment.name,
            "oneway": segment.oneway,
            "length_m": round(segment.length_m, 1),
        },
    }
