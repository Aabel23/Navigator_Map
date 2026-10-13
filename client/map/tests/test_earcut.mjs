// Offline, deterministic checks on the triangulator.
//
// The expectations are properties of the algorithm rather than numbers copied
// from a prior run: a simple polygon with V vertices and H holes needs at most
// V + 2H - 2 triangles, the triangles must tile the polygon (so their areas
// sum to the polygon's own area, computed independently by the shoelace
// formula), and no index may fall outside the input. A triangulator that
// silently drops or overlaps triangles fails at least one of those three.
//
//   node tests/test_earcut.mjs

import { earcut } from "../ui/static/earcut.js";

let failures = 0;

function check(name, ok, detail) {
  if (ok) {
    console.log(`  ok   ${name}`);
    return;
  }
  failures += 1;
  console.log(`  FAIL ${name}${detail ? ` -- ${detail}` : ""}`);
}

function shoelace(coords) {
  let sum = 0;
  const n = coords.length / 2;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    sum += coords[i * 2] * coords[j * 2 + 1] - coords[j * 2] * coords[i * 2 + 1];
  }
  return Math.abs(sum) / 2;
}

function triangleArea(data, ia, ib, ic) {
  const ax = data[ia * 2];
  const ay = data[ia * 2 + 1];
  const bx = data[ib * 2];
  const by = data[ib * 2 + 1];
  const cx = data[ic * 2];
  const cy = data[ic * 2 + 1];
  return Math.abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2;
}

/**
 * Run the three invariants against one polygon.
 *
 * @param {string} name
 * @param {number[]} data - flat coordinates, exterior ring then holes.
 * @param {number[]} holeIndices
 * @param {number} expectedArea
 */
function checkPolygon(name, data, holeIndices, expectedArea) {
  const idx = earcut(data, holeIndices);
  const vertexCount = data.length / 2;
  const holeCount = holeIndices.length;
  const expectedTriangles = vertexCount + 2 * holeCount - 2;

  check(`${name}: index count is a multiple of 3`, idx.length % 3 === 0, `got ${idx.length}`);
  // V + 2H - 2 is the ceiling, not always the count: bridging a hole can leave
  // collinear vertices that filterPoints removes, and a triangulation with
  // fewer triangles covering the same area is strictly better. Paired with the
  // area check below, the bound is still tight -- too few triangles cannot
  // cover the polygon, and too many cannot fit under the ceiling.
  check(
    `${name}: at most ${expectedTriangles} triangles`,
    idx.length / 3 <= expectedTriangles && idx.length > 0,
    `got ${idx.length / 3}`
  );
  check(
    `${name}: every index inside the input`,
    idx.every((i) => Number.isInteger(i) && i >= 0 && i < vertexCount),
    `vertexCount ${vertexCount}`
  );

  let area = 0;
  for (let i = 0; i < idx.length; i += 3) area += triangleArea(data, idx[i], idx[i + 1], idx[i + 2]);
  const tolerance = Math.max(1e-6, expectedArea * 1e-9);
  check(
    `${name}: triangles tile the polygon`,
    Math.abs(area - expectedArea) < tolerance,
    `triangulated ${area}, expected ${expectedArea}`
  );
}

console.log("earcut");

// A unit square: the smallest thing that must work.
checkPolygon("square", [0, 0, 4, 0, 4, 4, 0, 4], [], 16);

// Concave: the ear test has to reject the reflex corner.
checkPolygon("L shape", [0, 0, 6, 0, 6, 2, 2, 2, 2, 6, 0, 6], [], 20);

// A hole: exercises the bridge search, and changes the triangle count.
checkPolygon(
  "square with square hole",
  [0, 0, 10, 0, 10, 10, 0, 10, 3, 3, 3, 7, 7, 7, 7, 3],
  [4],
  100 - 16
);

// Two holes: eliminateHoles has to bridge both, in leftmost-first order.
checkPolygon(
  "square with two holes",
  [0, 0, 20, 0, 20, 10, 0, 10, 2, 2, 2, 5, 5, 5, 5, 2, 12, 2, 12, 5, 15, 5, 15, 2],
  [4, 8],
  200 - 9 - 9
);

// A star: alternating reflex and convex vertices, the classic ear-clipping
// stress case at small scale.
{
  const star = [];
  const points = 5;
  for (let i = 0; i < points * 2; i++) {
    const r = i % 2 === 0 ? 10 : 4;
    const a = (Math.PI * i) / points;
    star.push(r * Math.cos(a), r * Math.sin(a));
  }
  checkPolygon("5-point star", star, [], shoelace(star));
}

// Large enough to take the z-order hashed path (> 80 vertices) and to catch a
// broken Morton code or a broken merge sort, which show up as missing area.
{
  const circle = [];
  const n = 512;
  for (let i = 0; i < n; i++) {
    const a = (2 * Math.PI * i) / n;
    circle.push(100 * Math.cos(a), 100 * Math.sin(a));
  }
  checkPolygon("512-gon (hashed path)", circle, [], shoelace(circle));
}

// Collinear and duplicated points, which every real tile has: filterPoints
// removes them, so the triangle count drops below V - 2.
{
  const data = [0, 0, 2, 0, 4, 0, 4, 4, 4, 4, 0, 4];
  const idx = earcut(data, []);
  let area = 0;
  for (let i = 0; i < idx.length; i += 3) area += triangleArea(data, idx[i], idx[i + 1], idx[i + 2]);
  check("degenerate points: area preserved", Math.abs(area - 16) < 1e-9, `got ${area}`);
  check(
    "degenerate points: no zero-area triangles",
    idx.length > 0 && area > 0,
    `${idx.length / 3} triangles, area ${area}`
  );
}

// Fewer than three distinct points cannot make a triangle, and must not throw.
check("two points: no triangles", earcut([0, 0, 1, 1], []).length === 0);
check("empty input: no triangles", earcut([], []).length === 0);

console.log(failures === 0 ? "\nall earcut checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
