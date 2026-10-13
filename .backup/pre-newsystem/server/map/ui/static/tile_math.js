// Web Mercator projection and tile arithmetic, kept to the minimum the
// renderer and the scheduler both need. There is no camera easing and no
// pitch here -- the point of this package is the tile pipeline, not a
// feature-complete map camera.

export const TILE_SIZE = 256;

/** Longitude/latitude to world pixels at zoom 0 (independent of camera zoom). */
export function lonLatToWorldZ0(lon, lat) {
  const x = ((lon + 180) / 360) * TILE_SIZE;
  const sinLat = Math.sin((lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * TILE_SIZE;
  return { x, y };
}

/** The integer tile zoom tiles are actually requested at for a given camera zoom. */
export function tileZoomFor(cameraZoom, maxZoom, minZoom) {
  return Math.max(minZoom, Math.min(maxZoom, Math.round(cameraZoom)));
}

/**
 * Every tile that intersects the viewport at `tileZoom`, plus a margin ring.
 * `camera` is `{worldX, worldY, zoom}` in the same origin-relative world-Z0
 * units the GPU buffers are built in.
 */
export function visibleTiles(camera, origin, viewportW, viewportH, tileZoom, marginTiles) {
  const scale = Math.pow(2, camera.zoom);
  const halfW = viewportW / 2 / scale;
  const halfH = viewportH / 2 / scale;
  const minX = camera.worldX - halfW;
  const maxX = camera.worldX + halfW;
  const minY = camera.worldY - halfH;
  const maxY = camera.worldY + halfH;

  const tilesAtZoom = Math.pow(2, tileZoom);
  const tileSizeZ0 = TILE_SIZE / tilesAtZoom;
  // camera.worldX/Y are origin-relative; add the origin back before dividing
  // by tile size, since tile indices are absolute.
  const txMin = Math.floor((minX + origin.x) / tileSizeZ0) - marginTiles;
  const txMax = Math.floor((maxX + origin.x) / tileSizeZ0) + marginTiles;
  const tyMin = Math.floor((minY + origin.y) / tileSizeZ0) - marginTiles;
  const tyMax = Math.floor((maxY + origin.y) / tileSizeZ0) + marginTiles;

  const tiles = [];
  for (let tx = txMin; tx <= txMax; tx++) {
    if (tx < 0 || tx >= tilesAtZoom) continue;
    for (let ty = tyMin; ty <= tyMax; ty++) {
      if (ty < 0 || ty >= tilesAtZoom) continue;
      tiles.push([tileZoom, tx, ty]);
    }
  }
  return tiles;
}

/** Tiles in a ring ahead of the camera along `(dirX, dirY)` (unit vector). */
export function prefetchTiles(camera, origin, tileZoom, dirX, dirY, ringTiles) {
  const tilesAtZoom = Math.pow(2, tileZoom);
  const tileSizeZ0 = TILE_SIZE / tilesAtZoom;
  const aheadWorldX = camera.worldX + dirX * tileSizeZ0 * (ringTiles + 1);
  const aheadWorldY = camera.worldY + dirY * tileSizeZ0 * (ringTiles + 1);
  const centreTx = Math.floor((aheadWorldX + origin.x) / tileSizeZ0);
  const centreTy = Math.floor((aheadWorldY + origin.y) / tileSizeZ0);
  const tiles = [];
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const tx = centreTx + dx;
      const ty = centreTy + dy;
      if (tx < 0 || ty < 0 || tx >= tilesAtZoom || ty >= tilesAtZoom) continue;
      tiles.push([tileZoom, tx, ty]);
    }
  }
  return tiles;
}

export function tileKey(z, x, y) {
  return `${z}/${x}/${y}`;
}
