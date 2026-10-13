"""Entry point for the navigation demo.

    python main.py                              server in-process, one command
    python main.py --server-url http://...      against a server you started
    python main.py --port 8080

Opens a page with the client's real WebGL basemap on it, and drives everything
else off the server's public API: click for an origin and a destination, get a
route with turn-by-turn steps, see the traffic the route was priced with, close
a road and watch it reroute.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo.blocks import load_server_app  # noqa: E402
from demo.link import HttpLink, InProcessLink  # noqa: E402
from demo.web import create_app  # noqa: E402

#: Central District 1, Ho Chi Minh City -- the server's own default area.
DEFAULT_AREA = "106.675,10.758,106.725,10.798"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="A navigation demo over the server's public API.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=1540, help="port (default: 1540)")
    parser.add_argument(
        "--server-url",
        default=None,
        help="talk to a running server over HTTP instead of hosting it in-process, "
        "e.g. http://127.0.0.1:8000",
    )
    parser.add_argument(
        "--area",
        default=DEFAULT_AREA,
        help=f"west,south,east,north to open on (default: {DEFAULT_AREA})",
    )
    parser.add_argument("--debug", action="store_true", help="Flask debug mode")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.server_url:
        link = HttpLink(args.server_url)
        print(f"server: {args.server_url} (over HTTP)")
    else:
        print("server: in-process. Composing it now -- this opens the database")
        link = InProcessLink(load_server_app())

    app = create_app(link, default_area=args.area)
    print(f"open http://{args.host}:{args.port}/")
    print("the first route fetches the area from Overpass and builds a graph;")
    print("give it a few seconds, then it is cached")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
