"""How the demo calls the server: two ways, one interface.

The demo is a *client*. It knows the server by its published `/api/v1`
surface, six endpoints wide, and by nothing else — no block imported for its
behaviour, no shortcut into a service object, no peek at the database. That
restriction is the whole reason the demo is worth having: if it can build a
working navigation UI from the API alone, then so can a phone.

Two implementations, because the two ways of running it answer different
questions.

* :class:`InProcessLink` runs the server's real WSGI stack inside this
  process, through Flask's test client. Every blueprint, every middleware and
  every error handler runs exactly as it does under a real server; what is
  skipped is the socket. One command, no ports, nothing else to start — which
  is what makes the demo something you can hand to someone. A fresh client per
  call, because the demo serves on several threads and a client carries
  per-session state.
* :class:`HttpLink` makes real HTTP requests to a server you started
  yourself. Slower to set up, and the honest answer to "does this work over
  the wire".

Both return the same thing: a status code and a decoded body. The demo's HTTP
layer passes that straight through to the browser, so the page is talking to
`/api/v1/...` either way and cannot tell which is underneath.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Protocol

__all__ = ["ServerLink", "InProcessLink", "HttpLink", "LinkError"]

#: Generous, because the honest worst case is not a slow network: the first
#: request for an area the server has never seen fetches it from Overpass and
#: builds a graph, and that is tens of seconds. Every later request for the
#: same area is milliseconds.
_TIMEOUT_S = 300.0


class LinkError(RuntimeError):
    """The server could not be reached at all.

    Distinct from a 4xx or 5xx, which are answers. This is the absence of one,
    and the page reports it differently: a request that failed is a bug in the
    demo or the server, a link that is down means nothing is listening.
    """


class ServerLink(Protocol):
    """What the demo needs from the server, in three verbs."""

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> tuple[int, Any]: ...

    def post(self, path: str, body: Any) -> tuple[int, Any]: ...

    def delete(self, path: str) -> tuple[int, Any]: ...

    def describe(self) -> dict[str, Any]: ...


class InProcessLink:
    """The server's real WSGI stack, in this process, without a socket."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        with self._app.test_client() as client:
            response = client.get(path, query_string=dict(params or {}))
            return response.status_code, response.get_json(silent=True)

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        with self._app.test_client() as client:
            response = client.post(path, json=body)
            return response.status_code, response.get_json(silent=True)

    def delete(self, path: str) -> tuple[int, Any]:
        with self._app.test_client() as client:
            response = client.delete(path)
            return response.status_code, response.get_json(silent=True)

    def describe(self) -> dict[str, Any]:
        return {"mode": "in-process", "target": "server/api (WSGI, no socket)"}


class HttpLink:
    """A real HTTP client against a server you started separately."""

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        return self._call("GET", f"{path}?{query}" if query else path, None)

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        return self._call("POST", path, json.dumps(body or {}).encode("utf-8"))

    def delete(self, path: str) -> tuple[int, Any]:
        return self._call("DELETE", path, None)

    def describe(self) -> dict[str, Any]:
        return {"mode": "http", "target": self._base}

    def _call(self, method: str, path: str, body: bytes | None) -> tuple[int, Any]:
        request = urllib.request.Request(f"{self._base}{path}", data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as err:
            # A 4xx or 5xx is an answer, and the demo shows it. Only a failure
            # to get any answer at all is a LinkError.
            return err.code, _decode(err.read())
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise LinkError(f"{self._base} unreachable: {err}") from err


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"error": "the server did not return JSON"}
