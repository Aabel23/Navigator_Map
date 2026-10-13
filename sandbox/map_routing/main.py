"""Entry point for the map + routing + traffic simulator.

    python main.py
    python main.py --region helsinki
    python main.py --port 8080

Serves one page: the map block's real renderer, with a fake GPS for an origin,
a click for a destination, the routing block computing the path, and the
traffic block pricing it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sim.settings import DEBUG, DEFAULT_REGION, HOST, PORT, REGIONS  # noqa: E402
from sim.web import create_app  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Wire the map, routing and traffic blocks together and drive them by hand.",
    )
    parser.add_argument("--host", default=HOST, help=f"bind address (default: {HOST})")
    parser.add_argument("--port", type=int, default=PORT, help=f"port (default: {PORT})")
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        choices=sorted(REGIONS),
        help=f"which city to start in (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=DEBUG,
        help="Flask debug mode. The reloader is left off -- it would start a second simulator, "
        "and with it a second Overpass query.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = create_app(args.region)
    print(f"open http://{args.host}:{args.port}/")
    print(f"region: {REGIONS[args.region].label}")
    print("the road graph is fetched from Overpass on first start; give it a moment")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
