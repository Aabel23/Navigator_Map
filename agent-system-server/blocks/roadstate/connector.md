# roadstate — Connector

## Responsibility

Own what is temporarily true about a road: closures, flooding, construction,
incidents, restrictions. Classify a report into one of them, attach it to
published roads, keep it for as long as it is in force, answer what is in
force in an area, and express all of that to routing as **blocked edges** and
**cost multipliers**.

The distinction from `traffic` is this block's reason to exist. Traffic is a
measurement that decays — true for minutes, replaced by the next reading. A
condition *ends* rather than decaying, and until it does it is as true at 3
a.m. as at rush hour.

## Inputs

| Name | Type | Source |
|---|---|---|
| normalized report | plain mapping: id, geometry, kind hint, severity, window, provenance | `ingest.normalize_report` |
| published roads | `Sequence[RoadSegment]` | `mapdata`, handed in |
| road → edge mapping | `{road_id: (edge_id, …)}` | `mapdata.RoadGraphProvider.road_edges(area)` |
| persistence | `storage.DocumentStore` | the `road_conditions` collection |
| area | `domain.BBox` | whoever is asking |

## Outputs

| Name | Type | Meaning |
|---|---|---|
| `RoadCondition` | frozen dataclass | one condition: kind, severity, geometry, road ids, validity window, blocking |
| `RoadStateSnapshot` | frozen dataclass | what is in force in an area now |
| `ConditionKind`, `Severity` | enums | the vocabulary |
| `classify`, `classify_all`, `CLASSIFIERS` | functions, table | report → condition |
| `attribute`, `DEFAULT_RADIUS_M` | function, constant | geometry → road ids |
| `RoadStateStore` | class | record, query by area and instant, withdraw |
| `RoadStateSource.blocked_edges(area)` | method | `frozenset[edge_id]` |
| `RoadStateSource.multipliers_for(area)` | method | `{edge_id: float}`, each ≥ 1.0 |

## Connectors

### `ingest → roadstate`

A normalized report — shape only, no judgement. `classify` decides what it is.

### `roadstate → routing` — `RoadStateProvider`

Declared in `routing/providers.py` as a `typing.Protocol`; satisfied here by
`RoadStateSource`. **Two methods, two paths, and they must stay two:**

```text
blocking?  ──▶ blocked_edges(area)  ──▶ RouteConstraints.blocked_edges
otherwise  ──▶ multipliers_for(area) ──▶ DynamicCostModel
```

A closure is a **constraint**, never a cost. Expressing it as a very large
number is the classic navigation defect: when nothing else connects the two
ends of a trip, the search happily "uses" the expensive road and returns a
route down a flooded street, with an unusually long ETA as the only symptom. A
constraint cannot be traded off, so the honest answer — no route — is what
comes back.

Everything else is a cost. Roadworks, a crash, shallow water: worse, not gone.
A driver would rather crawl past a works site than be sent five kilometres
around it.

### `mapdata → roadstate` — `RoadEdgeIndex`

`road_edges(area)`. Same bridge `traffic` uses, for the same reason.

### `roadstate → storage`

Conditions are persisted with their validity windows.

### `roadstate → api`

`GET /api/v1/roadstate?bbox=`, `GET`/`DELETE /api/v1/roadstate/{id}`.

## Stable guarantees consumers may rely on

- **`blocked_edges` does not degrade.** If the road-to-edge mapping cannot be
  read it *raises*, the routing service turns that into an error, and the
  request fails safely. Silently dropping a closure is the one failure mode
  this block must never have.
- **`multipliers_for` does degrade**, to `{}`. A route priced without knowing
  about a works site is merely a worse route.
- **Every multiplier is ≥ 1.0**, capped, and where traffic and road state both
  report on an edge the **worse** value wins rather than the product. A flooded
  road is slow *because* it is flooded; multiplying charges the driver twice
  for one event observed twice.
- **Classification order is `closure → flooding → construction → incident`**,
  and it is not alphabetical. Reports overlap: "flooded street closed to
  traffic" matches two rules, and which wins decides whether a driver is
  routed around it or merely slowed. Closure first because it is the strongest
  claim in the system and the most expensive to get wrong permissively.
  Incident last, as the catch-all that never declines.
- **Flooding blocks at 30 cm** — deliberately below where a car actually
  fails, because the cost of an unnecessary detour is minutes and the cost of
  the other error is the vehicle. Where no depth is published (the common
  case) severity falls back to what the source declared, and only an
  explicitly impassable report blocks.
- **A condition without an end time stops being believed after six hours.**
  Several free feeds publish an incident and withdraw it once it clears; a
  crash nobody withdrew must not divert traffic for a week.

## Forbidden internal details

- `roadstate.kinds.*`, `roadstate.classify`, `roadstate.store` as import
  paths — import from `roadstate`.
- the keyword tables inside each `kinds/` module.
- the multiplier table values — product decisions, expected to move.
- **No other module may decide what a report is.** `classify.py` is the one
  place, in its stated order.

## Inside the block

```text
roadstate/
├── __init__.py        the public surface
├── models.py          RoadCondition, RoadStateSnapshot, ConditionKind, Severity,
│                      DEFAULT_MULTIPLIERS
├── classify.py        classify(), classify_all(), CLASSIFIERS -- the ordered table
├── kinds/
│   ├── closures.py       is this a closure?   (asked first)
│   ├── flooding.py       is this flooding?    (the 30 cm threshold)
│   ├── construction.py   is this works?
│   └── incidents.py      the catch-all that never declines
├── attribute.py       geometry -> road ids, along the whole length
├── store.py           RoadStateStore: record, query, withdraw, age out
└── provider.py        RoadStateSource: the two paths to routing
```

**The flow through the files.**

```text
report (operator, client, or a feed's incident)
    │
    ▼  ingest.incidents.normalize_report        shape only; no judgement
    │
    ▼  classify.py  -> kinds/closures.py -> flooding.py -> construction.py -> incidents.py
    │     first match wins; the order is the policy
    ▼
  RoadCondition (kind, severity, blocking, window)
    │
    ▼  attribute.py
    │     geometry -> road ids, along the whole length, via domain.SpatialIndex
    │     over the roads mapdata published
    ▼
  RoadCondition with road_ids
    │
    ▼  store.py  RoadStateStore.record()
    │     persisted through storage.DocumentStore with its validity window
    │     an open-ended condition ages out after DEFAULT_OPEN_ENDED_TTL
    ▼
  in force in this area, now
    │
    ▼  provider.py  RoadStateSource
    │     mapdata.road_edges(area) maps road_id -> edge_ids, then:
    ├──▶ blocked_edges(area)   frozenset[edge_id]      -> RouteConstraints
    └──▶ multipliers_for(area) {edge_id: float} ≥ 1.0  -> DynamicCostModel
```

**Why `kinds/` is one module per kind.** Each kind has its own rules, its own
severity scale and its own blocking test — flooding has a depth threshold,
construction has none, a closure is blocking by definition. Keeping them apart
means adding a kind is adding a module and a row in `CLASSIFIERS`, and changing
the flooding threshold cannot accidentally change what counts as roadworks.
