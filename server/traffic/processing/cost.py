"""Turning a speed ratio into what a route should pay for it.

This is the one arithmetic step between "this road is moving at 40% of free
flow" and a number the router can minimise, and it is deliberately trivial:
the multiplier is the reciprocal of the ratio, because a road at half speed
takes twice as long. Anything cleverer would be a model of congestion, and
this block has measurements rather than a model.

Two rules the reciprocal does not give you, and both matter:

* **Never below 1.0.** A sensor reporting traffic moving faster than the road's
  free-flow reference is reporting that the reference is wrong, not that the
  drive is quick. Routing rejects multipliers below 1.0 outright -- they would
  make its A* heuristic inadmissible, which does not fail loudly, it just
  returns a worse route with nothing on the result to show for it.
* **Capped.** A ratio near zero gives an enormous number. Standstill traffic is
  not the same as a closed road: the driver can still get through, and a route
  that treats a jam as impassable will send them twenty kilometres round. A
  closure is expressed by `roadstate` as a blocked edge, which is a different
  thing with a different answer.
"""

from __future__ import annotations

from typing import Iterable, Mapping

__all__ = ["multiplier_for_ratio", "multiplier_for", "MAX_MULTIPLIER"]

#: The worst a jam may cost. Eight times free flow is a road doing 6 kph where
#: it should do 50 -- standstill, and worse than any real alternative without
#: being infinite.
MAX_MULTIPLIER = 8.0


def multiplier_for_ratio(ratio: float | None, *, ceiling: float = MAX_MULTIPLIER) -> float:
    """Cost multiplier for a speed/free-flow ratio.

    ``None`` or a non-positive ratio gives 1.0: no reading is not congestion,
    and charging for the absence of data would make an unmonitored road look
    clear and a monitored one look bad.
    """
    if ratio is None or ratio <= 0:
        return 1.0
    return min(max(1.0 / ratio, 1.0), ceiling)


def multiplier_for(speed, *, ceiling: float = MAX_MULTIPLIER) -> float:
    """Cost multiplier for one :class:`~traffic.models.RoadSpeed`."""
    return multiplier_for_ratio(speed.ratio, ceiling=ceiling)
