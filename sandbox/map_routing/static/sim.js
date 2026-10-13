// The simulator's browser half.
//
// Three jobs, and it is worth being precise about which of them touches the
// map block and how:
//
// 1. It reads the camera. The map block's `ports.md` declares `camera_state`
//    as an output port -- "{worldX, worldY, zoom} ... destination: not yet
//    consumed" -- but nothing publishes it yet, and publishing it would be a
//    change to another block. So this file taps the value where it already
//    crosses a published seam: `Renderer.draw(camera)` is called once per
//    frame with exactly that object. The wrapper records it and calls
//    straight through. When the map block does publish `camera_state`, the
//    tap below is the one thing to delete.
//
// 2. It draws. On its own 2D canvas, above the map's, never into it. The map
//    block offers `Bucket.setStyleRange` for recolouring roads it already
//    holds, which is the right port for traffic on the basemap -- but a route
//    is not a feature the basemap has, so an overlay is what a route needs.
//
// 3. It picks. A click on the map canvas becomes a lon/lat, which the server
//    hands to map matching and then to routing.
//
// Everything drawn here is projected with the map block's own
// `lonLatToWorldZ0`, so the overlay and the basemap agree on where a
// coordinate is by construction rather than by coincidence.

import { Renderer } from "/static/gl.js";
import { lonLatToWorldZ0, TILE_SIZE } from "/static/tile_math.js";

// --- the camera tap ---------------------------------------------------------

const view = { camera: null, renderer: null };
const drawThroughTo = Renderer.prototype.draw;
Renderer.prototype.draw = function (camera) {
  view.camera = camera;
  view.renderer = this;
  const drawCalls = drawThroughTo.call(this, camera);
  paint();
  return drawCalls;
};

// --- constants --------------------------------------------------------------

const ROUTE_COLORS = {
  free_flow: "#7a8794",
  traffic: "#1f6feb",
};
const GPS_COLOR = "#1f6feb";
const DESTINATION_COLOR = "#c0243c";
const MATCH_COLOR = "#2b3138";
const OVERLAY_FPS_MS = 33;

// --- state ------------------------------------------------------------------

const state = {
  boot: null,
  sim: null,
  origin: null, // world-Z0 pixels of the map block's configured centre
  pick: "destination",
  showTraffic: true,
  follow: false,
  regionKey: null,
  trafficStamp: null,
  pendingCenter: null,
  busy: false,
};

// Everything drawable, pre-projected into world-Z0 pixels once. A frame then
// costs one multiply and one add per point instead of a projection.
const drawable = {
  traffic: [],
  routes: [],
  gps: null,
  destination: null,
  originMatch: null,
};

const levelColors = new Map();

// --- the overlay canvas -----------------------------------------------------

const overlay = document.getElementById("sim-overlay");
const ctx = overlay.getContext("2d");
let overlaySized = { w: 0, h: 0, dpr: 0 };
let lastPaint = 0;

function sizeOverlay(cssW, cssH) {
  const dpr = window.devicePixelRatio || 1;
  if (overlaySized.w === cssW && overlaySized.h === cssH && overlaySized.dpr === dpr) return;
  overlay.width = Math.round(cssW * dpr);
  overlay.height = Math.round(cssH * dpr);
  overlay.style.width = `${cssW}px`;
  overlay.style.height = `${cssH}px`;
  overlaySized = { w: cssW, h: cssH, dpr };
}

// --- projection -------------------------------------------------------------

function worldZ0ToLonLat(x, y) {
  const lon = (x / TILE_SIZE) * 360 - 180;
  const merc = Math.PI * (1 - (2 * y) / TILE_SIZE);
  const lat = (180 / Math.PI) * Math.atan(Math.sinh(merc));
  return [lon, lat];
}

/** lon/lat to world-Z0 pixels relative to the map block's configured origin. */
function toWorld(lon, lat) {
  const p = lonLatToWorldZ0(lon, lat);
  return [p.x - state.origin.x, p.y - state.origin.y];
}

/** The same screen transform app.js uses, read from the tapped camera. */
function makeTransform() {
  const { camera, renderer } = view;
  const scale = Math.pow(2, camera.zoom);
  return {
    scale,
    ox: renderer.cssWidth / 2 - camera.worldX * scale,
    oy: renderer.cssHeight / 2 - camera.worldY * scale,
    w: renderer.cssWidth,
    h: renderer.cssHeight,
  };
}

function screenToLonLat(px, py) {
  const { camera, renderer } = view;
  const scale = Math.pow(2, camera.zoom);
  const wx = camera.worldX + (px - renderer.cssWidth / 2) / scale + state.origin.x;
  const wy = camera.worldY + (py - renderer.cssHeight / 2) / scale + state.origin.y;
  return worldZ0ToLonLat(wx, wy);
}

function centerOn(lon, lat, zoom) {
  if (!state.origin) return;
  if (!view.camera) {
    // The map has not drawn its first frame yet, so there is no camera to
    // move. Hold the request; paint() flushes it on the frame it appears.
    state.pendingCenter = { lon, lat, zoom };
    return;
  }
  const [wx, wy] = toWorld(lon, lat);
  view.camera.worldX = wx;
  view.camera.worldY = wy;
  if (typeof zoom === "number") view.camera.zoom = zoom;
}

// --- painting ---------------------------------------------------------------

function paint() {
  if (!state.origin || !view.camera || !view.renderer) return;
  if (state.pendingCenter) {
    const { lon, lat, zoom } = state.pendingCenter;
    state.pendingCenter = null;
    centerOn(lon, lat, zoom);
  }
  const now = performance.now();
  if (now - lastPaint < OVERLAY_FPS_MS) return;
  lastPaint = now;

  sizeOverlay(view.renderer.cssWidth, view.renderer.cssHeight);
  const t = makeTransform();
  ctx.setTransform(overlaySized.dpr, 0, 0, overlaySized.dpr, 0, 0);
  ctx.clearRect(0, 0, t.w, t.h);

  if (state.showTraffic) paintTraffic(t);
  paintRoutes(t);
  paintMarkers(t);
}

function paintTraffic(t) {
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const record of drawable.traffic) {
    if (!inView(record.bounds, t)) continue;
    if (record.points.length === 2) {
      const x = record.points[0] * t.scale + t.ox;
      const y = record.points[1] * t.scale + t.oy;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = record.color;
      ctx.globalAlpha = 0.9;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.85)";
      ctx.stroke();
      continue;
    }
    ctx.globalAlpha = record.incident ? 0.95 : 0.72;
    ctx.strokeStyle = record.color;
    ctx.lineWidth = record.incident ? 6 : 4;
    if (record.incident) ctx.setLineDash([9, 6]);
    strokePolyline(record.points, t);
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }
}

function paintRoutes(t) {
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  // Free flow underneath, traffic-aware on top: where they agree the blue
  // line simply covers the grey one, and where they diverge both are visible.
  for (const route of drawable.routes) {
    if (!route.points.length) continue;
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = route.key === "traffic" ? 11 : 9;
    strokePolyline(route.points, t);
    ctx.strokeStyle = ROUTE_COLORS[route.key] || "#1f6feb";
    ctx.lineWidth = route.key === "traffic" ? 6 : 4;
    if (route.key === "free_flow") ctx.setLineDash([10, 7]);
    strokePolyline(route.points, t);
    ctx.setLineDash([]);
  }
}

function paintMarkers(t) {
  if (drawable.destination) {
    const [x, y] = place(drawable.destination, t);
    pin(x, y, DESTINATION_COLOR);
  }
  if (drawable.originMatch) {
    const [x, y] = place(drawable.originMatch, t);
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.strokeStyle = MATCH_COLOR;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  if (drawable.gps) {
    const [x, y] = place(drawable.gps, t);
    const accuracyPx = drawable.gps.accuracyM * t.scale * metresToWorldPx(drawable.gps.lat);
    if (accuracyPx > 3) {
      ctx.beginPath();
      ctx.arc(x, y, accuracyPx, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(31,111,235,0.12)";
      ctx.fill();
    }
    if (drawable.gps.moving) arrow(x, y, drawable.gps.bearing);
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fillStyle = GPS_COLOR;
    ctx.fill();
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = "#fff";
    ctx.stroke();
  }
}

function place(item, t) {
  return [item.x * t.scale + t.ox, item.y * t.scale + t.oy];
}

function strokePolyline(points, t) {
  ctx.beginPath();
  ctx.moveTo(points[0] * t.scale + t.ox, points[1] * t.scale + t.oy);
  for (let i = 2; i < points.length; i += 2) {
    ctx.lineTo(points[i] * t.scale + t.ox, points[i + 1] * t.scale + t.oy);
  }
  ctx.stroke();
}

function pin(x, y, color) {
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x - 7, y - 16);
  ctx.lineTo(x + 7, y - 16);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(x, y - 20, 7, 0, Math.PI * 2);
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#fff";
  ctx.stroke();
}

function arrow(x, y, bearing) {
  const a = ((bearing - 90) * Math.PI) / 180;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(a);
  ctx.beginPath();
  ctx.moveTo(18, 0);
  ctx.lineTo(6, -6);
  ctx.lineTo(6, 6);
  ctx.closePath();
  ctx.fillStyle = GPS_COLOR;
  ctx.fill();
  ctx.restore();
}

/** World-Z0 pixels per metre at a latitude -- for drawing an accuracy circle. */
function metresToWorldPx(lat) {
  const earth = 40075016.686;
  return TILE_SIZE / (earth * Math.cos((lat * Math.PI) / 180));
}

function inView(bounds, t) {
  const x0 = bounds[0] * t.scale + t.ox;
  const y0 = bounds[1] * t.scale + t.oy;
  const x1 = bounds[2] * t.scale + t.ox;
  const y1 = bounds[3] * t.scale + t.oy;
  return !(x1 < -40 || y1 < -40 || x0 > t.w + 40 || y0 > t.h + 40);
}

// --- turning server data into drawables -------------------------------------

function projectShape(coordinates) {
  const points = new Float64Array(coordinates.length * 2);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < coordinates.length; i++) {
    const [x, y] = toWorld(coordinates[i][0], coordinates[i][1]);
    points[i * 2] = x;
    points[i * 2 + 1] = y;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { points, bounds: [minX, minY, maxX, maxY] };
}

function rebuildTraffic(geojson) {
  const records = [];
  for (const feature of geojson.features || []) {
    const geometry = feature.geometry;
    const properties = feature.properties || {};
    const coordinates =
      geometry.type === "Point" ? [geometry.coordinates] : geometry.coordinates;
    if (!coordinates || !coordinates.length) continue;
    const shape = projectShape(coordinates);
    records.push({
      points: shape.points,
      bounds: shape.bounds,
      incident: properties.record === "incident",
      color:
        properties.record === "incident"
          ? properties.blocking
            ? "#c0243c"
            : "#8a5cd6"
          : levelColors.get(properties.level_slug) || "#9aa3ad",
    });
  }
  drawable.traffic = records;
}

function rebuildFromState(sim) {
  drawable.routes = (sim.routes || [])
    .filter((leg) => leg.ok)
    .map((leg) => ({ key: leg.key, ...projectShape(leg.geometry) }));

  const fix = sim.gps;
  const [gx, gy] = toWorld(fix.lon, fix.lat);
  drawable.gps = {
    x: gx,
    y: gy,
    lat: fix.lat,
    bearing: fix.bearing,
    moving: fix.moving,
    accuracyM: fix.accuracy_m,
  };

  const match = fix.match;
  if (match) {
    const [mx, my] = toWorld(match.lon, match.lat);
    drawable.originMatch = { x: mx, y: my };
  } else {
    drawable.originMatch = null;
  }

  const picked = sim.destination.picked;
  if (picked) {
    const [dx, dy] = toWorld(picked[0], picked[1]);
    drawable.destination = { x: dx, y: dy };
  } else {
    drawable.destination = null;
  }
}

// --- server calls -----------------------------------------------------------

async function post(path, body) {
  state.busy = true;
  try {
    const response = await fetch(path, {
      method: body === undefined ? "DELETE" : "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json();
    if (response.ok) applyState(payload);
    return payload;
  } finally {
    state.busy = false;
  }
}

function applyState(sim) {
  state.sim = sim;

  if (sim.region.key !== state.regionKey) {
    state.regionKey = sim.region.key;
    state.trafficStamp = null;
    drawable.traffic = [];
    centerOn(sim.region.center[0], sim.region.center[1], sim.region.zoom);
  }

  if (state.origin) rebuildFromState(sim);
  if (state.follow && state.origin) centerOn(sim.gps.lon, sim.gps.lat);

  const stamp = sim.traffic.ready ? sim.traffic.observed_at : null;
  if (stamp && stamp !== state.trafficStamp) {
    state.trafficStamp = stamp;
    loadTraffic();
  }

  renderPanel();
}

async function loadTraffic() {
  const geojson = await (await fetch("/api/sim/traffic")).json();
  if (state.origin) rebuildTraffic(geojson);
}

async function poll() {
  try {
    if (!state.busy) {
      const sim = await (await fetch("/api/sim/state")).json();
      applyState(sim);
    }
  } catch (err) {
    console.warn("[sim] state poll failed:", err.message);
  }
  const sim = state.sim;
  const quick = !sim || sim.graph.status !== "ready" || sim.gps.moving;
  setTimeout(poll, quick ? 350 : 1500);
}

// --- panel ------------------------------------------------------------------

const el = (id) => document.getElementById(id);

function kv(pairs) {
  return pairs
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`)
    .join("");
}

function duration(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}:${String(total % 60).padStart(2, "0")}`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

function distance(metres) {
  if (metres === null || metres === undefined) return "--";
  return metres >= 1000 ? `${(metres / 1000).toFixed(2)} km` : `${Math.round(metres)} m`;
}

function renderPanel() {
  const sim = state.sim;
  if (!sim) return;

  // Region
  if (state.boot) {
    el("sim-regions").innerHTML = state.boot.regions
      .map(
        (region) =>
          `<button class="sim-chip${region.key === sim.region.key ? " sim-on" : ""}" ` +
          `type="button" data-region="${region.key}">${region.label.split(" -- ")[0]}</button>`
      )
      .join("");
  }
  const badge = sim.region.measured
    ? '<span class="sim-badge sim-measured">measured</span>'
    : '<span class="sim-badge">modelled</span>';
  el("sim-region-note").innerHTML = `${badge} ${sim.region.note}`;

  // GPS
  const fix = sim.gps;
  el("sim-gps").innerHTML = kv([
    ["position", `${fix.lat.toFixed(5)}, ${fix.lon.toFixed(5)}`],
    ["speed", fix.moving ? `${fix.speed_kph.toFixed(0)} km/h` : "parked"],
    ["accuracy", `${fix.accuracy_m.toFixed(1)} m`],
    [
      "matched",
      fix.match ? `${fix.match.node_id} &middot; ${fix.match.distance_m.toFixed(1)} m` : "--",
    ],
    fix.moving ? ["driven", `${distance(fix.progress_m)} / ${distance(fix.route_m)}`] : null,
    fix.moving && fix.time_scale > 1 ? ["clock", `&times;${fix.time_scale} real time`] : null,
  ].filter(Boolean));
  el("sim-drive").textContent = fix.moving ? "Stop" : "Drive route";
  el("sim-drive").disabled = !fix.moving && !(sim.routes || []).some((leg) => leg.ok);
  el("sim-noise").classList.toggle("sim-on", fix.noise);
  el("sim-follow").classList.toggle("sim-on", state.follow);

  // Destination
  const destination = sim.destination;
  el("sim-destination").innerHTML = kv([
    [
      "picked",
      destination.picked
        ? `${destination.picked[1].toFixed(5)}, ${destination.picked[0].toFixed(5)}`
        : "--",
    ],
    [
      "matched",
      destination.match
        ? `${destination.match.node_id} &middot; ${destination.match.distance_m.toFixed(1)} m`
        : "--",
    ],
  ]);
  el("sim-clear").disabled = !destination.picked;

  // Routes
  el("sim-routes").innerHTML = renderRoutes(sim.routes || []);
  const note = el("sim-note");
  note.textContent = sim.note || "";
  note.classList.toggle("sim-warn", Boolean(sim.note));

  // Traffic
  const traffic = sim.traffic;
  const link = traffic.link || {};
  el("sim-traffic").innerHTML = traffic.ready
    ? kv([
        ["sources", (traffic.sources || []).join(", ") || "none"],
        [
          "records",
          `${traffic.counts.segments} seg &middot; ${traffic.counts.observations} obs &middot; ` +
            `${traffic.counts.incidents} inc`,
        ],
        ["age", `${Math.round(traffic.age_s)} s${traffic.from_cache ? " (cached)" : ""}`],
        ["edges priced", (link.edges_priced || 0).toLocaleString()],
        ["worst", `&times;${(link.worst_multiplier || 1).toFixed(2)}`],
        link.edges_blocked
          ? ["blocked", `${link.edges_blocked} edges / ${link.blocking_incidents} incidents`]
          : null,
        (traffic.failures || []).length
          ? ["failed", traffic.failures.map((f) => f.provider).join(", ")]
          : null,
      ].filter(Boolean))
    : kv([["status", "waiting for the first snapshot"]]);
  el("sim-show-traffic").classList.toggle("sim-on", state.showTraffic);
  // The traffic block's README makes this a condition of using the data:
  // "Both must be credited wherever this block's output is displayed."
  el("sim-credit").innerHTML = credits(traffic.sources || []);

  // Graph
  const graph = sim.graph;
  el("sim-graph").innerHTML = kv([
    ["status", graph.error ? `error` : graph.status],
    graph.error ? ["message", graph.error] : null,
    graph.nodes ? ["ways", graph.ways.toLocaleString()] : null,
    graph.nodes ? ["nodes", graph.nodes.toLocaleString()] : null,
    graph.edges ? ["edges", graph.edges.toLocaleString()] : null,
    graph.routable_nodes ? ["routable", graph.routable_nodes.toLocaleString()] : null,
  ].filter(Boolean));
}

function credits(sources) {
  const lines = [
    'Roads &amp; modelled traffic from &copy; <a href="https://www.openstreetmap.org/copyright">' +
      "OpenStreetMap</a> contributors (ODbL), via Overpass.",
  ];
  if (sources.includes("digitraffic")) {
    lines.push(
      'Measured traffic by <a href="https://www.digitraffic.fi/en/">Fintraffic / Digitraffic</a>, ' +
        'CC BY 4.0.'
    );
  }
  return lines.join("<br>");
}

function renderRoutes(legs) {
  if (!legs.length) return '<div class="sim-note">Click the map to set a destination.</div>';
  const free = legs.find((leg) => leg.key === "free_flow");
  const traffic = legs.find((leg) => leg.key === "traffic");

  const rows = legs.map((leg) => {
    const swatch = `<i class="sim-swatch" style="background:${ROUTE_COLORS[leg.key]}"></i>`;
    if (!leg.ok) {
      return (
        `<div class="sim-route">${swatch}` +
        `<span class="sim-route-name">${leg.label}</span>` +
        `<div class="sim-fail">${leg.error}</div></div>`
      );
    }
    return (
      `<div class="sim-route">${swatch}` +
      `<span class="sim-route-name">${leg.label}</span>` +
      `<span class="sim-route-eta">${duration(leg.travel_time_s)}</span>` +
      `<div class="sim-route-figures">${distance(leg.distance_m)} &middot; ` +
      `${leg.edges} edges &middot; ${leg.nodes_expanded.toLocaleString()} settled</div></div>`
    );
  });

  if (free && traffic && free.ok && traffic.ok) {
    const delta = traffic.travel_time_s - free.travel_time_s;
    const percent = free.travel_time_s > 0 ? (delta / free.travel_time_s) * 100 : 0;
    const same = free.geometry.length === traffic.geometry.length;
    rows.push(
      `<div class="sim-note">Traffic costs <span class="sim-delta${
        delta > 0 ? " sim-slower" : ""
      }">${delta >= 0 ? "+" : ""}${duration(Math.abs(delta))}</span>` +
        ` (${percent >= 0 ? "+" : ""}${percent.toFixed(0)}%) &mdash; ` +
        `${same ? "same road, priced differently" : "a different road"}.</div>`
    );
  }
  return rows.join("");
}

// --- input ------------------------------------------------------------------

function wirePanel() {
  el("sim-collapse").addEventListener("click", () => {
    el("sim-panel").classList.toggle("sim-collapsed");
  });

  el("sim-regions").addEventListener("click", (ev) => {
    const key = ev.target.dataset.region;
    if (key) post("/api/sim/region", { key });
  });

  el("sim-pickmode").addEventListener("click", (ev) => {
    const mode = ev.target.dataset.pick;
    if (!mode) return;
    state.pick = mode;
    for (const button of el("sim-pickmode").querySelectorAll("button")) {
      button.classList.toggle("sim-on", button.dataset.pick === mode);
    }
  });

  el("sim-drive").addEventListener("click", () => {
    post("/api/sim/drive", { on: !state.sim.gps.moving });
  });

  el("sim-noise").addEventListener("click", () => {
    post("/api/sim/gps", { noise: !state.sim.gps.noise });
  });

  el("sim-follow").addEventListener("click", () => {
    state.follow = !state.follow;
    renderPanel();
  });

  el("sim-clear").addEventListener("click", () => post("/api/sim/destination", undefined));
  el("sim-rebuild").addEventListener("click", () => post("/api/sim/rebuild", {}));

  el("sim-show-traffic").addEventListener("click", () => {
    state.showTraffic = !state.showTraffic;
    renderPanel();
  });
}

function wirePicking() {
  const canvas = document.getElementById("gl");
  const active = new Set();
  let candidate = null;
  let lastPick = 0;

  canvas.addEventListener("pointerdown", (ev) => {
    active.add(ev.pointerId);
    // A second finger means a pinch, not a pick.
    candidate = active.size === 1 ? { id: ev.pointerId, x: ev.clientX, y: ev.clientY, t: performance.now() } : null;
  });

  const finish = (ev) => {
    active.delete(ev.pointerId);
    if (!candidate || candidate.id !== ev.pointerId) return;
    const { x, y, t } = candidate;
    candidate = null;
    if (ev.type !== "pointerup") return;
    const moved = Math.hypot(ev.clientX - x, ev.clientY - y);
    const held = performance.now() - t;
    // A drag is a pan and a long press is not a click. Both belong to the map.
    if (moved > 6 || held > 700) return;
    // The map block zooms on double-click; the second click of one would
    // otherwise re-pick the same spot.
    if (performance.now() - lastPick < 350) return;
    lastPick = performance.now();
    pickAt(ev.clientX, ev.clientY);
  };

  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

function pickAt(px, py) {
  if (!view.camera || !state.origin) return;
  const [lon, lat] = screenToLonLat(px, py);
  if (state.pick === "gps") post("/api/sim/gps", { lon, lat });
  else post("/api/sim/destination", { lon, lat });
}

// --- start ------------------------------------------------------------------

async function start() {
  const [config, boot] = await Promise.all([
    (await fetch("/api/config")).json(),
    (await fetch("/api/sim/boot")).json(),
  ]);

  // The same origin app.js chooses, from the same endpoint. Sharing it is
  // what makes the overlay and the basemap agree without either knowing
  // about the other.
  state.origin = lonLatToWorldZ0(config.map.center[0], config.map.center[1]);
  state.boot = boot;

  for (const level of boot.levels) levelColors.set(level.slug, level.color);
  el("sim-legend").innerHTML = boot.levels
    .map((level) => `<span><i style="background:${level.color}"></i>${level.label}</span>`)
    .join("");

  wirePanel();
  wirePicking();
  poll();
}

start().catch((err) => {
  console.error("[sim] failed to start:", err);
  const note = document.getElementById("sim-note");
  if (note) {
    note.textContent = `Simulator failed to start: ${err.message}`;
    note.classList.add("sim-warn");
  }
});
