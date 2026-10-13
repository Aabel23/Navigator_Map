"""Start the server.

    python main.py                      # development, reloader off
    python main.py --check              # wire everything, report, exit

The second form is the useful one in a deployment. It builds every subsystem
exactly as a real start would -- opens the database, runs the migration, wires
the providers, runs the health checks -- and then exits with 0 or 1. A
configuration mistake surfaces there, in a second, rather than as the first
request failing.

This file deliberately does almost nothing. Everything it needs already exists
in :func:`api.create_app`, and a startup script that grew logic would be a
place the running server and the tested server could differ.

For production, hand ``api.create_app()`` to a WSGI server rather than using
this. Flask's own server is single-process and not meant for it, and
:func:`main` says so rather than leaving it to be discovered.
"""

from __future__ import annotations

import argparse
import json
import sys

from api import create_app
from config import Settings, SettingsError
from observability import configure, get_logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Navigation server")
    parser.add_argument("--host", help="override MAP_HOST")
    parser.add_argument("--port", type=int, help="override MAP_PORT")
    parser.add_argument(
        "--check",
        action="store_true",
        help="wire everything, run the health checks, print the report and exit",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except SettingsError as err:
        print(f"configuration error: {err}", file=sys.stderr)
        return 2

    configure(level=settings.log_level, as_json=settings.log_json)
    log = get_logger("startup")

    try:
        app = create_app(settings)
    except Exception as err:  # noqa: BLE001 - a startup failure must be legible
        log.exception("could not start")
        print(f"startup failed: {err}", file=sys.stderr)
        return 1

    services = app.extensions["services"]

    if args.check:
        ok, report = services.health.ready()
        print(json.dumps({"composition": services.describe(), "health": report}, indent=2, default=str))
        services.close()
        return 0 if ok else 1

    host = args.host or settings.host
    port = args.port or settings.port
    log.info("listening", extra={"host": host, "port": port})
    print(f"navigation server on http://{host}:{port}  (development server)")

    try:
        app.run(host=host, port=port, debug=settings.debug, use_reloader=False)
    finally:
        services.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
