"""The one place this block talks to the network.

Deliberately stdlib-only, so a build, a test or a head-less benchmark can
import this block without installing anything.

Each boundary block owns its own transport rather than sharing one. That is
the direct consequence of the connection rules: nothing points from `mapdata`
to `ingest` or back, so a shared client would have to become a third block
that both depend on -- a dependency edge in exchange for eighty lines, and a
place for one service's quirks to leak into another's. What is here is shaped
by Overpass alone: a form-encoded POST, gzip, and a caller-identifying header.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import BadResponse, SourceUnavailable

__all__ = ["HttpClient", "DEFAULT_USER_AGENT"]

#: Overpass asks API users to identify themselves so an abusive client can be
#: blocked without blocking everyone. Free services stay free by being used
#: politely.
DEFAULT_USER_AGENT = "hybrid-driver-navigation/0.1 (mapdata block; OSM-based, non-commercial)"


@dataclass(slots=True)
class HttpClient:
    """A small GET/POST-JSON client with a timeout and one retry.

    One retry, not three: a map build that is already waiting on a busy
    volunteer service is better off failing and being asked again than
    holding a connection open through three rounds of the same answer.
    """

    user_agent: str = DEFAULT_USER_AGENT
    timeout_s: float = 40.0
    retries: int = 1
    retry_delay_s: float = 0.6

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        return _decode_json(url, self._request(url, None, headers))

    def post_json(
        self, url: str, body: bytes, headers: Mapping[str, str] | None = None
    ) -> Any:
        return _decode_json(url, self._request(url, body, headers))

    def _request(
        self, url: str, body: bytes | None, headers: Mapping[str, str] | None
    ) -> bytes:
        request = urllib.request.Request(url, data=body, method="POST" if body else "GET")
        request.add_header("Accept-Encoding", "gzip")
        request.add_header("User-Agent", self.user_agent)
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
                    raise SourceUnavailable(f"{url} -> HTTP {err.code} {err.reason}") from err
                last_error = err
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last_error = err

        raise SourceUnavailable(f"{url} unreachable: {last_error}") from last_error


def _decode_json(url: str, payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise BadResponse(f"{url} did not return JSON: {err}") from err
