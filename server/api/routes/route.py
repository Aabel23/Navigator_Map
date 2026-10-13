"""POST /api/v1/route -- the central flow of the whole server.

    Mobile app
        │  POST /api/v1/route   {origin, destination, ...}
        ▼
    this handler          parse, call, serialise -- and nothing else
        ▼
    RoutingService        choose the area, snap, price, constrain
        ├── MapGraphProvider     (mapdata)
        ├── TrafficCostProvider  (traffic)
        └── RoadStateProvider    (roadstate)
        ▼
    Router                A* over the graph
        ▼
    Route  ──▶  route_payload  ──▶  JSON

Read the body of :func:`post_route` and notice what is not in it: no graph, no
cost model, no search, no database, no provider. Three statements. That is the
architecture rule from the brief -- *the API layer orchestrates, the routing
subsystem computes* -- and the way to keep it is to be suspicious of any line
added to this file that is not parsing or serialising.

Traffic is refreshed before the route is computed, not after, and not on a
timer: the area that needs to be fresh is the one being routed across, and
this is the moment that is known. The refresh is debounced and never raises --
a stale or missing traffic picture makes the route worse, and failing the
request would make it absent.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from domain import BBox

from ..schemas import parse_route_request, route_payload

blueprint = Blueprint("route", __name__)


@blueprint.post("/route")
def post_route():
    """Compute a route between two coordinates."""
    services = current_app.extensions["services"]

    query = parse_route_request(request.get_json(silent=True))
    area = BBox.covering(
        [point.as_tuple() for point in query.points],
        pad_degrees=services.routing.policy.pad_degrees,
    )
    refreshed = query.use_traffic and services.traffic.ensure_fresh(area)
    route = services.routing.route(query)

    return jsonify(
        route_payload(
            route,
            query=query,
            meta={
                "area": list(area.as_tuple()),
                "traffic_used": query.use_traffic and services.traffic.enabled,
                "traffic_refreshed": refreshed,
                "waypoints": len(query.waypoints),
            },
        )
    )
