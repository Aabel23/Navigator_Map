// An offline, deterministic check of mvt.js -- no network, no browser.
//
// The fixture (fixtures/tiny.pbf) was built once by the project's Python MVT
// encoder, which its own test suite already holds to the Mapbox Vector Tile
// spec. The expected counts below are worked out by hand from the four
// features that went into it, not copied from a prior run of this decoder --
// that is what makes this a check of correctness rather than a change
// detector.
//
//   building: one closed ring, 4 distinct vertices
//   water:    one closed ring, 3 distinct vertices
//   transportation, class=primary:     open line, 3 vertices
//   transportation, class=residential: open line, 2 vertices
//   poi: a point feature, class=cafe, with no name tag
//
// A quad triangulates to 2 triangles and a triangle to 1; an open line of N
// points extrudes to (N-1) quads, so 2(N-1) triangles over 2N vertices; a
// closed ring outlined as a line has one more point than the ring, for the
// closing edge the tile leaves implicit.
//
// Run: node tests/test_mvt_decode.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { decodeTileMesh } from "../ui/static/mvt.js";

const here = dirname(fileURLToPath(import.meta.url));
const buf = new Uint8Array(readFileSync(join(here, "fixtures", "tiny.pbf")));

// The same shape /api/config serves, cut down to the layers the fixture has.
// Style indices are arbitrary here: what matters is that they reach the
// vertices unchanged.
function styleFixture(overrides = {}) {
  return {
    buckets: ["land", "water", "building", "road"],
    bucket_kinds: { land: "fill", water: "fill", building: "fill", road: "line" },
    zoom_stops: [13, 18],
    label_name_fields: ["name", "name:latin"],
    label_rules: {
      poi: {
        placement: "point",
        min_zoom: 0,
        icon: true,
        max_rank: null,
        classes: { "*": { style: 0, min_zoom: 0, max_zoom: null, priority: 100 } },
      },
      transportation_name: {
        placement: "line",
        min_zoom: 0,
        icon: false,
        max_rank: null,
        classes: { "*": { style: 1, min_zoom: 0, max_zoom: null, priority: 400 } },
      },
    },
    rules: {
      water: {
        bucket: "water",
        kind: "fill",
        min_zoom: 0,
        classes: { "*": { style: 0, min_zoom: 0 } },
      },
      building: {
        bucket: "building",
        kind: "fill",
        min_zoom: 0,
        outline: { bucket: "road", style: 9, min_zoom: 0 },
        classes: { "*": { style: 1, min_zoom: 0 } },
      },
      transportation: {
        bucket: "road",
        kind: "line",
        min_zoom: 0,
        classes: {
          primary: { style: 2, min_zoom: 0 },
          "*": { style: 3, min_zoom: 0 },
        },
      },
      ...overrides,
    },
  };
}

let failures = 0;

function expect(label, actual, expected) {
  if (actual !== expected) {
    console.error(`FAIL ${label}: expected ${expected}, got ${actual}`);
    failures += 1;
    return;
  }
  console.log(`ok   ${label} = ${actual}`);
}

function check(label, ok, detail) {
  if (ok) {
    console.log(`ok   ${label}`);
    return;
  }
  console.error(`FAIL ${label}${detail ? ` -- ${detail}` : ""}`);
  failures += 1;
}

const FILL_FLOATS = 3;
const LINE_FLOATS = 6;

const { buckets, labels, stats } = decodeTileMesh(buf, 0, 0, 0, null, 20, styleFixture(), 0);

// Five, not four: the point of interest counts because a *label* rule reaches
// its layer, even though no geometry rule does.
expect("stats.featuresConsidered", stats.featuresConsidered, 5);
expect("stats.featuresKept", stats.featuresKept, 4);
expect("stats.verticesIn", stats.verticesIn, 12);

// water: one triangular ring.
expect("water triangles", buckets.water.indices.length / 3, 1);
expect("water vertices", buckets.water.vertices.length / FILL_FLOATS, 3);

// building: one quad ring.
expect("building triangles", buckets.building.indices.length / 3, 2);
expect("building vertices", buckets.building.vertices.length / FILL_FLOATS, 4);

// road: the primary (3 points -> 4 triangles), the residential falling through
// to the wildcard rule (2 points -> 2 triangles), and the building's outline
// (4-point ring closed to 5 points -> 8 triangles).
expect("road triangles", buckets.road.indices.length / 3, 4 + 2 + 8);
expect("road vertices", buckets.road.vertices.length / LINE_FLOATS, 6 + 4 + 10);

// Nothing in the fixture is landcover.
expect("land triangles", buckets.land.indices.length / 3, 0);

for (const [name, mesh] of Object.entries(buckets)) {
  const floats = mesh.kind === "line" ? LINE_FLOATS : FILL_FLOATS;
  const vertexCount = mesh.vertices.length / floats;
  check(
    `${name}: every index inside the mesh`,
    mesh.indices.every((i) => i < vertexCount),
    `vertexCount ${vertexCount}`
  );
  check(`${name}: no NaN vertices`, mesh.vertices.every((v) => Number.isFinite(v)));
}

// The style index reaches the vertices: the primary road's style (2) and the
// wildcard's (3) must both appear, and the outline's (9) with them.
{
  const styles = new Set();
  const verts = buckets.road.vertices;
  for (let i = LINE_FLOATS - 1; i < verts.length; i += LINE_FLOATS) styles.add(verts[i]);
  check("road styles carried on vertices", [2, 3, 9].every((s) => styles.has(s)), [...styles].join(","));
}

// The fixture's point of interest is a cafe with no name. A label rule matches
// its class, but a nameless feature has nothing to draw, so it must produce no
// label rather than an empty one.
expect("nameless POI produces no label", labels.length, 0);

// LOD is a decode-time gate, not a draw-time one: below a class's zoom its
// geometry must not exist at all.
{
  const gated = styleFixture({
    transportation: {
      bucket: "road",
      kind: "line",
      min_zoom: 15,
      classes: { "*": { style: 3, min_zoom: 15 } },
    },
    building: {
      bucket: "building",
      kind: "fill",
      min_zoom: 16,
      classes: { "*": { style: 1, min_zoom: 16 } },
    },
  });
  const low = decodeTileMesh(buf, 0, 0, 0, null, 14, gated, 0);
  expect("LOD gated: road triangles", low.buckets.road.indices.length, 0);
  expect("LOD gated: building triangles", low.buckets.building.indices.length, 0);
  expect("LOD gated: water survives", low.buckets.water.indices.length / 3, 1);
  // A layer gated at the layer level is not walked at all, so its features are
  // never even counted -- which is the whole point of putting the gate there
  // rather than filtering after the parse. Water and the point of interest
  // survive; the two gated layers contribute nothing.
  expect("LOD gated: features considered", low.stats.featuresConsidered, 2);
  expect("LOD gated: features kept", low.stats.featuresKept, 1);
}

// The origin is subtracted from every vertex, and nothing else moves.
{
  const shifted = decodeTileMesh(buf, 0, 0, 0, { x: 10, y: 20 }, 20, styleFixture(), 0);
  const before = buckets.water.vertices;
  const after = shifted.buckets.water.vertices;
  check(
    "origin subtracted from every vertex",
    before.length === after.length &&
      before.every((v, i) => {
        if (i % FILL_FLOATS === 0) return Math.abs(v - 10 - after[i]) < 1e-9;
        if (i % FILL_FLOATS === 1) return Math.abs(v - 20 - after[i]) < 1e-9;
        return v === after[i];
      })
  );
}

if (failures > 0) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log("\nall checks passed");
