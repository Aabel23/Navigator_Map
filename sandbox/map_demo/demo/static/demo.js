// The demo's browser half — a navigation client built on `/api/v1`.
//
// Everything on screen comes from one of two places and it is worth being
// precise about which:
//
//   the basemap        the client map block's real WebGL2 renderer, served
//                      unchanged from /static. This file never draws into it.
//   everything else    the server, over its published HTTP API. The route,
//                      the turns, the street names, the traffic colours, the
//                      closures and the graph counts are all answers to
//                      requests a phone could make.
//
// There is no routing here, no cost model, no graph and no snapping. If you
// find yourself adding one, the thing you want already exists one layer down.
//
// One shim, for one reason: the map block declares `camera_state` as an
// output port and does not publish it — `camera` is a local inside app.js's
// main(). The overlay needs exactly that value, so this file taps it where it
// already crosses a published seam: Renderer.draw(camera) is called once per
// frame with the object. The wrapper records it and calls straight through.
// When the map block publishes the port, delete the wrapper.

import { Renderer } from "/static/gl.js";
import { lonLatToWorldZ0, TILE_SIZE } from "/static/tile_math.js";

// ── the camera tap ──────────────────────────────────────────────────────────

const view = { camera: null, renderer: null };
const drawThrough = Renderer.prototype.draw;
Renderer.prototype.draw = function (camera) {
  view.camera = camera;
  view.renderer = this;
  const calls = drawThrough.call(this, camera);
  paint();
  return calls;
};

// ── constants ───────────────────────────────────────────────────────────────

const ROUTE_COLOR = "#1f6feb";
const FREEFLOW_COLOR = "#8b949e";
const ORIGIN_COLOR = "#1f6feb";
const DESTINATION_COLOR = "#c0243c";
const BLOCKING_COLOR = "#c0243c";
const CONDITION_COLOR = "#8a5cd6";
const NETWORK_COLOR = "rgba(90,100,112,0.42)";

const ROAD_WIDTH = {
  motorway: 5, motorway_link: 3.5, trunk: 4.5, trunk_link: 3.5,
  primary: 4, primary_link: 3, secondary: 3.5, secondary_link: 3,
  tertiary: 3, tertiary_link: 2.5, residential: 2.5, unclassified: 2.5,
};
const DEFAULT_ROAD_WIDTH = 2.5;

const MANEUVER_ICON = {
  depart: "●", continue: "↑", slight_left: "↖", left: "←",
  sharp_left: "↰", slight_right: "↗", right: "→",
  sharp_right: "↱", u_turn: "↩", arrive: "◎",
};

//: Wider than this (degrees of longitude) and the road/traffic overlay is not
//: fetched. A city-wide box is thousands of polylines, and the answer to
//: "why is it slow" should never be "the demo asked for the whole country".
const MAX_OVERLAY_SPAN_DEG = 0.09;

//: Requested areas are snapped outward to this grid before they are asked
//: for. It is the most consequential number in this file. Every distinct
//: box is, on the server, a fresh Overpass query and a fresh graph build --
//: tens of seconds -- and an unsnapped viewport changes on every pixel of
//: pan, so nothing would ever be a cache hit. At 0.02 degrees (~2 km) a
//: whole neighbourhood of panning reuses one box.
//:
//: Bigger is not better: snapping *grows* the box, and the cold cost is
//: dominated by how much road is inside it. 0.01 degrees (~1.1 km) is the
//: compromise -- fine enough that a snapped viewport is barely larger than the
//: real one, coarse enough that ordinary panning never changes the answer.
const AREA_GRID_DEG = 0.01;

const OVERLAY_MIN_MS = 33;
const AREA_IDLE_MS = 700;
//: Wall-clock speed-up while driving. The vehicle keeps the route's own speed;
//: only the clock runs fast, so the speedometer stays honest.
const DRIVE_TIME_SCALE = 8;

//: Marks the closures this page reported, so "Reopen all" withdraws its own
//: and never something a real operator entered.
const DEMO_CLOSURE_TAG = "demo-closure-";

// ── state ───────────────────────────────────────────────────────────────────

const state = {
  origin: null,        // [lon, lat]
  destination: null,
  picking: "origin",
  closing: false,
  profile: "car",
  costMode: "fastest",
  compare: true,
  layers: { traffic: true, roads: false, conditions: true },
  route: null,         // the traffic-priced route payload
  freeRoute: null,     // the same trip with use_traffic:false
  levels: [],
  levelColor: new Map(),
  areaKey: null,
  areaBusy: false,
  areaTooWide: false,
  trafficMeta: null,
  graph: null,
  conditions: [],
  myClosures: [],
  origin_world: null,  // map-block world origin, from /api/config
  drive: null,
  pendingCenter: null,
  info: null,
  routing: false,
  linkLabel: "",
  //: Snapped area keys the server has already answered for. Used only to
  //: decide how loudly to warn about a wait, never to skip a request.
  warmedAreas: new Set(),
};

// Pre-projected geometry. A frame costs one multiply and one add per point
// instead of a projection.
const drawable = {
  roads: new Map(),    // road_id -> {points, bounds, klass, name}
  traffic: new Map(),  // road_id -> {level, ratio, speed_kph, free_flow_kph, source}
  conditions: [],      // {points, bounds, blocking, kind}
  route: null,         // {points, bounds}
  freeRoute: null,
};

// ── the overlay canvas ──────────────────────────────────────────────────────

const overlay = document.getElementById("nav-overlay");
const ctx = overlay.getContext("2d");
let sized = { w: 0, h: 0, dpr: 0 };
let lastPaint = 0;

function sizeOverlay(cssW, cssH) {
  const dpr = window.devicePixelRatio || 1;
  if (sized.w === cssW && sized.h === cssH && sized.dpr === dpr) return;
  overlay.width = Math.round(cssW * dpr);
  overlay.height = Math.round(cssH * dpr);
  overlay.style.width = `${cssW}px`;
  overlay.style.height = `${cssH}px`;
  sized = { w: cssW, h: cssH, dpr };
}

// ── projection ──────────────────────────────────────────────────────────────

function worldToLonLat(x, y) {
  const lon = (x / TILE_SIZE) * 360 - 180;
  const merc = Math.PI * (1 - (2 * y) / TILE_SIZE);
  return [lon, (180 / Math.PI) * Math.atan(Math.sinh(merc))];
}

/** lon/lat -> world-Z0 pixels relative to the map block's configured origin. */
function toWorld(lon, lat) {
  const p = lonLatToWorldZ0(lon, lat);
  return [p.x - state.origin_world.x, p.y - state.origin_world.y];
}

/** The same screen transform app.js uses, read off the tapped camera. */
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
  return worldToLonLat(
    camera.worldX + (px - renderer.cssWidth / 2) / scale + state.origin_world.x,
    camera.worldY + (py - renderer.cssHeight / 2) / scale + state.origin_world.y
  );
}

function viewportBBox() {
  const t = makeTransform();
  const [west, north] = screenToLonLat(0, 0);
  const [east, south] = screenToLonLat(t.w, t.h);
  return [west, south, east, north];
}

/** Snap a box outward to the grid, so a small pan asks the same question. */
function snapBBox([west, south, east, north]) {
  const g = AREA_GRID_DEG;
  return [
    Math.floor(west / g) * g,
    Math.floor(south / g) * g,
    Math.ceil(east / g) * g,
    Math.ceil(north / g) * g,
  ].map((v) => Number(v.toFixed(4)));
}

function centerOn(lon, lat, zoom) {
  if (!state.origin_world) return;
  if (!view.camera) {
    state.pendingCenter = { lon, lat, zoom };
    return;
  }
  const [wx, wy] = toWorld(lon, lat);
  view.camera.worldX = wx;
  view.camera.worldY = wy;
  if (typeof zoom === "number") view.camera.zoom = zoom;
}

function projectShape(coords) {
  const points = new Float64Array(coords.length * 2);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (let i = 0; i < coords.length; i++) {
    const [x, y] = toWorld(coords[i][0], coords[i][1]);
    points[i * 2] = x;
    points[i * 2 + 1] = y;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return { points, bounds: [minX, minY, maxX, maxY] };
}

// ── painting ────────────────────────────────────────────────────────────────

function paint() {
  if (!state.origin_world || !view.camera || !view.renderer) return;
  if (state.pendingCenter) {
    const { lon, lat, zoom } = state.pendingCenter;
    state.pendingCenter = null;
    centerOn(lon, lat, zoom);
  }
  noticeCameraMoved();
  if (state.drive) stepDrive();

  const now = performance.now();
  if (now - lastPaint < OVERLAY_MIN_MS) return;
  lastPaint = now;

  sizeOverlay(view.renderer.cssWidth, view.renderer.cssHeight);
  const t = makeTransform();
  ctx.setTransform(sized.dpr, 0, 0, sized.dpr, 0, 0);
  ctx.clearRect(0, 0, t.w, t.h);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  if (state.layers.roads) paintNetwork(t);
  if (state.layers.traffic) paintTraffic(t);
  if (state.layers.conditions) paintConditions(t);
  paintRoutes(t);
  paintMarkers(t);
}

function paintNetwork(t) {
  ctx.strokeStyle = NETWORK_COLOR;
  ctx.lineWidth = 1;
  for (const road of drawable.roads.values()) {
    if (!inView(road.bounds, t)) continue;
    strokePolyline(road.points, t);
  }
}

function paintTraffic(t) {
  for (const [roadId, reading] of drawable.traffic) {
    const road = drawable.roads.get(roadId);
    if (!road || !inView(road.bounds, t)) continue;
    ctx.strokeStyle = state.levelColor.get(reading.level) || "#9aa3ad";
    ctx.lineWidth = ROAD_WIDTH[road.klass] || DEFAULT_ROAD_WIDTH;
    ctx.globalAlpha = 0.85;
    strokePolyline(road.points, t);
  }
  ctx.globalAlpha = 1;
}

function paintConditions(t) {
  for (const condition of drawable.conditions) {
    if (!inView(condition.bounds, t)) continue;
    const color = condition.blocking ? BLOCKING_COLOR : CONDITION_COLOR;
    if (condition.points.length === 2) {
      const x = condition.points[0] * t.scale + t.ox;
      const y = condition.points[1] * t.scale + t.oy;
      ctx.beginPath();
      ctx.arc(x, y, 9, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.22;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
      continue;
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 7;
    ctx.setLineDash([10, 7]);
    strokePolyline(condition.points, t);
    ctx.setLineDash([]);
  }
}

function paintRoutes(t) {
  if (drawable.freeRoute && state.compare) {
    ctx.strokeStyle = "rgba(255,255,255,0.8)";
    ctx.lineWidth = 8;
    strokePolyline(drawable.freeRoute.points, t);
    ctx.strokeStyle = FREEFLOW_COLOR;
    ctx.lineWidth = 4;
    ctx.setLineDash([11, 8]);
    strokePolyline(drawable.freeRoute.points, t);
    ctx.setLineDash([]);
  }
  if (drawable.route) {
    ctx.strokeStyle = "rgba(255,255,255,0.9)";
    ctx.lineWidth = 13;
    strokePolyline(drawable.route.points, t);
    ctx.strokeStyle = ROUTE_COLOR;
    ctx.lineWidth = 7;
    strokePolyline(drawable.route.points, t);
  }
}

function paintMarkers(t) {
  if (state.origin) {
    const [x, y] = placeLonLat(state.origin, t);
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(x, y, 6, 0, Math.PI * 2);
    ctx.fillStyle = ORIGIN_COLOR;
    ctx.fill();
  }
  if (state.destination) {
    const [x, y] = placeLonLat(state.destination, t);
    pin(x, y, DESTINATION_COLOR);
  }
  if (state.drive) {
    const [x, y] = placeLonLat(state.drive.position, t);
    arrow(x, y, state.drive.bearing);
  }
}

function placeLonLat(lonlat, t) {
  const [wx, wy] = toWorld(lonlat[0], lonlat[1]);
  return [wx * t.scale + t.ox, wy * t.scale + t.oy];
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
  ctx.lineTo(x - 8, y - 18);
  ctx.lineTo(x + 8, y - 18);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(x, y - 23, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = "#fff";
  ctx.stroke();
}

function arrow(x, y, bearing) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(((bearing - 90) * Math.PI) / 180);
  ctx.beginPath();
  ctx.moveTo(15, 0);
  ctx.lineTo(-9, -10);
  ctx.lineTo(-4, 0);
  ctx.lineTo(-9, 10);
  ctx.closePath();
  ctx.fillStyle = ROUTE_COLOR;
  ctx.fill();
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = "#fff";
  ctx.stroke();
  ctx.restore();
}

function inView(bounds, t) {
  const x0 = bounds[0] * t.scale + t.ox;
  const y0 = bounds[1] * t.scale + t.oy;
  const x1 = bounds[2] * t.scale + t.ox;
  const y1 = bounds[3] * t.scale + t.oy;
  return !(x1 < -40 || y1 < -40 || x0 > t.w + 40 || y0 > t.h + 40);
}

// ── talking to the server ───────────────────────────────────────────────────

async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = new Error(payload.error || `${path} -> ${response.status}`);
    err.status = response.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

let cameraSignature = "";
let areaTimer = 0;

function noticeCameraMoved() {
  const { camera } = view;
  const signature = `${camera.worldX.toFixed(4)},${camera.worldY.toFixed(4)},${camera.zoom.toFixed(2)}`;
  if (signature === cameraSignature) return;
  cameraSignature = signature;
  clearTimeout(areaTimer);
  areaTimer = setTimeout(refreshArea, AREA_IDLE_MS);
}

async function refreshArea(force = false) {
  // Not while a route is being computed or a drive is running: both move the
  // camera, and a new area is a cold fetch on the server that would queue
  // behind the thing the user is actually waiting for.
  if (!view.camera || state.areaBusy || state.routing) return;
  if (state.drive && !force) return;

  const raw = viewportBBox();
  const span = Math.max(raw[2] - raw[0], raw[3] - raw[1]);
  state.areaTooWide = span > MAX_OVERLAY_SPAN_DEG;
  if (state.areaTooWide) {
    renderTrafficMeta();
    return;
  }

  const bbox = snapBBox(raw);
  const key = bbox.join(",");
  if (!force && key === state.areaKey) return;
  state.areaKey = key;
  state.areaBusy = true;
  const query = bbox.join(",");
  if (!state.warmedAreas.has(key)) {
    setStatus("Fetching the road network for this area…");
  }

  try {
    // Deliberately not /mapdata/graph. That endpoint *builds* the graph for
    // whatever box it is given, and the viewport box is not the box a route
    // needs -- asking here would build a second graph nobody searches. The
    // summary is fetched after a route instead, for the area the route
    // actually used, where it is already built and costs nothing.
    const [roads, traffic, conditions] = await Promise.all([
      api(`/api/v1/mapdata/roads?bbox=${query}`),
      api(`/api/v1/traffic?bbox=${query}`),
      api(`/api/v1/roadstate?bbox=${query}`),
    ]);

    drawable.roads.clear();
    for (const feature of roads.features || []) {
      const shape = projectShape(feature.geometry.coordinates);
      drawable.roads.set(feature.properties.id, {
        ...shape,
        klass: feature.properties.road_class,
        name: feature.properties.name,
      });
    }

    drawable.traffic.clear();
    for (const reading of traffic.roads || []) {
      drawable.traffic.set(reading.road_id, reading);
    }
    state.trafficMeta = traffic;

    state.conditions = [...(conditions.conditions || [])];
    drawable.conditions = state.conditions.map((condition) => ({
      ...projectShape(condition.geometry),
      blocking: condition.blocking,
      kind: condition.kind,
    }));

    state.warmedAreas.add(key);
    syncMyClosures();
    renderTrafficMeta();
    renderServer();
  } catch (err) {
    toast(`Could not load the area: ${err.message}`, true);
  } finally {
    state.areaBusy = false;
    setStatus(null);
  }
}

async function computeRoute() {
  if (!state.origin || !state.destination) return;
  stopDrive();
  state.routing = true;
  setBusy(true, "Routing…");

  // The first request reaching an area the server has not seen fetches it from
  // OpenStreetMap and builds a graph: tens of seconds. Every later one is
  // milliseconds. Saying so is the whole difference between "slow" and
  // "broken".
  const cold = !state.warmedAreas.has(state.areaKey);
  const slowTimer = setTimeout(
    () =>
      setStatus(
        "Still working — the server is fetching this area from OpenStreetMap " +
          "and building its graph. First time only."
      ),
    cold ? 1200 : 6000
  );

  const body = {
    origin: state.origin,
    destination: state.destination,
    profile: state.profile,
    cost_mode: state.costMode,
  };
  try {
    // Both at once. They are two searches over the same graph, and asking in
    // sequence would pay any cold-start cost twice.
    const [priced, free] = await Promise.all([
      api("/api/v1/route", { method: "POST", body: { ...body, use_traffic: true } }),
      state.compare
        ? api("/api/v1/route", { method: "POST", body: { ...body, use_traffic: false } }).catch(() => null)
        : Promise.resolve(null),
    ]);

    state.route = priced;
    drawable.route = projectShape(priced.geometry.coordinates);
    state.freeRoute = free;
    drawable.freeRoute = free ? projectShape(free.geometry.coordinates) : null;

    renderResult();
    state.routing = false;
    // The graph for the routed area exists now, so its summary is free.
    readGraphSummary(priced.meta.area);
    // The server refreshed traffic for that area too; pick that up.
    refreshArea(true);
  } catch (err) {
    state.route = null;
    state.freeRoute = null;
    drawable.route = null;
    drawable.freeRoute = null;
    renderResult();
    const known = {
      400: "The server could not use that request.",
      404: "Nothing legal connects those two points.",
      502: "An upstream source is unreadable.",
      503: "An upstream source is unavailable — try again shortly.",
    };
    toast(`${known[err.status] || "Routing failed."} ${err.message}`, true);
  } finally {
    clearTimeout(slowTimer);
    state.routing = false;
    setBusy(false);
    setStatus(null);
  }
}

/** The graph summary for an area the server has already built. */
async function readGraphSummary(area) {
  if (!Array.isArray(area)) return;
  try {
    state.graph = await api(`/api/v1/mapdata/graph?bbox=${area.join(",")}`);
    renderServer();
  } catch {
    // Informational only; a missing summary is not worth telling anyone about.
  }
}

async function closeRoadAt(lon, lat) {
  const id = `${DEMO_CLOSURE_TAG}${Date.now()}`;
  setBusy(true, "Reporting…");
  // The server derives the report's own area from its geometry, and that area
  // is usually one it has never seen -- so the first closure in a district
  // pays a cold road fetch before anything else happens.
  setStatus("Recording the closure, attaching it to the network, re-routing…");
  try {
    const result = await api("/api/v1/ingest/reports", {
      method: "POST",
      body: {
        reports: [
          {
            id,
            kind: "closure",
            severity: "critical",
            blocking: true,
            description: "Road closed (reported from the demo)",
            geometry: [[lon, lat]],
            reported_at: new Date().toISOString(),
          },
        ],
      },
    });
    if (!result.accepted) {
      // accept_reports answers with counts plus up to ten reasons, so a
      // client can find out its field names are wrong.
      toast(`The server refused the report: ${(result.reasons || []).join("; ") || "no reason given"}`, true);
      return;
    }
    // The server assigns the condition's real id -- it prefixes the report
    // source -- and answers the report with counts rather than ids. So the
    // id is discovered from /roadstate rather than assumed here.
    await refreshArea(true);
    toast("Closure recorded. Re-routing around it…");
    if (state.route) await computeRoute();
  } catch (err) {
    toast(`Could not report the closure: ${err.message}`, true);
  } finally {
    setBusy(false);
    setClosing(false);
  }
}

/** Which of the conditions in view this page put there. */
function syncMyClosures() {
  state.myClosures = state.conditions
    .map((condition) => condition.id)
    .filter((id) => id.includes(DEMO_CLOSURE_TAG));
  const button = el("nav-reopen");
  if (button) button.disabled = state.myClosures.length === 0;
}

async function reopenAll() {
  const ids = [...state.myClosures];
  if (!ids.length) return;
  setBusy(true, "Withdrawing…");
  try {
    for (const id of ids) {
      await fetch(`/api/v1/roadstate/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {});
    }
    await refreshArea(true);
    toast(`${ids.length} closure${ids.length === 1 ? "" : "s"} withdrawn.`);
    if (state.route) await computeRoute();
  } finally {
    setBusy(false);
  }
}

// ── driving ─────────────────────────────────────────────────────────────────

function startDrive() {
  const route = state.route;
  if (!route || route.duration_s <= 0) return;
  const coords = route.geometry.coordinates;
  const legs = [];
  let total = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const d = haversine(coords[i], coords[i + 1]);
    legs.push(d);
    total += d;
  }
  state.drive = {
    coords,
    legs,
    total,
    speedMps: route.distance_m / route.duration_s,
    startedAt: performance.now(),
    position: coords[0],
    bearing: bearingOf(coords[0], coords[1] || coords[0]),
    travelled: 0,
  };
  document.getElementById("nav-guidance").hidden = false;
  document.getElementById("nav-drive").textContent = "Restart drive";
  centerOn(coords[0][0], coords[0][1]);
}

function stopDrive() {
  state.drive = null;
  document.getElementById("nav-guidance").hidden = true;
  const button = document.getElementById("nav-drive");
  if (button) button.textContent = "Start drive";
  for (const li of document.querySelectorAll(".nav-step-active")) {
    li.classList.remove("nav-step-active");
  }
}

function stepDrive() {
  const drive = state.drive;
  const elapsed = ((performance.now() - drive.startedAt) / 1000) * DRIVE_TIME_SCALE;
  const travelled = Math.min(elapsed * drive.speedMps, drive.total);
  drive.travelled = travelled;

  let walked = 0;
  for (let i = 0; i < drive.legs.length; i++) {
    if (walked + drive.legs[i] >= travelled) {
      const t = drive.legs[i] > 0 ? (travelled - walked) / drive.legs[i] : 0;
      const a = drive.coords[i];
      const b = drive.coords[i + 1];
      drive.position = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      drive.bearing = bearingOf(a, b);
      break;
    }
    walked += drive.legs[i];
  }
  if (travelled >= drive.total) {
    drive.position = drive.coords[drive.coords.length - 1];
    renderGuidance(true);
    stopDrive();
    toast("Arrived.");
    return;
  }
  centerOn(drive.position[0], drive.position[1]);
  renderGuidance(false);
}

function haversine(a, b) {
  const R = 6371008.8;
  const [lon1, lat1] = a.map((v) => (v * Math.PI) / 180);
  const [lon2, lat2] = b.map((v) => (v * Math.PI) / 180);
  const h =
    Math.sin((lat2 - lat1) / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function bearingOf(a, b) {
  const [lon1, lat1] = a.map((v) => (v * Math.PI) / 180);
  const [lon2, lat2] = b.map((v) => (v * Math.PI) / 180);
  const dlon = lon2 - lon1;
  const y = Math.sin(dlon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dlon);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

// ── rendering the panel ─────────────────────────────────────────────────────

const el = (id) => document.getElementById(id);

function duration(seconds) {
  if (seconds == null) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h) return `${h} h ${String(m).padStart(2, "0")}`;
  return `${m} min`;
}

function shortDuration(seconds) {
  const total = Math.round(Math.abs(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m ? `${m} min ${String(s).padStart(2, "0")} s` : `${s} s`;
}

function distance(metres) {
  if (metres == null) return "—";
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km` : `${Math.round(metres)} m`;
}

function coordText(point) {
  return point ? `${point[1].toFixed(5)}, ${point[0].toFixed(5)}` : "click the map";
}

function renderEndpoints() {
  el("nav-origin-text").textContent = coordText(state.origin);
  el("nav-destination-text").textContent = coordText(state.destination);
  el("nav-pick-origin").classList.toggle("nav-picking", state.picking === "origin" && !state.closing);
  el("nav-pick-destination").classList.toggle("nav-picking", state.picking === "destination" && !state.closing);
  const ready = Boolean(state.origin && state.destination);
  el("nav-go").disabled = !ready;
  el("nav-swap").disabled = !ready;
  el("nav-clear").disabled = !(state.origin || state.destination);
}

function renderResult() {
  const route = state.route;
  el("nav-result").hidden = !route;
  el("nav-steps-section").hidden = !route;
  if (!route) return;

  el("nav-duration").textContent = duration(route.duration_s);
  el("nav-distance").textContent = distance(route.distance_m);
  el("nav-profile-echo").textContent = `${route.profile} · ${route.cost_mode}`;

  const arrival = new Date(Date.now() + route.duration_s * 1000);
  el("nav-arrival").textContent = `arrive ${arrival.getHours()}:${String(arrival.getMinutes()).padStart(2, "0")}`;

  const free = state.freeRoute;
  const delta = el("nav-delta");
  if (free && route.meta.traffic_used) {
    const lost = route.duration_s - free.duration_s;
    const percent = free.duration_s > 0 ? (lost / free.duration_s) * 100 : 0;
    const sameRoad = JSON.stringify(free.segments) === JSON.stringify(route.segments);
    delta.innerHTML = lost > 1
      ? `Traffic is costing <b>${shortDuration(lost)}</b> (+${percent.toFixed(0)}%). ` +
        `Free-flow would be ${duration(free.duration_s)} — ` +
        `${sameRoad ? "same road, priced differently" : "the server picked a different road because of it"}.`
      : `Traffic is not slowing this trip. Free-flow is ${duration(free.duration_s)}.`;
  } else if (!route.meta.traffic_used) {
    delta.textContent = "Traffic pricing is off on this server, so this is a free-flow route.";
  } else {
    delta.textContent = "";
  }

  el("nav-steps").innerHTML = route.steps
    .map(
      (step, index) =>
        `<li data-step="${index}">` +
        `<span class="nav-step-icon">${MANEUVER_ICON[step.maneuver] || "↑"}</span>` +
        `<span class="nav-step-name">${step.name ? escapeHtml(step.name) : '<span class="nav-unnamed">unnamed road</span>'}</span>` +
        `<span class="nav-step-dist">${distance(step.distance_m)}</span>` +
        `</li>`
    )
    .join("");
}

function renderGuidance(arrived) {
  const drive = state.drive;
  if (!drive || !state.route) return;
  const steps = state.route.steps;

  let covered = 0;
  let index = steps.length - 1;
  for (let i = 0; i < steps.length; i++) {
    if (covered + steps[i].distance_m > drive.travelled) {
      index = i;
      break;
    }
    covered += steps[i].distance_m;
  }
  const remainingInStep = Math.max(0, covered + steps[index].distance_m - drive.travelled);
  const next = steps[Math.min(index + 1, steps.length - 1)];

  el("nav-next-icon").innerHTML = MANEUVER_ICON[next.maneuver] || "↑";
  el("nav-next-distance").textContent = arrived ? "" : `in ${distance(remainingInStep)}`;
  el("nav-next-name").textContent = arrived
    ? "Arrived"
    : next.maneuver === "arrive"
      ? "arrive at destination"
      : `${next.maneuver.replace(/_/g, " ")} onto ${next.name || "an unnamed road"}`;

  const left = drive.total - drive.travelled;
  const etaS = drive.speedMps > 0 ? left / drive.speedMps : 0;
  el("nav-progress").textContent =
    `${distance(drive.travelled)} of ${distance(drive.total)} · ` +
    `${(drive.speedMps * 3.6).toFixed(0)} km/h · ${duration(etaS)} left · clock ×${DRIVE_TIME_SCALE}`;

  for (const li of document.querySelectorAll("#nav-steps li")) {
    li.classList.toggle("nav-step-active", Number(li.dataset.step) === index);
  }
}

function renderTrafficMeta() {
  const node = el("nav-traffic-meta");
  if (state.areaTooWide) {
    node.innerHTML = "Zoom in to load traffic and the road network for the view.";
    node.classList.add("nav-warn");
    return;
  }
  node.classList.remove("nav-warn");
  const meta = state.trafficMeta;
  if (!meta) {
    node.textContent = "";
    return;
  }
  const badge = meta.simulated
    ? '<span class="nav-badge nav-badge-sim">modelled</span>'
    : '<span class="nav-badge nav-badge-measured">measured</span>';
  const failures = (meta.failures || []).map((f) => f.source).join(", ");
  node.innerHTML =
    `${badge} ${(meta.roads || []).length.toLocaleString()} roads from ` +
    `${(meta.sources || []).join(", ") || "no source"}` +
    (failures ? ` · <span class="nav-warn">failed: ${escapeHtml(failures)}</span>` : "") +
    (meta.simulated
      ? "<br>No free live traffic feed covers this area, so the server models it — and says so on every reading."
      : "");
}

function renderServer() {
  const graph = state.graph;
  const info = state.info;
  const rows = [];
  if (info) rows.push(["link", `${info.link.mode}`]);
  if (graph) {
    rows.push(["graph nodes", (graph.nodes || 0).toLocaleString()]);
    rows.push(["graph edges", (graph.edges || 0).toLocaleString()]);
    rows.push(["source ways", (graph.sources || 0).toLocaleString()]);
  }
  const conditions = state.conditions.length;
  rows.push(["conditions", `${conditions} (${state.conditions.filter((c) => c.blocking).length} blocking)`]);
  el("nav-server").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/** The line under the panel title: what the page is waiting for, if anything. */
function setStatus(message) {
  const node = el("nav-link");
  if (!node) return;
  node.textContent = message || state.linkLabel;
  node.classList.toggle("nav-working", Boolean(message));
}

let toastTimer = 0;
function toast(message, bad = false) {
  const node = el("nav-toast");
  node.textContent = message;
  node.classList.toggle("nav-bad", bad);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.hidden = true;
  }, bad ? 7000 : 3800);
}

function setBusy(busy, label) {
  const go = el("nav-go");
  go.disabled = busy || !(state.origin && state.destination);
  go.textContent = busy ? label || "Working…" : "Get route";
}

function setClosing(on) {
  state.closing = on;
  el("nav-close-road").classList.toggle("nav-on", on);
  el("nav-close-road").textContent = on ? "Click a road…" : "Close a road";
  renderEndpoints();
}

// ── input ───────────────────────────────────────────────────────────────────

function wirePanel() {
  el("nav-collapse").addEventListener("click", () => {
    el("nav-panel").classList.toggle("nav-collapsed");
  });

  for (const id of ["nav-pick-origin", "nav-pick-destination"]) {
    el(id).addEventListener("click", () => {
      setClosing(false);
      state.picking = el(id).dataset.pick;
      renderEndpoints();
    });
  }

  el("nav-go").addEventListener("click", computeRoute);
  el("nav-clear").addEventListener("click", () => {
    state.origin = null;
    state.destination = null;
    state.route = null;
    state.freeRoute = null;
    drawable.route = null;
    drawable.freeRoute = null;
    state.picking = "origin";
    stopDrive();
    renderEndpoints();
    renderResult();
  });
  el("nav-swap").addEventListener("click", () => {
    [state.origin, state.destination] = [state.destination, state.origin];
    renderEndpoints();
    if (state.route) computeRoute();
  });

  el("nav-profile").addEventListener("change", (ev) => {
    state.profile = ev.target.value;
    if (state.route) computeRoute();
  });
  el("nav-mode").addEventListener("change", (ev) => {
    state.costMode = ev.target.value;
    if (state.route) computeRoute();
  });

  el("nav-compare").addEventListener("click", () => {
    state.compare = !state.compare;
    el("nav-compare").classList.toggle("nav-on", state.compare);
    if (state.route) computeRoute();
  });

  el("nav-drive").addEventListener("click", startDrive);
  el("nav-stop").addEventListener("click", stopDrive);

  el("nav-layers").addEventListener("click", (ev) => {
    const layer = ev.target.dataset.layer;
    if (!layer) return;
    state.layers[layer] = !state.layers[layer];
    ev.target.classList.toggle("nav-on", state.layers[layer]);
  });

  el("nav-close-road").addEventListener("click", () => setClosing(!state.closing));
  el("nav-reopen").addEventListener("click", reopenAll);

  el("nav-steps").addEventListener("click", (ev) => {
    const li = ev.target.closest("li");
    if (!li || !state.route) return;
    const step = state.route.steps[Number(li.dataset.step)];
    const coords = step.geometry.coordinates;
    if (coords && coords.length) centerOn(coords[0][0], coords[0][1], Math.max(view.camera.zoom, 17));
  });
}

function wirePicking() {
  const canvas = document.getElementById("gl");
  const active = new Set();
  let candidate = null;
  let lastPick = 0;

  canvas.addEventListener("pointerdown", (ev) => {
    active.add(ev.pointerId);
    candidate = active.size === 1
      ? { id: ev.pointerId, x: ev.clientX, y: ev.clientY, t: performance.now() }
      : null;
  });

  const finish = (ev) => {
    active.delete(ev.pointerId);
    if (!candidate || candidate.id !== ev.pointerId) return;
    const { x, y, t } = candidate;
    candidate = null;
    if (ev.type !== "pointerup") return;
    // A drag is a pan and a long press is not a click; both belong to the map.
    if (Math.hypot(ev.clientX - x, ev.clientY - y) > 6 || performance.now() - t > 700) return;
    // The map zooms on double-click; the second click must not re-pick.
    if (performance.now() - lastPick < 350) return;
    lastPick = performance.now();
    handlePick(ev.clientX, ev.clientY);
  };

  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", finish);
}

function handlePick(px, py) {
  if (!view.camera || !state.origin_world) return;
  const [lon, lat] = screenToLonLat(px, py);

  if (state.closing) {
    closeRoadAt(lon, lat);
    return;
  }

  if (state.picking === "origin") {
    state.origin = [lon, lat];
    state.picking = "destination";
  } else {
    state.destination = [lon, lat];
    state.picking = "origin";
  }
  renderEndpoints();
  if (state.origin && state.destination) computeRoute();
}

// ── boot ────────────────────────────────────────────────────────────────────

async function start() {
  const [config, info, levels] = await Promise.all([
    api("/api/config"),
    api("/api/demo/info"),
    api("/api/v1/traffic/levels"),
  ]);

  // The same origin app.js chooses, from the same endpoint, so the overlay and
  // the basemap agree on where a coordinate is by construction.
  state.origin_world = lonLatToWorldZ0(config.map.center[0], config.map.center[1]);
  state.info = info;
  state.levels = levels.levels || [];
  for (const level of state.levels) state.levelColor.set(level.slug, level.color);

  state.linkLabel =
    info.link.mode === "http"
      ? `API over HTTP · ${info.link.target}`
      : "API in-process · server/api";
  setStatus(null);

  el("nav-legend").innerHTML = state.levels
    .map((level) => `<span><i style="background:${level.color}"></i>${level.label}</span>`)
    .join("");

  el("nav-credit").innerHTML =
    'Roads &amp; modelled traffic from &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
    "contributors (ODbL), via Overpass. Measured traffic, where a feed covers the area, " +
    'by <a href="https://www.digitraffic.fi/en/">Fintraffic</a> (CC BY 4.0).';

  wirePanel();
  wirePicking();
  renderEndpoints();
  renderServer();

  // Open on the area the server was configured for.
  const [west, south, east, north] = info.default_area.split(",").map(Number);
  // Zoom 16, not 15: the box the page then asks for is a quarter of the
  // area, and the first one is the only one that is ever slow.
  centerOn((west + east) / 2, (south + north) / 2, 16);
  toast("Click the map for a start point, then again for a destination.");

  // Ask for the configured area straight away. It is almost certainly where
  // the first click lands, and paying its cold start now -- while the panel is
  // still being read -- beats paying it after a click that looks like it did
  // nothing at all.
  refreshArea(true).catch(() => {});
}

start().catch((err) => {
  console.error("[demo] failed to start:", err);
  const node = document.getElementById("nav-link");
  if (node) node.textContent = `failed to start: ${err.message}`;
});
