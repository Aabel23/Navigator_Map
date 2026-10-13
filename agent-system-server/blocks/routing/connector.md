# routing — Connector

## Responsibility

Compute the authoritative route. Given coordinates and preferences, return the
best path under the cost model in force. Routing does not decide what a road
costs, where road data comes from, where the driver is, or how a route is drawn
or spoken.

Routing is server-side. The client never holds the graph or the search.

## Inputs

- `RouteQuery` — origin, destination, optional waypoints, vehicle profile, cost
  mode, departure, road classes to avoid, whether to price traffic
- `RouteRequest` — the engine-level form: origin and destination *node ids*,
  profile, cost mode, departure, request-time constraints
- `RoadGraph` — nodes, edges, turn restrictions; shared and read-only
- `CostModel` — edge cost, turn cost, travel time

## Outputs

- `Route` — node path, segment path, manoeuvre steps, drawable geometry,
  distance in meters, travel time in seconds, total cost in the mode's unit
- `RoutingError` — typed failure. Nothing else escapes a routing call.

## Connectors

### `api → routing`
Calls `RoutingService.route(RouteQuery)`. The handler parses and serialises;
it never touches the graph, the cost model or the search.

### `mapdata → routing`
Satisfies `MapGraphProvider`: `graph_for(area) -> GraphView` with `.graph` and
`.nearest_node(point, within_m)`. Routing takes node ids, never coordinates —
snapping belongs where the nodes live.

### `traffic → routing`
Satisfies `TrafficCostProvider`: `multipliers_for(area) -> {edge_id: float}`,
every value at least 1.0. Conditions may slow a road, never speed it past free
flow.

### `roadstate → routing`
Satisfies `RoadStateProvider`. `blocked_edges(area)` becomes a request-time
constraint; `multipliers_for(area)` becomes a cost. These must stay separate.

### `routing → api`
Provides `Route`. The API converts it to JSON; routing knows no JSON.

## Stable guarantees consumers may rely on

Determinism, connectivity, legality, cost-model consistency, optimality within
0.5%, termination, and purity. Each is stated precisely in
`server/routing/contract.md` and enforced by `routing/tests/contract/test_v1.py`.

`Route.travel_time` is real seconds and equals the cost model's total exactly.
`Route.total_cost` is what the search minimized and may be penalty-weighted.
They are different numbers on purpose.

## Forbidden internal details

Consumers may import from `routing` only. Internal and free to change:

- `routing.search` — the algorithm, its state representation, the frontier
- `routing.assemble` — how a path becomes geometry and steps
- `routing.heuristics` — heuristic choice, caching, admissibility bounds
- `Route.nodes_expanded` — a benchmark signal, not a promise
- which of several equal-cost routes is returned
- `tests/`, `bench/` — not shipped, never importable from production code

## Inside the block

```text
routing/
├── __init__.py     the public surface -- the whole contract, and nothing else
├── service.py      RouteQuery -> Route. The application-level entry point
├── providers.py    what the service needs from the rest, as three Protocols
├── router.py       validation, cost-model and heuristic choice
├── search.py       A* over (via_edge, node) states
├── assemble.py     a path -> geometry, manoeuvre steps, distance, time
├── graph.py        RoadGraph interface + InMemoryRoadGraph
├── costs.py        CostModel family, VehicleProfile, CostContext
├── constraints.py  per-request avoid rules
├── models.py       Node, Edge, TurnRestriction, RouteRequest, Route
├── heuristics.py   admissible bounds (internal)
├── geometry.py     haversine, bearings, turn angles
├── bench/          A* against Dijkstra
└── tests/          207 tests, contract suite included
```

**The flow through the files.**

```text
POST /api/v1/route
    │
    ▼  api/routes/route.py          parse, call, serialise. Three statements
RouteQuery
    │
    ▼  service.py  RoutingService.route()
    │     1. area    = BBox.covering(endpoints, pad)
    │     2. view    = MapGraphProvider.graph_for(area)          [mapdata]
    │     3. nodes   = view.nearest_node(point), per endpoint    [mapdata]
    │     4. costs   = DynamicCostModel(static, combine(traffic, roadstate))
    │     5. blocked = RoadStateProvider.blocked_edges(area)  -> constraint
    ▼
RouteRequest (node ids, a loaded graph, a cost model)
    │
    ▼  router.py     validates the request, picks the cost model and heuristic
    ▼  search.py     A* over (via_edge, node) states -- the via_edge is what
    │                makes turn restrictions and u-turn rules expressible
    ▼  assemble.py   the settled path -> geometry, merged steps, distance, time
    ▼
Route
    │
    ▼  api/schemas/route.py         -> JSON, longitude first
```

**Cost is not baked into the graph.** An `Edge` in `models.py` stores *facts* --
distance, speed, class, name, shape. A `CostModel` in `costs.py` decides what
those are worth for this vehicle at this moment. `StaticCostModel` covers
`fastest` and `shortest`; `DynamicCostModel` wraps it with a per-edge multiplier
map, which is the single seam live conditions reach the search through.

**Waypoints** are searched as separate legs and joined in `service.py`: the
duplicated junction dropped from `nodes`, the duplicated coordinate from
`geometry`, distances and times summed. Steps are left alone -- each leg ends
with an arrival and the next begins with a departure, which is what stopping at
a waypoint actually is.
