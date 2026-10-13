// Polyline -> triangle strip, with the width left to the vertex shader.
//
// A road is not a GL_LINES segment: it has a real width in screen pixels that
// has to stay constant as the camera zooms, and it needs a casing drawn under
// it. Both fall out of the same trick -- store the *direction* to push each
// vertex sideways, not the pushed position, and let the shader multiply that
// direction by whatever half-width the style says at the current zoom. One
// buffer of geometry then serves both the casing pass and the fill pass, at
// any zoom, without ever being rebuilt.
//
// Vertex layout, six floats:
//   x, y      world position of the centreline point
//   ex, ey    unit-ish sideways direction; length > 1 at a mitred join
//   side      +1 or -1, the signed edge of the ribbon, for the shader's
//             one-pixel antialiasing feather
//   style     index into the line style table

export const LINE_VERTEX_FLOATS = 6;

/** Beyond this, a mitre spike is cut back to a bevel-ish stub. */
const MITER_LIMIT = 2.0;

/**
 * Append one polyline's ribbon to a bucket's vertex and index arrays.
 *
 * @param {number[]} verts - flat vertex array being accumulated.
 * @param {number[]} indices - flat index array being accumulated; indices are
 *   local to `verts`, and get rebased once when the tile is uploaded.
 * @param {ArrayLike<number>} xs - centreline x coordinates.
 * @param {ArrayLike<number>} ys - centreline y coordinates.
 * @param {number} n - how many of `xs`/`ys` to use.
 * @param {number} styleIndex - row in the line style table.
 * @returns {number} triangles appended.
 */
export function addPolyline(verts, indices, xs, ys, n, styleIndex) {
  if (n < 2) return 0;

  const base = verts.length / LINE_VERTEX_FLOATS;
  let written = 0;
  let prevX = 0;
  let prevY = 0;

  for (let i = 0; i < n; i++) {
    const x = xs[i];
    const y = ys[i];
    // A repeated point has no direction of its own and would produce a NaN
    // normal, so it is dropped rather than special-cased downstream.
    if (written > 0 && x === prevX && y === prevY) continue;

    let ex;
    let ey;
    const prev = written > 0 ? { x: prevX, y: prevY } : null;
    const next = i + 1 < n ? { x: xs[i + 1], y: ys[i + 1] } : null;

    if (!prev && next) {
      [ex, ey] = normalOf(x, y, next.x, next.y);
    } else if (prev && !next) {
      [ex, ey] = normalOf(prev.x, prev.y, x, y);
    } else if (prev && next) {
      [ex, ey] = miterOf(prev.x, prev.y, x, y, next.x, next.y);
    } else {
      continue; // a single point is not a line
    }

    verts.push(x, y, ex, ey, 1, styleIndex);
    verts.push(x, y, -ex, -ey, -1, styleIndex);
    written += 1;
    prevX = x;
    prevY = y;
  }

  if (written < 2) {
    // Undo: a run of duplicates collapsed to fewer than two real points.
    verts.length = base * LINE_VERTEX_FLOATS;
    return 0;
  }

  for (let i = 0; i < written - 1; i++) {
    const a = base + i * 2;
    indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
  }
  return (written - 1) * 2;
}

/** Unit left normal of the segment (x0,y0) -> (x1,y1). */
function normalOf(x0, y0, x1, y1) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len = Math.hypot(dx, dy);
  if (len === 0) return [0, 0];
  return [-dy / len, dx / len];
}

/**
 * Extrusion at an interior vertex: the bisector of the two segment normals,
 * lengthened so the ribbon's outer edges actually meet, and clamped so a
 * hairpin turn produces a stub instead of a spike halfway across the tile.
 */
function miterOf(x0, y0, x1, y1, x2, y2) {
  const [n1x, n1y] = normalOf(x0, y0, x1, y1);
  const [n2x, n2y] = normalOf(x1, y1, x2, y2);

  let mx = n1x + n2x;
  let my = n1y + n2y;
  const len = Math.hypot(mx, my);
  if (len < 1e-6) return [n1x, n1y]; // doubles back on itself

  mx /= len;
  my /= len;
  const cos = mx * n2x + my * n2y;
  const scale = cos > 1 / MITER_LIMIT ? 1 / cos : MITER_LIMIT;
  return [mx * scale, my * scale];
}

/**
 * Pick where a label should sit on a polyline, and which way it should read.
 *
 * The anchor is the halfway point by arc length, and the angle is the local
 * tangent there. Text is placed straight rather than bent along the curve:
 * over the length of a street name at driving zoom a road is very nearly
 * straight, and a straight label needs no re-layout when the camera zooms,
 * which a curved one would.
 *
 * @returns {{x, y, angle, length}|null}
 */
export function lineAnchor(xs, ys, count) {
  if (count < 2) return null;

  let total = 0;
  for (let i = 1; i < count; i++) total += Math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]);
  if (total === 0) return null;

  const half = total / 2;
  let walked = 0;
  for (let i = 1; i < count; i++) {
    const dx = xs[i] - xs[i - 1];
    const dy = ys[i] - ys[i - 1];
    const segment = Math.hypot(dx, dy);
    if (segment === 0) continue;
    if (walked + segment < half) {
      walked += segment;
      continue;
    }
    const t = (half - walked) / segment;
    let angle = Math.atan2(dy, dx);
    // Keep text reading left to right. The map has no bearing, so a world
    // angle is a screen angle, and flipping by half a turn is enough. Wrap
    // back into (-pi, pi] afterwards -- the shader only ever consumes this
    // through sin/cos, so an unwrapped 2*pi renders identically to 0, but a
    // canonical range is what a caller doing anything else with the angle
    // will expect.
    if (angle > Math.PI / 2 || angle < -Math.PI / 2) angle += Math.PI;
    if (angle > Math.PI) angle -= 2 * Math.PI;
    return {
      x: xs[i - 1] + dx * t,
      y: ys[i - 1] + dy * t,
      angle,
      length: total,
    };
  }
  return null;
}
