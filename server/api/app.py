"""The Flask application factory.

A factory rather than a module-level ``app``, because a module-level one is
constructed at import time: a test could not build a second with different
settings, and importing this module would open a database. Here, nothing
happens until :func:`create_app` is called.

Flask is the only third-party dependency in the whole server, and it lives
entirely in this directory. `routing`, `mapdata`, `traffic`, `roadstate`,
`ingest`, `storage`, `domain` and `config` are standard library only, which is
what lets them be imported by a script, a test or a benchmark without a web
framework being installed -- and what would let this file be replaced by an
ASGI one without any of them noticing.

    create_app(settings)
        │
        ▶ build_services()      wire every subsystem, once
        ▶ install middleware    errors, request logging
        ▶ register blueprints   /api/v1/... and /health
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from config import Settings
from observability import configure, get_logger

from .composition import Services, build_services
from .middleware import install_error_handlers, install_request_logging
from .routes import API_BLUEPRINTS, ROOT_BLUEPRINTS

__all__ = ["create_app", "API_PREFIX"]

API_PREFIX = "/api/v1"


def create_app(
    settings: Settings | None = None, *, services: Services | None = None
) -> Flask:
    """Build the application.

    Args:
        settings: Configuration. Read from the environment when omitted.
        services: Pre-wired subsystems. Supplying them is how a test runs the
            real HTTP layer over fakes -- no database, no network, no
            monkey-patching -- and it is the reason composition is a separate
            module rather than inline here.
    """
    settings = settings or (services.settings if services else Settings.from_env())
    configure(level=settings.log_level, as_json=settings.log_json)
    log = get_logger("api")

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.extensions["services"] = services or build_services(settings)
    app.extensions["settings"] = settings

    install_request_logging(app)
    install_error_handlers(app)

    for blueprint in API_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    for blueprint in ROOT_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.get("/")
    def index() -> Any:
        """What this server is and what it answers. The only unversioned page.

        Served because a person who reaches the root of an API deserves
        something better than a 404, and because the endpoint list is the
        cheapest possible documentation to keep true -- it is generated from
        the routes actually registered.
        """
        return jsonify(
            {
                "status": "ok",
                "service": "navigation server",
                "api": API_PREFIX,
                "endpoints": sorted(
                    f"{sorted(rule.methods & {'GET', 'POST', 'DELETE', 'PUT'})[0]} {rule.rule}"
                    for rule in app.url_map.iter_rules()
                    if rule.endpoint != "static"
                ),
            }
        )

    log.info(
        "server composed",
        extra={
            "storage": app.extensions["services"].storage.name,
            "traffic": settings.traffic_enabled,
            "roadstate": settings.roadstate_enabled,
        },
    )
    return app
