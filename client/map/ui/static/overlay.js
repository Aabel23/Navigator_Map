// What sits on top of the basemap and changes every second: the driver's
// position, how sure the receiver is of it, where they are going, and the
// route between.
//
// A 2D canvas over the WebGL one rather than a bucket inside it. The basemap's
// buffers are built per tile, on workers, for geometry that does not move;
// a dot that moves every second and a route that is replaced on every request
// are the opposite workload, and a few hundred points drawn with Canvas 2D
// cost less than one buffer upload. The overlay never receives input --
// `pointer-events: none` -- so the map underneath keeps every gesture.

import { lonLatToWorldZ0, metresPerWorldZ0 } from "./tile_math.js";

const ROUTE_CASING = "rgba(255, 255, 255, 0.95)";
const ROUTE_FILL = "#1a73e8";
const DOT_FILL = "#1a73e8";
const DOT_STALE = "#8a939c";
const ACCURACY_FILL = "rgba(26, 115, 232, 0.14)";
const ACCURACY_EDGE = "rgba(26, 115, 232, 0.45)";
const DESTINATION_FILL = "#d93025";

/** A fix older than this is drawn grey: the receiver has gone quiet. */
const STALE_AFTER_MS = 15000;

export class Overlay {
  constructor(canvas, origin) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.origin = origin;
    this.fix = null;
    this.route = null; // [{x, y}] world-Z0, origin-relative
    this.destination = null;
    this.cssWidth = 0;
    this.cssHeight = 0;
  }

  resize(width, height) {
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(width * ratio);
    this.canvas.height = Math.round(height * ratio);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.cssWidth = width;
    this.cssHeight = height;
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  /** `{lon, lat}` to origin-relative world-Z0, the space the camera lives in. */
  toWorld(lon, lat) {
    const p = lonLatToWorldZ0(lon, lat);
    return { x: p.x - this.origin.x, y: p.y - this.origin.y };
  }

  setFix(fix) {
    this.fix = fix ? { ...fix, world: this.toWorld(fix.lon, fix.lat) } : null;
  }

  /** GeoJSON LineString coordinates, `[lon, lat]` pairs, or null to clear. */
  setRoute(coordinates) {
    this.route = coordinates ? coordinates.map(([lon, lat]) => this.toWorld(lon, lat)) : null;
  }

  setDestination(point) {
    this.destination = point ? { ...point, world: this.toWorld(point.lon, point.lat) } : null;
  }

  draw(camera) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.cssWidth, this.cssHeight);
    const scale = Math.pow(2, camera.zoom);
    const toScreen = (w) => ({
      x: (w.x - camera.worldX) * scale + this.cssWidth / 2,
      y: (w.y - camera.worldY) * scale + this.cssHeight / 2,
    });

    if (this.route && this.route.length > 1) {
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      this.route.forEach((w, i) => {
        const s = toScreen(w);
        if (i === 0) ctx.moveTo(s.x, s.y);
        else ctx.lineTo(s.x, s.y);
      });
      ctx.strokeStyle = ROUTE_CASING;
      ctx.lineWidth = 9;
      ctx.stroke();
      ctx.strokeStyle = ROUTE_FILL;
      ctx.lineWidth = 5.5;
      ctx.stroke();
    }

    if (this.destination) {
      const s = toScreen(this.destination.world);
      drawPin(ctx, s.x, s.y);
    }

    if (this.fix) {
      const s = toScreen(this.fix.world);
      const stale = Date.now() - this.fix.timestamp > STALE_AFTER_MS;
      if (this.fix.accuracy) {
        const radius = (this.fix.accuracy / metresPerWorldZ0(this.fix.lat)) * scale;
        if (radius > 9) {
          ctx.beginPath();
          ctx.arc(s.x, s.y, radius, 0, Math.PI * 2);
          ctx.fillStyle = ACCURACY_FILL;
          ctx.fill();
          ctx.strokeStyle = ACCURACY_EDGE;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
      if (this.fix.heading !== null && (this.fix.speedKph ?? 0) >= 3) {
        drawHeading(ctx, s.x, s.y, this.fix.heading, stale ? DOT_STALE : DOT_FILL);
      }
      ctx.beginPath();
      ctx.arc(s.x, s.y, 8, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.shadowColor = "rgba(0, 0, 0, 0.3)";
      ctx.shadowBlur = 4;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.beginPath();
      ctx.arc(s.x, s.y, 5.5, 0, Math.PI * 2);
      ctx.fillStyle = stale ? DOT_STALE : DOT_FILL;
      ctx.fill();
    }
  }
}

function drawHeading(ctx, x, y, heading, colour) {
  const angle = ((heading - 90) * Math.PI) / 180;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(20, 0);
  ctx.lineTo(9, -6);
  ctx.lineTo(9, 6);
  ctx.closePath();
  ctx.fillStyle = colour;
  ctx.fill();
  ctx.restore();
}

function drawPin(ctx, x, y) {
  ctx.save();
  ctx.translate(x, y);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.bezierCurveTo(-3, -9, -10, -13, -10, -21);
  ctx.arc(0, -21, 10, Math.PI, 0);
  ctx.bezierCurveTo(10, -13, 3, -9, 0, 0);
  ctx.fillStyle = DESTINATION_FILL;
  ctx.shadowColor = "rgba(0, 0, 0, 0.3)";
  ctx.shadowBlur = 4;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.beginPath();
  ctx.arc(0, -21, 3.5, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.restore();
}
