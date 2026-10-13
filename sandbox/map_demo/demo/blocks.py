"""Where the demo reaches the server and the client map block.

Two very different kinds of reach, and keeping them apart is the point of this
file.

**The server** is reached as a *client* reaches it — over its published
`/api/v1` HTTP surface, and nothing else. No block of the server is imported
for its behaviour. `link.py` has the two ways to make that call; this module
only locates the tree.

**The client map block** is reached for two things a browser needs and an HTTP
API cannot supply: the directory its renderer is served from, and the
`/api/config` payload that tells that renderer where the tiles are and what a
motorway looks like. Its `create_app` view function is borrowed rather than
copied, so the demo can never hold a second opinion about the map's style.

That borrowing needs care, because `client/map/` and `server/` both contain a
top-level `config`. Python's import system resolves a regular package before a
namespace one no matter what order `sys.path` is in, so simply putting the map
block on the path would hand it the *server's* configuration. The map block is
therefore imported inside a window where its two configuration modules are
loaded by file and installed under the name it expects — and the window is
closed again immediately.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEMO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DEMO_ROOT.parents[1]

SERVER_ROOT = PROJECT_ROOT / "server"
MAP_BLOCK = PROJECT_ROOT / "client" / "map"

#: The map block's browser assets, served by the demo unchanged.
MAP_STATIC_DIR = MAP_BLOCK / "ui" / "static"

__all__ = [
    "DEMO_ROOT",
    "PROJECT_ROOT",
    "SERVER_ROOT",
    "MAP_BLOCK",
    "MAP_STATIC_DIR",
    "load_map_config_view",
    "load_server_app",
]


def _load_file(name: str, path: Path) -> types.ModuleType:
    """Import one .py file under an explicit name, bypassing path resolution."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _map_block_importable() -> Iterator[None]:
    """Make ``from config import config, style`` mean the *map block's* config.

    Only for the duration of one import. Anything already imported keeps the
    module objects it captured, so the server's own ``config`` package is
    unaffected on the way in and restored on the way out.
    """
    saved_path = list(sys.path)
    saved_config = sys.modules.get("config")

    shim = types.ModuleType("config")
    shim.config = _load_file("map_block_config", MAP_BLOCK / "config" / "config.py")
    shim.style = _load_file("map_block_style", MAP_BLOCK / "config" / "style.py")

    sys.path.insert(0, str(MAP_BLOCK))
    sys.modules["config"] = shim
    try:
        yield
    finally:
        sys.path[:] = saved_path
        if saved_config is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = saved_config


def load_map_config_view() -> Any:
    """The map block's own ``/api/config`` view function.

    Borrowed, not copied. A copied endpoint would be a second statement of the
    tile source and the entire visual style, and it would drift the first time
    either changed.
    """
    if not MAP_STATIC_DIR.is_dir():
        raise RuntimeError(
            f"the client map block is not where it was expected: {MAP_BLOCK}\n"
            "This demo serves its renderer, so it cannot start without it."
        )
    with _map_block_importable():
        from ui.view import create_app as create_map_app  # noqa: PLC0415

        return create_map_app().view_functions["api_config"]


def load_server_app() -> Any:
    """The server's Flask application, for the in-process link.

    ``server/`` is a path root rather than a package -- ``import api`` works
    with nothing but that directory on the path -- which is exactly what makes
    running it inside another process a one-line affair.

    The working directory is moved there first, and that is not incidental.
    The server's configuration carries relative defaults (``data/server.db``,
    its Overpass cache), so composing it from anywhere else would quietly
    build a *second* database and a second cache beside the demo. Sharing them
    is the point: a closure entered here is the same closure ``cd server &&
    python main.py`` would show.
    """
    if not (SERVER_ROOT / "api").is_dir():
        raise RuntimeError(f"server not found at {SERVER_ROOT}")
    if str(SERVER_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_ROOT))
    os.chdir(SERVER_ROOT)
    from api import create_app  # noqa: PLC0415

    return create_app()
