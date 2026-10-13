// The icon sheet: one texture holding every point-of-interest symbol, and a
// JSON index saying where each one sits in it.
//
// This is the same sprite format map styles have used for a decade, served by
// the same keyless provider as the tiles and the glyphs. Using it means the
// block ships no image assets of its own and no icon ever costs a draw call:
// a parking symbol and a hospital symbol are two rectangles of one texture,
// drawn in the same batch as every other icon on screen.

/**
 * @typedef {{x: number, y: number, width: number, height: number, pixelRatio: number}} SpriteEntry
 */

export class SpriteStore {
  constructor(gl, index, bitmap) {
    this.gl = gl;
    this.index = index;
    this.width = bitmap.width;
    this.height = bitmap.height;

    this.texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
  }

  /**
   * Fetch the sheet and its index.
   *
   * @param {WebGL2RenderingContext} gl
   * @param {string} baseUrl - without the `.json`/`.png` suffix.
   * @param {boolean} highDpi - take the 2x sheet, for a hidpi screen.
   */
  static async load(gl, baseUrl, highDpi) {
    const suffix = highDpi ? "@2x" : "";
    const [index, blob] = await Promise.all([
      fetch(`${baseUrl}${suffix}.json`).then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status} for the sprite index`);
        return res.json();
      }),
      fetch(`${baseUrl}${suffix}.png`).then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status} for the sprite sheet`);
        return res.blob();
      }),
    ]);
    const bitmap = await createImageBitmap(blob);
    return new SpriteStore(gl, index, bitmap);
  }

  /**
   * Look up an icon, trying each candidate name in turn.
   *
   * The tile schema's point-of-interest classes were named after the same icon
   * set this sheet comes from, so `class` usually hits directly; `subclass` is
   * the fallback for the cases where it does not, and a plain marker is the
   * fallback for everything else.
   *
   * @param {...(string|null)} names
   * @returns {SpriteEntry|null}
   */
  get(...names) {
    for (const name of names) {
      if (!name) continue;
      const entry = this.index[name];
      if (entry) return entry;
    }
    return null;
  }
}
