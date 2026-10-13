"""The public shape of a route request and a route response.

This module is the translation layer, and translating is all it does. A
:class:`routing.RouteQuery` goes in one direction and a
:class:`routing.Route` comes back the other; neither knows JSON exists, and
that is what lets the routing engine be tested, benchmarked and replaced
without an HTTP server anywhere near it.

The response is deliberately not the internal object with its fields renamed.
Two differences matter:

* **``total_cost`` is not published.** It is what the search minimised, in the
  cost mode's own unit, and it may be penalty-weighted. A client that found it
  in the response would eventually show it to someone as a duration. The ETA
  is ``duration_s``, which comes from ``Route.travel_time`` and is real
  seconds by construction.
* **Geometry is published as GeoJSON, longitude first.** Routing stores points
  latitude-first because its contract says so. Publishing that order would
  make every client that draws the route do the flip, and one of them would
  forget.

Internal ids -- node ids, edge ids -- *are* published. They are stable, they
are how a client asks about one segment's traffic, and they are documented as
part of the contract rather than leaking by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from domain import GeoPoint
from routing import Route, RouteQuery

from .geo import ApiError, parse_point, parse_points

__all__ = ["parse_route_request", "route_payload", "PROFILES", "COST_MODES"]

#: Accepted values, checked here so a typo is a 400 with a list of options
#: rather than a 500 from inside the cost model.
PROFILES = ("car", "truck", "motorbike", "bicycle", "pedestrian")
COST_MODES = ("fastest", "shortest")

#: Most waypoints one request may carry. Each is a separate search, so an
#: unbounded list is an unbounded amount of work for one request.
MAX_WAYPOINTS = 24


def parse_route_request(body: Mapping[str, Any] | None) -> RouteQuery:
    """Turn a JSON body into the routing subsystem's own request type.

    Raises:
        ApiError: the body cannot be read. Every message names the field, so a
            client gets to fix it rather than guess.
    """
    if not isinstance(body, Mapping):
        raise ApiError("a route request needs a JSON object body")

    origin = parse_point(body.get("origin"), field="origin")
    destination = parse_point(body.get("destination"), field="destination")
    waypoints = parse_points(body.get("waypoints"), field="waypoints")
    if len(waypoints) > MAX_WAYPOINTS:
        raise ApiError(
            f"waypoints: at most {MAX_WAYPOINTS} allowed, got {len(waypoints)}",
            field="waypoints",
        )

    profile = str(body.get("profile", "car")).lower()
    if profile not in PROFILES:
        raise ApiError(f"profile must be one of {', '.join(PROFILES)}", field="profile")

    cost_mode = str(body.get("cost_mode", "fastest")).lower()
    if cost_mode not in COST_MODES:
        raise ApiError(f"cost_mode must be one of {', '.join(COST_MODES)}", field="cost_mode")

    return RouteQuery(
        origin=origin,
        destination=destination,
        waypoints=waypoints,
        profile=profile,
        cost_mode=cost_mode,
        departure=_departure(body.get("departure")),
        avoid_road_classes=frozenset(
            str(value) for value in body.get("avoid_road_classes", ()) if value
        ),
        allow_u_turns=bool(body.get("allow_u_turns", False)),
        use_traffic=bool(body.get("use_traffic", True)),
    )


def route_payload(route: Route, *, query: RouteQuery, meta: Mapping[str, Any]) -> dict[str, Any]:
    """The public response for one computed route."""
    return {
        "status": "ok",
        "distance_m": round(route.distance, 1),
        "duration_s": round(route.travel_time, 1),
        "cost_mode": route.cost_mode,
        "profile": query.profile,
        "geometry": {
            "type": "LineString",
            "coordinates": [[point.longitude, point.latitude] for point in route.geometry],
        },
        "segments": list(route.segments),
        "nodes": list(route.nodes),
        "steps": [_step_payload(step) for step in route.steps],
        "meta": dict(meta),
    }


def _step_payload(step) -> dict[str, Any]:
    return {
        "maneuver": step.maneuver.value,
        "name": step.name,
        "distance_m": round(step.distance, 1),
        "duration_s": round(step.travel_time, 1),
        "from_node": step.from_node,
        "to_node": step.to_node,
        "segments": list(step.segments),
        "bearing_before": step.bearing_before,
        "bearing_after": step.bearing_after,
        "geometry": {
            "type": "LineString",
            "coordinates": [[point.longitude, point.latitude] for point in step.geometry],
        },
    }


def _departure(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        moment = raw
    else:
        try:
            moment = datetime.fromisoformat(str(raw))
        except ValueError as err:
            raise ApiError(f"departure: {err}", field="departure") from err
    if moment.tzinfo is None:
        raise ApiError(
            "departure must carry a timezone offset; the server will not guess "
            "one, because a guess is wrong by whole hours with nothing looking "
            "broken",
            field="departure",
        )
    return moment
