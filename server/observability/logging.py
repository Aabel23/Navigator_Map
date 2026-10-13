"""Logging set up once, in one shape, so a log line is worth reading.

Two formats, chosen by configuration. The plain one is for a developer with a
terminal; the JSON one is for anything that ships logs somewhere. Both carry
the same fields, so moving between them changes how a line looks and not what
it says.

The rule this module exists to enforce is that no subsystem calls
``logging.basicConfig``. A library that configures the root logger takes the
decision away from whoever imported it, and the symptom -- duplicated lines,
or a level nobody set -- appears far from the cause.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

__all__ = ["configure", "get_logger", "JsonFormatter"]

LOGGER_NAME = "server"

#: Fields a LogRecord carries that are not ours to republish.
_STANDARD = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any extra fields merged in.

    ``logger.info("routed", extra={"distance_m": 4408})`` produces a line
    carrying ``distance_m``, so a structured query can find it without parsing
    prose. That is the whole reason to prefer this over a message string.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(*, level: str = "INFO", as_json: bool = False) -> logging.Logger:
    """Set up the server logger. Safe to call twice; the second call re-does it.

    Returns the server's own logger, which is the only one anything should log
    through. Handlers are attached here rather than to the root, so a library
    that logs elsewhere is unaffected by what this server decided.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        JsonFormatter()
        if as_json
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s")
    )
    logger.addHandler(handler)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """A child of the server logger, so configuration applies to it."""
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")
