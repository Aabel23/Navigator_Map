// Mapbox Vector Tile bytes in, GPU-ready meshes and label records out, in one
// pass.
//
// This walks the protobuf exactly once and never builds an intermediate
// representation. There is no GeoJSON, no per-feature object, no command list
// handed to a second consumer. What a feature turns into is decided while its
// bytes are being read: which bucket it belongs to, which style index its
// vertices carry, whether the zoom is high enough for it to exist at all, and
// then, immediately, its triangles.
//
// Polygons are triangulated here (earcut.js) and polylines are extruded into
// ribbons here (lines.js), because "here" is a worker thread. The main thread
// receives typed arrays it can hand straight to bufferSubData.
//
// Labels are the one thing that leaves here unfinished. A label's geometry
// depends on glyph metrics, and the glyph atlas lives on the main thread with
// the GPU texture it belongs to -- so what leaves here is the *decision*: this
// text, at this world anchor, at this angle, with this priority. Laying it out
// into quads is the main thread's job, and it is cheap, because everything
// expensive about the tile has already happened.

import { earcut } from "./earcut.js";
import { addPolyline, lineAnchor, LINE_VERTEX_FLOATS } from "./lines.js";
import { readUVarint, unzigzag, skipField } from "./pbf.js";

const CMD_MOVE_TO = 1;
const CMD_LINE_TO = 2;
const CMD_CLOSE_PATH = 7;

const GEOM_POINT = 1;
const GEOM_LINESTRING = 2;
const GEOM_POLYGON = 3;

const TILE_SIZE = 256;

/** Fill vertices are [worldX, worldY, styleIndex]. */
const FILL_VERTEX_FLOATS = 3;

// -- protobuf structure --------------------------------------------------------

/**
 * Read one `Value` message.
 *
 * The tile schema uses a different field for each scalar type, so a rank is a
 * varint and a name is a string. Both matter here: names are what a label
 * says, ranks are how a label wins or loses a collision.
 */
function readValue(buf, start, end) {
  let i = start;
  while (i < end) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;

    if (field === 1 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      return new TextDecoder().decode(buf.subarray(after, after + len));
    }
    if (field === 2 && wire === 5) {
      return new DataView(buf.buffer, buf.byteOffset + i, 4).getFloat32(0, true);
    }
    if (field === 3 && wire === 1) {
      return new DataView(buf.buffer, buf.byteOffset + i, 8).getFloat64(0, true);
    }
    if ((field === 4 || field === 5) && wire === 0) {
      return readUVarint(buf, i)[0];
    }
    if (field === 6 && wire === 0) {
      return unzigzag(readUVarint(buf, i)[0]);
    }
    if (field === 7 && wire === 0) {
      return readUVarint(buf, i)[0] !== 0;
    }
    i = skipField(buf, i, wire);
  }
  return null;
}

function layerSpans(buf) {
  const spans = [];
  let i = 0;
  const end = buf.length;
  while (i < end) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;
    if (field === 3 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      spans.push([after, after + len]);
      i = after + len;
    } else {
      i = skipField(buf, i, wire);
    }
  }
  return spans;
}

function layerHeader(buf, start, end) {
  let name = "";
  let extent = 4096;
  const keys = [];
  const values = [];
  const features = [];
  let i = start;
  while (i < end) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;
    if (field === 1 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      name = new TextDecoder().decode(buf.subarray(after, after + len));
      i = after + len;
    } else if (field === 2 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      features.push([after, after + len]);
      i = after + len;
    } else if (field === 3 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      keys.push(new TextDecoder().decode(buf.subarray(after, after + len)));
      i = after + len;
    } else if (field === 4 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      values.push(readValue(buf, after, after + len));
      i = after + len;
    } else if (field === 5 && wire === 0) {
      const [v, after] = readUVarint(buf, i);
      extent = v;
      i = after;
    } else {
      i = skipField(buf, i, wire);
    }
  }
  return { name, extent, keys, values, features };
}

function featureFields(buf, start, end) {
  let geomType = 0;
  let tagsStart = 0;
  let tagsEnd = 0;
  let geomStart = 0;
  let geomEnd = 0;
  let i = start;
  while (i < end) {
    const [key, next] = readUVarint(buf, i);
    i = next;
    const field = key >>> 3;
    const wire = key & 7;
    if (field === 1 && wire === 0) {
      i = readUVarint(buf, i)[1];
    } else if (field === 2 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      tagsStart = after;
      tagsEnd = after + len;
      i = after + len;
    } else if (field === 3 && wire === 0) {
      const [v, after] = readUVarint(buf, i);
      geomType = v;
      i = after;
    } else if (field === 4 && wire === 2) {
      const [len, after] = readUVarint(buf, i);
      geomStart = after;
      geomEnd = after + len;
      i = after + len;
    } else {
      i = skipField(buf, i, wire);
    }
  }
  return { geomType, tagsStart, tagsEnd, geomStart, geomEnd };
}

/** Walk one feature's command stream into parts of tile-local coordinates. */
function readParts(buf, start, end) {
  const parts = [];
  let xs = null;
  let ys = null;
  let x = 0;
  let y = 0;
  let i = start;

  while (i < end) {
    const [cmd, next] = readUVarint(buf, i);
    i = next;
    const cmdId = cmd & 0x7;
    const count = cmd >>> 3;

    if (cmdId === CMD_MOVE_TO) {
      for (let k = 0; k < count; k++) {
        const [dx, n1] = readUVarint(buf, i);
        const [dy, n2] = readUVarint(buf, n1);
        i = n2;
        x += unzigzag(dx);
        y += unzigzag(dy);
        xs = [x];
        ys = [y];
        parts.push({ xs, ys });
      }
    } else if (cmdId === CMD_LINE_TO) {
      for (let k = 0; k < count; k++) {
        const [dx, n1] = readUVarint(buf, i);
        const [dy, n2] = readUVarint(buf, n1);
        i = n2;
        x += unzigzag(dx);
        y += unzigzag(dy);
        if (xs) {
          xs.push(x);
          ys.push(y);
        }
      }
    } else if (cmdId === CMD_CLOSE_PATH) {
      // The ring's closing edge is implicit; both consumers below know a ring
      // returns to its first point, so nothing is appended here.
    }
  }
  return parts;
}

/** Every tag of one feature, as a plain object. */
function readTags(buf, tagsStart, tagsEnd, keys, values) {
  const tags = {};
  let i = tagsStart;
  while (i < tagsEnd) {
    const [ki, n1] = readUVarint(buf, i);
    const [vi, n2] = readUVarint(buf, n1);
    const key = keys[ki];
    if (key !== undefined) tags[key] = values[vi];
    i = n2;
  }
  return tags;
}

// -- geometry --------------------------------------------------------------------

/** Twice the signed area of a ring, in tile coordinates (y grows downward). */
function ringArea(xs, ys) {
  let sum = 0;
  const n = xs.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    sum += xs[j] * ys[i] - xs[i] * ys[j];
  }
  return sum;
}

/**
 * Group a polygon feature's rings into polygons, each an exterior ring
 * followed by its holes.
 *
 * The MVT spec fixes the winding of exterior and interior rings, but rather
 * than trust one absolute direction, this takes the first non-degenerate
 * ring's direction as "exterior" and starts a new polygon each time that
 * direction reappears. That is correct under the spec and still correct for
 * an encoder that wound everything the other way.
 */
function classifyRings(parts) {
  if (parts.length === 0) return [];
  const polygons = [];
  let current = null;
  let exteriorSign = 0;

  for (const part of parts) {
    if (part.xs.length < 3) continue;
    const area = ringArea(part.xs, part.ys);
    if (area === 0) continue;
    const sign = area > 0 ? 1 : -1;
    if (exteriorSign === 0) exteriorSign = sign;

    if (sign === exteriorSign) {
      if (current) polygons.push(current);
      current = [part];
    } else if (current) {
      current.push(part);
    }
  }
  if (current) polygons.push(current);
  return polygons;
}

/** Drop vertices closer than `tolerance` to the last kept one; keep the ends. */
function simplify(xs, ys, tolerance) {
  const n = xs.length;
  if (tolerance <= 0 || n <= 2) return { xs, ys, n };
  const tol2 = tolerance * tolerance;
  const outX = [xs[0]];
  const outY = [ys[0]];
  let lastX = xs[0];
  let lastY = ys[0];
  for (let i = 1; i < n; i++) {
    const dx = xs[i] - lastX;
    const dy = ys[i] - lastY;
    if (i !== n - 1 && dx * dx + dy * dy < tol2) continue;
    outX.push(xs[i]);
    outY.push(ys[i]);
    lastX = xs[i];
    lastY = ys[i];
  }
  return { xs: outX, ys: outY, n: outX.length };
}

// -- the one pass ------------------------------------------------------------------

/**
 * Decode one tile into one mesh per bucket, plus its label records.
 *
 * @param {Uint8Array} buf - raw .pbf bytes.
 * @param {number} tileZ
 * @param {number} tileX
 * @param {number} tileY
 * @param {{x: number, y: number}|null} origin - world-Z0 pixels subtracted
 *   from every vertex, so a float32 still carries sub-pixel precision across
 *   a buffer shared by the whole map.
 * @param {number} cameraZoom - drives every LOD gate in the style.
 * @param {object} style - the resolved style payload from /api/config.
 * @param {number} simplifyTolerance - tile-local units on the layer's extent;
 *   applied to lines only, since dropping a polygon vertex changes its area.
 * @returns {{buckets: Object, labels: Array, stats: Object}}
 */
export function decodeTileMesh(buf, tileZ, tileX, tileY, origin, cameraZoom, style, simplifyTolerance) {
  const meshes = {};
  for (const bucket of style.buckets) {
    meshes[bucket] = { kind: style.bucket_kinds[bucket] ?? "fill", verts: [], idx: [] };
  }
  const labels = [];

  let featuresConsidered = 0;
  let featuresKept = 0;
  let verticesIn = 0;

  const tileSizeZ0 = TILE_SIZE / Math.pow(2, tileZ);
  const originX = origin ? origin.x : 0;
  const originY = origin ? origin.y : 0;

  for (const [lstart, lend] of layerSpans(buf)) {
    const { name, extent, keys, values, features } = layerHeader(buf, lstart, lend);
    const rule = style.rules[name];
    const labelRule = style.label_rules[name];
    if (!rule && !labelRule) continue;

    const geometryWanted = rule && cameraZoom >= rule.min_zoom;
    const labelsWanted = labelRule && cameraZoom >= labelRule.min_zoom;
    if (!geometryWanted && !labelsWanted) continue;

    // Tile units -> world-Z0 pixels, then shifted onto the shared origin.
    const unit = tileSizeZ0 / extent;
    const offsetX = tileX * tileSizeZ0 - originX;
    const offsetY = tileY * tileSizeZ0 - originY;

    for (const [fstart, fend] of features) {
      featuresConsidered += 1;
      const { geomType, tagsStart, tagsEnd, geomStart, geomEnd } = featureFields(buf, fstart, fend);
      const tags = readTags(buf, tagsStart, tagsEnd, keys, values);
      const classValue = typeof tags.class === "string" ? tags.class : null;
      const subclassValue = typeof tags.subclass === "string" ? tags.subclass : null;

      let kept = false;

      if (geometryWanted && (geomType === GEOM_LINESTRING || geomType === GEOM_POLYGON)) {
        const entry = matchClass(rule.classes, classValue, subclassValue);
        if (entry && cameraZoom >= entry.min_zoom) {
          const parts = readParts(buf, geomStart, geomEnd);
          for (const part of parts) verticesIn += part.xs.length;

          if (rule.kind === "line") {
            emitLines(meshes[rule.bucket], parts, entry.style, simplifyTolerance, unit, offsetX, offsetY);
          } else {
            emitFills(meshes[rule.bucket], parts, entry.style, unit, offsetX, offsetY);
            if (rule.outline && cameraZoom >= rule.outline.min_zoom) {
              emitRingOutlines(meshes[rule.outline.bucket], parts, rule.outline.style, unit, offsetX, offsetY);
            }
          }
          kept = true;
        }
      }

      if (labelsWanted) {
        const record = readLabel(
          buf, geomStart, geomEnd, geomType, tags, classValue, subclassValue,
          labelRule, style, cameraZoom, unit, offsetX, offsetY
        );
        if (record) {
          labels.push(record);
          kept = true;
        }
      }

      if (kept) featuresKept += 1;
    }
  }

  const buckets = {};
  let verticesOut = 0;
  let trianglesOut = 0;
  for (const [bucket, mesh] of Object.entries(meshes)) {
    const stride = mesh.kind === "line" ? LINE_VERTEX_FLOATS : FILL_VERTEX_FLOATS;
    buckets[bucket] = {
      kind: mesh.kind,
      vertices: new Float32Array(mesh.verts),
      indices: new Uint32Array(mesh.idx),
    };
    verticesOut += mesh.verts.length / stride;
    trianglesOut += mesh.idx.length / 3;
  }

  return {
    buckets,
    labels: dedupeLabels(labels),
    stats: {
      featuresConsidered,
      featuresKept,
      verticesIn,
      verticesOut,
      trianglesOut,
      labelsFound: labels.length,
    },
  };
}

/** The class entry a feature matches, or null if the style drops it. */
function matchClass(classes, classValue, subclassValue) {
  if (classValue !== null && Object.prototype.hasOwnProperty.call(classes, classValue)) {
    return classes[classValue];
  }
  if (subclassValue !== null && Object.prototype.hasOwnProperty.call(classes, subclassValue)) {
    return classes[subclassValue];
  }
  return Object.prototype.hasOwnProperty.call(classes, "*") ? classes["*"] : null;
}

// -- labels --------------------------------------------------------------------

/**
 * Decide whether one feature carries a label, and if so, where it goes.
 *
 * What comes back is a placement decision, not geometry: a world anchor, an
 * angle, the text, and how hard the label should fight for its space. The
 * main thread turns that into quads once it knows the glyphs.
 */
function readLabel(
  buf, geomStart, geomEnd, geomType, tags, classValue, subclassValue,
  labelRule, style, cameraZoom, unit, offsetX, offsetY
) {
  const entry = matchClass(labelRule.classes, classValue, subclassValue);
  if (!entry) return null;
  if (cameraZoom < entry.min_zoom) return null;
  if (entry.max_zoom !== null && cameraZoom > entry.max_zoom) return null;

  const text = pickName(tags, style.label_name_fields);
  if (!text) return null;

  const rank = typeof tags.rank === "number" ? tags.rank : 0;
  if (labelRule.max_rank !== null && rank > labelRule.max_rank) return null;

  const parts = readParts(buf, geomStart, geomEnd);
  if (parts.length === 0) return null;

  // A lower rank is a more important feature, so it has to raise the priority.
  const priority = entry.priority - rank;
  const icon = labelRule.icon ? [classValue, subclassValue] : null;

  if (labelRule.placement === "line" && geomType === GEOM_LINESTRING) {
    let best = null;
    for (const part of parts) {
      const n = part.xs.length;
      if (n < 2) continue;
      const wx = new Float64Array(n);
      const wy = new Float64Array(n);
      for (let k = 0; k < n; k++) {
        wx[k] = part.xs[k] * unit + offsetX;
        wy[k] = part.ys[k] * unit + offsetY;
      }
      const anchor = lineAnchor(wx, wy, n);
      if (anchor && (!best || anchor.length > best.length)) best = anchor;
    }
    if (!best) return null;
    return {
      text, style: entry.style, priority, icon,
      x: best.x, y: best.y, angle: best.angle, length: best.length,
    };
  }

  if (geomType !== GEOM_POINT && geomType !== GEOM_POLYGON) return null;
  const first = parts[0];
  return {
    text, style: entry.style, priority, icon,
    x: first.xs[0] * unit + offsetX,
    y: first.ys[0] * unit + offsetY,
    angle: 0,
    length: 0,
  };
}

/**
 * The first name field that has a value.
 *
 * The order comes from configuration, so a deployment picks its own language
 * preference. In Vietnam the plain `name` is already Vietnamese, which is why
 * a bare `name` beats a transliteration in the default order.
 */
function pickName(tags, fields) {
  for (const field of fields) {
    const value = tags[field];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return null;
}

/**
 * One label per name per tile.
 *
 * A street is many features -- one per block, per bridge, per one-way pair --
 * and every one of them carries the same name. Keeping them all would ask the
 * collision grid to reject dozens of copies of "Hàm Nghi" on every frame. The
 * longest run is kept, because it is the one with room to be read.
 */
function dedupeLabels(labels) {
  const best = new Map();
  for (const label of labels) {
    const key = `${label.style}|${label.text}`;
    const held = best.get(key);
    if (!held || label.length > held.length) best.set(key, label);
  }
  return [...best.values()];
}

// -- geometry emitters ------------------------------------------------------------

function emitLines(mesh, parts, styleIndex, tolerance, unit, offsetX, offsetY) {
  if (!mesh) return;
  for (const part of parts) {
    const { xs, ys, n } = simplify(part.xs, part.ys, tolerance);
    if (n < 2) continue;
    const wx = new Float64Array(n);
    const wy = new Float64Array(n);
    for (let k = 0; k < n; k++) {
      wx[k] = xs[k] * unit + offsetX;
      wy[k] = ys[k] * unit + offsetY;
    }
    addPolyline(mesh.verts, mesh.idx, wx, wy, n, styleIndex);
  }
}

function emitFills(mesh, parts, styleIndex, unit, offsetX, offsetY) {
  if (!mesh) return;
  for (const rings of classifyRings(parts)) {
    // Triangulate in tile-local integer coordinates: they are exact, so the
    // ear tests are decided by integer arithmetic rather than by whichever
    // way a float rounded.
    let total = 0;
    for (const ring of rings) total += ring.xs.length;
    const coords = new Float64Array(total * 2);
    const holeIndices = [];
    let cursor = 0;
    for (let r = 0; r < rings.length; r++) {
      const ring = rings[r];
      if (r > 0) holeIndices.push(cursor);
      for (let k = 0; k < ring.xs.length; k++) {
        coords[cursor * 2] = ring.xs[k];
        coords[cursor * 2 + 1] = ring.ys[k];
        cursor += 1;
      }
    }

    const triangles = earcut(coords, holeIndices);
    if (triangles.length === 0) continue;

    const base = mesh.verts.length / FILL_VERTEX_FLOATS;
    for (let k = 0; k < total; k++) {
      mesh.verts.push(coords[k * 2] * unit + offsetX, coords[k * 2 + 1] * unit + offsetY, styleIndex);
    }
    for (const index of triangles) mesh.idx.push(base + index);
  }
}

function emitRingOutlines(mesh, parts, styleIndex, unit, offsetX, offsetY) {
  if (!mesh) return;
  for (const part of parts) {
    const n = part.xs.length;
    if (n < 3) continue;
    // A ring's closing edge is implicit in the tile, so it is added here --
    // without it every building would be drawn with one side missing.
    const wx = new Float64Array(n + 1);
    const wy = new Float64Array(n + 1);
    for (let k = 0; k < n; k++) {
      wx[k] = part.xs[k] * unit + offsetX;
      wy[k] = part.ys[k] * unit + offsetY;
    }
    wx[n] = wx[0];
    wy[n] = wy[0];
    addPolyline(mesh.verts, mesh.idx, wx, wy, n + 1, styleIndex);
  }
}
