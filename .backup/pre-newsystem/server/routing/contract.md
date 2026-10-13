# Block Contract

```
BLOCK          routing
CONTRACT       1.0
TESTS          tests/contract/test_v1.py
STATUS         stable
LAST_UPDATED   2026-09-13
```

## PURPOSE

Given a `RouteRequest` and a `RoadGraph`, return the best path under the
supplied `CostModel`.

## INPUTS

| name | type | meaning |
|---|---|---|
| `request` | `RouteRequest` | origin and destination node ids, vehicle profile, cost mode, departure, constraints, U-turn policy, A* on or off |
| `graph` | `RoadGraph` | nodes, edges, turn restrictions. Shared, read-only, given at construction |
| `costs` | `CostModel \| None` | edge cost, turn cost, travel time. Optional; `None` builds a `StaticCostModel` per request from that request's cost mode |

## OUTPUTS

| name | type | meaning |
|---|---|---|
| `Route.nodes` | `tuple[str, ...]` | junctions visited, origin and destination included |
| `Route.segments` | `tuple[str, ...]` | edge ids traversed, in order |
| `Route.steps` | `tuple[RouteStep, ...]` | manoeuvre boundaries with name, turn type, bearings, distance, travel time |
| `Route.geometry` | `tuple[LatLon, ...]` | contiguous drawable shape, usable without the graph |
| `Route.distance` | `float` | meters |
| `Route.travel_time` | `float` | seconds, from the cost model |
| `Route.total_cost` | `float` | what the search minimized, in the cost mode's unit |

## SEMANTICS

"Best" means minimum total cost under the `CostModel` in force. Routing does
not define cost, speed, or what "fastest" means; the cost model does.

Endpoints are graph node ids. Converting a coordinate to a node is map
matching's responsibility, not routing's.

`departure` is timezone-aware and passed to the cost model unchanged. A naive
datetime is rejected rather than assigned a zone, because a time-dependent
cost model reading a guessed timestamp is wrong by whole hours with nothing
looking broken.

`Route.segments` is the traversal order, head to tail. A segment may repeat
only where the network genuinely requires reversing.

A U-turn — leaving a junction by the edge just arrived on — is refused unless
`allow_u_turns` is set. A junction with exactly one traversable edge is exempt:
turning round in a cul-de-sac is not a manoeuvre the driver chose.

A cost model supplied at construction must not be mutated while a route is
being computed. Build a new mapping and a new model instead
(`DynamicCostModel.with_multipliers`).

## GUARANTEES

- **G1 Determinism.** Same request, same graph, same cost model gives an
  identical `Route`, tie-breaking included, within one process and across
  restarts.
- **G2 Connectivity.** Consecutive segments share a node, `len(nodes) ==
  len(segments) + 1`, geometry is contiguous, and steps tile the segment list
  exactly once with no gap or overlap.
- **G3 Legality.** No traversal violates a one-way, a closure, a turn
  restriction, or a vehicle restriction of the requested profile, as reported
  by the graph.
- **G4 Consistency.** `Route.travel_time` equals the cost model's total for the
  traversed segments and turns — exactly, not approximately, summed in
  traversal order. It is never the penalty-weighted cost.
- **G5 Optimality.** Total cost is within 0.5% of the true minimum and never
  below it. With the built-in cost models the search is exactly optimal; the
  margin exists so a future heuristic may trade a bounded amount of accuracy
  for speed without a contract break.
- **G6 Termination.** `find()` returns or raises; it never blocks
  indefinitely, including for an unreachable destination.
- **G7 Purity.** No I/O, no network, no disk, no mutation of the graph or the
  cost model. One router serves many requests; constraints are a request-time
  overlay, never a graph edit.

## ERRORS

| name | meaning |
|---|---|
| `InvalidRequest` | unknown vehicle profile or cost mode, naive departure, or a cost model measuring in a different unit than the request asks for |
| `UnknownNode` | the origin or destination is not in the graph |
| `UnknownEdge` | the graph was asked for an edge it does not have |
| `NoRouteFound` | both endpoints exist, but nothing legal connects them under this profile, these constraints, and the graph's turn restrictions |

No other exception escapes `find()` or `find_many()`. An internal failure
surfaces as `RoutingError` with the original raised as its cause.

## SIDE EFFECTS

None. Routing reads; it does not write, cache to disk, or emit telemetry. The
caller times it.

## PERFORMANCE

Measured on `bench/benchmark.py`, seeded grid graphs, one developer machine.
Treat the ratios as the result and the milliseconds as machine-specific.

| graph | mode | Dijkstra | A* | states saved |
|---|---|---|---|---|
| 60x60, 3 600 nodes | shortest | 95 ms | 79 ms | 30% |
| 60x60, 3 600 nodes | fastest | 99 ms | 102 ms | 13% |
| 90x90, 8 100 nodes | shortest | 228 ms | 203 ms | 25% |
| 90x90, 8 100 nodes | fastest | 238 ms | 256 ms | 8% |

A* always settles fewer states. It is reliably faster in `shortest` mode,
where straight-line distance is a tight bound, and roughly a wash in `fastest`
mode, where dividing by the graph's single fastest speed makes the bound loose
enough that the states saved barely pay for the trigonometry. Tightening that
is a 2.0 concern; correctness does not depend on it.

There is no preprocessing step: the graph is usable as loaded.

## NOT GUARANTEED

- Global optimality as a proof. G5 is a bound, verified against Dijkstra on a
  corpus.
- Tie-breaking between equal-cost routes. Deterministic (G1), unspecified.
- Alternatives. `find()` returns one route.
- Stability across cost model changes. A different model may legally produce a
  completely different route.
- Any relationship between distance and travel time. A longer, faster road may
  legitimately win. Do not infer one from the other.
- `nodes_expanded`. A benchmark signal; a replacement may report anything.
- Thread safety of the `Router` object. The graph is shared and safe to read;
  construct one router per thread.
- Coordinate endpoints, and therefore an `OffNetwork` error. Snapping a GPS fix
  to the network belongs to `map_matching`.

## COMPATIBILITY

A replacement must satisfy every guarantee above and pass
`tests/contract/test_v1.py` unchanged. It may differ in tie-breaking, in states
settled, and in memory profile. It may **not** introduce a preprocessing
requirement without a 2.0 bump: the graph being usable as loaded is a promise
the map-data pipeline depends on, and it is what makes a live closure a
zero-cost change rather than a rebuild.
