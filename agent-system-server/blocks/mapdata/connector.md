# mapdata — Connector

## Responsibility

Own the server's authoritative road network and the routable graph built from
it — including the nearest-junction lookup that turns a coordinate into a node
id.

"MapData" and "the map the driver looks at" are different things that share a
word. This block owns geometry, classes, speed limits, connectivity and the
graph. The **client** owns tiles, styles, sprites and rendering. The server
never sends a tile.

## Inputs

| Name | Type | Source |
|---|---|---|
| area | `domain.BBox` | whoever is asking |
| map source data | Overpass JSON over HTTP | OpenStreetMap, free and keyless |
| stored roads | `storage.DocumentStore` | the `roads` collection |
| source cache | `storage.Cache` | so a volunteer service is not asked twice |

## Outputs

| Name | Type | Meaning |
|---|---|---|
| `RoadSegment` | frozen dataclass | one published road: geometry, class, free-flow reference, name, one-way |
| `RoadNetwork` | protocol | `roads(area) -> Sequence[RoadSegment]` |
| `RoadGraphProvider.graph_for(area)` | method | a `GraphView` |
| `NetworkGraphView` | class | `.graph`, `.nearest_node(point)`, `.road_edges()` |
| `build_graph`, `GraphBuild`, `node_id_for` | function, dataclass, function | the way→edge split, exposed for tests and diagnostics |
| `MapDataError`, `SourceUnavailable`, `BadResponse` | exceptions | the only failures that escape |

## Connectors

### `mapdata → routing` — `MapGraphProvider`

Declared in `routing/providers.py` as a `typing.Protocol`; satisfied here by
`RoadGraphProvider`. Routing asks `graph_for(area)` and receives a `GraphView`
carrying the loaded graph and a `nearest_node` callable. **Routing imports
nothing from this block**, and this block imports routing's types rather than
the reverse.

### `mapdata → traffic`, `mapdata → roadstate` — `RoadEdgeIndex`

`road_edges(area) -> {road_id: (edge_id, …)}`. Both blocks are keyed by *road*
and routing is keyed by *edge*; this is the bridge. Ask for it — **never
reconstruct the `way#index` convention**. Guessing works today and breaks
silently the first time splitting changes, with the only symptom being routes
that ignore traffic.

### `mapdata → ingest` — `RoadNetwork`

The modelled traffic provider needs a reference network to attach numbers to.
It receives one structurally; neither block imports the other.

### `mapdata → api`

`GET /api/v1/mapdata/roads?bbox=` and `GET /api/v1/mapdata/graph?bbox=`.

### `mapdata → storage`

Roads are persisted as documents; source responses go through `Cache`.

## Stable guarantees consumers may rely on

- **Edge ids are stable.** `way#index`. A closure recorded yesterday still
  names a real edge today.
- **Node ids are derived from a rounded coordinate**, so the same junction
  gets the same id on every build.
- A `RoadSegment` carries geometry, class, free-flow speed, name and one-way —
  and **nothing about cost, traffic or conditions**.
- Each edge keeps its own slice of the source polyline, so a route is drawable
  without the consumer ever touching the graph.
- Map data is **longitude-first**; routing is latitude-first. The single
  conversion is in `graph/build.py` and nowhere else.
- If the source is unreachable, a previously imported area still answers from
  storage. An area never imported answers "no roads" rather than a stale graph
  from a neighbouring area.

## Forbidden internal details

- `mapdata.roads.overpass`, `mapdata.graph.build`, `mapdata.http` as import
  paths — import from `mapdata`.
- the Overpass query text, the cache key, the free-flow default table.
- how a way is split, provided edge ids stay stable and `road_edges()` keeps
  reporting the mapping.
- **Nothing else may hold a second road network.**

## Inside the block

```text
mapdata/
├── __init__.py         the public surface
├── models.py           RoadSegment, coords_of
├── network.py          RoadNetwork -- the protocol a source satisfies
├── errors.py           MapDataError, SourceUnavailable, BadResponse
├── http.py             the one place this block touches the network
├── roads/overpass.py   OverpassRoadSource: query, parse, maxspeed, class defaults
├── graph/
│   ├── build.py        ways -> junctions -> edges; the lon/lat flip
│   └── provider.py     RoadGraphProvider, NetworkGraphView, snapping
└── store.py            RoadStore, StoredRoadNetwork, PersistingRoadNetwork
```

**The flow through the files.**

```text
BBox
 │
 ▼  store.PersistingRoadNetwork.roads(area)
 │     ├─ try roads/overpass.py  -> http.py -> Overpass -> parse -> RoadSegment[]
 │     │      (storage.Cache short-circuits a repeat question)
 │     ├─ save through store.RoadStore -> storage.DocumentStore
 │     └─ on failure, fall back to store.StoredRoadNetwork (what was saved before)
 ▼
RoadSegment[]                     lon/lat, one line per OSM way
 │
 ▼  graph/build.py  build_graph()
 │     1. find junctions: any coordinate two ways share, plus every way's ends
 │     2. split each way there; each piece keeps its slice of the polyline
 │     3. name them: node id from the rounded coordinate, edge id from way#index
 │     4. flip to latitude-first -- the only place in the server that does
 ▼
GraphBuild (routing.RoadGraph + the road_id -> edge_ids mapping)
 │
 ▼  graph/provider.py
 │     RoadGraphProvider caches the build per area
 │     NetworkGraphView wraps it: .graph, .nearest_node(), .road_edges()
 │       nearest_node uses domain.SpatialIndex over the junctions
 ▼
consumed by routing (the graph and the snap) and by
traffic / roadstate (the road_id -> edge_id mapping)
```

**Ways are not edges** is the most consequential thing this block does. OSM
publishes a *way*: one line that may run two kilometres through nine
intersections. A router needs an *edge*: a stretch between two junctions with
nothing to turn off onto in between. Handing a way straight to the router makes
every junction along it invisible and the route sails past the turn it needed —
not a crash, and not something a test that merely checks a route came back
would catch. Hence `tests/test_graph.py`.

**Snapping lives here** because the nodes do. Routing's contract is explicit
that turning a coordinate into a node id is not routing's job, and doing it in
two places would give the system two ways to disagree about where the driver
is.
