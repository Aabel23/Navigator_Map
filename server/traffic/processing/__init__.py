"""Observations to conclusions: attach a measurement to a road, price it.

The level table is not here. Classifying a ratio is vocabulary the whole block
shares -- :class:`traffic.RoadSpeed` reports its own level -- so it lives at
``traffic/levels.py`` beside the models rather than downstream of them.
"""

from .attach import DEFAULT_SNAP_RADIUS_M, RoadIndex, attach
from .cost import MAX_MULTIPLIER, multiplier_for, multiplier_for_ratio

__all__ = [
    "attach",
    "RoadIndex",
    "DEFAULT_SNAP_RADIUS_M",
    "multiplier_for",
    "multiplier_for_ratio",
    "MAX_MULTIPLIER",
]
