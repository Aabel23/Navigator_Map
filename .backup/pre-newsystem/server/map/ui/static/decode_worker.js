// The whole worker: fetch a tile's bytes, decode them, triangulate them, and
// hand back typed arrays.
//
// Everything expensive about a tile happens on this thread. A 400 KB tile with
// ten thousand buildings cannot drop a frame, because there is no frame on
// this thread to drop -- the main thread's only remaining work is one
// bufferSubData per bucket.
//
// The style arrives once, in an init message, rather than riding along with
// every tile request: it is the same object for every tile, and postMessage is
// ordered per worker, so a tile request posted after it is guaranteed to find
// it here.

import { decodeTileMesh } from "./mvt.js";

let style = null;

const EMPTY_STATS = {
  featuresConsidered: 0,
  featuresKept: 0,
  verticesIn: 0,
  verticesOut: 0,
  trianglesOut: 0,
  labelsFound: 0,
};

self.onmessage = async (ev) => {
  const msg = ev.data;

  if (msg.type === "style") {
    style = msg.style;
    return;
  }

  const { reqId, tileKey, z, x, y, url, origin, lodZoom, simplifyTolerance } = msg;
  try {
    if (!style) throw new Error("tile requested before the style arrived");

    const res = await fetch(url);
    // Outside the source's coverage there is simply no tile. That is an empty
    // tile, not a failure: reporting it as one lets the scheduler mark it
    // resident and stop asking.
    if (res.status === 404) {
      self.postMessage({ reqId, tileKey, ok: true, buckets: {}, labels: [], stats: EMPTY_STATS, tileBytes: 0 });
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);

    const bytes = new Uint8Array(await res.arrayBuffer());
    const { buckets, labels, stats } = decodeTileMesh(bytes, z, x, y, origin, lodZoom, style, simplifyTolerance);

    const transfer = [];
    for (const mesh of Object.values(buckets)) {
      transfer.push(mesh.vertices.buffer, mesh.indices.buffer);
    }
    // Labels are plain objects with strings in them, so they are cloned
    // rather than transferred -- there are a few hundred per tile and the
    // strings are short, which is far cheaper than it would be to encode
    // them into a buffer just to avoid the copy.
    self.postMessage(
      { reqId, tileKey, ok: true, buckets, labels, stats, tileBytes: bytes.byteLength },
      transfer
    );
  } catch (err) {
    self.postMessage({ reqId, tileKey, ok: false, error: String((err && err.message) || err) });
  }
};
