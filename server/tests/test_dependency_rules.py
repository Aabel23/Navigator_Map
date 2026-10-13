"""The architecture, checked by the build rather than by review.

Every rule in this file is one that would otherwise be enforced by someone
remembering it. Each has a specific, known way of going wrong:

* A ``sqlite3`` import creeping into `routing` or `api`, one query at a time,
  until the PostgreSQL migration is a rewrite instead of a new file.
* `routing` importing `mapdata` for a convenient type, which makes the engine
  untestable without a road source and unusable by anything else.
* `storage` importing a domain block, which is how persistence starts holding
  domain policy.
* A cycle, which nothing notices until an import order changes.
* `flask` appearing below the API, which ends the property that every
  subsystem runs in a script or a test with no web framework installed.

These are read off the source with `ast`, not by importing, so a rule is
checked even for a module a test never loads.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent

#: The top-level modules that make up the server. Anything else imported is
#: either the standard library or a third-party package.
BLOCKS = frozenset(
    {
        "domain",
        "config",
        "observability",
        "storage",
        "routing",
        "mapdata",
        "traffic",
        "roadstate",
        "ingest",
        "api",
    }
)

#: Which blocks each block is allowed to import. The layering, stated once.
#:
#: `routing` may see `domain` and nothing else: it is the engine, and keeping
#: it at the bottom is what lets it be benchmarked, contract-tested and
#: replaced on its own.
#:
#: `mapdata`, `traffic` and `roadstate` may see `routing`, because each builds
#: or feeds something routing consumes -- a graph, a cost multiplier, a
#: constraint. The dependency runs one way and routing never returns it.
#:
#: `api` may see everything: it is the composition root.
ALLOWED: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "config": frozenset({"domain"}),
    "observability": frozenset(),
    "storage": frozenset({"domain", "observability"}),
    "routing": frozenset({"domain"}),
    "mapdata": frozenset({"domain", "storage", "routing", "observability"}),
    "traffic": frozenset({"domain", "storage", "observability"}),
    "roadstate": frozenset({"domain", "storage", "observability"}),
    "ingest": frozenset({"domain", "storage", "observability"}),
    "api": frozenset(BLOCKS - {"api"}),
}

#: Modules only the storage block may import.
DATABASE_MODULES = frozenset({"sqlite3", "psycopg", "psycopg2", "sqlalchemy", "asyncpg"})

#: Modules only the API block may import.
WEB_MODULES = frozenset({"flask", "werkzeug", "fastapi", "starlette", "django"})


def source_files(block: str) -> list[Path]:
    """Every production module in a block. Tests and benchmarks excluded."""
    root = SERVER / block
    return [
        path
        for path in root.rglob("*.py")
        if "tests" not in path.parts and "bench" not in path.parts
    ]


def imports_of(path: Path) -> set[str]:
    """Top-level module names this file imports, absolute imports only."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: inside the block, not a
            # dependency on another one.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


ALL_FILES = [(block, path) for block in sorted(BLOCKS) for path in source_files(block)]


def ids(pairs):
    return [str(path.relative_to(SERVER)).replace("\\", "/") for _, path in pairs]


@pytest.mark.parametrize("block,path", ALL_FILES, ids=ids(ALL_FILES))
def test_block_imports_only_what_it_may(block: str, path: Path) -> None:
    allowed = ALLOWED[block] | {block}
    offenders = sorted((imports_of(path) & BLOCKS) - allowed)
    assert not offenders, (
        f"{path.relative_to(SERVER)} imports {offenders}, which {block!r} may not depend on. "
        f"{block!r} may import {sorted(ALLOWED[block]) or 'nothing'}."
    )


@pytest.mark.parametrize("block,path", ALL_FILES, ids=ids(ALL_FILES))
def test_only_storage_touches_a_database_driver(block: str, path: Path) -> None:
    offenders = sorted(imports_of(path) & DATABASE_MODULES)
    if block == "storage":
        return
    assert not offenders, (
        f"{path.relative_to(SERVER)} imports {offenders}. Only storage/ may name a "
        "database driver; everything else goes through storage.DocumentStore."
    )


@pytest.mark.parametrize("block,path", ALL_FILES, ids=ids(ALL_FILES))
def test_only_the_api_touches_a_web_framework(block: str, path: Path) -> None:
    offenders = sorted(imports_of(path) & WEB_MODULES)
    if block == "api":
        return
    assert not offenders, (
        f"{path.relative_to(SERVER)} imports {offenders}. Only api/ may name a web "
        "framework; every other block must stay importable without one."
    )


def test_the_database_driver_is_confined_to_the_sqlite_adapter() -> None:
    """Even inside storage, only the adapter and nothing else."""
    offenders = [
        path.relative_to(SERVER)
        for path in source_files("storage")
        if imports_of(path) & DATABASE_MODULES and "sqlite" not in path.parts
    ]
    assert not offenders, f"sqlite3 imported outside storage/sqlite/: {offenders}"


def test_there_are_no_cycles_between_blocks() -> None:
    """A cycle is invisible until an import order changes, then it is fatal."""
    graph = {
        block: {
            other
            for path in source_files(block)
            for other in (imports_of(path) & BLOCKS)
            if other != block
        }
        for block in BLOCKS
    }

    visiting: set[str] = set()
    done: set[str] = set()
    trail: list[str] = []

    def walk(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            cycle = " -> ".join(trail[trail.index(node) :] + [node])
            pytest.fail(f"import cycle: {cycle}")
        visiting.add(node)
        trail.append(node)
        for neighbour in sorted(graph[node]):
            walk(neighbour)
        trail.pop()
        visiting.discard(node)
        done.add(node)

    for block in sorted(BLOCKS):
        walk(block)


def test_every_block_declares_a_public_surface() -> None:
    """A block without ``__all__`` has no boundary, only a directory."""
    missing = []
    for block in sorted(BLOCKS):
        init = SERVER / block / "__init__.py"
        if not init.exists():
            missing.append(f"{block}: no __init__.py")
            continue
        if "__all__" not in init.read_text(encoding="utf-8"):
            missing.append(f"{block}: __init__.py declares no __all__")
    assert not missing, missing


def test_the_server_root_is_a_path_not_a_package() -> None:
    """``server/__init__.py`` would make every block a submodule of one package.

    Blocks are top-level on purpose: ``import routing`` works with nothing but
    this directory on the path, which is what keeps the engine independently
    runnable.
    """
    assert not (SERVER / "__init__.py").exists()
