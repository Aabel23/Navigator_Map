// Wiring: camera and input on the main thread, decode and triangulation on a
// pool of workers, one shared GPU buffer per bucket, a directional-prefetch
// scheduler, and a HUD that prints what was measured rather than what was
// intended.
//
// The division of labour is the point. This file computes the *plan* -- which
// tiles should exist, which should be dropped, where the camera is -- and
// never touches a coordinate. The workers compute the *geometry*. The GPU
// draws it in a handful of calls.

import { lonLatToWorldZ0, tileZoomFor, visibleTiles, prefetchTiles, tileKey } from "./tile_math.js";
import { Renderer } from "./gl.js";
import { GlyphStore } from "./glyphs.js";
import { SpriteStore } from "./sprite.js";
import { LabelPlacement } from "./placement.js";

const SCHEDULE_INTERVAL_MS = 150;
const ZOOM_SPEED = 0.0022;
const HUD_INTERVAL_MS = 500;

async function main() {
  const cfg = await (await fetch("/api/config")).json();
  const tilejson = await (await fetch(cfg.source.tilejson_url)).json();
  const tileUrlTemplate = tilejson.tiles[0];
  const dataMinZoom = tilejson.minzoom ?? cfg.source.min_zoom;
  const dataMaxZoom = tilejson.maxzoom ?? cfg.source.max_zoom;
  const maxCameraZoom = dataMaxZoom + cfg.source.max_camera_overzoom;
  const style = cfg.style;

  document.getElementById("attribution").innerHTML = cfg.page.attribution;
  document.body.style.background = cssColor(style.background);

  const canvas = document.getElementById("gl");
  const renderer = new Renderer(canvas, style, style.bucket_kinds);

  // Text and icons are a second, independent supply chain: glyph ranges and
  // an icon sheet, neither of which comes from the tiles. Neither is required
  // for the map to draw -- if the font service is unreachable the basemap
  // still renders, just without names on it.
  const glyphStore = new GlyphStore(renderer.gl, cfg.labels.glyphs_url, cfg.labels.font);
  const spriteStore = await SpriteStore.load(renderer.gl, cfg.labels.sprite_url, window.devicePixelRatio > 1)
    .catch((err) => {
      console.warn("[map] sprite sheet unavailable:", err.message);
      return null;
    });
  renderer.setLabelTextures(glyphStore, spriteStore);
  const placement = new LabelPlacement(style, glyphStore, spriteStore);
  const glyphsReady = glyphStore.ensureRanges(cfg.labels.preload_ranges);

  // cfg.map.center is [lon, lat] (GeoJSON order); lonLatToWorldZ0 takes the
  // same order -- do not swap them here.
  const origin = lonLatToWorldZ0(cfg.map.center[0], cfg.map.center[1]);
  const home = { worldX: 0, worldY: 0, zoom: cfg.map.zoom };
  const camera = { ...home };

  function resize() {
    renderer.resize(window.innerWidth, window.innerHeight);
  }
  window.addEventListener("resize", resize);
  resize();

  // -- input: drag to pan, wheel or pinch to zoom -----------------------------
  const pointers = new Map();
  let pinchStartDist = 0;
  let pinchStartZoom = 0;

  function screenToWorld(px, py) {
    const scale = Math.pow(2, camera.zoom);
    return {
      x: camera.worldX + (px - renderer.cssWidth / 2) / scale,
      y: camera.worldY + (py - renderer.cssHeight / 2) / scale,
    };
  }

  function zoomAround(px, py, newZoom) {
    const before = screenToWorld(px, py);
    camera.zoom = Math.max(dataMinZoom, Math.min(maxCameraZoom, newZoom));
    const scale = Math.pow(2, camera.zoom);
    camera.worldX = before.x - (px - renderer.cssWidth / 2) / scale;
    camera.worldY = before.y - (py - renderer.cssHeight / 2) / scale;
  }

  canvas.addEventListener("pointerdown", (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinchStartDist = Math.hypot(a.x - b.x, a.y - b.y);
      pinchStartZoom = camera.zoom;
    }
  });

  canvas.addEventListener("pointermove", (ev) => {
    if (!pointers.has(ev.pointerId)) return;
    const prev = pointers.get(ev.pointerId);
    const cur = { x: ev.clientX, y: ev.clientY };
    pointers.set(ev.pointerId, cur);

    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinchStartDist > 1) {
        zoomAround((a.x + b.x) / 2, (a.y + b.y) / 2, pinchStartZoom + Math.log2(dist / pinchStartDist));
      }
      return;
    }
    const scale = Math.pow(2, camera.zoom);
    camera.worldX -= (cur.x - prev.x) / scale;
    camera.worldY -= (cur.y - prev.y) / scale;
  });

  function releasePointer(ev) {
    pointers.delete(ev.pointerId);
    if (pointers.size < 2) pinchStartDist = 0;
  }
  canvas.addEventListener("pointerup", releasePointer);
  canvas.addEventListener("pointercancel", releasePointer);

  canvas.addEventListener(
    "wheel",
    (ev) => {
      ev.preventDefault();
      zoomAround(ev.clientX, ev.clientY, camera.zoom - ev.deltaY * ZOOM_SPEED);
    },
    { passive: false }
  );

  canvas.addEventListener("dblclick", (ev) => {
    zoomAround(ev.clientX, ev.clientY, camera.zoom + 1);
  });

  function zoomByStep(step) {
    zoomAround(renderer.cssWidth / 2, renderer.cssHeight / 2, Math.round(camera.zoom) + step);
  }
  document.getElementById("zoom-in").addEventListener("click", () => zoomByStep(1));
  document.getElementById("zoom-out").addEventListener("click", () => zoomByStep(-1));
  document.getElementById("recenter").addEventListener("click", () => Object.assign(camera, home));

  const hud = document.getElementById("hud");
  document.getElementById("hud-toggle").addEventListener("click", () => {
    hud.classList.toggle("hidden");
  });

  // -- worker pool -------------------------------------------------------------
  const workerCount = Math.max(2, Math.min(4, navigator.hardwareConcurrency || 2));
  const workers = [];
  for (let i = 0; i < workerCount; i++) {
    const worker = new Worker("/static/decode_worker.js", { type: "module" });
    worker.onmessage = onWorkerMessage;
    worker.postMessage({ type: "style", style });
    workers.push(worker);
  }
  let nextWorker = 0;
  let nextReqId = 1;

  const inFlight = new Set();
  /** @type {Map<string, {generation: string, lastSeen: number}>} */
  const resident = new Map();
  let currentGeneration = null;
  let previousGeneration = null;
  let frameCounter = 0;

  let labelsDirty = true;
  const stats = {
    tilesDecoded: 0,
    featuresKept: 0,
    verticesOut: 0,
    trianglesOut: 0,
    tileBytesFetched: 0,
    fps: 0,
  };

  function onWorkerMessage(ev) {
    const msg = ev.data;
    inFlight.delete(msg.tileKey);
    if (!msg.ok) {
      console.warn("[map] tile failed:", msg.tileKey, msg.error);
      return;
    }
    for (const [name, bucket] of renderer.buckets) {
      const mesh = msg.buckets[name];
      if (mesh) bucket.appendTile(msg.tileKey, mesh.vertices, mesh.indices);
      else bucket.appendTile(msg.tileKey, new Float32Array(0), new Uint32Array(0));
    }
    resident.set(msg.tileKey, { generation: generationOf(msg.tileKey), lastSeen: frameCounter });
    if (msg.labels && msg.labels.length > 0) {
      glyphsReady
        .then(() => placement.addTile(msg.tileKey, msg.labels))
        .then(() => {
          labelsDirty = true;
        });
    }
    stats.tilesDecoded += 1;
    stats.featuresKept += msg.stats.featuresKept;
    stats.verticesOut += msg.stats.verticesOut;
    stats.trianglesOut += msg.stats.trianglesOut;
    stats.tileBytesFetched += msg.tileBytes;
  }

  // -- heading estimate, for the prefetch cone -----------------------------------
  let lastSampleWorld = { x: camera.worldX, y: camera.worldY };
  let lastSampleTime = performance.now();
  let headingDir = { x: 0, y: 0 };
  let headingSpeedPxS = 0;

  function updateHeading() {
    const now = performance.now();
    const dt = (now - lastSampleTime) / 1000;
    if (dt < 0.1) return;
    const dx = camera.worldX - lastSampleWorld.x;
    const dy = camera.worldY - lastSampleWorld.y;
    const scale = Math.pow(2, camera.zoom);
    headingSpeedPxS = (Math.hypot(dx, dy) * scale) / dt;
    if (headingSpeedPxS > 2) {
      const len = Math.hypot(dx, dy) || 1;
      headingDir = { x: dx / len, y: dy / len };
    }
    lastSampleWorld = { x: camera.worldX, y: camera.worldY };
    lastSampleTime = now;
  }

  // -- scheduling: which tiles to fetch, which to drop ----------------------------
  //
  // A tile's identity is its coordinate, the tile zoom it was requested at,
  // and the LOD zoom it was decoded at -- because LOD is a decode-time switch:
  // the z14 tile decoded at camera zoom 14 genuinely does not contain the
  // buildings the same tile decoded at zoom 17 does.
  //
  // Together, tile zoom and LOD zoom form a *generation*. Changing zoom starts
  // a new one, and at most two are ever resident: the current one, and the
  // previous one kept as a fallback so the map never blinks empty mid-zoom.
  // The fallback is dropped the moment the new generation has fully arrived,
  // which is what stops two zoom levels of the same street being drawn on top
  // of each other.

  function generationOf(key) {
    const [coordinate, lod] = key.split("@");
    return `${coordinate.split("/")[0]}@${lod}`;
  }

  function schedule() {
    updateHeading();
    const tileZoom = tileZoomFor(camera.zoom, dataMaxZoom, dataMinZoom);
    const lodZoom = Math.round(camera.zoom);
    const generation = `${tileZoom}@${lodZoom}`;
    if (generation !== currentGeneration) {
      previousGeneration = currentGeneration;
      currentGeneration = generation;
    }

    const visible = visibleTiles(camera, origin, renderer.cssWidth, renderer.cssHeight, tileZoom, 1);
    const wanted = new Map(visible.map((t) => [`${tileKey(...t)}@${lodZoom}`, t]));

    if (headingSpeedPxS > cfg.pipeline.prefetch_min_speed_px_s) {
      const ahead = prefetchTiles(
        camera, origin, tileZoom, headingDir.x, headingDir.y, cfg.pipeline.prefetch_ring_tiles
      );
      for (const t of ahead) {
        const key = `${tileKey(...t)}@${lodZoom}`;
        if (!wanted.has(key)) wanted.set(key, t);
      }
    }

    for (const [key, [z, x, y]] of wanted) {
      const entry = resident.get(key);
      if (entry) {
        entry.lastSeen = frameCounter;
        continue;
      }
      if (inFlight.has(key)) continue;
      inFlight.add(key);
      const url = tileUrlTemplate.replace("{z}", z).replace("{x}", x).replace("{y}", y);
      workers[nextWorker].postMessage({
        reqId: nextReqId++,
        tileKey: key,
        z, x, y, url, origin,
        lodZoom,
        simplifyTolerance: cfg.pipeline.simplify_tolerance_units,
      });
      nextWorker = (nextWorker + 1) % workers.length;
    }

    evict(wanted, generation);
  }

  function evict(wanted, generation) {
    const arrived = [...wanted.keys()].every((key) => resident.has(key));

    const drop = [];
    for (const [key, entry] of resident) {
      if (entry.generation === generation) continue;
      // Two generations back is never useful -- the fallback has itself been
      // superseded. The one fallback generation survives only until the
      // current one covers the screen.
      if (entry.generation !== previousGeneration || arrived) drop.push(key);
    }

    // Then the plain LRU cap, over whatever the camera is not looking at.
    const remaining = resident.size - drop.length;
    if (remaining > cfg.pipeline.resident_tile_cap) {
      const dropped = new Set(drop);
      const candidates = [...resident.entries()]
        .filter(([key]) => !wanted.has(key) && !dropped.has(key))
        .sort((a, b) => a[1].lastSeen - b[1].lastSeen)
        .slice(0, remaining - cfg.pipeline.resident_tile_cap);
      for (const [key] of candidates) drop.push(key);
    }

    if (drop.length === 0) return;
    for (const bucket of renderer.buckets.values()) bucket.removeTiles(drop);
    placement.removeTiles(drop);
    for (const key of drop) resident.delete(key);
    labelsDirty = true;
  }

  setInterval(schedule, SCHEDULE_INTERVAL_MS);
  schedule();

  // -- render loop + HUD -----------------------------------------------------------
  let lastHudUpdate = 0;
  let framesSinceHud = 0;
  let lastPlacement = 0;
  let placedView = "";

  // Which labels are drawn depends on where the camera is, so placement has to
  // be redone as it moves -- but not every frame. Comparing the camera against
  // the view placement last ran for keeps a still map from redoing the work,
  // and the interval keeps a moving one from doing it more often than a person
  // can see.
  function runPlacementIfNeeded(now) {
    const view = `${camera.worldX.toFixed(6)},${camera.worldY.toFixed(6)},${camera.zoom.toFixed(3)}`;
    if (!labelsDirty && view === placedView) return;
    if (now - lastPlacement < cfg.pipeline.placement_interval_ms) return;
    placement.run(camera, renderer.cssWidth, renderer.cssHeight, renderer);
    lastPlacement = now;
    placedView = view;
    labelsDirty = false;
  }

  function frame(now) {
    frameCounter += 1;
    framesSinceHud += 1;
    runPlacementIfNeeded(now);
    const drawCalls = renderer.draw(camera);

    if (now - lastHudUpdate > HUD_INTERVAL_MS) {
      stats.fps = (framesSinceHud * 1000) / (now - lastHudUpdate);
      lastHudUpdate = now;
      framesSinceHud = 0;
      hud.textContent = hudText(cfg, camera, renderer, resident, inFlight, stats, drawCalls, headingSpeedPxS, placement);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function hudText(cfg, camera, renderer, resident, inFlight, stats, drawCalls, headingSpeedPxS, placement) {
  let gpuBytes = 0;
  let residentTriangles = 0;
  const perBucket = [];
  for (const bucket of renderer.buckets.values()) {
    gpuBytes += bucket.bytesUsed;
    residentTriangles += bucket.usedIndices / 3;
    perBucket.push(
      `  ${bucket.name.padEnd(9)}${(bucket.usedIndices / 3).toLocaleString().padStart(9)} tri` +
        `${(bucket.bytesUsed / 1e6).toFixed(1).padStart(7)} MB`
    );
  }
  const prefetching = headingSpeedPxS > cfg.pipeline.prefetch_min_speed_px_s;
  return [
    `${cfg.page.title}`,
    `zoom ${camera.zoom.toFixed(2)}   ${stats.fps.toFixed(0)} fps`,
    `tiles resident ${resident.size}   in flight ${inFlight.size}`,
    `buckets ${renderer.buckets.size}   draw calls/frame ${drawCalls}`,
    `triangles resident ${Math.round(residentTriangles).toLocaleString()}`,
    ...perBucket,
    `labels ${placement.placedCount} drawn / ${placement.candidateCount} on screen / ${placement.records.length} resident`,
    `gpu ${(gpuBytes / 1e6).toFixed(2)} MB   fetched ${(stats.tileBytesFetched / 1e6).toFixed(2)} MB`,
    `prefetch ${prefetching ? `ahead (${headingSpeedPxS.toFixed(0)} px/s)` : "off (too slow)"}`,
  ].join("\n");
}

function cssColor(rgba) {
  const [r, g, b] = rgba;
  return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}

main().catch((err) => {
  document.getElementById("hud").textContent = `Failed to start: ${err.message}`;
  console.error(err);
});
