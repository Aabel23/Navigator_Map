"""The traffic -> routing connector, realised.

Both blocks describe this join and neither implements it, which is the whole
point of the arrangement. Routing's connector says:

    `traffic -> routing` ... Provide a `Mapping[edge_id, float]` of
    multipliers, wrapped in `DynamicCostModel`. Each multiplier must be at
    least 1.0 -- conditions may slow a road down, never speed it past its
    free-flow speed. An impassable segment is expressed by the graph's
    `Access.BLOCKED` or by a request constraint, not by an enormous
    multiplier. Neither block imports routing; routing does not import them.

Traffic's own README lists the same thing as work not yet done: "turn a
snapshot into ``{edge_id: multiplier}`` ... A plain dict, so this block never
imports the routing block."

So this module is the adapter, and it lives in the sandbox precisely so that
neither block has to know the other exists. Everything it reads is a public
field of :class:`traffic.TrafficSnapshot`; everything it produces is a plain
dict and a plain set of ids.

Three shapes of record have to become one mapping:

* a **segment** already names an ``edge_id`` -- the id of the
  :class:`RoadSegment` it was derived from, which is the OSM way the graph
  builder cut its edges out of. One way becomes several edges, so one segment
  prices several.
* an **observation** is a speed at a point, with no extent at all. Almost
  every free government feed publishes only these. It is matched to the
  nearest road and then applied to that road's whole way, because a roadside
  station is measuring a stretch, not a vertex.
* an **incident** that is ``blocking`` is not a multiplier. Per the routing
  connector it becomes a request constraint, so blocking incidents come back
  as a set of edge ids to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .blocks import TrafficSnapshot
from .matching import EdgeIndex
from .settings import Tuning

__all__ = ["TrafficLink", "link_traffic_to_edges"]

#: How many vertices of one incident's geometry are probed against the edge
#: index. A roadworks polyline can carry hundreds; a few dozen spread along it
#: find the same roads for a fraction of the lookups.
_MAX_INCIDENT_PROBES = 40


@dataclass(frozen=True, slots=True)
class TrafficLink:
    """What one traffic snapshot means to the router.

    Attributes:
        multipliers: Edge id to cost multiplier, every value at least 1.0.
            Handed straight to :class:`routing.DynamicCostModel`.
        blocked_edges: Edge ids a blocking incident sits on. Handed to
            :class:`routing.RouteConstraints`, never expressed as a huge
            multiplier.
        stats: What was matched and what was not, for the panel. An adapter
            that silently matched nothing would otherwise look exactly like a
            city with no congestion.
    """

    multipliers: dict[str, float] = field(default_factory=dict)
    blocked_edges: frozenset[str] = frozenset()
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.multipliers and not self.blocked_edges


def link_traffic_to_edges(
    snapshot: TrafficSnapshot,
    *,
    way_edges: Mapping[str, tuple[str, ...]],
    edge_index: EdgeIndex,
    tuning: Tuning,
) -> TrafficLink:
    """Turn a snapshot into the two things a routing request can carry."""
    edge_to_way = {
        edge_id: way_id for way_id, edge_ids in way_edges.items() for edge_id in edge_ids
    }

    multipliers: dict[str, float] = {}
    matched_segments = 0
    matched_observations = 0

    for segment in snapshot.segments:
        multiplier = _multiplier(segment.ratio, tuning.max_multiplier)
        if multiplier is None:
            continue
        targets = _edges_for_way(segment.edge_id, way_edges)
        if not targets:
            targets = _edges_near_shape(segment.geometry, edge_index, way_edges, edge_to_way, tuning)
        if targets:
            matched_segments += 1
            _apply(multipliers, targets, multiplier)

    for observation in snapshot.observations:
        multiplier = _multiplier(observation.ratio, tuning.max_multiplier)
        if multiplier is None:
            continue
        hit = edge_index.nearest(observation.point, tuning.traffic_match_radius_m)
        if hit is None:
            continue
        targets = _edges_for_way(edge_to_way.get(hit[0]), way_edges) or (hit[0],)
        matched_observations += 1
        _apply(multipliers, targets, multiplier)

    blocked: set[str] = set()
    blocking_incidents = 0
    for incident in snapshot.incidents:
        if not incident.blocking:
            continue
        blocking_incidents += 1
        for point in _probe_points(incident.geometry):
            for edge_id, _ in edge_index.near(point, tuning.incident_block_radius_m):
                blocked.add(edge_id)

    return TrafficLink(
        multipliers=multipliers,
        blocked_edges=frozenset(blocked),
        stats={
            "segments_seen": len(snapshot.segments),
            "segments_matched": matched_segments,
            "observations_seen": len(snapshot.observations),
            "observations_matched": matched_observations,
            "edges_priced": len(multipliers),
            "blocking_incidents": blocking_incidents,
            "edges_blocked": len(blocked),
            "worst_multiplier": round(max(multipliers.values()), 2) if multipliers else 1.0,
        },
    )


def _multiplier(ratio: float | None, ceiling: float) -> float | None:
    """A speed/free-flow ratio as a cost multiplier, or ``None`` for no reading.

    The inverse of the ratio is exactly the factor the drive is lengthened by:
    a road running at half its free-flow speed takes twice as long. Clamped
    below at 1.0 because the routing block forbids a multiplier that would
    make a road *faster* than free flow -- that would break the A* heuristic's
    admissibility, not merely bend the numbers -- and above at the tuning
    ceiling so one broken reading cannot dominate a whole city.
    """
    if ratio is None or ratio <= 0:
        return None
    return max(1.0, min(ceiling, 1.0 / ratio))


def _edges_for_way(
    way_id: str | None, way_edges: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    if way_id is None:
        return ()
    return way_edges.get(way_id, ())


def _edges_near_shape(
    shape: tuple[tuple[float, float], ...],
    edge_index: EdgeIndex,
    way_edges: Mapping[str, tuple[str, ...]],
    edge_to_way: Mapping[str, str],
    tuning: Tuning,
) -> tuple[str, ...]:
    """Fallback for a segment whose ``edge_id`` names nothing in this graph."""
    found: set[str] = set()
    for point in _probe_points(shape):
        hit = edge_index.nearest(point, tuning.traffic_match_radius_m)
        if hit is None:
            continue
        found.update(_edges_for_way(edge_to_way.get(hit[0]), way_edges) or (hit[0],))
    return tuple(found)


def _probe_points(
    shape: tuple[tuple[float, float], ...]
) -> tuple[tuple[float, float], ...]:
    if len(shape) <= _MAX_INCIDENT_PROBES:
        return shape
    step = len(shape) / _MAX_INCIDENT_PROBES
    return tuple(shape[int(i * step)] for i in range(_MAX_INCIDENT_PROBES))


def _apply(multipliers: dict[str, float], edge_ids: tuple[str, ...], value: float) -> None:
    """Keep the worst reading per edge.

    Two stations on the same stretch disagreeing is normal, and the slower of
    the two is the one a driver will actually experience.
    """
    for edge_id in edge_ids:
        if value > multipliers.get(edge_id, 0.0):
            multipliers[edge_id] = value
