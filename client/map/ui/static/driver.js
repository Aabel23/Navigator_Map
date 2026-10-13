// The driver's side of the page: where am I, what is this street called,
// how do I get there, and -- if they agree -- telling the server how fast
// the road is moving.
//
// Everything here talks to the navigation server through this page's own
// origin (`/api/v1/...`, proxied by `ui/view.py`), so one HTTPS tunnel to this
// page is all a phone needs. The map renderer knows nothing about any of it:
// this file reads the camera and moves it, and draws through the overlay.

import { GpsTracker, ProbeUploader, haversineM } from "./gps.js";

export function startDriver({ cfg, camera, overlay, ui }) {
  const api = cfg.driver.api_base;
  const state = {
    fix: null,
    follow: false,
    lastAddressAt: 0,
    lastAddressFix: null,
    addressPending: false,
    destination: null,
    routeSeq: 0,
  };

  // -- probes: anonymous, opt-out, remembered per device ------------------------
  const uploader = new ProbeUploader({
    url: `${api}/ingest/probes`,
    deviceId: deviceId(),
    flushMs: cfg.driver.probe_flush_ms,
    minIntervalMs: cfg.driver.probe_min_interval_ms,
  });
  uploader.enabled = readPref("share-probes", cfg.driver.probes_enabled);
  ui.shareProbes.checked = uploader.enabled;
  ui.shareProbes.addEventListener("change", () => {
    uploader.enabled = ui.shareProbes.checked;
    writePref("share-probes", uploader.enabled);
  });
  uploader.start();
  window.addEventListener("pagehide", () => uploader.flush());

  // -- GPS ------------------------------------------------------------------------
  const tracker = new GpsTracker({
    maxAccuracyM: cfg.driver.max_accuracy_m,
    onFix: onFix,
    onError: (message) => {
      ui.status.textContent = message;
      ui.status.hidden = false;
      if (!tracker.running) setLocateState("off");
    },
  });

  function onFix(fix) {
    const first = state.fix === null;
    state.fix = fix;
    overlay.setFix(fix);
    ui.status.hidden = true;
    setLocateState(state.follow ? "follow" : "on");
    if (first) {
      setFollow(true);
      camera.zoom = Math.max(camera.zoom, cfg.driver.follow_zoom);
    }
    if (state.follow) centreOn(fix);
    renderFixMeta();
    maybeLookUpAddress(fix);
    uploader.add(fix);
  }

  function startGps() {
    ui.address.textContent = "Đang tìm vị trí…";
    if (tracker.start()) setLocateState("searching");
  }

  ui.locate.addEventListener("click", () => {
    if (!tracker.running) {
      startGps();
      setFollow(true);
      return;
    }
    if (state.fix) {
      setFollow(true);
      centreOn(state.fix);
    }
  });

  // A person who has already said yes should not have to say it again on every
  // visit. Asking for a permission that has not been granted waits for a tap.
  navigator.permissions
    ?.query({ name: "geolocation" })
    .then((status) => {
      if (status.state === "granted") startGps();
    })
    .catch(() => {});

  function centreOn(fix) {
    const w = overlay.toWorld(fix.lon, fix.lat);
    camera.worldX = w.x;
    camera.worldY = w.y;
  }

  function setFollow(on) {
    state.follow = on;
    if (tracker.running) setLocateState(on && state.fix ? "follow" : state.fix ? "on" : "searching");
  }

  function setLocateState(name) {
    ui.locate.dataset.state = name;
  }

  function renderFixMeta() {
    const fix = state.fix;
    if (!fix) return;
    const parts = [];
    if (fix.accuracy !== null) parts.push(`±${Math.round(fix.accuracy)} m`);
    if (fix.speedKph !== null) parts.push(`${fix.derived ? "≈" : ""}${Math.round(fix.speedKph)} km/h`);
    parts.push(new Date(fix.timestamp).toLocaleTimeString("vi-VN"));
    if (uploader.enabled && uploader.stats.accepted > 0) parts.push(`đã gửi ${uploader.stats.accepted}`);
    ui.fixMeta.textContent = parts.join(" · ");
  }

  // -- address: only when the driver has actually moved ---------------------------
  async function maybeLookUpAddress(fix) {
    if (state.addressPending) return;
    const now = Date.now();
    const moved = state.lastAddressFix ? haversineM(state.lastAddressFix, fix) : Infinity;
    if (moved < cfg.driver.address_min_move_m) return;
    if (now - state.lastAddressAt < cfg.driver.address_min_interval_ms) return;

    state.addressPending = true;
    state.lastAddressAt = now;
    try {
      const body = await getJson(`${api}/mapdata/address?point=${fix.lon.toFixed(6)},${fix.lat.toFixed(6)}`);
      state.lastAddressFix = fix;
      ui.address.textContent = body.label;
      ui.address.title = body.display_name || body.label;
    } catch (err) {
      if (!state.lastAddressFix) ui.address.textContent = `${fix.lat.toFixed(5)}, ${fix.lon.toFixed(5)}`;
      console.warn("[driver] address lookup failed:", err.message);
    } finally {
      state.addressPending = false;
    }
  }

  // -- routing: from where the driver is to where they tapped ---------------------
  async function routeTo(point) {
    state.destination = point;
    overlay.setDestination(point);
    ui.trip.hidden = false;
    if (!state.fix) {
      overlay.setRoute(null);
      ui.tripSummary.textContent = "Cần vị trí GPS để tìm đường. Bấm nút định vị trước.";
      return;
    }
    const seq = ++state.routeSeq;
    ui.tripSummary.textContent = "Đang tìm đường…";
    try {
      const route = await postJson(`${api}/route`, {
        origin: [state.fix.lon, state.fix.lat],
        destination: [point.lon, point.lat],
      });
      if (seq !== state.routeSeq) return; // a newer tap has already replaced it
      overlay.setRoute(route.geometry.coordinates);
      ui.tripSummary.textContent = summarise(route);
    } catch (err) {
      if (seq !== state.routeSeq) return;
      overlay.setRoute(null);
      ui.tripSummary.textContent = `Không tìm được đường: ${err.message}`;
    }
  }

  ui.tripClear.addEventListener("click", () => {
    state.routeSeq += 1;
    state.destination = null;
    overlay.setRoute(null);
    overlay.setDestination(null);
    ui.trip.hidden = true;
  });

  return {
    routeTo,
    /** The person moved the map themselves: stop dragging it back. */
    userMovedCamera() {
      if (state.follow) setFollow(false);
    },
    hudLines() {
      const f = state.fix;
      return [
        `gps ${tracker.running ? (f ? `${f.lat.toFixed(5)}, ${f.lon.toFixed(5)} ±${Math.round(f.accuracy ?? 0)}m` : "searching") : "off"}` +
          `${tracker.rejected ? `  (${tracker.rejected} imprecise)` : ""}`,
        `probes ${uploader.enabled ? `sent ${uploader.stats.sent} accepted ${uploader.stats.accepted} queued ${uploader.queue.length} failed ${uploader.stats.failures}` : "off"}`,
      ];
    },
  };
}

function summarise(route) {
  const km = route.distance_m / 1000;
  const minutes = Math.max(1, Math.round(route.duration_s / 60));
  const arrive = new Date(Date.now() + route.duration_s * 1000).toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });
  const via = [...new Set((route.steps || []).map((s) => s.name).filter(Boolean))].slice(0, 2);
  return (
    `${km < 1 ? `${Math.round(route.distance_m)} m` : `${km.toFixed(1)} km`} · ${minutes} phút · đến lúc ${arrive}` +
    (via.length ? `\nqua ${via.join(", ")}` : "")
  );
}

async function getJson(url) {
  return readJson(await fetch(url));
}

async function postJson(url, body) {
  return readJson(
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

async function readJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.status === "error") {
    throw new Error(body.error || `HTTP ${response.status}`);
  }
  return body;
}

// An opaque random id, so the server can stop one phone dominating a road's
// average. It names a browser, not a person, and never leaves this origin
// except inside a probe.
function deviceId() {
  const existing = readPref("device-id", null);
  if (existing) return existing;
  const made = (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).replace(/[^a-z0-9-]/gi, "");
  writePref("device-id", made);
  return made;
}

function readPref(name, fallback) {
  try {
    const raw = localStorage.getItem(`nav.${name}`);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writePref(name, value) {
  try {
    localStorage.setItem(`nav.${name}`, JSON.stringify(value));
  } catch {
    // Private mode or blocked storage: the preference lasts this page load.
  }
}
