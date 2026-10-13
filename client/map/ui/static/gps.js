// The driver's real position, from the device's own receiver.
//
// The browser's Geolocation API is the only door to it: on a phone that is the
// GNSS chip (fused with Wi-Fi and cell towers), on a laptop it is usually
// Wi-Fi alone. Either way it arrives as a `GeolocationPosition`, and this file
// is where that shape is turned into the project's -- longitude first, speed
// in km/h, a timestamp in milliseconds -- so nothing downstream ever sees the
// browser's object.
//
// Two things the browser enforces and this file reports rather than hides:
// the page must be a secure context (HTTPS, or http://localhost), and the
// person must grant permission. A phone on plain http://192.168.x.x gets
// neither a prompt nor an error from the API -- just silence -- so the check
// is made up front and said out loud.
//
// The pure functions are exported so `tests/test_gps.mjs` can check them
// without a browser.

const EARTH_RADIUS_M = 6371008.8;

/** Great-circle distance between two `{lon, lat}` points, in metres. */
export function haversineM(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Degrees from north, 0..360, from `a` towards `b`. */
export function bearingDeg(a, b) {
  const rad = Math.PI / 180;
  const y = Math.sin((b.lon - a.lon) * rad) * Math.cos(b.lat * rad);
  const x =
    Math.cos(a.lat * rad) * Math.sin(b.lat * rad) -
    Math.sin(a.lat * rad) * Math.cos(b.lat * rad) * Math.cos((b.lon - a.lon) * rad);
  return ((Math.atan2(y, x) / rad) + 360) % 360;
}

/**
 * A `GeolocationPosition` (or anything shaped like one) as a fix.
 *
 * Speed and heading are `null` when the device does not report them, which
 * most do not while standing still and many laptops never do. They are not
 * invented here; `deriveMotion` fills them from consecutive fixes, and says so.
 */
export function fixFromPosition(position) {
  const c = position.coords;
  const finite = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const speedMs = finite(c.speed);
  return {
    lon: c.longitude,
    lat: c.latitude,
    accuracy: finite(c.accuracy),
    speedKph: speedMs === null ? null : speedMs * 3.6,
    heading: finite(c.heading),
    timestamp: finite(position.timestamp) ?? Date.now(),
    derived: false,
  };
}

/** Whether a fix is precise enough to show and use. */
export function isUsable(fix, maxAccuracyM) {
  if (!Number.isFinite(fix.lon) || !Number.isFinite(fix.lat)) return false;
  if (Math.abs(fix.lon) > 180 || Math.abs(fix.lat) > 90) return false;
  return fix.accuracy === null || fix.accuracy <= maxAccuracyM;
}

/**
 * Fill a missing speed or heading from the previous fix.
 *
 * Only when the two are far enough apart, in metres and in time, that the
 * difference is movement rather than the receiver's own wander -- a phone on
 * a table reports positions a few metres apart every second, and dividing
 * that by one second is a car doing 15 km/h through a kitchen.
 */
export function deriveMotion(fix, previous) {
  if (!previous || (fix.speedKph !== null && fix.heading !== null)) return fix;
  const dt = (fix.timestamp - previous.timestamp) / 1000;
  if (dt <= 0 || dt > 30) return fix;
  const distance = haversineM(previous, fix);
  const noise = Math.max(fix.accuracy ?? 10, previous.accuracy ?? 10);
  if (distance < noise) return { ...fix, speedKph: fix.speedKph ?? 0 };
  return {
    ...fix,
    speedKph: fix.speedKph ?? (distance / dt) * 3.6,
    heading: fix.heading ?? bearingDeg(previous, fix),
    derived: true,
  };
}

/** One fix as the body the server's `POST /api/v1/ingest/probes` accepts. */
export function probeFromFix(fix, deviceId) {
  const probe = {
    device_id: deviceId,
    lon: fix.lon,
    lat: fix.lat,
    observed_at: new Date(fix.timestamp).toISOString(),
  };
  if (fix.speedKph !== null) probe.speed_kph = Math.round(fix.speedKph * 10) / 10;
  if (fix.heading !== null) probe.bearing = Math.round(fix.heading);
  if (fix.accuracy !== null) probe.accuracy_m = Math.round(fix.accuracy);
  return probe;
}

/** What went wrong, in words a driver can act on. */
export function describeGeolocationError(error) {
  switch (error && error.code) {
    case 1:
      return "Bạn đã chặn quyền vị trí. Mở cài đặt trang web và cho phép Vị trí.";
    case 2:
      return "Thiết bị chưa bắt được vị trí. Ra chỗ thoáng hoặc bật GPS.";
    case 3:
      return "Chờ GPS quá lâu, đang thử lại…";
    default:
      return (error && error.message) || "Không đọc được vị trí.";
  }
}

/**
 * Watches the device position and hands usable fixes to `onFix`.
 *
 * `geolocation` and `secure` are injectable for tests; in the page they are
 * `navigator.geolocation` and `window.isSecureContext`.
 */
export class GpsTracker {
  constructor({
    onFix,
    onError,
    maxAccuracyM = 100,
    geolocation = globalThis.navigator?.geolocation,
    secure = globalThis.isSecureContext,
  }) {
    this.onFix = onFix;
    this.onError = onError;
    this.maxAccuracyM = maxAccuracyM;
    this.geolocation = geolocation;
    this.secure = secure;
    this.watchId = null;
    this.last = null;
    this.rejected = 0;
  }

  get running() {
    return this.watchId !== null;
  }

  start() {
    if (this.running) return true;
    if (!this.secure) {
      this.onError?.(
        "Trình duyệt chỉ cho đọc GPS trên HTTPS hoặc localhost. Mở trang qua đường dẫn https:// (ví dụ Cloudflare Tunnel)."
      );
      return false;
    }
    if (!this.geolocation) {
      this.onError?.("Trình duyệt này không hỗ trợ định vị.");
      return false;
    }
    this.watchId = this.geolocation.watchPosition(
      (position) => this.handle(position),
      (error) => {
        this.onError?.(describeGeolocationError(error));
        // Permission refused is final until the person changes it; anything
        // else the browser keeps retrying on its own.
        if (error && error.code === 1) this.stop();
      },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 }
    );
    return true;
  }

  stop() {
    if (this.watchId !== null && this.geolocation) this.geolocation.clearWatch(this.watchId);
    this.watchId = null;
  }

  handle(position) {
    const fix = deriveMotion(fixFromPosition(position), this.last);
    if (!isUsable(fix, this.maxAccuracyM)) {
      this.rejected += 1;
      this.onError?.(`Tín hiệu GPS yếu (±${Math.round(fix.accuracy)} m), đang chờ chính xác hơn…`);
      return;
    }
    this.last = fix;
    this.onFix?.(fix);
  }
}

/**
 * Batches fixes and posts them as probes.
 *
 * At most one probe per `minIntervalMs`, posted every `flushMs`. A failed post
 * keeps its probes for the next attempt, up to `maxQueued`, because a phone
 * going through a tunnel is the normal case for a driver, not an outage --
 * but the server refuses anything older than ten minutes, so the queue is
 * trimmed to what it would still accept.
 */
export class ProbeUploader {
  constructor({
    url,
    deviceId,
    flushMs = 15000,
    minIntervalMs = 2000,
    maxQueued = 300,
    maxAgeMs = 9 * 60 * 1000,
    fetchFn = globalThis.fetch?.bind(globalThis),
    now = () => Date.now(),
  }) {
    Object.assign(this, { url, deviceId, flushMs, minIntervalMs, maxQueued, maxAgeMs, fetchFn, now });
    this.queue = [];
    this.lastQueuedAt = -Infinity;
    this.enabled = true;
    this.stats = { sent: 0, accepted: 0, rejected: 0, failures: 0 };
    this.timer = null;
    this.inFlight = false;
  }

  add(fix) {
    if (!this.enabled) return false;
    if (fix.timestamp - this.lastQueuedAt < this.minIntervalMs) return false;
    this.lastQueuedAt = fix.timestamp;
    this.queue.push(probeFromFix(fix, this.deviceId));
    if (this.queue.length > this.maxQueued) this.queue.splice(0, this.queue.length - this.maxQueued);
    return true;
  }

  start() {
    if (this.timer === null) this.timer = setInterval(() => this.flush(), this.flushMs);
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  async flush() {
    if (this.inFlight || this.queue.length === 0 || !this.fetchFn) return;
    const cutoff = this.now() - this.maxAgeMs;
    this.queue = this.queue.filter((p) => Date.parse(p.observed_at) >= cutoff);
    if (this.queue.length === 0) return;

    const batch = this.queue.splice(0, this.queue.length);
    this.inFlight = true;
    try {
      const response = await this.fetchFn(this.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ probes: batch }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json().catch(() => ({}));
      this.stats.sent += batch.length;
      this.stats.accepted += Number(body.accepted ?? 0);
      this.stats.rejected += Array.isArray(body.rejected) ? body.rejected.length : Number(body.rejected ?? 0);
    } catch (err) {
      this.stats.failures += 1;
      this.queue = batch.concat(this.queue).slice(-this.maxQueued);
    } finally {
      this.inFlight = false;
    }
  }
}
