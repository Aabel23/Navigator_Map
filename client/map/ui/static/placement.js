// Deciding which labels are drawn, and turning the survivors into geometry.
//
// The decoder hands over every label the resident tiles could show -- tens of
// thousands of them across a city. Almost none are drawn. This is where that
// gets decided, and it has to be redone whenever the camera moves, because
// two names that are far apart at one zoom overlap at another.
//
// The work is arranged so the expensive part only touches labels that survive:
//
//   1. project every anchor and throw away what is off screen  (cheap)
//   2. measure the text of what is left, from glyph advances    (cheap, cached)
//   3. sort by priority and collide                             (cheap)
//   4. shape the survivors into quads                           (cached forever)
//
// Shaping is cached on the record, so panning back to somewhere already seen
// costs nothing. The vertex buffer, by contrast, is rewritten outright each
// pass: a few hundred labels is a few hundred kilobytes, which is far less
// work than tracking spans for geometry that changes this often.

import { CollisionGrid, rotatedBounds } from "./collision.js";
import { shapeText, shapeIcon, appendLabelQuads } from "./labels.js";
import { SDF_FONT_SIZE } from "./glyphs.js";

/** Screen margin, in CSS pixels, outside which a label is not considered. */
const CULL_MARGIN = 48;

/** Padding around every label's collision box, so text never quite touches. */
const COLLISION_PADDING = 2;

/** How close two copies of the same name may be, in CSS pixels. */
const MIN_REPEAT_DISTANCE = 320;

export class LabelPlacement {
  /**
   * @param {object} style - the resolved style payload.
   * @param {import("./glyphs.js").GlyphStore} glyphStore
   * @param {import("./sprite.js").SpriteStore} spriteStore
   */
  constructor(style, glyphStore, spriteStore) {
    this.style = style;
    this.glyphStore = glyphStore;
    this.spriteStore = spriteStore;
    /** @type {Map<string, Array>} tileKey -> label records */
    this.tiles = new Map();
    /** @type {Array} every resident record, flattened */
    this.records = [];
    this.placedCount = 0;
    this.candidateCount = 0;
  }

  /**
   * Take one tile's labels, once their glyphs are available.
   *
   * Waiting here rather than at shaping time means a label is never laid out
   * with half its characters missing -- which, for Vietnamese, would silently
   * drop every tone mark.
   */
  async addTile(tileKey, labels) {
    if (labels.length > 0) {
      const codePoints = new Set();
      for (const label of labels) {
        for (const character of label.text) codePoints.add(character.codePointAt(0));
      }
      await this.glyphStore.ensure(codePoints);
    }
    // The tile may have been evicted while its glyphs were in flight.
    if (this.tiles.has(tileKey) || labels.length === 0) return;
    for (const label of labels) this._resolveIcon(label);
    this.tiles.set(tileKey, labels);
    this._flatten();
  }

  removeTiles(tileKeys) {
    let removed = false;
    for (const key of tileKeys) removed = this.tiles.delete(key) || removed;
    if (removed) this._flatten();
  }

  _flatten() {
    this.records = [];
    for (const labels of this.tiles.values()) {
      for (const label of labels) this.records.push(label);
    }
  }

  /**
   * Turn the decoder's candidate icon names into a sprite entry.
   *
   * The tile schema's point-of-interest classes were named after this icon
   * set, so the class usually resolves directly; the subclass covers the rest,
   * and a plain circle covers what neither does, because a point of interest
   * with no symbol at all reads as a bug rather than as a place.
   */
  _resolveIcon(label) {
    if (!label.icon) {
      label.sprite = null;
      return;
    }
    label.sprite = this.spriteStore ? this.spriteStore.get(...label.icon, "circle") : null;
  }

  /** Width of a label's text in CSS pixels, without laying out its quads. */
  _measure(record, style) {
    if (record.textWidth !== undefined) return record.textWidth;
    const scale = style.size / SDF_FONT_SIZE;
    let pen = 0;
    for (const character of record.text) {
      const glyph = this.glyphStore.get(character.codePointAt(0));
      if (glyph) pen += glyph.advance;
    }
    record.textWidth = pen * scale;
    return record.textWidth;
  }

  /** Lay a record out into quads, once. */
  _shape(record, style) {
    if (record.shaped) return record.shaped;
    const text = shapeText(record.text, this.glyphStore, style.size);
    const icon = record.sprite ? shapeIcon(record.sprite, style.icon_size) : null;
    record.shaped = { text, icon };
    return record.shaped;
  }

  /**
   * Place every visible label and rewrite the renderer's label meshes.
   *
   * @param {{worldX, worldY, zoom}} camera
   * @param {number} viewWidth - CSS pixels.
   * @param {number} viewHeight
   * @param {import("./gl.js").Renderer} renderer
   */
  run(camera, viewWidth, viewHeight, renderer) {
    const scale = Math.pow(2, camera.zoom);
    const halfW = viewWidth / 2;
    const halfH = viewHeight / 2;

    const candidates = [];
    for (const record of this.records) {
      const screenX = (record.x - camera.worldX) * scale + halfW;
      const screenY = (record.y - camera.worldY) * scale + halfH;
      if (screenX < -CULL_MARGIN || screenX > viewWidth + CULL_MARGIN) continue;
      if (screenY < -CULL_MARGIN || screenY > viewHeight + CULL_MARGIN) continue;
      candidates.push({ record, screenX, screenY });
    }

    // Highest priority first: the greedy pass that follows gives a label its
    // space only if nothing more important has already taken it.
    candidates.sort((a, b) => b.record.priority - a.record.priority);

    const grid = new CollisionGrid(viewWidth, viewHeight);
    const repeats = new Map();
    const textVerts = [];
    const textIdx = [];
    const iconVerts = [];
    const iconIdx = [];
    let placed = 0;

    for (const { record, screenX, screenY } of candidates) {
      const style = this.style.label_styles[record.style];
      if (!style) continue;

      const textWidth = this._measure(record, style);
      if (textWidth === 0) continue;

      // A street name only goes on a road long enough to hold it. Below that
      // the name would run off both ends of its own road.
      if (record.length > 0 && record.length * scale < textWidth) continue;

      if (this._repeatsTooSoon(repeats, record, screenX, screenY)) continue;

      const box = this._boundsOf(record, style, textWidth, screenX, screenY);
      if (!grid.fits(box)) continue;
      grid.insert(box);
      this._remember(repeats, record, screenX, screenY);

      const shaped = this._shape(record, style);
      if (shaped.icon) {
        appendLabelQuads(iconVerts, iconIdx, shaped.icon.quads, record.x, record.y, 0, 0, record.style);
      }
      appendLabelQuads(
        textVerts, textIdx, shaped.text.quads,
        record.x, record.y, record.angle, style.text_offset, record.style
      );
      placed += 1;
    }

    renderer.textMesh.upload(new Float32Array(textVerts), new Uint32Array(textIdx));
    renderer.iconMesh.upload(new Float32Array(iconVerts), new Uint32Array(iconIdx));
    this.placedCount = placed;
    this.candidateCount = candidates.length;
  }

  /**
   * The screen box a label occupies.
   *
   * A point of interest is an icon with its name underneath, so its box has to
   * cover both -- otherwise the icon of one place lands on the name of another.
   */
  _boundsOf(record, style, textWidth, screenX, screenY) {
    const textHeight = style.size * 1.2;
    if (style.icon_size > 0) {
      const iconHeight = record.sprite ? style.icon_size : 0;
      const width = Math.max(textWidth, iconHeight);
      const top = -iconHeight / 2;
      const bottom = style.text_offset + textHeight / 2;
      return [
        screenX - width / 2 - COLLISION_PADDING,
        screenY + top - COLLISION_PADDING,
        screenX + width / 2 + COLLISION_PADDING,
        screenY + bottom + COLLISION_PADDING,
      ];
    }
    return rotatedBounds(screenX, screenY, textWidth, textHeight, record.angle, COLLISION_PADDING);
  }

  /**
   * A long street crosses many tiles, and each one offers its own copy of the
   * name. Repeating it every few hundred pixels is how a paper map does it;
   * repeating it every tile boundary is not.
   */
  _repeatsTooSoon(repeats, record, screenX, screenY) {
    const seen = repeats.get(record.text);
    if (!seen) return false;
    for (const [x, y] of seen) {
      if (Math.hypot(x - screenX, y - screenY) < MIN_REPEAT_DISTANCE) return true;
    }
    return false;
  }

  _remember(repeats, record, screenX, screenY) {
    const seen = repeats.get(record.text);
    if (seen) seen.push([screenX, screenY]);
    else repeats.set(record.text, [[screenX, screenY]]);
  }
}
