"""The one place this block talks to the network.

Deliberately stdlib-only. The core of this block has no third-party
dependency at all, which is what lets `roadstate`, a test, or a head-less
benchmark import it without installing anything.

Each boundary block owns its own transport rather than sharing one. That
follows directly from the connection rules: nothing points from `mapdata` to
`ingest` or back, so a shared client would have to become a third block both
depend on -- a dependency edge in exchange for eighty lines, and a place for
one service's quirks to leak into another's.

Two things here are not incidental, and both belong to the feeds this block
reads rather than to HTTP in general:

* **gzip is mandatory, not an optimisation.** Digitraffic answers 406 Not
  Acceptable to a request that does not send an Accept-Encoding: gzip header.
* **A caller-identifying header always goes out.** Digitraffic asks API users
  to identify themselves so an abusive client can be blocked without blocking
  everyone. Free services stay free by being used politely.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import BadResponse, ProviderUnavailable

__all__ = ["HttpClient", "DEFAULT_USER_AGENT"]

#: Sent as both User-Agent and Digitraffic-User. A project name and a way to
#: reach someone is what the services ask for.
DEFAULT_USER_AGENT = "hybrid-driver-navigation/0.1 (ingest block; OSM-based, non-commercial)"


@dataclass(slots=True)
class HttpClient:
    """A small GET/POST-JSON client with a timeout and one retry.

    One retry, not three: a traffic refresh that is already late is worth less
    than the next one, and a provider that fails is expected to degrade to an
    empty batch rather than hold up a frame.
    """

    user_agent: str = DEFAULT_USER_AGENT
    timeout_s: float = 20.0
    retries: int = 1
    retry_delay_s: float = 0.6

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        return _decode_json(url, self._request(url, None, headers))

    def post_json(self, url: str, body: bytes, headers: Mapping[str, str] | None = None) -> Any:
        return _decode_json(url, self._request(url, body, headers))

    def _request(
        self, url: str, body: bytes | None, headers: Mapping[str, str] | None
    ) -> bytes:
        request = urllib.request.Request(url, data=body, method="POST" if body else "GET")
        request.add_header("Accept-Encoding", "gzip")
        request.add_header("User-Agent", self.user_agent)
        request.add_header("Digitraffic-User", self.user_agent)
        for key, value in (headers or {}).items():
            request.add_header(key, value)

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.retry_delay_s)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        return gzip.decompress(raw)
                    return raw
            except urllib.error.HTTPError as err:
                # A 4xx is the server saying the request itself is wrong.
                # Retrying an identical request cannot change that.
                if 400 <= err.code < 500:
                    raise ProviderUnavailable(f"{url} -> HTTP {err.code} {err.reason}") from err
                last_error = err
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last_error = err

        raise ProviderUnavailable(f"{url} unreachable: {last_error}") from last_error


def _decode_json(url: str, payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise BadResponse(f"{url} did not return JSON: {err}") from err
