"""Observability -- logging and health, set up once for the whole server.

    from observability import configure, get_logger, HealthRegistry

    configure(level="INFO", as_json=False)
    log = get_logger("api")

Owns:
    how a log line is shaped and where it goes, and what "is this server
    working" means

Does not own:
    what is worth logging. A subsystem decides that and calls
    :func:`get_logger`; nothing here reaches into one to instrument it.
"""

from .health import Check, CheckResult, HealthRegistry
from .logging import JsonFormatter, configure, get_logger

__all__ = [
    "configure",
    "get_logger",
    "JsonFormatter",
    "HealthRegistry",
    "Check",
    "CheckResult",
]
