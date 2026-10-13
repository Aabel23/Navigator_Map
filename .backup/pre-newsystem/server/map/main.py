"""Entry point for the map block.

    python main.py
    python main.py --port 8080

Serves one page: a WebGL2 basemap reading real vector tiles through this
project's own decoder -- polygons triangulated and roads extruded on worker
threads, one shared GPU buffer per bucket for the whole map, styling carried on
vertex attributes rather than paid for in draw calls.
"""

from __future__ import annotations

import argparse

from config import config
from ui.view import create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="main.py", description="Serve the specialised map.")
    parser.add_argument(
        "--host", default=config.HOST, help=f"bind address (default: {config.HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=config.PORT, help=f"port (default: {config.PORT})"
    )
    parser.add_argument(
        "--debug", action="store_true", default=config.DEBUG, help="Flask debug mode"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = create_app()
    print(f"open http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
