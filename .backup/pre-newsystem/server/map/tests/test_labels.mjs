// Offline, deterministic checks on label layout, placement geometry, and
// collision -- no browser, no network, no GPU.
//
// The glyph store is stubbed with metrics whose arithmetic is easy to do in
// your head, so every expectation below can be derived rather than recorded.
// What is being checked is the part that goes visibly wrong when it breaks:
// text that is not centred on the thing it names, street names that read
// backwards, and labels that overlap.
//
//   node tests/test_labels.mjs

import { shapeText, shapeIcon, appendLabelQuads, LABEL_VERTEX_FLOATS } from "../ui/static/labels.js";
import { lineAnchor } from "../ui/static/lines.js";
import { CollisionGrid, rotatedBounds } from "../ui/static/collision.js";
import { SDF_FONT_SIZE, SDF_BUFFER } from "../ui/static/glyphs.js";

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

/**
 * A glyph store where every letter is 10 units wide and 20 tall, resting on a
 * baseline at 20, with a cap height of 20. Round numbers, so the expected
 * layout is arithmetic rather than a recorded result.
 */
function stubStore(extra = {}) {
  const uniform = { advance: 10, width: 10 + 2 * SDF_BUFFER, height: 20 + 2 * SDF_BUFFER, left: 0, top: -20, u: 4, v: 8 };
  return {
    verticalMetrics: () => ({ baseline: 20, capHeight: 20 }),
    get: (codePoint) => {
      if (codePoint in extra) return extra[codePoint];
      if (codePoint === 32) return { advance: 6, width: 0, height: 0, left: 0, top: 0, u: 0, v: 0 };
      return uniform;
    },
  };
}

console.log("labels");

// -- shaping ---------------------------------------------------------------------

// Four letters, ten units of advance each, at the SDF's own size: forty units
// wide, centred, so the run spans -20..20.
{
  const shaped = shapeText("ABCD", stubStore(), SDF_FONT_SIZE);
  check("4 glyphs produce 4 quads", shaped.quads.length === 4, `got ${shaped.quads.length}`);
  check("width is the total advance", near(shaped.width, 40), `got ${shaped.width}`);
  const left = Math.min(...shaped.quads.map((q) => q.x1));
  const right = Math.max(...shaped.quads.map((q) => q.x2));
  check("text is centred horizontally", near((left + right) / 2, 0), `centre ${(left + right) / 2}`);
  check("first quad starts at -halfWidth - buffer", near(shaped.quads[0].x1, -20 - SDF_BUFFER), `got ${shaped.quads[0].x1}`);
}

// Halving the size halves every dimension: the offsets are pure geometry, so
// the same shaping serves any point size.
{
  const full = shapeText("ABCD", stubStore(), SDF_FONT_SIZE);
  const half = shapeText("ABCD", stubStore(), SDF_FONT_SIZE / 2);
  check("size scales width linearly", near(half.width, full.width / 2), `${half.width} vs ${full.width}`);
  check("size scales offsets linearly", near(half.quads[0].x1, full.quads[0].x1 / 2));
}

// Vertical centring uses the typographic box, not the inked one: adding a tone
// mark that reaches higher must not shift the line it sits on. This is the
// check that keeps "Ha Noi" and "Hà Nội" on the same baseline.
{
  // Quad top is `-top - buffer`: a glyph whose ink reaches closer to the top
  // of the line (an accented capital, say) has a *less* negative `top` than a
  // plain one, not a more negative one -- confirmed against real decoded
  // metrics, where 'j' (top -8, dot near cap height) sits higher than 'g'
  // (top -13, bowl at x-height) despite 'j' having the smaller |top|.
  const tall = { advance: 10, width: 10 + 2 * SDF_BUFFER, height: 30 + 2 * SDF_BUFFER, left: 0, top: -8, u: 0, v: 0 };
  const plain = shapeText("AA", stubStore(), SDF_FONT_SIZE);
  const marked = shapeText("AÀ", stubStore({ 192: tall }), SDF_FONT_SIZE);
  check(
    "a tone mark does not move the baseline",
    near(plain.quads[0].y1, marked.quads[0].y1),
    `${plain.quads[0].y1} vs ${marked.quads[0].y1}`
  );
  check(
    "the taller glyph reaches higher",
    marked.quads[1].y1 < plain.quads[1].y1,
    `${marked.quads[1].y1} vs ${plain.quads[1].y1}`
  );
}

// A space advances the pen and emits no quad; a code point with no glyph at all
// emits nothing and advances nothing, so it cannot leave a hole.
{
  const spaced = shapeText("A B", stubStore(), SDF_FONT_SIZE);
  check("space emits no quad", spaced.quads.length === 2, `got ${spaced.quads.length}`);
  check("space still advances", near(spaced.width, 26), `got ${spaced.width}`);

  const missing = shapeText("A\u{10FFFF}B", { verticalMetrics: () => ({ baseline: 20, capHeight: 20 }), get: (cp) => (cp > 0xffff ? null : stubStore().get(cp)) }, SDF_FONT_SIZE);
  check("unmapped code point is skipped", missing.quads.length === 2 && near(missing.width, 20), `${missing.quads.length} quads, width ${missing.width}`);

  check("empty text produces nothing", shapeText("", stubStore(), 12).quads.length === 0);
}

// -- icons ---------------------------------------------------------------------

// A 2x sprite entry is half its pixel size on screen, and scaling to a target
// height must preserve the aspect ratio, or every icon is subtly squashed.
{
  const icon = shapeIcon({ x: 10, y: 20, width: 40, height: 40, pixelRatio: 2 }, 15);
  check("icon scaled to the requested height", near(icon.height, 15), `got ${icon.height}`);
  check("icon keeps its aspect ratio", near(icon.width, 15), `got ${icon.width}`);
  check("icon is centred on its anchor", near(icon.quads[0].x1, -7.5) && near(icon.quads[0].y1, -7.5));
  check("icon uses sprite-sheet pixels for uv", icon.quads[0].u1 === 10 && icon.quads[0].u2 === 50);

  const native = shapeIcon({ x: 0, y: 0, width: 40, height: 40, pixelRatio: 2 }, 0);
  check("size 0 means the sprite's own size", near(native.height, 20), `got ${native.height}`);
}

// -- vertex emission --------------------------------------------------------------

{
  const verts = [];
  const indices = [];
  const shaped = shapeText("AB", stubStore(), SDF_FONT_SIZE);
  const written = appendLabelQuads(verts, indices, shaped.quads, 100, 200, 0.5, 7, 3);

  check("4 vertices per quad", written === 8, `got ${written}`);
  check("6 indices per quad", indices.length === 12, `got ${indices.length}`);
  check("every index inside the run", indices.every((i) => i < written));

  const first = verts.slice(0, LABEL_VERTEX_FLOATS);
  check("anchor rides on every vertex", first[0] === 100 && first[1] === 200);
  check("angle rides on every vertex", first[4] === 0.5);
  check("style rides on every vertex", first[7] === 3);
  check("vertical offset is applied", near(first[3], shaped.quads[0].y1 + 7), `${first[3]}`);

  // Appending a second label must not renumber the first one's triangles.
  const before = indices.length;
  appendLabelQuads(verts, indices, shaped.quads, 0, 0, 0, 0, 1);
  check("second label's indices are rebased", indices.slice(before).every((i) => i >= written));
}

// -- line placement ----------------------------------------------------------------

// The anchor is the halfway point by arc length, not the middle vertex: on an
// unevenly divided line those are different points.
{
  const anchor = lineAnchor([0, 10, 100], [0, 0, 0], 3);
  check("anchor is halfway by length", near(anchor.x, 50) && near(anchor.y, 0), `${anchor.x},${anchor.y}`);
  check("anchor reports total length", near(anchor.length, 100), `got ${anchor.length}`);
  check("horizontal line has zero angle", near(anchor.angle, 0));
}

// A road drawn right-to-left would otherwise render its name upside down: the
// raw tangent points backwards (angle pi), and the flip must bring it back to
// pointing forwards (angle 0) -- not leave it pointing backwards still.
{
  const backwards = lineAnchor([100, 0], [0, 0], 2);
  check(
    "right-to-left line is flipped to point forward",
    near(Math.cos(backwards.angle), 1) && near(Math.sin(backwards.angle), 0),
    `got ${backwards.angle}`
  );
  const diagonal = lineAnchor([0, 100], [0, 100], 2);
  check("diagonal keeps its slope", near(diagonal.angle, Math.PI / 4), `got ${diagonal.angle}`);
  const steepBack = lineAnchor([100, 0], [0, 100], 2);
  check(
    "up-and-left line reads left to right",
    Math.abs(steepBack.angle) <= Math.PI / 2 + 1e-9,
    `got ${steepBack.angle}`
  );
}

check("a single point is not a line", lineAnchor([5], [5], 1) === null);
check("a zero-length line has no anchor", lineAnchor([5, 5], [5, 5], 2) === null);

// -- collision ------------------------------------------------------------------

{
  const grid = new CollisionGrid(400, 400);
  const first = [10, 10, 110, 40];
  check("the first box always fits", grid.fits(first));
  grid.insert(first);
  check("an overlapping box does not fit", !grid.fits([100, 30, 200, 60]));
  check("a touching-but-not-overlapping box fits", grid.fits([110, 10, 200, 40]));
  check("a distant box fits", grid.fits([300, 300, 380, 330]));

  // A box spanning many cells has to be found from any of them, not just the
  // one its top-left corner lands in.
  const wide = [0, 200, 400, 230];
  grid.insert(wide);
  check("a box spanning cells is found from the far end", !grid.fits([380, 210, 395, 225]));
}

// A rotated label's bounds must grow, never shrink: a diagonal street name
// sweeps a bigger axis-aligned box than the same text laid flat.
{
  const flat = rotatedBounds(0, 0, 100, 20, 0, 0);
  const tilted = rotatedBounds(0, 0, 100, 20, Math.PI / 4, 0);
  check("upright bounds are the text box", near(flat[0], -50) && near(flat[1], -10));
  check("rotated bounds are wider", tilted[3] - tilted[1] > flat[3] - flat[1]);
  const quarter = rotatedBounds(0, 0, 100, 20, Math.PI / 2, 0);
  check(
    "a quarter turn swaps width and height",
    near(quarter[2] - quarter[0], 20) && near(quarter[3] - quarter[1], 100),
    `${quarter[2] - quarter[0]} x ${quarter[3] - quarter[1]}`
  );
  const padded = rotatedBounds(0, 0, 100, 20, 0, 5);
  check("padding widens the box on both sides", near(padded[0], -55) && near(padded[2], 55));
}

console.log(failures === 0 ? "\nall label checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
