"""Traffic -- how fast the network is actually moving, and what that costs.

    from traffic import TrafficState, TrafficCostSource

    state = TrafficState()
    state.apply(batches_from_ingest, roads_from_mapdata)
    costs = TrafficCostSource(state, graphs)      # graphs: mapdata provider

Owns:
    attaching observations to published roads, deciding what a speed ratio
    means, holding the current picture, and expressing it as the edge cost
    multipliers routing consumes

Does not own:
    fetching anything. Traffic does no I/O at all -- `ingest` talks to
    providers and hands over normalized batches. It does not own road geometry
    either; `mapdata` does, and this block is handed the roads it needs.
    Closures and flooding belong to `roadstate`: a jam is slower, a closure is
    impassable, and conflating them sends a driver twenty kilometres round a
    queue.

The split from `ingest` is the one worth remembering. What leaves ingest is
what a source *said* -- a speed, a free-flow reference, a timestamp. What
leaves this block is what the server *concluded*: this road is at this level
and costs this much more to drive. The judgement is here, in one place, for
every provider at once.

This module is the block's entire public surface. Stdlib-only.
"""

from .models import SIMULATED_SOURCE, RoadSpeed, TrafficSnapshot
from .levels import (
    LEVEL_COLORS,
    LEVEL_ORDER,
    LEVEL_THRESHOLDS,
    TrafficLevel,
    level_for_ratio,
    level_for_speed,
    level_payload,
)
from .processing import (
    MAX_MULTIPLIER,
    RoadIndex,
    attach,
    multiplier_for,
    multiplier_for_ratio,
)
from .state import DEFAULT_MAX_AGE_S, RoadEdgeIndex, TrafficCostSource, TrafficState

__all__ = [
    # State
    "TrafficState",
    "TrafficSnapshot",
    "RoadSpeed",
    "DEFAULT_MAX_AGE_S",
    "SIMULATED_SOURCE",
    # The seam routing reads
    "TrafficCostSource",
    "RoadEdgeIndex",
    # Processing
    "attach",
    "RoadIndex",
    "TrafficLevel",
    "LEVEL_THRESHOLDS",
    "LEVEL_COLORS",
    "LEVEL_ORDER",
    "level_for_ratio",
    "level_for_speed",
    "level_payload",
    "multiplier_for",
    "multiplier_for_ratio",
    "MAX_MULTIPLIER",
]
