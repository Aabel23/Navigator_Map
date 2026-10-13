"""API -- the server's external surface, and the only place Flask exists.

    from api import create_app

    app = create_app()
    app.run()

Owns:
    HTTP transport, request validation, response serialisation, error
    mapping, request logging, and the composition root that wires every
    subsystem together at startup

Does not own:
    any computation. A handler parses a request, calls one application
    service, and serialises the result. The route is computed by `routing`,
    the traffic picture by `traffic`, the conditions by `roadstate`, the
    network by `mapdata`. None of them knows this layer exists.

The public API is deliberately small -- route calculation, map-data access,
traffic state, road state, ingest, health -- and public responses never expose
an internal class or a database structure. Stable ids are published because a
client genuinely needs them; internal shapes are not.
"""

from .app import API_PREFIX, create_app
from .composition import Services, build_services

__all__ = ["create_app", "build_services", "Services", "API_PREFIX"]
