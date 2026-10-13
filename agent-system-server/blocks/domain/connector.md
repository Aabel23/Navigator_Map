# domain — Connector

## Responsibility

Hold the vocabulary every block shares, and nothing else. One geographic
rectangle, one geographic point, and one proximity search.

This block exists because the alternative is three spellings of the same
rectangle and three hand-rolled nearest-neighbour grids, which is how a server
starts disagreeing with itself about what it was asked.

## Inputs

None. `domain` imports nothing — not another block, not a third-party package.
It is the bottom of the dependency graph and must stay there.

## Outputs

- `BBox` — a lon/lat rectangle, with parsing, intersection, padding and
  outward quantization
- `GeoPoint` — one validated position, longitude first
- `Coord` — a bare `(lon, lat)` pair
- `SpatialIndex` — labelled positions, searchable by proximity
- `index_of_polylines`, `densify` — building an index over line geometry
- `haversine_m`, `polyline_length_m`, `bounds_of`

## Connectors

### `domain → everything`
Every other block may import this one. None of them may be imported by it.

## Stable guarantees consumers may rely on

- Coordinates are `(longitude, latitude)` in degrees, WGS84, everywhere.
- `GeoPoint` refuses an out-of-range pair at construction, so a swapped
  lat/lon is an error rather than a plausible position in the Gulf of Guinea.
- `BBox.quantized` rounds **outward**, so a result cached under a snapped box
  is never smaller than the box actually asked for.
- `BBox.intersects` treats a shared edge as intersecting.
- `SpatialIndex.nearest` with `within_m` returns `None` when nothing is that
  close — an answer, not a failure. Without it, it returns the nearest point
  in the index whatever the distance.
- Ties are broken by label, ascending, so proximity results are deterministic.
- `index_of_polylines` fills long spans so a point beside the middle of a
  straight kilometre still finds its line, with error bounded by the step.

## Boundary rule

Nothing with a policy in it may be added here. A traffic level, a cost, a
severity, a road class — each is a judgement owned by a block, and putting one
here would make every block depend on it.

## Forbidden internal details

- the grid: cell size, ring widening, the full-scan fallback
- how densification interpolates

## Inside the block

```text
domain/
├── __init__.py   the public surface; the only import path
├── geo.py        BBox, GeoPoint, Coord, haversine_m, polyline_length_m, bounds_of
└── spatial.py    SpatialIndex, densify, index_of_polylines
```

**How they work together.** `geo.py` defines the value types and the distance
arithmetic and depends on nothing. `spatial.py` builds on it: `densify` turns a
polyline into points spaced closely enough that the 25 m bound holds,
`index_of_polylines` runs that over many polylines and drops the results into a
degree grid, and `SpatialIndex.nearest` walks outward ring by ring using
`haversine_m` to rank candidates. Two blocks use it for different things —
`mapdata` indexes graph junctions to snap a coordinate to a node id,
`roadstate` and `traffic` index road polylines to attach a report or a
measurement to a road — and neither had to write the grid.
