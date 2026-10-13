// Offline, deterministic check of the glyph-range decoder.
//
// Rather than commit a font binary, this encodes a glyph range by hand, from
// the published schema, and checks that the decoder reads back exactly what
// was written. That makes the test a statement about the wire format -- the
// thing that could actually change under us -- instead of a statement about
// one vendor's font file.
//
// The schema being encoded:
//
//   glyphs   { repeated fontstack stacks = 1; }
//   fontstack{ string name = 1; string range = 2; repeated glyph glyphs = 3; }
//   glyph    { uint32 id = 1; bytes bitmap = 2; uint32 width = 3;
//              uint32 height = 4; sint32 left = 5; sint32 top = 6;
//              uint32 advance = 7; }
//
// The one detail worth asserting on its own is the bitmap size: a glyph's
// bitmap is not width x height, it is (width + 2*buffer) x (height + 2*buffer),
// and getting that wrong shears every letter on the map.
//
//   node tests/test_glyphs.mjs

import { decodeGlyphRange, SDF_BUFFER } from "../ui/static/glyphs.js";

let failures = 0;

function check(name, ok, detail) {
  if (ok) {
    console.log(`  ok   ${name}`);
    return;
  }
  failures += 1;
  console.log(`  FAIL ${name}${detail ? ` -- ${detail}` : ""}`);
}

// -- a minimal protobuf writer -------------------------------------------------

function varint(value) {
  const out = [];
  let v = value >>> 0;
  while (v > 0x7f) {
    out.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
  out.push(v);
  return out;
}

function zigzag(value) {
  return (value << 1) ^ (value >> 31);
}

function tag(field, wire) {
  return varint((field << 3) | wire);
}

function varintField(field, value) {
  return [...tag(field, 0), ...varint(value)];
}

function bytesField(field, bytes) {
  return [...tag(field, 2), ...varint(bytes.length), ...bytes];
}

function stringField(field, text) {
  return bytesField(field, [...new TextEncoder().encode(text)]);
}

function encodeGlyph({ id, width, height, left, top, advance }) {
  const bitmapSize = width === 0 ? 0 : (width + 2 * SDF_BUFFER) * (height + 2 * SDF_BUFFER);
  // Fill the bitmap with a recognisable ramp so a mis-sliced row is visible.
  const bitmap = Array.from({ length: bitmapSize }, (_, i) => i % 251);
  return [
    ...varintField(1, id),
    ...(bitmapSize > 0 ? bytesField(2, bitmap) : []),
    ...varintField(3, width),
    ...varintField(4, height),
    ...varintField(5, zigzag(left)),
    ...varintField(6, zigzag(top)),
    ...varintField(7, advance),
  ];
}

function encodeRange(name, range, glyphs) {
  const stack = [
    ...stringField(1, name),
    ...stringField(2, range),
    ...glyphs.flatMap((g) => bytesField(3, encodeGlyph(g))),
  ];
  return new Uint8Array(bytesField(1, stack));
}

// -- the checks -------------------------------------------------------------------

console.log("glyphs");

// Metrics chosen to look like real ones: 'A' rests on the baseline, 'g'
// descends below it (so its top is further negative than its height allows),
// and a space has metrics but no bitmap at all.
const written = [
  { id: 32, width: 0, height: 0, left: 0, top: -26, advance: 6 },
  { id: 65, width: 15, height: 17, left: 0, top: -9, advance: 15 },
  { id: 103, width: 12, height: 19, left: 1, top: -13, advance: 14 },
  { id: 7844, width: 15, height: 24, left: 0, top: -2, advance: 15 },
];

const decoded = decodeGlyphRange(encodeRange("Test Sans Regular", "0-255", written));

check("every glyph decoded", decoded.size === written.length, `got ${decoded.size}`);

for (const expected of written) {
  const actual = decoded.get(expected.id);
  if (!actual) {
    check(`glyph ${expected.id} present`, false);
    continue;
  }
  const fields = ["width", "height", "left", "top", "advance"];
  const wrong = fields.filter((f) => actual[f] !== expected[f]);
  check(
    `glyph ${expected.id}: metrics round-trip`,
    wrong.length === 0,
    wrong.map((f) => `${f} ${actual[f]} != ${expected[f]}`).join(", ")
  );
}

// The buffered-bitmap rule, stated as its own check because every glyph on the
// map is sliced by it.
{
  const a = decoded.get(65);
  const expectedBytes = (15 + 2 * SDF_BUFFER) * (17 + 2 * SDF_BUFFER);
  check(
    "bitmap is (width + 2*buffer) x (height + 2*buffer)",
    a.bitmap.length === expectedBytes,
    `got ${a.bitmap.length}, expected ${expectedBytes}`
  );
  check("bitmap bytes survive intact", a.bitmap[0] === 0 && a.bitmap[1] === 1 && a.bitmap[250] === 250);
}

// A space carries an advance and nothing else. Treating it as a missing glyph
// would run every word together.
{
  const space = decoded.get(32);
  check("space has an advance", space.advance === 6);
  check("space has no bitmap", !space.bitmap || space.bitmap.length === 0);
}

// Negative metrics are zigzag-encoded; reading them as plain varints turns
// every `top` into a large positive number and throws the text off screen.
{
  const g = decoded.get(103);
  check("negative top decodes as negative", g.top === -13, `got ${g.top}`);
}

// A code point above the Basic Latin block, to prove ids are not truncated to
// one byte -- U+1EA4 is a Vietnamese tone-marked vowel.
{
  const viet = decoded.get(7844);
  check("multi-byte code point id", viet !== undefined && viet.advance === 15);
}

check("truncated input does not throw", decodeGlyphRange(new Uint8Array(0)).size === 0);

console.log(failures === 0 ? "\nall glyph checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
