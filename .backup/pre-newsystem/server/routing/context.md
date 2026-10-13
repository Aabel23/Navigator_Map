# routing

Graph search. `RouteRequest` in, `Route` out. Nothing else.

```
ENTRY   routing/__init__.py -> Router.find()
IN      RouteRequest (navigation, app) | RoadGraph (map data) | CostModel (traffic, road_condition)
OUT     Route | RoutingError
```

## Read first

| file | what it holds |
|---|---|
| `routing/__init__.py` | the entire public surface, and the list of what is internal |
| `routing/router.py` | validation, cost-model and heuristic choice, both entry points |
| `routing/search.py` | the algorithm. A* over `(via_edge, node)` states |

## Then, only if the task needs it

| task | where |
|---|---|
| changing the search or its heuristic | `routing/search.py`, `routing/heuristics.py` |
| wrong or missing geometry, steps, manoeuvres | `routing/assemble.py` |
| wrong distance or travel time | `routing/assemble.py`, then `routing/costs.py` |
| route avoids the wrong things | `routing/costs.py`, `routing/constraints.py` |
| one-way or turn restriction ignored | `routing/graph.py` first — is the data there? |
| changing what `find()` promises | `contract.md` FIRST, then `tests/contract/test_v1.py` |
| performance work | `bench/benchmark.py`, then `routing/heuristics.py` |

## Facts that save you a read

The graph is shared and read-only. Never mutate it. A temporary closure is a
cost or a constraint, not a graph edit.

A search state is `(via_edge, node)`, not a node. That is the only reason turn
restrictions can be expressed at all — whether leaving a junction into a given
street is legal depends on the street you arrived by.

`Route` carries its own geometry. Consumers never need the graph to draw it.

`travel_time` comes from the cost model and is real seconds. `total_cost` is
what the search minimized and may be penalty-weighted. They are different
numbers on purpose; never present `total_cost` as an arrival time.

The router builds its own heuristic and does not accept one. A heuristic that
does not match the cost mode returns a worse route silently, with nothing on
the result to show for it. This was a live defect before v1.0.

Penalties and condition multipliers are validated to be at least 1.0. That is
not fussiness — it is what makes the heuristic's lower bound structural rather
than a thing every caller has to re-derive.

## Do not read

`map/`, `traffic/`, `location/`, `agent-system-server/` — not dependencies.
Another block's internals — use its `connector.md`.
`tests/`, `bench/` — unless the task is testing or measurement.
