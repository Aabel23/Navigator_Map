// Flat-array polygon triangulation: ear clipping with hole bridging, a
// z-order curve to keep the ear test near-linear on large rings, and the two
// standard fallbacks (cure local intersections, then split) for self-touching
// input. This is the classic earcut algorithm, written against the shape of
// data this project already has: one flat coordinate array plus an array of
// ring start indices, exactly what the MVT decoder produces when it walks a
// polygon feature's command stream.
//
// It runs on the decode worker, so a pathological ring costs a slow tile, not
// a dropped frame. What leaves it is a list of vertex indices, ready to be
// rebased and appended to a bucket's ELEMENT_ARRAY_BUFFER without a second
// pass over the geometry.

/**
 * Triangulate one polygon.
 *
 * @param {Float64Array|number[]} data - flat [x0,y0, x1,y1, ...] coordinates
 *   holding the exterior ring first, then every hole ring.
 * @param {number[]} holeIndices - vertex (not coordinate) index where each
 *   hole ring starts. Empty or omitted for a polygon with no holes.
 * @returns {number[]} triangle vertex indices, three per triangle.
 */
export function earcut(data, holeIndices) {
  const hasHoles = holeIndices && holeIndices.length > 0;
  const outerLen = hasHoles ? holeIndices[0] * 2 : data.length;
  let outerNode = linkedList(data, 0, outerLen, true);
  const triangles = [];
  if (!outerNode || outerNode.next === outerNode.prev) return triangles;

  if (hasHoles) outerNode = eliminateHoles(data, holeIndices, outerNode);

  // The z-order index only pays for itself on rings big enough that the
  // linear ear scan starts to hurt; below that it is pure overhead.
  let minX = 0;
  let minY = 0;
  let invSize = 0;
  if (data.length > 160) {
    minX = data[0];
    minY = data[1];
    let maxX = minX;
    let maxY = minY;
    for (let i = 2; i < outerLen; i += 2) {
      const x = data[i];
      const y = data[i + 1];
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
    const size = Math.max(maxX - minX, maxY - minY);
    invSize = size !== 0 ? 32767 / size : 0;
  }

  earcutLinked(outerNode, triangles, minX, minY, invSize, 0);
  return triangles;
}

// -- linked list plumbing ----------------------------------------------------

function linkedList(data, start, end, clockwise) {
  let last = null;
  if (clockwise === signedArea(data, start, end) > 0) {
    for (let i = start; i < end; i += 2) last = insertNode(i, data[i], data[i + 1], last);
  } else {
    for (let i = end - 2; i >= start; i -= 2) last = insertNode(i, data[i], data[i + 1], last);
  }
  if (last && equals(last, last.next)) {
    removeNode(last);
    last = last.next;
  }
  return last;
}

function insertNode(i, x, y, last) {
  const p = { i, x, y, prev: null, next: null, z: 0, prevZ: null, nextZ: null, steiner: false };
  if (!last) {
    p.prev = p;
    p.next = p;
  } else {
    p.next = last.next;
    p.prev = last;
    last.next.prev = p;
    last.next = p;
  }
  return p;
}

function removeNode(p) {
  p.next.prev = p.prev;
  p.prev.next = p.next;
  if (p.prevZ) p.prevZ.nextZ = p.nextZ;
  if (p.nextZ) p.nextZ.prevZ = p.prevZ;
}

/** Drop duplicate and collinear points; they only produce zero-area ears. */
function filterPoints(start, end) {
  if (!start) return start;
  if (!end) end = start;
  let p = start;
  let again;
  do {
    again = false;
    if (!p.steiner && (equals(p, p.next) || area(p.prev, p, p.next) === 0)) {
      removeNode(p);
      p = end = p.prev;
      if (p === p.next) break;
      again = true;
    } else {
      p = p.next;
    }
  } while (again || p !== end);
  return end;
}

// -- the clipping loop -------------------------------------------------------

function earcutLinked(ear, triangles, minX, minY, invSize, pass) {
  if (!ear) return;
  if (!pass && invSize) indexCurve(ear, minX, minY, invSize);

  let stop = ear;
  while (ear.prev !== ear.next) {
    const prev = ear.prev;
    const next = ear.next;

    if (invSize ? isEarHashed(ear, minX, minY, invSize) : isEar(ear)) {
      triangles.push(prev.i / 2, ear.i / 2, next.i / 2);
      removeNode(ear);
      ear = next.next;
      stop = next.next;
      continue;
    }

    ear = next;
    if (ear !== stop) continue;

    // A full lap with no ear found means the ring is degenerate in some way,
    // so fall through the recovery passes in order of increasing cost.
    if (!pass) {
      earcutLinked(filterPoints(ear), triangles, minX, minY, invSize, 1);
    } else if (pass === 1) {
      const fixed = cureLocalIntersections(filterPoints(ear), triangles);
      earcutLinked(fixed, triangles, minX, minY, invSize, 2);
    } else if (pass === 2) {
      splitEarcut(ear, triangles, minX, minY, invSize);
    }
    break;
  }
}

function isEar(ear) {
  const a = ear.prev;
  const b = ear;
  const c = ear.next;
  if (area(a, b, c) >= 0) return false; // reflex vertex, cannot be an ear

  const x0 = Math.min(a.x, b.x, c.x);
  const y0 = Math.min(a.y, b.y, c.y);
  const x1 = Math.max(a.x, b.x, c.x);
  const y1 = Math.max(a.y, b.y, c.y);

  let p = c.next;
  while (p !== a) {
    if (inside(p, a, b, c, x0, y0, x1, y1)) return false;
    p = p.next;
  }
  return true;
}

function isEarHashed(ear, minX, minY, invSize) {
  const a = ear.prev;
  const b = ear;
  const c = ear.next;
  if (area(a, b, c) >= 0) return false;

  const x0 = Math.min(a.x, b.x, c.x);
  const y0 = Math.min(a.y, b.y, c.y);
  const x1 = Math.max(a.x, b.x, c.x);
  const y1 = Math.max(a.y, b.y, c.y);

  const minZ = zOrder(x0, y0, minX, minY, invSize);
  const maxZ = zOrder(x1, y1, minX, minY, invSize);

  let p = ear.prevZ;
  let n = ear.nextZ;

  // Walk outwards along the z-curve in both directions, stopping as soon as
  // the codes leave the ear triangle's bounding box.
  while (p && p.z >= minZ && n && n.z <= maxZ) {
    if (p !== a && p !== c && inside(p, a, b, c, x0, y0, x1, y1)) return false;
    p = p.prevZ;
    if (n !== a && n !== c && inside(n, a, b, c, x0, y0, x1, y1)) return false;
    n = n.nextZ;
  }
  while (p && p.z >= minZ) {
    if (p !== a && p !== c && inside(p, a, b, c, x0, y0, x1, y1)) return false;
    p = p.prevZ;
  }
  while (n && n.z <= maxZ) {
    if (n !== a && n !== c && inside(n, a, b, c, x0, y0, x1, y1)) return false;
    n = n.nextZ;
  }
  return true;
}

/** Does reflex vertex `p` fall inside candidate ear `a,b,c`? */
function inside(p, a, b, c, x0, y0, x1, y1) {
  return (
    p.x >= x0 && p.x <= x1 && p.y >= y0 && p.y <= y1 &&
    pointInTriangle(a.x, a.y, b.x, b.y, c.x, c.y, p.x, p.y) &&
    area(p.prev, p, p.next) >= 0
  );
}

/** Clip off pairs of edges that cross each other locally. */
function cureLocalIntersections(start, triangles) {
  let p = start;
  do {
    const a = p.prev;
    const b = p.next.next;
    if (
      !equals(a, b) && intersects(a, p, p.next, b) &&
      locallyInside(a, b) && locallyInside(b, a)
    ) {
      triangles.push(a.i / 2, p.i / 2, b.i / 2);
      removeNode(p);
      removeNode(p.next);
      p = start = b;
    }
    p = p.next;
  } while (p !== start);
  return filterPoints(p);
}

/** Last resort: cut the ring in two along a valid diagonal and recurse. */
function splitEarcut(start, triangles, minX, minY, invSize) {
  let a = start;
  do {
    let b = a.next.next;
    while (b !== a.prev) {
      if (a.i !== b.i && isValidDiagonal(a, b)) {
        let c = splitPolygon(a, b);
        a = filterPoints(a, a.next);
        c = filterPoints(c, c.next);
        earcutLinked(a, triangles, minX, minY, invSize, 0);
        earcutLinked(c, triangles, minX, minY, invSize, 0);
        return;
      }
      b = b.next;
    }
    a = a.next;
  } while (a !== start);
}

// -- holes -------------------------------------------------------------------

function eliminateHoles(data, holeIndices, outerNode) {
  const queue = [];
  for (let i = 0, len = holeIndices.length; i < len; i++) {
    const start = holeIndices[i] * 2;
    const end = i < len - 1 ? holeIndices[i + 1] * 2 : data.length;
    const list = linkedList(data, start, end, false);
    if (!list) continue;
    if (list === list.next) list.steiner = true;
    queue.push(getLeftmost(list));
  }
  queue.sort((a, b) => a.x - b.x);
  for (const hole of queue) outerNode = eliminateHole(hole, outerNode);
  return outerNode;
}

function eliminateHole(hole, outerNode) {
  const bridge = findHoleBridge(hole, outerNode);
  if (!bridge) return outerNode;
  const bridgeReverse = splitPolygon(bridge, hole);
  filterPoints(bridgeReverse, bridgeReverse.next);
  return filterPoints(bridge, bridge.next);
}

/** The outer-ring vertex a hole's leftmost point can safely be bridged to. */
function findHoleBridge(hole, outerNode) {
  let p = outerNode;
  const hx = hole.x;
  const hy = hole.y;
  let qx = -Infinity;
  let m = null;

  // Cast a ray left from the hole's leftmost point; keep the closest hit.
  do {
    if (hy <= p.y && hy >= p.next.y && p.next.y !== p.y) {
      const x = p.x + ((hy - p.y) * (p.next.x - p.x)) / (p.next.y - p.y);
      if (x <= hx && x > qx) {
        qx = x;
        m = p.x < p.next.x ? p : p.next;
        if (x === hx) return m;
      }
    }
    p = p.next;
  } while (p !== outerNode);

  if (!m) return null;

  // Then look for a reflex vertex inside the ray's triangle that gives a
  // shallower bridge -- without this the bridge can cross the outer ring.
  const stop = m;
  const mx = m.x;
  const my = m.y;
  let tanMin = Infinity;
  p = m;
  do {
    if (
      hx >= p.x && p.x >= mx && hx !== p.x &&
      pointInTriangle(hy < my ? hx : qx, hy, mx, my, hy < my ? qx : hx, hy, p.x, p.y)
    ) {
      const tan = Math.abs(hy - p.y) / (hx - p.x);
      if (
        locallyInside(p, hole) &&
        (tan < tanMin ||
          (tan === tanMin && (p.x > m.x || (p.x === m.x && sectorContainsSector(m, p)))))
      ) {
        m = p;
        tanMin = tan;
      }
    }
    p = p.next;
  } while (p !== stop);

  return m;
}

function sectorContainsSector(m, p) {
  return area(m.prev, m, p.prev) < 0 && area(p.next, m, m.next) < 0;
}

function getLeftmost(start) {
  let p = start;
  let leftmost = start;
  do {
    if (p.x < leftmost.x || (p.x === leftmost.x && p.y < leftmost.y)) leftmost = p;
    p = p.next;
  } while (p !== start);
  return leftmost;
}

/** Link two ring vertices, splitting one ring into two. Returns the copy. */
function splitPolygon(a, b) {
  const a2 = { i: a.i, x: a.x, y: a.y, prev: null, next: null, z: 0, prevZ: null, nextZ: null, steiner: false };
  const b2 = { i: b.i, x: b.x, y: b.y, prev: null, next: null, z: 0, prevZ: null, nextZ: null, steiner: false };
  const an = a.next;
  const bp = b.prev;

  a.next = b;
  b.prev = a;
  a2.next = an;
  an.prev = a2;
  b2.next = a2;
  a2.prev = b2;
  bp.next = b2;
  b2.prev = bp;

  return b2;
}

// -- z-order index -----------------------------------------------------------

function indexCurve(start, minX, minY, invSize) {
  let p = start;
  do {
    if (p.z === 0) p.z = zOrder(p.x, p.y, minX, minY, invSize);
    p.prevZ = p.prev;
    p.nextZ = p.next;
    p = p.next;
  } while (p !== start);

  p.prevZ.nextZ = null;
  p.prevZ = null;
  sortLinked(p);
}

/** Merge sort over the nextZ chain -- in place, no allocation per pass. */
function sortLinked(list) {
  let inSize = 1;
  let numMerges;
  do {
    let p = list;
    let tail = null;
    list = null;
    numMerges = 0;

    while (p) {
      numMerges++;
      let q = p;
      let pSize = 0;
      for (let i = 0; i < inSize && q; i++) {
        pSize++;
        q = q.nextZ;
      }
      let qSize = inSize;

      while (pSize > 0 || (qSize > 0 && q)) {
        let e;
        if (pSize !== 0 && (qSize === 0 || !q || p.z <= q.z)) {
          e = p;
          p = p.nextZ;
          pSize--;
        } else {
          e = q;
          q = q.nextZ;
          qSize--;
        }
        if (tail) tail.nextZ = e;
        else list = e;
        e.prevZ = tail;
        tail = e;
      }
      p = q;
    }
    tail.nextZ = null;
    inSize *= 2;
  } while (numMerges > 1);

  return list;
}

/** 32-bit Morton code of a point normalised into the ring's bounding box. */
function zOrder(x, y, minX, minY, invSize) {
  let ix = ((x - minX) * invSize) | 0;
  let iy = ((y - minY) * invSize) | 0;

  ix = (ix | (ix << 8)) & 0x00ff00ff;
  ix = (ix | (ix << 4)) & 0x0f0f0f0f;
  ix = (ix | (ix << 2)) & 0x33333333;
  ix = (ix | (ix << 1)) & 0x55555555;

  iy = (iy | (iy << 8)) & 0x00ff00ff;
  iy = (iy | (iy << 4)) & 0x0f0f0f0f;
  iy = (iy | (iy << 2)) & 0x33333333;
  iy = (iy | (iy << 1)) & 0x55555555;

  return ix | (iy << 1);
}

// -- geometric predicates ----------------------------------------------------

function area(p, q, r) {
  return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y);
}

function equals(p1, p2) {
  return p1.x === p2.x && p1.y === p2.y;
}

function pointInTriangle(ax, ay, bx, by, cx, cy, px, py) {
  return (
    (cx - px) * (ay - py) >= (ax - px) * (cy - py) &&
    (ax - px) * (by - py) >= (bx - px) * (ay - py) &&
    (bx - px) * (cy - py) >= (cx - px) * (by - py)
  );
}

function isValidDiagonal(a, b) {
  return (
    a.next.i !== b.i && a.prev.i !== b.i && !intersectsPolygon(a, b) &&
    ((locallyInside(a, b) && locallyInside(b, a) && middleInside(a, b) &&
      (area(a.prev, a, b.prev) !== 0 || area(a, b.prev, b) !== 0)) ||
      (equals(a, b) && area(a.prev, a, a.next) > 0 && area(b.prev, b, b.next) > 0))
  );
}

function sign(num) {
  return num > 0 ? 1 : num < 0 ? -1 : 0;
}

function intersects(p1, q1, p2, q2) {
  const o1 = sign(area(p1, q1, p2));
  const o2 = sign(area(p1, q1, q2));
  const o3 = sign(area(p2, q2, p1));
  const o4 = sign(area(p2, q2, q1));

  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(p1, p2, q1)) return true;
  if (o2 === 0 && onSegment(p1, q2, q1)) return true;
  if (o3 === 0 && onSegment(p2, p1, q2)) return true;
  if (o4 === 0 && onSegment(p2, q1, q2)) return true;
  return false;
}

function onSegment(p, q, r) {
  return (
    q.x <= Math.max(p.x, r.x) && q.x >= Math.min(p.x, r.x) &&
    q.y <= Math.max(p.y, r.y) && q.y >= Math.min(p.y, r.y)
  );
}

function intersectsPolygon(a, b) {
  let p = a;
  do {
    if (
      p.i !== a.i && p.next.i !== a.i && p.i !== b.i && p.next.i !== b.i &&
      intersects(p, p.next, a, b)
    ) {
      return true;
    }
    p = p.next;
  } while (p !== a);
  return false;
}

function locallyInside(a, b) {
  return area(a.prev, a, a.next) < 0
    ? area(a, b, a.next) >= 0 && area(a, a.prev, b) >= 0
    : area(a, b, a.prev) < 0 || area(a, a.next, b) < 0;
}

function middleInside(a, b) {
  let p = a;
  let inside = false;
  const px = (a.x + b.x) / 2;
  const py = (a.y + b.y) / 2;
  do {
    if (
      p.y > py !== p.next.y > py && p.next.y !== p.y &&
      px < ((p.next.x - p.x) * (py - p.y)) / (p.next.y - p.y) + p.x
    ) {
      inside = !inside;
    }
    p = p.next;
  } while (p !== a);
  return inside;
}

/** Twice the signed area of a ring, in the same sign convention earcut uses. */
export function signedArea(data, start, end) {
  let sum = 0;
  for (let i = start, j = end - 2; i < end; i += 2) {
    sum += (data[j] - data[i]) * (data[i + 1] + data[j + 1]);
    j = i;
  }
  return sum;
}
