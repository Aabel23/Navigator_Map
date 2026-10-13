"""The HTTP surface. One blueprint per subsystem it exposes.

The whole public API is the five modules here, and it is deliberately small:
route calculation, map-data access, traffic state, road state, ingest, health.
Adding an endpoint means a client needs something it cannot express today, not
that a subsystem grew a method worth publishing.

A handler parses, calls one application service, and serialises. Anything more
belongs one layer down.
"""

from .health import blueprint as health_blueprint
from .ingest import blueprint as ingest_blueprint
from .mapdata import blueprint as mapdata_blueprint
from .roadstate import blueprint as roadstate_blueprint
from .route import blueprint as route_blueprint
from .traffic import blueprint as traffic_blueprint

#: Mounted under /api/v1.
API_BLUEPRINTS = (
    route_blueprint,
    mapdata_blueprint,
    traffic_blueprint,
    roadstate_blueprint,
    ingest_blueprint,
)

#: Mounted at the root -- a health check should not be versioned.
ROOT_BLUEPRINTS = (health_blueprint,)

__all__ = ["API_BLUEPRINTS", "ROOT_BLUEPRINTS"]
