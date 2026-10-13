# routing — Connector

## Responsibility

Given a request and a road graph, return the best path under a supplied cost
model. Routing does not decide what a road costs, where road data comes from,
where the driver is, or how a route is drawn or spoken.

## Inputs

- `RouteRequest` — origin and destination node ids, vehicle profile, cost mode,
  departure time, request-time constraints
- `RoadGraph` — nodes, edges, turn restrictions; shared and read-only
- `CostModel` — edge cost, turn cost, travel time; optional, defaults to a
  static model built from the request's cost mode

## Outputs

- `Route` — node path, segment path, manoeuvre steps, drawable geometry,
  distance in meters, travel time in seconds, total cost in the mode's unit
- `RoutingError` — typed failure. Nothing else escapes a routing call.

## Connectors

### `map_matching → routing`
Provides the node ids a request names. Routing takes graph node ids, never
coordinates: converting a GPS fix to a position on the network is map
matching's responsibility, and doing it in both places would give the system
two ways to disagree about where the driver is.

### `traffic → routing`, `road_condition → routing`
Provide a `Mapping[edge_id, float]` of multipliers, wrapped in
`DynamicCostModel`. Each multiplier must be at least 1.0 — conditions may slow
a road down, never speed it past its free-flow speed. An impassable segment is
expressed by the graph's `Access.BLOCKED` or by a request constraint, not by an
enormous multiplier. Neither block imports routing; routing does not import
them.

### `routing → navigation`
Provides `Route.steps`, manoeuvre boundaries with street name, turn type,
bearings, distance and travel time, plus `Route.segments` for progress
tracking.

### `routing → map`
Provides `Route.geometry`, a contiguous coordinate sequence. This exists so
that drawing a route requires no access to road data at all — it is the single
field that keeps `map` independent of the graph.

### `routing → eta`
Provides `Route.travel_time` in seconds, equal by construction to what the
cost model reports. It is never weighted by vehicle preference; a road-class
penalty changes what a route costs, not how long the drive takes.

## Stable guarantees consumers may rely on

Determinism, connectivity, legality, cost-model consistency, optimality within
0.5%, termination, and purity. Each is stated precisely in `contract.md` and
enforced by `tests/contract/test_v1.py`.

## Forbidden internal details

Consumers may import from `routing` only. The following are internal and may
change without a contract version bump:

- `routing.search` — the algorithm, its state representation, the frontier
- `routing.assemble` — how a path becomes geometry and steps
- `routing.heuristics` — heuristic choice, caching, admissibility bounds
- `Route.nodes_expanded` — a benchmark signal, not a promise
- which of several equal-cost routes is returned
- `tests/`, `bench/` — not shipped, never importable from production code
