"""One place where an exception becomes a response.

Without this, every handler ends up with its own try/except, they disagree
about status codes, and the one that forgets returns a stack trace to a
client. With it, a handler raises or lets a subsystem raise, and the mapping
below is the whole error contract.

The mapping is the interesting part, and it follows one rule: **the status
says whose problem it is.** A request naming a place with no roads near it is
the client's problem and a 400 -- retrying unchanged will not help, and
changing the coordinates will. A destination that exists but that nothing
legal connects to is not an error at all in the HTTP sense; it is a successful
computation whose answer is "no route", and it returns 404 with a body that
says so rather than a 500 that suggests the server broke.

An unexpected exception is the server's problem, is logged with its traceback,
and returns a message that says nothing about the internals. A stack trace in
a response body is a gift to the wrong reader.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from ingest.errors import BadResponse, IngestError, OutsideCoverage, ProviderUnavailable
from mapdata import MapDataError, SourceUnavailable
from observability import get_logger
from routing import InvalidRequest, NoRouteFound, RoutingError, UnknownNode
from storage import StorageError

from ..schemas import ApiError

__all__ = ["install_error_handlers", "STATUS_BY_ERROR"]

log = get_logger("api.errors")

#: Checked in order, so a subclass may precede its base.
STATUS_BY_ERROR: tuple[tuple[type[Exception], int, str], ...] = (
    (ApiError, 400, "bad_request"),
    (InvalidRequest, 400, "invalid_request"),
    (UnknownNode, 400, "unknown_node"),
    (NoRouteFound, 404, "no_route"),
    (OutsideCoverage, 400, "outside_coverage"),
    (BadResponse, 502, "upstream_unreadable"),
    (ProviderUnavailable, 503, "upstream_unavailable"),
    (SourceUnavailable, 503, "map_source_unavailable"),
    (MapDataError, 503, "map_data_unavailable"),
    (StorageError, 503, "storage_unavailable"),
    (IngestError, 400, "ingest_failed"),
    (RoutingError, 500, "routing_failed"),
)


def install_error_handlers(app: Flask) -> None:
    """Register the one handler that turns any exception into JSON."""

    @app.errorhandler(Exception)
    def _handle(err: Exception):  # type: ignore[misc]
        status, code = _classify(err)

        if status >= 500:
            log.exception("request failed", extra={"code": code})
        else:
            log.info("request refused", extra={"code": code, "reason": str(err)})

        payload: dict[str, Any] = {"status": "error", "code": code}
        if isinstance(err, ApiError):
            payload.update(err.to_payload())
            status = err.status
        elif status < 500:
            payload["error"] = str(err)
        else:
            payload["error"] = "the server could not complete this request"
        return jsonify(payload), status

    @app.errorhandler(404)
    def _not_found(err):  # type: ignore[misc]
        return jsonify({"status": "error", "code": "not_found", "error": "no such endpoint"}), 404

    @app.errorhandler(405)
    def _not_allowed(err):  # type: ignore[misc]
        return (
            jsonify(
                {"status": "error", "code": "method_not_allowed", "error": "wrong HTTP method"}
            ),
            405,
        )


def _classify(err: Exception) -> tuple[int, str]:
    for kind, status, code in STATUS_BY_ERROR:
        if isinstance(err, kind):
            return status, code
    return 500, "internal_error"
