// Offline checks on turning browser positions into fixes and probes.
//
// No browser: `navigator.geolocation` is a fake that records the watch and
// lets the test deliver positions by hand, and `fetch` is a fake that records
// bodies. What is asserted is the contract with the server -- longitude first,
// km/h, an ISO timestamp with a zone -- and the rules that keep a phone lying
// on a table from reporting traffic.
//
//   node tests/test_gps.mjs

import {
  haversineM,
  bearingDeg,
  fixFromPosition,
  isUsable,
  deriveMotion,
  probeFromFix,
  GpsTracker,
  ProbeUploader,
} from "../ui/static/gps.js";
import { lonLatToWorldZ0, worldZ0ToLonLat, metresPerWorldZ0 } from "../ui/static/tile_math.js";

let failures = 0;

function check(name, ok, detail) {
  if (ok) {
    console.log(`  ok   ${name}`);
    return;
  }
  failures += 1;
  console.log(`  FAIL ${name}${detail ? ` -- ${detail}` : ""}`);
}

function near(a, b, eps) {
  return Math.abs(a - b) < eps;
}

function position(lon, lat, { accuracy = 5, speed = null, heading = null, timestamp = 1_700_000_000_000 } = {}) {
  return { coords: { longitude: lon, latitude: lat, accuracy, speed, heading }, timestamp };
}

console.log("geometry");
{
  // One degree of latitude is ~111.2 km everywhere.
  check("haversine: one degree of latitude", near(haversineM({ lon: 106, lat: 10 }, { lon: 106, lat: 11 }), 111195, 50));
  check("bearing: due north is 0", near(bearingDeg({ lon: 106, lat: 10 }, { lon: 106, lat: 10.01 }), 0, 1e-6));
  check("bearing: due east is 90", near(bearingDeg({ lon: 106, lat: 0 }, { lon: 106.01, lat: 0 }), 90, 1e-6));

  const w = lonLatToWorldZ0(106.7009, 10.7769);
  const back = worldZ0ToLonLat(w.x, w.y);
  check("projection round-trips", near(back.lon, 106.7009, 1e-9) && near(back.lat, 10.7769, 1e-9));
  check("metres per world pixel at the equator", near(metresPerWorldZ0(0), 156543.03, 0.1));
}

console.log("fixes");
{
  const fix = fixFromPosition(position(106.7, 10.77, { speed: 10, heading: 45 }));
  check("longitude first", fix.lon === 106.7 && fix.lat === 10.77);
  check("speed m/s -> km/h", near(fix.speedKph, 36, 1e-9));
  check("heading kept", fix.heading === 45);

  const bare = fixFromPosition(position(106.7, 10.77, { speed: NaN }));
  check("NaN speed is null, not invented", bare.speedKph === null && bare.heading === null);

  check("accurate fix is usable", isUsable(fix, 100));
  check("imprecise fix is not", !isUsable({ ...fix, accuracy: 500 }, 100));
  check("swapped-looking fix is not", !isUsable({ ...fix, lat: 106.7 }, 100));
}

console.log("derived motion");
{
  const a = fixFromPosition(position(106.7, 10.77, { timestamp: 0 }));
  // ~111 m north in 10 s: 40 km/h.
  const b = fixFromPosition(position(106.7, 10.771, { timestamp: 10_000 }));
  const moved = deriveMotion(b, a);
  check("speed derived from two fixes", near(moved.speedKph, 40, 0.5), String(moved.speedKph));
  check("heading derived from two fixes", near(moved.heading, 0, 0.5));
  check("derived values are marked", moved.derived === true);

  // 3 m apart with 5 m accuracy: the receiver wandering, not a car moving.
  const jitter = fixFromPosition(position(106.70003, 10.77, { timestamp: 1000 }));
  const still = deriveMotion(jitter, a);
  check("jitter inside accuracy is standing still", still.speedKph === 0 && still.heading === null);

  const reported = fixFromPosition(position(106.7, 10.771, { timestamp: 10_000, speed: 2, heading: 90 }));
  check("device-reported motion is never overwritten", deriveMotion(reported, a).speedKph === 7.2);
}

console.log("probes");
{
  const fix = deriveMotion(
    fixFromPosition(position(106.7, 10.771, { timestamp: Date.parse("2026-10-13T05:00:10Z") })),
    fixFromPosition(position(106.7, 10.77, { timestamp: Date.parse("2026-10-13T05:00:00Z") }))
  );
  const probe = probeFromFix(fix, "dev-1");
  check("probe is lon/lat by name", probe.lon === 106.7 && probe.lat === 10.771);
  check("probe timestamp carries a zone", probe.observed_at === "2026-10-13T05:00:10.000Z");
  check("probe speed in km/h", near(probe.speed_kph, 40, 0.5));
  check("probe device id", probe.device_id === "dev-1");
}

console.log("tracker");
{
  const errors = [];
  const insecure = new GpsTracker({ onFix() {}, onError: (m) => errors.push(m), secure: false, geolocation: {} });
  check("insecure page refuses to start", insecure.start() === false && /HTTPS/.test(errors[0]));

  let handler = null;
  let errorHandler = null;
  const geo = {
    watchPosition(ok, fail, options) {
      handler = ok;
      errorHandler = fail;
      this.options = options;
      return 7;
    },
    clearWatch(id) {
      this.cleared = id;
    },
  };
  const fixes = [];
  const tracker = new GpsTracker({ onFix: (f) => fixes.push(f), onError: (m) => errors.push(m), secure: true, geolocation: geo, maxAccuracyM: 50 });
  check("secure page starts a watch", tracker.start() === true && tracker.running);
  check("asks for high accuracy", geo.options.enableHighAccuracy === true);
  handler(position(106.7, 10.77, { accuracy: 400 }));
  check("imprecise fix is held back", fixes.length === 0 && tracker.rejected === 1);
  handler(position(106.7, 10.77, { accuracy: 8 }));
  check("good fix is delivered", fixes.length === 1);
  errorHandler({ code: 1 });
  check("permission denied stops the watch", !tracker.running && geo.cleared === 7);
}

console.log("uploader");
{
  const bodies = [];
  let fail = false;
  let clock = Date.parse("2026-10-13T05:10:00Z");
  const fetchFn = async (url, init) => {
    if (fail) throw new Error("offline");
    bodies.push({ url, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ accepted: JSON.parse(init.body).probes.length, rejected: 0 }) };
  };
  const up = new ProbeUploader({ url: "/api/v1/ingest/probes", deviceId: "d", minIntervalMs: 2000, fetchFn, now: () => clock });
  const at = (t) => ({ lon: 106.7, lat: 10.77, accuracy: 5, speedKph: 30, heading: 0, timestamp: t });

  check("first fix queued", up.add(at(clock)));
  check("fix 1 s later is thinned out", !up.add(at(clock + 1000)));
  check("fix 2 s later is queued", up.add(at(clock + 2000)));

  fail = true;
  await up.flush();
  check("failed post keeps its probes", up.queue.length === 2 && up.stats.failures === 1);

  fail = false;
  await up.flush();
  check("retry posts them as one batch", bodies.length === 1 && bodies[0].body.probes.length === 2);
  check("posts to the probe endpoint", bodies[0].url === "/api/v1/ingest/probes");
  check("accepted count recorded", up.stats.accepted === 2 && up.queue.length === 0);

  up.add(at(clock + 10_000));
  clock += 20 * 60 * 1000;
  await up.flush();
  check("probes too old for the server are dropped, not sent", bodies.length === 1 && up.queue.length === 0);

  up.enabled = false;
  check("opted out: nothing queued", !up.add(at(clock)) && up.queue.length === 0);
}

console.log(failures === 0 ? "\nall gps checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
