// Signed-distance-field glyphs, decoded from the standard glyph-range
// protobuf and packed into one atlas texture.
//
// Text cannot be drawn the way the browser draws text and still end up in a
// batched WebGL draw call. The way every vector map solves this is a signed
// distance field: each glyph is rasterised once, at one size, into a small
// bitmap where each byte says how far that pixel is from the glyph's edge.
// The shader then reconstructs a crisp outline at *any* size from that one
// bitmap, and a halo comes free by thresholding the same value further out.
//
// The ranges are fetched from the tile provider's font endpoint -- the same
// keyless, open service the tiles come from -- 256 code points at a time,
// which is how the format is published. Vietnamese needs three of those
// blocks: Basic Latin, Latin Extended-A (for the D-with-stroke), and Latin
// Extended Additional (for every tone-marked vowel).

import { readUVarint, unzigzag, skipField } from "./pbf.js";

/** The pixel size glyph bitmaps are rendered at; a shader scales from this. */
export const SDF_FONT_SIZE = 24;

/** Padding baked into every glyph bitmap, so a halo has room to grow into. */
export const SDF_BUFFER = 3;

const RANGE_SIZE = 256;
const ATLAS_START = 1024;
const ATLAS_MAX = 4096;
const ATLAS_GAP = 1;

/**
 * Decode one glyph-range protobuf.
 *
 * @param {Uint8Array} buf
 * @returns {Map<number, {id, bitmap, width, height, left, top, advance}>}
 */
export function decodeGlyphRange(buf) {
  const glyphs = new Map();
  let i = 0;
  while (i < buf.length) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;
    // glyphs.stacks
    if (field === 1 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      readFontstack(buf, after, after + len, glyphs);
      i = after + len;
      continue;
    }
    i = skipField(buf, i, wire);
  }
  return glyphs;
}

function readFontstack(buf, start, end, out) {
  let i = start;
  while (i < end) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;
    // fontstack.glyphs; name and range are of no use once the bytes are here
    if (field === 3 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      const glyph = readGlyph(buf, after, after + len);
      if (glyph) out.set(glyph.id, glyph);
      i = after + len;
      continue;
    }
    i = skipField(buf, i, wire);
  }
}

function readGlyph(buf, start, end) {
  let id = -1;
  let bitmap = null;
  let width = 0;
  let height = 0;
  let left = 0;
  let top = 0;
  let advance = 0;

  let i = start;
  while (i < end) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;

    if (field === 1 && wire === 0) {
      [id, i] = readUVarint(buf, i);
    } else if (field === 2 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      bitmap = buf.subarray(after, after + len);
      i = after + len;
    } else if (field === 3 && wire === 0) {
      [width, i] = readUVarint(buf, i);
    } else if (field === 4 && wire === 0) {
      [height, i] = readUVarint(buf, i);
    } else if (field === 5 && wire === 0) {
      const [raw, after] = readUVarint(buf, i);
      left = unzigzag(raw);
      i = after;
    } else if (field === 6 && wire === 0) {
      const [raw, after] = readUVarint(buf, i);
      top = unzigzag(raw);
      i = after;
    } else if (field === 7 && wire === 0) {
      [advance, i] = readUVarint(buf, i);
    } else {
      i = skipField(buf, i, wire);
    }
  }

  if (id < 0) return null;
  return { id, bitmap, width, height, left, top, advance };
}

/**
 * Every glyph the map has needed so far, in one texture.
 *
 * Ranges are fetched on demand and never dropped: a city's worth of Latin and
 * Vietnamese text is a few hundred distinct code points, so the atlas reaches
 * a steady state within the first few tiles and stops costing anything.
 */
export class GlyphStore {
  /**
   * @param {WebGL2RenderingContext} gl
   * @param {string} urlTemplate - with `{fontstack}` and `{range}` placeholders.
   * @param {string} fontstack - e.g. "Noto Sans Regular".
   */
  constructor(gl, urlTemplate, fontstack) {
    this.gl = gl;
    this.urlTemplate = urlTemplate;
    this.fontstack = fontstack;

    this.width = ATLAS_START;
    this.height = ATLAS_START;
    this.pixels = new Uint8Array(this.width * this.height);
    this.shelfX = 0;
    this.shelfY = 0;
    this.shelfHeight = 0;

    /** @type {Map<number, {advance, width, height, left, top, u, v}|null>} */
    this.glyphs = new Map();
    /** @type {Map<string, Promise<void>>} */
    this.ranges = new Map();
    this.overflowed = false;

    this.texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this._allocateTexture();
  }

  _allocateTexture() {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, this.width, this.height, 0, gl.RED, gl.UNSIGNED_BYTE, this.pixels);
  }

  /** The 256-code-point block a character belongs to, as the endpoint names it. */
  static rangeOf(codePoint) {
    const start = Math.floor(codePoint / RANGE_SIZE) * RANGE_SIZE;
    return `${start}-${start + RANGE_SIZE - 1}`;
  }

  /**
   * Make sure every range these code points fall in has been fetched.
   * Resolves immediately when they all already have.
   */
  async ensure(codePoints) {
    const wanted = new Set();
    for (const cp of codePoints) {
      const range = GlyphStore.rangeOf(cp);
      if (!this.ranges.has(range)) wanted.add(range);
    }
    if (wanted.size === 0) return;
    await Promise.all([...wanted].map((range) => this._loadRange(range)));
  }

  /**
   * Fetch named ranges up front.
   *
   * The alternative is discovering them one tile at a time, which shows the
   * user a map whose labels arrive in visible waves. Four blocks cover Latin
   * and Vietnamese completely, so paying for them once at start-up is worth
   * it.
   */
  async ensureRanges(ranges) {
    await Promise.all(ranges.map((range) => this._loadRange(range)));
  }

  _loadRange(range) {
    const existing = this.ranges.get(range);
    if (existing) return existing;

    const url = this.urlTemplate
      .replace("{fontstack}", encodeURIComponent(this.fontstack))
      .replace("{range}", range);

    const pending = fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
        const bytes = new Uint8Array(await res.arrayBuffer());
        for (const glyph of decodeGlyphRange(bytes).values()) this._add(glyph);
        this._allocateTexture();
      })
      .catch((err) => {
        // A missing range is not fatal -- those characters simply do not draw.
        console.warn("[map] glyph range failed:", range, err.message);
      });

    this.ranges.set(range, pending);
    return pending;
  }

  _add(glyph) {
    if (this.glyphs.has(glyph.id)) return;

    // A space has metrics but no bitmap: it advances the pen and draws
    // nothing, so it needs no room in the atlas.
    if (!glyph.bitmap || glyph.width === 0 || glyph.height === 0) {
      this.glyphs.set(glyph.id, {
        advance: glyph.advance,
        width: 0,
        height: 0,
        left: glyph.left,
        top: glyph.top,
        u: 0,
        v: 0,
      });
      return;
    }

    const boxWidth = glyph.width + 2 * SDF_BUFFER;
    const boxHeight = glyph.height + 2 * SDF_BUFFER;
    const spot = this._reserve(boxWidth, boxHeight);
    if (!spot) {
      if (!this.overflowed) {
        console.warn("[map] glyph atlas is full; some characters will not draw");
        this.overflowed = true;
      }
      return;
    }

    for (let row = 0; row < boxHeight; row++) {
      const src = row * boxWidth;
      const dst = (spot.y + row) * this.width + spot.x;
      this.pixels.set(glyph.bitmap.subarray(src, src + boxWidth), dst);
    }

    this.glyphs.set(glyph.id, {
      advance: glyph.advance,
      width: boxWidth,
      height: boxHeight,
      left: glyph.left,
      top: glyph.top,
      u: spot.x,
      v: spot.y,
    });
  }

  /** Shelf packing: fill a row, then start the next one above it. */
  _reserve(w, h) {
    for (;;) {
      if (this.shelfX + w <= this.width && this.shelfY + h <= this.height) {
        const spot = { x: this.shelfX, y: this.shelfY };
        this.shelfX += w + ATLAS_GAP;
        this.shelfHeight = Math.max(this.shelfHeight, h + ATLAS_GAP);
        return spot;
      }
      if (this.shelfX > 0 && this.shelfY + this.shelfHeight + h <= this.height) {
        this.shelfY += this.shelfHeight;
        this.shelfX = 0;
        this.shelfHeight = 0;
        continue;
      }
      if (!this._grow()) return null;
    }
  }

  _grow() {
    if (this.height >= ATLAS_MAX) return false;
    const grown = new Uint8Array(this.width * this.height * 2);
    grown.set(this.pixels);
    this.pixels = grown;
    this.height *= 2;
    return true;
  }

  /** Metrics and atlas position for one code point, or null if unavailable. */
  get(codePoint) {
    return this.glyphs.get(codePoint) ?? null;
  }

  /**
   * Where the baseline and cap line sit, in SDF units.
   *
   * The range format carries no font-level metrics, but a capital letter
   * carries them implicitly: it rests on the baseline and reaches the cap
   * line, so its own box says where both are. 'H' is used because it has no
   * curve overshoot at either end. The fallback is the same measurement taken
   * from this project's default font, for the case where 'H' has not loaded.
   */
  verticalMetrics() {
    if (this._vertical) return this._vertical;
    const reference = this.glyphs.get(72); // 'H'
    if (!reference || reference.height === 0) return { baseline: 26, capHeight: 17 };
    const capHeight = reference.height - 2 * SDF_BUFFER;
    this._vertical = { baseline: -reference.top + capHeight, capHeight };
    return this._vertical;
  }
}
