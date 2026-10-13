"""Serialisation only. Nothing here decides anything.

A schema module reads a request into a domain value or writes a domain value
into a response. Where one starts to contain a rule -- a default that is really
a policy, a derived field that is really a computation -- that rule belongs to
the subsystem that owns the concept.
"""

from .geo import ApiError, bbox_payload, parse_bbox, parse_point, parse_points
from .route import COST_MODES, PROFILES, parse_route_request, route_payload

__all__ = [
    "ApiError",
    "parse_bbox",
    "parse_point",
    "parse_points",
    "bbox_payload",
    "parse_route_request",
    "route_payload",
    "PROFILES",
    "COST_MODES",
]
