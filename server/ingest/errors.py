"""Failures a provider can have, separated by what a caller should do.

Traffic is the one input to navigation that is allowed to be missing: a route
computed without it is worse, not wrong. So every error here is recoverable by
falling back to an empty batch, and the distinctions exist only to tell a
caller whether retrying, waiting, or asking a different provider is the
sensible response.
"""

from __future__ import annotations

__all__ = [
    "IngestError",
    "ProviderUnavailable",
    "OutsideCoverage",
    "BadResponse",
]


class IngestError(Exception):
    """Base class for every failure raised by this block."""


class ProviderUnavailable(IngestError):
    """The upstream service could not be reached, or refused the request.

    Transient. Retrying later is reasonable; until then the caller should
    serve the last good batch, or an empty one.
    """


class OutsideCoverage(IngestError):
    """The bounding box lies outside everything this provider knows about.

    Not transient. Retrying will fail identically -- ask a provider whose
    ``coverage()`` intersects the area instead.
    """


class BadResponse(IngestError):
    """The service answered, but not with something this adapter can read.

    Means the upstream schema moved, or a proxy returned an error page.
    Retrying does not fix it; the adapter needs updating.
    """
