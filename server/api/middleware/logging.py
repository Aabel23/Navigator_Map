"""Request logging and timing, attached once rather than per handler.

What is logged is chosen to be useful during an incident rather than complete:
method, path, status, duration, and a request id. The id is generated here and
returned in the ``X-Request-Id`` header, so a client reporting "my route
request failed at 14:03" can be found in one query instead of by guessing from
timestamps.

Bodies are never logged. A route request carries where a person is and where
they are going, and that does not belong in a log file that is shipped
somewhere and kept for a year.
"""

from __future__ import annotations

import time
import uuid

from flask import Flask, g, request

from observability import get_logger

__all__ = ["install_request_logging", "REQUEST_ID_HEADER"]

REQUEST_ID_HEADER = "X-Request-Id"

log = get_logger("api.request")


def install_request_logging(app: Flask) -> None:
    """Time every request and log one line when it finishes."""

    @app.before_request
    def _start() -> None:
        g.started_at = time.perf_counter()
        g.request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]

    @app.after_request
    def _finish(response):  # type: ignore[misc]
        started = getattr(g, "started_at", None)
        duration_ms = (time.perf_counter() - started) * 1000.0 if started else 0.0
        request_id = getattr(g, "request_id", "-")
        response.headers[REQUEST_ID_HEADER] = request_id

        # Health checks are polled constantly and would drown everything else.
        if not request.path.startswith("/health"):
            log.info(
                "%s %s -> %s",
                request.method,
                request.path,
                response.status_code,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        return response
