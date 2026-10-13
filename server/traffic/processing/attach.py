"""Attaching a measurement to a road, which is most of what this block does.

Free traffic data does not arrive keyed by road. A national sensor feed gives
a point with a speed and, if you are lucky, a road name; a modelled provider
gives a stretch it derived from a road network it was handed. Turning either
into "this published road is moving at this speed" is the step that makes the
data usable by routing, and it is a judgement rather than a lookup.

Three rules, in the order they apply:

1. **A record that names its road wins.** :class:`ingest.TrafficSegment`
   carries ``road_id`` when the provider derived it from a published road.
   Nothing here can improve on that, so nothing here tries.
2. **A point snaps to the nearest road, within a radius.** Past that radius
   the answer is "no road", not "the least distant one in the city" -- a
   motorway sensor attributed to a side street 800 m away is worse than no
   reading, because a route will be planned around a jam that is not there.
3. **Readings that disagree are ranked, not averaged.** Measured beats
   modelled, then confidence, then recency. Averaging a sensor with a model
   produces a number that is neither, and there is no honest source to put on
   it.

Inputs:  ingest records, and the published roads they might belong to
Outputs: RoadSpeed, one per road that anything could be attributed to
Not here: where records came from, what a level means, what a route costs
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from domain import Coord, index_of_polylines

from ..models import RoadSpeed

__all__ = ["RoadIndex", "attach", "DEFAULT_SNAP_RADIUS_M"]

#: How far a point observation may be from a road and still be attributed to
#: it. 120 m is wide enough for a sensor mast beside a dual carriageway and
#: narrow enough that a parallel side street does not collect the motorway's
#: congestion.
DEFAULT_SNAP_RADIUS_M = 120.0


class RoadIndex:
    """Nearest published road for a point, plus that road's free-flow speed.

    A thin wrapper over :class:`domain.SpatialIndex`: the proximity search is
    shared with `mapdata` and `roadstate`, and what this class adds is the one
    thing proximity cannot answer -- what speed the road runs at when nothing
    is in the way, which is the denominator of every ratio this block
    produces.
    """

    __slots__ = ("_index", "_free_flow")

    def __init__(self, roads: Iterable) -> None:
        roads = tuple(roads)
        self._index = index_of_polylines(roads)
        self._free_flow = {road.id: float(road.free_flow_kph) for road in roads}

    def __len__(self) -> int:
        return len(self._free_flow)

    def free_flow_of(self, road_id: str) -> float | None:
        return self._free_flow.get(road_id)

    def nearest_road(self, point: Coord, *, within_m: float) -> str | None:
        """Id of the closest road, or ``None`` when none is within range."""
        return self._index.nearest_label(point, within_m=within_m)


def attach(
    batches: Iterable,
    index: RoadIndex,
    *,
    snap_radius_m: float = DEFAULT_SNAP_RADIUS_M,
) -> dict[str, RoadSpeed]:
    """Turn ingest batches into one :class:`RoadSpeed` per road.

    Args:
        batches: :class:`ingest.Observations` values, or anything with
            ``segments``, ``observations`` and ``source``.
        index: The roads measurements may be attributed to.
        snap_radius_m: How far a point observation may be from a road.

    Returns:
        Road id to the best reading found for it. A road nothing could be
        attributed to is absent rather than present with a null speed: absent
        means "no information", and the cost model's behaviour for that --
        charge free-flow -- is correct, whereas a null speed would need every
        consumer to remember the same thing.
    """
    best: dict[str, RoadSpeed] = {}

    for batch in batches:
        source = getattr(batch, "source", "unknown")
        for segment in getattr(batch, "segments", ()):
            reading = _from_segment(segment, index, source, snap_radius_m)
            if reading is not None:
                _keep_better(best, reading)
        for observation in getattr(batch, "observations", ()):
            reading = _from_observation(observation, index, source, snap_radius_m)
            if reading is not None:
                _keep_better(best, reading)

    return best


# --- One record at a time --------------------------------------------------


def _from_segment(segment, index: RoadIndex, source: str, radius_m: float) -> RoadSpeed | None:
    road_id = getattr(segment, "road_id", None)
    free_flow = segment.free_flow_kph
    if road_id is None:
        road_id = index.nearest_road(_midpoint(segment.geometry), within_m=radius_m)
        if road_id is None:
            return None
    free_flow = free_flow or index.free_flow_of(road_id)

    if not free_flow or segment.speed_kph is None:
        return None
    return RoadSpeed(
        road_id=road_id,
        speed_kph=float(segment.speed_kph),
        free_flow_kph=float(free_flow),
        observed_at=segment.observed_at,
        source=getattr(segment, "source", source),
        confidence=float(getattr(segment, "confidence", 1.0)),
    )


def _from_observation(
    observation, index: RoadIndex, source: str, radius_m: float
) -> RoadSpeed | None:
    if observation.speed_kph is None:
        return None
    road_id = index.nearest_road(observation.point, within_m=radius_m)
    if road_id is None:
        return None
    free_flow = observation.free_flow_kph or index.free_flow_of(road_id)
    if not free_flow:
        return None
    return RoadSpeed(
        road_id=road_id,
        speed_kph=float(observation.speed_kph),
        free_flow_kph=float(free_flow),
        observed_at=observation.observed_at,
        source=getattr(observation, "source", source),
        confidence=float(getattr(observation, "confidence", 1.0)),
    )


def _keep_better(best: dict[str, RoadSpeed], reading: RoadSpeed) -> None:
    held = best.get(reading.road_id)
    if held is None:
        best[reading.road_id] = reading
        return
    if reading.beats(held):
        best[reading.road_id] = _with_sample(reading, held.sample_count + 1)
    else:
        best[reading.road_id] = _with_sample(held, held.sample_count + 1)


def _with_sample(reading: RoadSpeed, count: int) -> RoadSpeed:
    return RoadSpeed(
        road_id=reading.road_id,
        speed_kph=reading.speed_kph,
        free_flow_kph=reading.free_flow_kph,
        observed_at=reading.observed_at,
        source=reading.source,
        confidence=reading.confidence,
        sample_count=count,
    )


def _midpoint(geometry: Sequence[Coord]) -> Coord:
    return geometry[len(geometry) // 2]
