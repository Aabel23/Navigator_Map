"""Failures this block can have, separated by what a caller should do.

Map data is the one input the server cannot proceed without: a route needs a
graph and a graph needs geometry. So unlike a traffic failure, a failure here
is not something to shrug at -- but it is still worth saying whether waiting
would help.
"""

from __future__ import annotations

__all__ = ["MapDataError", "SourceUnavailable", "BadResponse"]


class MapDataError(Exception):
    """Base class for every failure raised by this block."""


class SourceUnavailable(MapDataError):
    """The upstream map source could not be reached, or refused the request.

    Transient. Retrying later is reasonable; until then the caller should use
    the last published artifact if it has one.
    """


class BadResponse(MapDataError):
    """The source answered, but not with something this reader can parse.

    Means the upstream schema moved, or a proxy returned an error page.
    Retrying does not fix it; the reader needs updating.
    """
