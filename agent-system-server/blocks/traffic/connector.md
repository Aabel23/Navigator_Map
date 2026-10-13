# traffic — Connector

## Responsibility

Turn measurements into what the server believes about how fast the network is
moving, and into what that should cost a route.

This block does no I/O. `ingest` fetches; `traffic` interprets.

## Inputs

- `Observations` batches from `ingest` — speeds a source reported, with
  provenance and confidence, carrying no interpretation
- the published roads those measurements may be attributed to, from a
  `RoadNetwork`
- a `RoadEdgeIndex` — `road_edges(area) -> {road_id: (edge_id, ...)}`

## Outputs

- `RoadSpeed` — one conclusion per road: speed, free-flow reference, level,
  source, confidence, age
- `TrafficSnapshot` — the picture for one area, with its sources and failures
- `{edge_id: multiplier}` for routing, every value at least 1.0

## Connectors

### `ingest → traffic`
Normalized observation batches. Traffic never calls a provider itself.

### `mapdata → traffic`
Published roads to attach measurements to, and the road-to-edge mapping.
Traffic holds no geometry of its own.

### `traffic → routing`
`TrafficCostSource` satisfies `routing.TrafficCostProvider`.

### `traffic → api`
`TrafficSnapshot` for `GET /api/v1/traffic`, and the level table for
`GET /api/v1/traffic/levels` — served rather than documented, so no renderer
ships its own opinion of what "heavy" looks like.

## Stable guarantees consumers may rely on

- Every multiplier is at least 1.0 and at most the documented ceiling. A jam is
  never infinite: blocking belongs to `roadstate`.
- An edge with no reading is absent from the mapping, not present as 1.0.
- Measured always beats modelled for the same road. Readings are ranked, never
  averaged.
- A reading older than `max_age_s` is gone, not stale.
- A modelled record carries `source == "simulated"`, and a snapshot made only
  of them reports `is_simulated`.

## Forbidden internal details

- `traffic.processing.attach` — how a measurement finds its road
- `traffic.state.store` internals — the dictionary, the lock, the clock
- the `way#index` edge-id convention. Ask `mapdata` for the mapping.

## Inside the block

```text
traffic/
├── __init__.py            the public surface
├── levels.py              ratio -> level, thresholds, colours, level_payload()
├── models.py              RoadSpeed, TrafficSnapshot, SIMULATED_SOURCE
├── processing/
│   ├── attach.py          attach(): measurement -> published road; RoadIndex
│   └── cost.py            multiplier_for(): ratio -> cost, capped
└── state/
    ├── store.py           TrafficState: the current picture, expiring
    └── provider.py        TrafficCostSource: road ids -> edge ids -> multipliers
```

**The flow through the files.**

```text
ingest.Observations  +  mapdata RoadSegment[]
        │
        ▼  processing/attach.py
        │     a record naming its road_id wins outright
        │     a point snaps to the nearest road within 120 m
        │     past that: "no road"
        ▼
   RoadSpeed(road_id, speed_kph, free_flow_kph, source, confidence, at)
        │
        ▼  state/store.py  TrafficState.apply()
        │     ranked, never averaged: measured > confidence > recency
        │     entries older than DEFAULT_MAX_AGE_S drop out
        ▼
   the current picture  ──▶ models.TrafficSnapshot ──▶ GET /api/v1/traffic
        │                     (levels.py classifies each ratio here)
        │
        ▼  state/provider.py  TrafficCostSource.multipliers_for(area)
        │     1. read the roads in the area out of TrafficState
        │     2. processing/cost.py turns each ratio into a multiplier, capped
        │     3. mapdata.road_edges(area) maps road_id -> edge_ids
        ▼
   {edge_id: multiplier}  ──▶ routing.DynamicCostModel
```

**The three judgements this block makes** — and all three are judgements
rather than lookups, which is exactly why none of them is in `ingest`:

1. **Which road a measurement is about** (`processing/attach.py`).
2. **Which reading to believe when two disagree** (`state/store.py`).
3. **What a ratio means** (`levels.py`), in one place, for every provider at
   once.
