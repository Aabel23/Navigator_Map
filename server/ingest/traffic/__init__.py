"""Fetching traffic data from the sources that publish it.

Not to be confused with the top-level ``traffic`` block, which interprets what
this one collects. The names are adjacent because the architecture names them
that way; the boundary between them is not blurry at all. What leaves here is
what a source *said*. What leaves `traffic` is what the server *concluded*.
"""

from .collector import Collection, TrafficCollector

__all__ = ["TrafficCollector", "Collection"]
