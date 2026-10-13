# routing

A storage-agnostic routing engine. Takes a road graph and a request, returns a
route with drawable geometry, manoeuvre steps, a distance, and a travel time.

It has no dependencies beyond the standard library, no I/O, and no knowledge of
where road data came from. The only third-party package it needs is `pytest`,
and only to run its own tests.

```text
map data  ──▶  RoadGraph ─┐
                          ├──▶  Router.find()  ──▶  Route ──┬──▶  map          (geometry)
traffic / road_condition ─┤                                 ├──▶  navigation   (steps)
  as a multiplier map ────┘                                 └──▶  eta          (travel_time)
map_matching  ──▶  node ids  ──▶  RouteRequest
```

`contract.md` is what this block promises. `connector.md` is how other blocks
reach it. `context.md` says what to read for a given task. This file explains
how it works.

## Layout

```text
routing/
├── routing/             the block itself — no I/O, no frameworks
│   ├── __init__.py       PUBLIC SURFACE. Import from here, never deeper
│   ├── router.py         Router.find / find_many: validate, choose, delegate
│   ├── search.py         A* over (via_edge, node) states
│   ├── assemble.py       path -> geometry, manoeuvre steps, distance, time
│   ├── graph.py          RoadGraph interface + InMemoryRoadGraph
│   ├── models.py         Node, Edge, TurnRestriction, RouteRequest, Route
│   ├── costs.py          CostModel family, VehicleProfile, CostContext
│   ├── constraints.py    per-request avoid rules
│   ├── heuristics.py     admissible bounds (internal)
│   ├── geometry.py       haversine, bearings, turn angles
│   └── errors.py         RoutingError and its subclasses
│
├── tests/
│   ├── contract/test_v1.py   THE SPECIFICATION. Imports the public surface only
│   ├── fixtures/             a hand-built town, and seeded random grids
│   └── test_*.py             unit and block tests
│
└── bench/benchmark.py    A* against Dijkstra, both cost modes, by graph size
```

## Running it

```bash
pip install -r requirements.txt

pytest                                  # 180 tests
pytest tests/contract                   # just the contract suite
python -m bench.benchmark
python -m bench.benchmark --sizes 10 50 100 --repeats 5
```

## Using it

```python
from routing import Router, RouteRequest

router = Router(graph=graph)
route = router.find(RouteRequest(origin="n_4471", destination="n_9102"))

route.distance        # 4408.6  metres
route.travel_time     # 358.2   seconds, what an ETA is built from
route.geometry        # (LatLon(...), ...) drawable without the graph
for step in route.steps:
    print(step.maneuver.value, step.name, round(step.distance), "m")
    # depart     Nguyen Hue          1092 m
    # right      Nam Ky Khoi Nghia   1112 m
    # left       Le Loi              1092 m
    # right      Hai Ba Trung        1112 m
    # arrive     Hai Ba Trung           0 m
```

Live conditions, which is how `traffic` and `road_condition` connect:

```python
from routing import DynamicCostModel, StaticCostModel, CostMode

conditions = {"seg_881": 2.5, "seg_882": 1.8}      # >= 1.0; slower, never faster
router = Router(graph=graph, costs=DynamicCostModel(StaticCostModel(CostMode.FASTEST), conditions))
```

## How it works

**The graph is an interface.** `RoadGraph` is an abstract base class;
`InMemoryRoadGraph` is the only implementation here, and `search.py` never
imports it. A PostGIS-, SQLite-, or tile-backed graph is a drop-in replacement.
Two methods have working defaults so a graph carrying no turn data is still a
valid graph, and `max_speed()` can be answered from a stored value instead of a
full scan.

**A search state is `(via_edge, node)`, not a node.** Whether leaving a
junction into a given street is legal depends on the street you arrived by, so
the arrival edge has to be part of the state. This is what makes turn
restrictions — OSM's `no_left_turn` and `only_straight_on` — expressible at
all, and it is why a U-turn can be recognised and refused. The cost is roughly
one state per directed edge rather than one per node.

**Cost is not baked into the graph.** `Edge` stores facts: distance, speed,
class, name, shape. `CostModel` decides what those facts are worth for this
vehicle at this moment. That is what lets cost mode and live traffic vary per
request without the graph ever changing.

**Travel time is not the cost.** `StaticCostModel` multiplies time cost by a
road-class penalty, so a truck's cost for a residential street exceeds the time
it takes to drive it. `Route.travel_time` is computed separately, from
`CostModel.travel_time`, and the contract requires the two to agree exactly.
An ETA built from the weighted number would be wrong in a way nothing
downstream could detect.

**The router owns the heuristic.** Callers cannot supply one. A heuristic that
does not match the cost mode does not fail — it returns a worse route, silently.
Instead, penalties and condition multipliers are validated to be at least 1.0,
and the router derives a bound that is provably admissible from the graph's
fastest edge and the profile's speed factor. A cost model that cannot promise
that bound declares `admits_astar = False` and gets Dijkstra. Correct by
construction beats correct by convention.

**Constraints are a request-time overlay.** Blocking a segment for one trip
never touches the shared graph, so one `Router` and one `RoadGraph` serve
concurrent requests carrying different rules.

## A* against Dijkstra

Both run the same code path over the same graph for the same request,
differing only in whether a heuristic is supplied, so the gap is attributable
to the heuristic and nothing else. From `python -m bench.benchmark`:

```text
     grid   nodes  mode       algorithm   mean ms   settled
    60x60    3600  shortest   dijkstra      98.76     13867
    60x60    3600  shortest   astar         80.97     10067
    60x60    3600  fastest    dijkstra     119.90     13864
    60x60    3600  fastest    astar        106.72     12615
```

A* always settles fewer states. It wins clearly in `shortest` mode, where
straight-line distance is a tight bound. In `fastest` mode the bound divides by
the graph's single fastest speed, so where speeds vary widely it is loose, saves
under 15% of states, and barely pays for its own trigonometry. That is a real
property of the heuristic, not a measurement artefact, and it is written down
in `contract.md` rather than smoothed over. Tightening it needs per-region
speed bounds or landmarks — a 2.0 concern; correctness does not depend on it.

## What is not here

Coordinate endpoints and nearest-road snapping (`map_matching`), alternative
routes, live rerouting (`navigation`), and any source of road data. The block
does one thing.
