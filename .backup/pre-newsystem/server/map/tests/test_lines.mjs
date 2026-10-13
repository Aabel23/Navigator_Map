// Offline, deterministic checks on polyline extrusion.
//
// The properties that matter to the renderer are geometric, so that is what is
// asserted: the ribbon has two vertices per kept centreline point, its indices
// are rebased against whatever was already in the buffer, the extrusion at an
// endpoint is a unit normal to that segment, and the extrusion at a corner is
// the bisector lengthened by exactly 1/cos(half-angle) -- which is what makes
// the two segments' outer edges meet instead of overlapping or gapping.
//
//   node tests/test_lines.mjs

import { addPolyline, LINE_VERTEX_FLOATS as F } from "../ui/static/lines.js";

let failures = 0;

function check(name, ok, detail) {
  if (ok) {
    console.log(`  ok   ${name}`);
    return;
  }
  failures += 1;
  console.log(`  FAIL ${name}${detail ? ` -- ${detail}` : ""}`);
}

function near(a, b, eps = 1e-9) {
  return Math.abs(a - b) < eps;
}

function vertex(verts, i) {
  return {
    x: verts[i * F],
    y: verts[i * F + 1],
    ex: verts[i * F + 2],
    ey: verts[i * F + 3],
    side: verts[i * F + 4],
    style: verts[i * F + 5],
  };
}

console.log("lines");

// A straight horizontal run: three points, two quads, four triangles.
{
  const verts = [];
  const idx = [];
  const tris = addPolyline(verts, idx, [0, 10, 20], [0, 0, 0], 3, 7);

  check("straight: 4 triangles", tris === 4, `got ${tris}`);
  check("straight: 6 vertices", verts.length / F === 6, `got ${verts.length / F}`);
  check("straight: 12 indices", idx.length === 12, `got ${idx.length}`);

  const v0 = vertex(verts, 0);
  const v1 = vertex(verts, 1);
  check("straight: normal is perpendicular", near(v0.ex, 0) && near(v0.ey, 1), `${v0.ex},${v0.ey}`);
  check("straight: opposite edge mirrors it", near(v1.ex, -v0.ex) && near(v1.ey, -v0.ey));
  check("straight: sides are +1 / -1", v0.side === 1 && v1.side === -1);
  check("straight: style rides on every vertex", verts.every((_, i) => i % F !== 5 || verts[i] === 7));
  check(
    "straight: every index inside the ribbon",
    idx.every((i) => i >= 0 && i < verts.length / F)
  );
}

// A right-angle corner: the mitre must be sqrt(2) long, or the outer edges of
// the two segments do not meet at the corner.
{
  const verts = [];
  const idx = [];
  addPolyline(verts, idx, [0, 10, 10], [0, 0, 10], 3, 0);
  const corner = vertex(verts, 2);
  const length = Math.hypot(corner.ex, corner.ey);
  check("right angle: mitre length is 1/cos(45deg)", near(length, Math.SQRT2, 1e-12), `got ${length}`);
}

// A hairpin: the bisector is degenerate, and must fall back rather than emit
// NaN, which would silently blank the whole draw call.
{
  const verts = [];
  const idx = [];
  addPolyline(verts, idx, [0, 10, 0], [0, 0, 0], 3, 0);
  check("hairpin: no NaN in the ribbon", verts.every((v) => Number.isFinite(v)));
}

// Appending to a buffer that already holds geometry: the second ribbon's
// indices must start after the first, not at zero.
{
  const verts = [];
  const idx = [];
  addPolyline(verts, idx, [0, 10], [0, 0], 2, 0);
  const firstVertexCount = verts.length / F;
  const firstIndexCount = idx.length;
  addPolyline(verts, idx, [0, 10], [5, 5], 2, 1);

  const second = idx.slice(firstIndexCount);
  check(
    "append: second ribbon is rebased",
    second.every((i) => i >= firstVertexCount),
    `firstVertexCount ${firstVertexCount}, got ${second.join(",")}`
  );
  check(
    "append: indices still inside the buffer",
    idx.every((i) => i < verts.length / F)
  );
}

// Repeated coordinates are common in real tiles after simplification; they
// carry no direction, so they must be dropped rather than produce a zero-length
// normal.
{
  const verts = [];
  const idx = [];
  const tris = addPolyline(verts, idx, [0, 0, 10, 10], [0, 0, 0, 0], 4, 0);
  check("duplicates: collapsed to one quad", tris === 2, `got ${tris}`);
  check("duplicates: 4 vertices", verts.length / F === 4, `got ${verts.length / F}`);
}

// Everything collapsing to one point must leave the buffer exactly as it was.
{
  const verts = [];
  const idx = [];
  addPolyline(verts, idx, [5, 5], [5, 5], 2, 0);
  check("all duplicates: nothing appended", verts.length === 0 && idx.length === 0);

  addPolyline(verts, idx, [1], [1], 1, 0);
  check("single point: nothing appended", verts.length === 0 && idx.length === 0);
}

console.log(failures === 0 ? "\nall line checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
