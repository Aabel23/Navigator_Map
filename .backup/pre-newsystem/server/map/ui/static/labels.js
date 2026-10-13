// Turning a string into quads, and a label into geometry.
//
// Layout here is deliberately simple: left to right, one line, advance by the
// glyph's own advance. That is enough for Latin and for Vietnamese, which is
// Latin with tone marks already composed into single code points. It is not
// enough for Arabic or Devanagari, which need real shaping, and this does not
// pretend otherwise.
//
// The important structural decision is that a glyph's *position* is a screen
// pixel offset from a single world anchor, not a world position of its own.
// One anchor per label means a label never stretches or shears as the camera
// zooms -- the anchor moves, the text keeps its size -- and it means a whole
// label can be accepted or rejected by collision as one unit.

import { SDF_FONT_SIZE, SDF_BUFFER } from "./glyphs.js";

/** Label vertices are [anchorX, anchorY, offsetX, offsetY, angle, u, v, style]. */
export const LABEL_VERTEX_FLOATS = 8;

/**
 * Lay out one line of text.
 *
 * Offsets come back in CSS pixels relative to the label's centre, so the
 * caller only has to know where the label goes, not how tall the font is.
 *
 * @param {string} text
 * @param {import("./glyphs.js").GlyphStore} store
 * @param {number} sizePx - cap-height-ish font size in CSS pixels.
 * @returns {{quads: Array, width: number, height: number}}
 */
export function shapeText(text, store, sizePx) {
  const scale = sizePx / SDF_FONT_SIZE;
  const { baseline, capHeight } = store.verticalMetrics();
  const laid = [];
  let pen = 0;

  for (const character of text) {
    const codePoint = character.codePointAt(0);
    const glyph = store.get(codePoint);
    // A code point with no glyph draws nothing and takes no space. Advancing
    // for it would leave a hole that looks like a layout bug.
    if (!glyph) continue;
    if (glyph.width > 0) laid.push({ pen, glyph });
    pen += glyph.advance;
  }

  if (laid.length === 0) return { quads: [], width: 0, height: 0 };

  // Centre on the text's own box: horizontally on the total advance, and
  // vertically between the baseline and the cap line. Using the typographic
  // box rather than the inked box keeps "Ha Noi" and "Hà Nội" on the same
  // line instead of nudging one up by the height of its tone marks.
  const shiftX = -(pen * scale) / 2;
  const shiftY = -(baseline - capHeight / 2) * scale;

  const quads = laid.map(({ pen: penAt, glyph }) => {
    const x1 = (penAt + glyph.left - SDF_BUFFER) * scale + shiftX;
    const y1 = (-glyph.top - SDF_BUFFER) * scale + shiftY;
    return {
      x1,
      y1,
      x2: x1 + glyph.width * scale,
      y2: y1 + glyph.height * scale,
      u1: glyph.u,
      v1: glyph.v,
      u2: glyph.u + glyph.width,
      v2: glyph.v + glyph.height,
    };
  });

  return { quads, width: pen * scale, height: capHeight * scale };
}

/**
 * One quad for a sprite icon, centred on its own origin.
 *
 * @param {{x, y, width, height, pixelRatio}} icon
 * @param {number} sizePx - target height in CSS pixels, or 0 to use the
 *   sprite's own size.
 */
export function shapeIcon(icon, sizePx) {
  const nativeHeight = icon.height / icon.pixelRatio;
  const scale = sizePx > 0 ? sizePx / nativeHeight : 1;
  const width = (icon.width / icon.pixelRatio) * scale;
  const height = nativeHeight * scale;
  return {
    quads: [
      {
        x1: -width / 2,
        y1: -height / 2,
        x2: width / 2,
        y2: height / 2,
        u1: icon.x,
        v1: icon.y,
        u2: icon.x + icon.width,
        v2: icon.y + icon.height,
      },
    ],
    width,
    height,
  };
}

/**
 * Append a shaped label's quads to a vertex array.
 *
 * @param {number[]} verts - flat vertex array being accumulated.
 * @param {number[]} indices - flat index array being accumulated.
 * @param {Array} quads - from `shapeText` or `shapeIcon`.
 * @param {number} anchorX - world position the label hangs from.
 * @param {number} anchorY
 * @param {number} angle - radians; 0 for upright point labels.
 * @param {number} offsetY - extra vertical shift in CSS pixels, for stacking
 *   an icon above its text.
 * @param {number} styleIndex
 * @returns {number} vertices appended.
 */
export function appendLabelQuads(verts, indices, quads, anchorX, anchorY, angle, offsetY, styleIndex) {
  const base = verts.length / LABEL_VERTEX_FLOATS;
  for (const q of quads) {
    const corners = [
      [q.x1, q.y1 + offsetY, q.u1, q.v1],
      [q.x2, q.y1 + offsetY, q.u2, q.v1],
      [q.x1, q.y2 + offsetY, q.u1, q.v2],
      [q.x2, q.y2 + offsetY, q.u2, q.v2],
    ];
    const corner0 = verts.length / LABEL_VERTEX_FLOATS;
    for (const [ox, oy, u, v] of corners) {
      verts.push(anchorX, anchorY, ox, oy, angle, u, v, styleIndex);
    }
    indices.push(corner0, corner0 + 1, corner0 + 2, corner0 + 1, corner0 + 3, corner0 + 2);
  }
  return verts.length / LABEL_VERTEX_FLOATS - base;
}
