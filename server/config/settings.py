"""Every decision a deployment gets to make, in one dataclass.

Configuration is read here and nowhere else. No module below this one calls
``os.environ``, and that is the point: a subsystem that read its own
environment variable would be untestable without setting it, and undiscoverable
without grepping for it. What a deployment can change is the field list below,
and there is nothing else.

Everything has a default that works. A fresh checkout with no environment set
starts, serves, builds a graph from Overpass over central Ho Chi Minh City,
models traffic over it, and answers a route request -- because a server that
needs a page of configuration before it does anything is a server nobody runs.

Variables are prefixed ``MAP_``. Booleans accept ``1/true/yes/on``, case
insensitive.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

__all__ = ["Settings", "SettingsError"]


class SettingsError(ValueError):
    """A configured value is unusable. Raised at startup, never later."""


#: Where the server looks when nothing says otherwise: central District 1,
#: Ho Chi Minh City. A default area matters because several endpoints accept
#: an optional box, and "the whole world" is not a usable fallback for an
#: Overpass query.
DEFAULT_AREA = "106.675,10.758,106.725,10.798"


@dataclass(frozen=True, slots=True)
class Settings:
    """The whole configuration surface.

    Attributes:
        host, port, debug: Where and how the HTTP server listens.
        storage_backend: ``"sqlite"`` or ``"memory"``. The PostgreSQL backend
            is not written -- see ``storage/postgres/MIGRATION.md``; naming it
            here fails at startup rather than at the first query.
        database_path: SQLite file. Parent directories are created.
        cache_dir: Where upstream responses are cached on disk. Empty disables
            the disk cache; the backend's own cache is still used.
        cache_ttl_s: How long a cached upstream response stays usable.
        default_area: The box used when a request does not name one.
        overpass_endpoint, overpass_timeout_s: The free OSM road source.
        route_pad_degrees: How far outside the endpoints roads are loaded.
        route_snap_radius_m: How far an endpoint may be from a road.
        graph_cache_size: How many built graphs to keep in memory.
        traffic_enabled: Whether routes are priced with live traffic.
        traffic_max_age_s: How long a traffic reading stays usable.
        traffic_simulated: Whether the modelled provider is used where no
            measured source covers the area. Off gives free-flow routing and
            an honest empty traffic response instead of a plausible model.
        digitraffic_enabled: Whether Finland's free, keyless sensor feed is
            consulted. On by default because it costs nothing and is the only
            genuinely measured source available.
        roadstate_enabled: Whether closures and conditions affect routes.
        roadstate_open_ended_ttl_s: How long a condition with no end time is
            honoured.
        log_level, log_json: Observability.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    storage_backend: str = "sqlite"
    database_path: str = "data/server.db"
    cache_dir: str = ".cache/upstream"
    cache_ttl_s: float = 24 * 3600.0

    default_area: str = DEFAULT_AREA
    overpass_endpoint: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout_s: int = 30

    route_pad_degrees: float = 0.02
    route_snap_radius_m: float = 250.0
    graph_cache_size: int = 4

    traffic_enabled: bool = True
    traffic_max_age_s: float = 600.0
    traffic_simulated: bool = True
    digitraffic_enabled: bool = True

    roadstate_enabled: bool = True
    roadstate_open_ended_ttl_s: float = 6 * 3600.0

    log_level: str = "INFO"
    log_json: bool = False

    # --- Construction ------------------------------------------------------

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Read settings from the environment, falling back to the defaults.

        An unreadable value raises rather than being ignored. A server that
        silently ran on the default port because ``MAP_PORT`` was ``"eight
        thousand"`` would be found out much later, by someone else.
        """
        source = os.environ if env is None else env
        values: dict[str, Any] = {}

        for spec in fields(cls):
            raw = source.get(f"MAP_{spec.name.upper()}")
            if raw is None:
                continue
            values[spec.name] = _coerce(spec.name, spec.type, raw)

        made = cls(**values)
        made.validate()
        return made

    def validate(self) -> None:
        """Check what the type system cannot. Called once, at startup."""
        if self.storage_backend not in ("sqlite", "memory"):
            raise SettingsError(
                f"storage_backend {self.storage_backend!r} is not available. "
                "'sqlite' and 'memory' are implemented; 'postgres' is a "
                "documented migration path with no adapter written -- see "
                "storage/postgres/MIGRATION.md"
            )
        if not 1 <= self.port <= 65535:
            raise SettingsError(f"port {self.port} is out of range")
        if self.route_pad_degrees < 0:
            raise SettingsError("route_pad_degrees must not be negative")
        if self.route_snap_radius_m <= 0:
            raise SettingsError("route_snap_radius_m must be positive")
        if self.graph_cache_size < 1:
            raise SettingsError("graph_cache_size must be at least 1")
        if self.traffic_max_age_s <= 0:
            raise SettingsError("traffic_max_age_s must be positive")
        try:
            self.area()
        except ValueError as err:
            raise SettingsError(f"default_area is unusable: {err}") from err

    # --- Derived values ----------------------------------------------------

    def area(self):
        """The default bounding box, parsed.

        Imported locally so that this module -- which every other one reads --
        imports nothing at module level and cannot become a cycle.
        """
        from domain import BBox

        return BBox.parse(self.default_area)

    def database_file(self) -> Path:
        return Path(self.database_path)

    def cache_path(self) -> Path | None:
        return Path(self.cache_dir) if self.cache_dir else None

    def describe(self) -> dict[str, Any]:
        """Configuration as plain data, for the health endpoint.

        Paths are reported; nothing here is secret today. When something is --
        a database password in a URL -- it must be redacted in this method, not
        merely omitted from the log line that happens to print it.
        """
        return {
            "storage_backend": self.storage_backend,
            "database_path": self.database_path if self.storage_backend == "sqlite" else None,
            "default_area": self.default_area,
            "traffic_enabled": self.traffic_enabled,
            "traffic_simulated": self.traffic_simulated,
            "digitraffic_enabled": self.digitraffic_enabled,
            "roadstate_enabled": self.roadstate_enabled,
            "route_pad_degrees": self.route_pad_degrees,
            "route_snap_radius_m": self.route_snap_radius_m,
        }


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce(name: str, declared: Any, raw: str) -> Any:
    """Turn one environment string into the field's type."""
    kind = declared if isinstance(declared, str) else getattr(declared, "__name__", "str")
    text = raw.strip()
    try:
        if kind == "bool":
            lowered = text.lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
            raise ValueError(f"{raw!r} is not a boolean")
        if kind == "int":
            return int(text)
        if kind == "float":
            return float(text)
        return text
    except ValueError as err:
        raise SettingsError(f"MAP_{name.upper()}: {err}") from err
