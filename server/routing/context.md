# routing

Graph search. `RouteRequest` in, `Route` out. Nothing else.

```
ENTRY   routing/__init__.py -> RoutingService.route()   coordinates, what api calls
                            -> Router.find()            node ids, the engine
IN      RouteQuery | RouteRequest | RoadGraph (mapdata) | CostModel (traffic, roadstate)
OUT     Route | RoutingError
```

## Read first

| file | what it holds |
|---|---|
| `__init__.py` | the entire public surface, and the list of what is internal |
| `service.py` | area, snapping, cost combination, constraints. The API calls this |
| `providers.py` | the three Protocols: map graph, traffic cost, road state |
| `router.py` | validation, cost-model and heuristic choice, both entry points |
| `search.py` | the algorithm. A* over `(via_edge, node)` states |

## Then, only if the task needs it

| task | where |
|---|---|
| a route starts at the wrong junction | `service.py` snapping, then mapdata's connector |
| traffic or a closure is being ignored | `service.py`, then that provider's own block |
| changing the search or its heuristic | `search.py`, `heuristics.py` |
| wrong or missing geometry, steps, manoeuvres | `assemble.py` |
| wrong distance or travel time | `assemble.py`, then `costs.py` |
| route avoids the wrong things | `costs.py`, `constraints.py` |
| one-way or turn restriction ignored | `graph.py` first — is the data there? |
| changing what `find()` promises | `contract.md` FIRST, then `tests/contract/test_v1.py` |
| performance work | `bench/benchmark.py`, then `heuristics.py` |

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

`mapdata/`, `traffic/`, `roadstate/`, `ingest/`, `storage/`, `api/` — not
dependencies. Routing declares what it needs from them in `providers.py` and
imports none of them; `server/tests/test_dependency_rules.py` fails the build
if that changes.

Another block's internals — use its `connector.md` under
`agent-system-server/blocks/`.

`tests/`, `bench/` — unless the task is testing or measurement.
