"""An in-process backend. Real enough to test against, gone on restart."""

from .backend import InMemoryStorage

__all__ = ["InMemoryStorage"]
