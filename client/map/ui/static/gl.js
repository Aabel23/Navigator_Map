// One shared GPU buffer per bucket, for the whole map -- not one per layer
// per tile.
//
// A bucket is a vertex buffer, an index buffer, and a map of which tile owns
// which span of each. Appending a tile writes to the end of both and rebases
// its indices once; dropping tiles rebuilds the buffer without them, in a
// single pass, rebasing the survivors as it goes. The payoff is at draw time:
// every polygon in the resident map is one `drawElements`, and every road in
// the resident map is two -- casing, then fill -- no matter how many tiles are
// loaded or how many classes are on screen.
//
// Style never becomes a draw call. Each vertex carries a style index; the
// shader reads colour and width out of a uniform block indexed by it. That is
// what lets a motorway, a service road and a building outline share one
// buffer and one pass while looking nothing alike.

import { SDF_FONT_SIZE } from "./glyphs.js";

const FILL_VERTEX_FLOATS = 3; // x, y, style
const LINE_VERTEX_FLOATS = 6; // x, y, ex, ey, side, style
const MAX_STYLES = 64;

const INITIAL_VERTS = 8192;
const INITIAL_INDICES = 16384;

const COMMON_VERTEX_HEAD = `#version 300 es
  uniform vec2 uCamWorld;
  uniform vec2 uViewport;
  uniform float uScale;

  vec4 toClip(vec2 screen) {
    return vec4(
      screen.x / uViewport.x * 2.0 - 1.0,
      1.0 - screen.y / uViewport.y * 2.0,
      0.0,
      1.0
    );
  }
`;

const FILL_VERTEX_SHADER = `${COMMON_VERTEX_HEAD}
  layout(location = 0) in vec2 aPos;
  layout(location = 1) in float aStyle;

  layout(std140) uniform FillStyles {
    vec4 uFillColor[${MAX_STYLES}];
  };

  out vec4 vColor;

  void main() {
    gl_Position = toClip((aPos - uCamWorld) * uScale + uViewport * 0.5);
    vColor = uFillColor[int(aStyle)];
  }
`;

const FILL_FRAGMENT_SHADER = `#version 300 es
  precision mediump float;
  in vec4 vColor;
  out vec4 outColor;
  void main() {
    outColor = vColor;
  }
`;

// The width lives in the shader, not the geometry: the vertex carries the
// direction to push sideways, and the style table says how far, at this zoom,
// for this pass. One ribbon of triangles therefore serves both the casing and
// the fill, at every zoom, without ever being rebuilt.
const LINE_VERTEX_SHADER = `${COMMON_VERTEX_HEAD}
  layout(location = 0) in vec2 aPos;
  layout(location = 1) in vec2 aExtrude;
  layout(location = 2) in float aSide;
  layout(location = 3) in float aStyle;

  layout(std140) uniform LineStyles {
    vec4 uLineColor[${MAX_STYLES}];
    vec4 uCasingColor[${MAX_STYLES}];
    vec4 uLineWidth[${MAX_STYLES}];
  };

  uniform float uZoomT;
  uniform float uCasingPass;
  uniform float uPixelRatio;

  out vec4 vColor;
  out float vSide;
  out float vHalfPx;

  void main() {
    int s = int(aStyle);
    vec4 w = uLineWidth[s];
    float widthCss = uCasingPass > 0.5 ? mix(w.z, w.w, uZoomT) : mix(w.x, w.y, uZoomT);
    float halfPx = widthCss * 0.5 * uPixelRatio;

    vec2 screen = (aPos - uCamWorld) * uScale + aExtrude * halfPx + uViewport * 0.5;
    gl_Position = toClip(screen);

    vColor = uCasingPass > 0.5 ? uCasingColor[s] : uLineColor[s];
    vSide = aSide;
    vHalfPx = halfPx;
  }
`;

// One pixel of feather at the ribbon's edge. Without it a diagonal road is a
// staircase at every zoom that is not a power of two, which is most of them.
const LINE_FRAGMENT_SHADER = `#version 300 es
  precision mediump float;
  in vec4 vColor;
  in float vSide;
  in float vHalfPx;
  out vec4 outColor;
  void main() {
    float distFromCentre = abs(vSide) * vHalfPx;
    float alpha = clamp(vHalfPx - distFromCentre, 0.0, 1.0);
    outColor = vec4(vColor.rgb, vColor.a * alpha);
  }
`;

// -- labels -------------------------------------------------------------------
// A label vertex is a world anchor plus a screen-pixel offset from it. The
// anchor moves with the map; the offset does not, so text keeps its size at
// every zoom and a rotated street name rotates about its own centre rather
// than shearing. One shared vertex shader serves both text and icons, because
// the only thing that differs between them is which texture is sampled and
// how the sample is interpreted.

const LABEL_VERTEX_FLOATS = 8; // anchorX, anchorY, offsetX, offsetY, angle, u, v, style

const LABEL_VERTEX_SHADER = `#version 300 es
  layout(location = 0) in vec2 aAnchor;
  layout(location = 1) in vec2 aOffset;
  layout(location = 2) in float aAngle;
  layout(location = 3) in vec2 aTexCoord;
  layout(location = 4) in float aStyle;

  uniform vec2 uCamWorld;
  uniform vec2 uViewport;
  uniform float uScale;
  uniform float uPixelRatio;
  uniform vec2 uTextureSize;

  out vec2 vTexCoord;
  flat out int vStyle;

  void main() {
    float s = sin(aAngle);
    float c = cos(aAngle);
    vec2 rotated = vec2(aOffset.x * c - aOffset.y * s, aOffset.x * s + aOffset.y * c);
    vec2 screen = (aAnchor - uCamWorld) * uScale + rotated * uPixelRatio + uViewport * 0.5;
    gl_Position = vec4(
      screen.x / uViewport.x * 2.0 - 1.0,
      1.0 - screen.y / uViewport.y * 2.0,
      0.0,
      1.0
    );
    vTexCoord = aTexCoord / uTextureSize;
    vStyle = int(aStyle);
  }
`;

// Reconstructing a glyph from its distance field. The texture says how far
// each pixel is from the edge; thresholding at the edge gives the letter, and
// thresholding further out gives a halo around it, which is the only reason
// text stays readable over a busy map.
const TEXT_FRAGMENT_SHADER = `#version 300 es
  precision mediump float;

  #define SDF_PX 8.0
  #define EDGE 0.75
  #define EDGE_GAMMA 0.105
  #define HALO_BLUR 0.5

  layout(std140) uniform LabelStyles {
    vec4 uTextColor[${MAX_STYLES}];
    vec4 uHaloColor[${MAX_STYLES}];
    vec4 uTextParams[${MAX_STYLES}]; // fontScale, haloWidth, unused, unused
  };

  uniform sampler2D uAtlas;
  uniform float uHaloPass;

  in vec2 vTexCoord;
  flat in int vStyle;
  out vec4 outColor;

  void main() {
    float fontScale = max(uTextParams[vStyle].x, 0.0001);
    float haloWidth = uTextParams[vStyle].y;
    float dist = texture(uAtlas, vTexCoord).r;

    float edge = uHaloPass > 0.5 ? (6.0 - haloWidth / fontScale) / SDF_PX : EDGE;
    float gamma = (uHaloPass > 0.5 ? HALO_BLUR * 1.19 / SDF_PX + EDGE_GAMMA : EDGE_GAMMA) / fontScale;

    float alpha = smoothstep(edge - gamma, edge + gamma, dist);
    vec4 color = uHaloPass > 0.5 ? uHaloColor[vStyle] : uTextColor[vStyle];
    outColor = vec4(color.rgb, color.a * alpha);
  }
`;

const ICON_FRAGMENT_SHADER = `#version 300 es
  precision mediump float;
  uniform sampler2D uSprite;
  in vec2 vTexCoord;
  flat in int vStyle;
  out vec4 outColor;
  void main() {
    outColor = texture(uSprite, vTexCoord);
  }
`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`shader compile failed: ${info}`);
  }
  return shader;
}

function link(gl, vertexSource, fragmentSource) {
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertexSource));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragmentSource));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(`program link failed: ${gl.getProgramInfoLog(program)}`);
  }
  return program;
}

export class Bucket {
  /**
   * @param {WebGL2RenderingContext} gl
   * @param {string} name
   * @param {"fill"|"line"} kind - decides the vertex layout and which program
   *   draws it.
   */
  constructor(gl, name, kind) {
    this.gl = gl;
    this.name = name;
    this.kind = kind;
    this.floatsPerVertex = kind === "line" ? LINE_VERTEX_FLOATS : FILL_VERTEX_FLOATS;

    this.vertexCapacity = INITIAL_VERTS;
    this.indexCapacity = INITIAL_INDICES;
    this.usedVerts = 0;
    this.usedIndices = 0;
    this.vertexCpu = new Float32Array(this.vertexCapacity * this.floatsPerVertex);
    this.indexCpu = new Uint32Array(this.indexCapacity);

    this.vertexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, this.vertexCpu.byteLength, gl.DYNAMIC_DRAW);

    this.indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.indexCpu.byteLength, gl.DYNAMIC_DRAW);

    /** @type {Map<string, {vStart:number, vCount:number, iStart:number, iCount:number}>} */
    this.spans = new Map();
    this.compactions = 0;
    this.appends = 0;
    this.dirtyBytesTotal = 0;
  }

  _growVertices(minVerts) {
    let capacity = this.vertexCapacity;
    while (capacity < minVerts) capacity *= 2;
    const grown = new Float32Array(capacity * this.floatsPerVertex);
    grown.set(this.vertexCpu.subarray(0, this.usedVerts * this.floatsPerVertex));
    this.vertexCpu = grown;
    this.vertexCapacity = capacity;

    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, grown.byteLength, gl.DYNAMIC_DRAW);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, grown, 0, this.usedVerts * this.floatsPerVertex);
  }

  _growIndices(minIndices) {
    let capacity = this.indexCapacity;
    while (capacity < minIndices) capacity *= 2;
    const grown = new Uint32Array(capacity);
    grown.set(this.indexCpu.subarray(0, this.usedIndices));
    this.indexCpu = grown;
    this.indexCapacity = capacity;

    const gl = this.gl;
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, grown.byteLength, gl.DYNAMIC_DRAW);
    gl.bufferSubData(gl.ELEMENT_ARRAY_BUFFER, 0, grown, 0, this.usedIndices);
  }

  /**
   * Append one tile's mesh. Indices arrive local to the tile and are rebased
   * onto the shared buffer here -- one add per index, the only per-tile work
   * left on the main thread.
   *
   * @param {string} tileKey
   * @param {Float32Array} vertices
   * @param {Uint32Array} indices
   */
  appendTile(tileKey, vertices, indices) {
    const vertexCount = vertices.length / this.floatsPerVertex;
    const span = {
      vStart: this.usedVerts,
      vCount: vertexCount,
      iStart: this.usedIndices,
      iCount: indices.length,
    };
    this.spans.set(tileKey, span);
    if (vertexCount === 0 || indices.length === 0) return;

    if (this.usedVerts + vertexCount > this.vertexCapacity) {
      this._growVertices(this.usedVerts + vertexCount);
    }
    if (this.usedIndices + indices.length > this.indexCapacity) {
      this._growIndices(this.usedIndices + indices.length);
    }

    const base = this.usedVerts;
    this.vertexCpu.set(vertices, base * this.floatsPerVertex);
    for (let i = 0; i < indices.length; i++) {
      this.indexCpu[this.usedIndices + i] = indices[i] + base;
    }

    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferSubData(gl.ARRAY_BUFFER, base * this.floatsPerVertex * 4, vertices);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bufferSubData(
      gl.ELEMENT_ARRAY_BUFFER,
      this.usedIndices * 4,
      this.indexCpu,
      this.usedIndices,
      indices.length
    );

    this.usedVerts += vertexCount;
    this.usedIndices += indices.length;
    this.appends += 1;
  }

  /** Drop tiles and rebuild both buffers without them, in one pass. */
  removeTiles(tileKeys) {
    const drop = new Set(tileKeys.filter((key) => this.spans.has(key)));
    if (drop.size === 0) return;

    // Spans are held in append order, which is arrival order; walking them in
    // that order and skipping the dropped ones keeps every survivor
    // contiguous, which is what single-draw-call rendering depends on.
    const survivors = [...this.spans.entries()].filter(([key]) => !drop.has(key));
    const vertexFloats = this.floatsPerVertex;
    const rebuiltVertices = new Float32Array(this.vertexCpu.length);
    const rebuiltIndices = new Uint32Array(this.indexCpu.length);
    const newSpans = new Map();

    let vCursor = 0;
    let iCursor = 0;
    for (const [key, span] of survivors) {
      if (span.vCount > 0) {
        rebuiltVertices.set(
          this.vertexCpu.subarray(span.vStart * vertexFloats, (span.vStart + span.vCount) * vertexFloats),
          vCursor * vertexFloats
        );
      }
      const shift = vCursor - span.vStart;
      for (let i = 0; i < span.iCount; i++) {
        rebuiltIndices[iCursor + i] = this.indexCpu[span.iStart + i] + shift;
      }
      newSpans.set(key, { vStart: vCursor, vCount: span.vCount, iStart: iCursor, iCount: span.iCount });
      vCursor += span.vCount;
      iCursor += span.iCount;
    }

    this.vertexCpu = rebuiltVertices;
    this.indexCpu = rebuiltIndices;
    this.usedVerts = vCursor;
    this.usedIndices = iCursor;
    this.spans = newSpans;

    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, this.vertexCpu, 0, this.usedVerts * vertexFloats);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bufferSubData(gl.ELEMENT_ARRAY_BUFFER, 0, this.indexCpu, 0, this.usedIndices);
    this.compactions += 1;
  }

  /**
   * Restyle a contiguous run of vertices and re-upload only the bytes it
   * covers -- not the buffer, not the tile.
   *
   * This is the block's mechanism for "something about this road changed"
   * without a rebuild: nothing in the base map uses it, because the base map
   * is static, but a live per-segment signal (traffic, a closure, the active
   * route) restyles through here.
   *
   * @returns {number} bytes actually uploaded.
   */
  setStyleRange(startVert, count, styleIndex) {
    if (count <= 0 || startVert < 0 || startVert + count > this.usedVerts) return 0;
    const stride = this.floatsPerVertex;
    const styleOffset = stride - 1; // style is the last float in both layouts
    for (let v = startVert; v < startVert + count; v++) {
      this.vertexCpu[v * stride + styleOffset] = styleIndex;
    }
    const gl = this.gl;
    const slice = this.vertexCpu.subarray(startVert * stride, (startVert + count) * stride);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferSubData(gl.ARRAY_BUFFER, startVert * stride * 4, slice);
    this.dirtyBytesTotal += slice.byteLength;
    return slice.byteLength;
  }

  get bytesUsed() {
    return this.usedVerts * this.floatsPerVertex * 4 + this.usedIndices * 4;
  }

  get bytesAllocated() {
    return this.vertexCpu.byteLength + this.indexCpu.byteLength;
  }
}

/**
 * A buffer whose whole contents are replaced at once.
 *
 * Labels do not accumulate the way geometry does. Which ones are drawn is
 * decided fresh whenever the camera moves, and the answer is a few hundred
 * labels out of the tens of thousands resident -- so rewriting the buffer
 * outright is both simpler and cheaper than tracking per-tile spans and
 * compacting them. There is nothing to rebase and nothing to evict.
 */
export class DynamicMesh {
  constructor(gl, floatsPerVertex, attributes) {
    this.gl = gl;
    this.floatsPerVertex = floatsPerVertex;
    this.vertexCapacity = 4096;
    this.indexCapacity = 8192;
    this.indexCount = 0;

    this.vertexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, this.vertexCapacity * floatsPerVertex * 4, gl.STREAM_DRAW);

    this.indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.indexCapacity * 4, gl.STREAM_DRAW);

    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    const stride = floatsPerVertex * 4;
    for (const { location, size, offset } of attributes) {
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride, offset);
    }
    gl.bindVertexArray(null);
  }

  /**
   * @param {Float32Array} vertices
   * @param {Uint32Array} indices
   */
  upload(vertices, indices) {
    const gl = this.gl;
    this.indexCount = indices.length;
    if (indices.length === 0) return;

    const vertexCount = vertices.length / this.floatsPerVertex;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
    if (vertexCount > this.vertexCapacity) {
      while (this.vertexCapacity < vertexCount) this.vertexCapacity *= 2;
      gl.bufferData(gl.ARRAY_BUFFER, this.vertexCapacity * this.floatsPerVertex * 4, gl.STREAM_DRAW);
    }
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, vertices);

    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    if (indices.length > this.indexCapacity) {
      while (this.indexCapacity < indices.length) this.indexCapacity *= 2;
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.indexCapacity * 4, gl.STREAM_DRAW);
    }
    gl.bufferSubData(gl.ELEMENT_ARRAY_BUFFER, 0, indices);
  }

  get bytesUsed() {
    return this.vertexCapacity * this.floatsPerVertex * 4 + this.indexCapacity * 4;
  }
}

export class Renderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} style - the resolved style payload from /api/config.
   * @param {Object<string,"fill"|"line">} bucketKinds - bucket name to layout.
   */
  constructor(canvas, style, bucketKinds) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: false });
    if (!gl) throw new Error("WebGL2 is not available in this browser");
    this.gl = gl;
    this.canvas = canvas;
    this.style = style;
    this.pixelRatio = 1;

    this.fillProgram = link(gl, FILL_VERTEX_SHADER, FILL_FRAGMENT_SHADER);
    this.lineProgram = link(gl, LINE_VERTEX_SHADER, LINE_FRAGMENT_SHADER);
    this.textProgram = link(gl, LABEL_VERTEX_SHADER, TEXT_FRAGMENT_SHADER);
    this.iconProgram = link(gl, LABEL_VERTEX_SHADER, ICON_FRAGMENT_SHADER);

    this.fillUniforms = this._uniformsOf(this.fillProgram, []);
    this.lineUniforms = this._uniformsOf(this.lineProgram, ["uZoomT", "uCasingPass", "uPixelRatio"]);
    this.textUniforms = this._uniformsOf(this.textProgram, ["uPixelRatio", "uTextureSize", "uAtlas", "uHaloPass"]);
    this.iconUniforms = this._uniformsOf(this.iconProgram, ["uPixelRatio", "uTextureSize", "uSprite"]);

    this._buildStyleBlocks();

    const labelAttributes = [
      { location: 0, size: 2, offset: 0 },
      { location: 1, size: 2, offset: 8 },
      { location: 2, size: 1, offset: 16 },
      { location: 3, size: 2, offset: 20 },
      { location: 4, size: 1, offset: 28 },
    ];
    this.textMesh = new DynamicMesh(gl, LABEL_VERTEX_FLOATS, labelAttributes);
    this.iconMesh = new DynamicMesh(gl, LABEL_VERTEX_FLOATS, labelAttributes);
    this.glyphStore = null;
    this.spriteStore = null;

    /** @type {Map<string, Bucket>} in the style's draw order. */
    this.buckets = new Map();
    for (const name of style.buckets) {
      const kind = bucketKinds[name] ?? "fill";
      const bucket = new Bucket(gl, name, kind);
      bucket.vao = this._buildVao(bucket);
      this.buckets.set(name, bucket);
    }

    const bg = style.background;
    gl.clearColor(bg[0], bg[1], bg[2], 1);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  }

  _uniformsOf(program, extra) {
    const gl = this.gl;
    const names = ["uCamWorld", "uViewport", "uScale", ...extra];
    const uniforms = {};
    for (const name of names) uniforms[name] = gl.getUniformLocation(program, name);
    return uniforms;
  }

  /**
   * Upload both style tables once, as uniform blocks.
   *
   * Colour and width are not per-draw state here, they are indexed data, so a
   * restyle is one `bufferSubData` and zero extra passes.
   */
  _buildStyleBlocks() {
    const gl = this.gl;
    const style = this.style;

    const fillData = new Float32Array(MAX_STYLES * 4);
    style.fill_styles.forEach((entry, i) => {
      if (i >= MAX_STYLES) return;
      fillData.set(entry.color, i * 4);
    });

    const lineData = new Float32Array(MAX_STYLES * 4 * 3);
    const casingBase = MAX_STYLES * 4;
    const widthBase = MAX_STYLES * 8;
    style.line_styles.forEach((entry, i) => {
      if (i >= MAX_STYLES) return;
      lineData.set(entry.color, i * 4);
      lineData.set(entry.casing, casingBase + i * 4);
      lineData.set([entry.width[0], entry.width[1], entry.casing_width[0], entry.casing_width[1]], widthBase + i * 4);
    });

    const labelData = new Float32Array(MAX_STYLES * 4 * 3);
    const haloBase = MAX_STYLES * 4;
    const paramBase = MAX_STYLES * 8;
    style.label_styles.forEach((entry, i) => {
      if (i >= MAX_STYLES) return;
      labelData.set(entry.color, i * 4);
      labelData.set(entry.halo, haloBase + i * 4);
      // The shader needs the glyph scale rather than the point size: a
      // distance field is thresholded relative to how far it has been
      // stretched from the size it was rasterised at.
      labelData.set([entry.size / SDF_FONT_SIZE, entry.halo_width, 0, 0], paramBase + i * 4);
    });

    this.fillStyleBuffer = this._uniformBlock(this.fillProgram, "FillStyles", 0, fillData);
    this.lineStyleBuffer = this._uniformBlock(this.lineProgram, "LineStyles", 1, lineData);
    this.labelStyleBuffer = this._uniformBlock(this.textProgram, "LabelStyles", 2, labelData);
  }

  /** Hand the renderer the two textures labels are drawn from. */
  setLabelTextures(glyphStore, spriteStore) {
    this.glyphStore = glyphStore;
    this.spriteStore = spriteStore;
  }

  _uniformBlock(program, blockName, bindingPoint, data) {
    const gl = this.gl;
    const blockIndex = gl.getUniformBlockIndex(program, blockName);
    if (blockIndex === gl.INVALID_INDEX) throw new Error(`missing uniform block ${blockName}`);
    gl.uniformBlockBinding(program, blockIndex, bindingPoint);

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.UNIFORM_BUFFER, buffer);
    gl.bufferData(gl.UNIFORM_BUFFER, data, gl.STATIC_DRAW);
    gl.bindBufferBase(gl.UNIFORM_BUFFER, bindingPoint, buffer);
    return buffer;
  }

  _buildVao(bucket) {
    const gl = this.gl;
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, bucket.vertexBuffer);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, bucket.indexBuffer);

    if (bucket.kind === "line") {
      const stride = LINE_VERTEX_FLOATS * 4;
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, stride, 0);
      gl.enableVertexAttribArray(1);
      gl.vertexAttribPointer(1, 2, gl.FLOAT, false, stride, 8);
      gl.enableVertexAttribArray(2);
      gl.vertexAttribPointer(2, 1, gl.FLOAT, false, stride, 16);
      gl.enableVertexAttribArray(3);
      gl.vertexAttribPointer(3, 1, gl.FLOAT, false, stride, 20);
    } else {
      const stride = FILL_VERTEX_FLOATS * 4;
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, stride, 0);
      gl.enableVertexAttribArray(1);
      gl.vertexAttribPointer(1, 1, gl.FLOAT, false, stride, 8);
    }

    gl.bindVertexArray(null);
    return vao;
  }

  resize(width, height) {
    const gl = this.gl;
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(width * ratio);
    this.canvas.height = Math.round(height * ratio);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    this.cssWidth = width;
    this.cssHeight = height;
    this.pixelRatio = ratio;
  }

  /**
   * Draw every resident tile.
   *
   * @param {{worldX:number, worldY:number, zoom:number}} camera
   * @returns {number} draw calls issued this frame.
   */
  draw(camera) {
    const gl = this.gl;
    gl.clear(gl.COLOR_BUFFER_BIT);

    const scale = Math.pow(2, camera.zoom) * this.pixelRatio;
    const [zLo, zHi] = this.style.zoom_stops;
    const zoomT = Math.max(0, Math.min(1, (camera.zoom - zLo) / (zHi - zLo)));
    let drawCalls = 0;

    for (const bucket of this.buckets.values()) {
      if (bucket.usedIndices === 0) continue;
      const isLine = bucket.kind === "line";
      const program = isLine ? this.lineProgram : this.fillProgram;
      const uniforms = isLine ? this.lineUniforms : this.fillUniforms;

      gl.useProgram(program);
      gl.uniform2f(uniforms.uViewport, this.canvas.width, this.canvas.height);
      gl.uniform2f(uniforms.uCamWorld, camera.worldX, camera.worldY);
      gl.uniform1f(uniforms.uScale, scale);
      gl.bindVertexArray(bucket.vao);

      if (!isLine) {
        gl.drawElements(gl.TRIANGLES, bucket.usedIndices, gl.UNSIGNED_INT, 0);
        drawCalls += 1;
        continue;
      }

      gl.uniform1f(uniforms.uZoomT, zoomT);
      gl.uniform1f(uniforms.uPixelRatio, this.pixelRatio);
      // Every casing in the bucket, then every fill: two passes over one
      // buffer is what makes a junction read as a junction rather than as a
      // stack of separately outlined ribbons.
      for (const casingPass of [1, 0]) {
        gl.uniform1f(uniforms.uCasingPass, casingPass);
        gl.drawElements(gl.TRIANGLES, bucket.usedIndices, gl.UNSIGNED_INT, 0);
        drawCalls += 1;
      }
    }

    drawCalls += this._drawLabels(camera, scale);

    gl.bindVertexArray(null);
    return drawCalls;
  }

  /**
   * Icons, then text haloes, then text.
   *
   * The order is the whole trick to readable labels: every halo is laid down
   * before any letter, so one label's halo can never punch a white hole
   * through its neighbour's letters. It is the same two-pass shape as road
   * casings and fills, for the same reason.
   */
  _drawLabels(camera, scale) {
    const gl = this.gl;
    let drawCalls = 0;

    if (this.spriteStore && this.iconMesh.indexCount > 0) {
      gl.useProgram(this.iconProgram);
      gl.uniform2f(this.iconUniforms.uViewport, this.canvas.width, this.canvas.height);
      gl.uniform2f(this.iconUniforms.uCamWorld, camera.worldX, camera.worldY);
      gl.uniform1f(this.iconUniforms.uScale, scale);
      gl.uniform1f(this.iconUniforms.uPixelRatio, this.pixelRatio);
      gl.uniform2f(this.iconUniforms.uTextureSize, this.spriteStore.width, this.spriteStore.height);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.spriteStore.texture);
      gl.uniform1i(this.iconUniforms.uSprite, 0);
      gl.bindVertexArray(this.iconMesh.vao);
      gl.drawElements(gl.TRIANGLES, this.iconMesh.indexCount, gl.UNSIGNED_INT, 0);
      drawCalls += 1;
    }

    if (this.glyphStore && this.textMesh.indexCount > 0) {
      gl.useProgram(this.textProgram);
      gl.uniform2f(this.textUniforms.uViewport, this.canvas.width, this.canvas.height);
      gl.uniform2f(this.textUniforms.uCamWorld, camera.worldX, camera.worldY);
      gl.uniform1f(this.textUniforms.uScale, scale);
      gl.uniform1f(this.textUniforms.uPixelRatio, this.pixelRatio);
      gl.uniform2f(this.textUniforms.uTextureSize, this.glyphStore.width, this.glyphStore.height);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.glyphStore.texture);
      gl.uniform1i(this.textUniforms.uAtlas, 0);
      gl.bindVertexArray(this.textMesh.vao);
      for (const haloPass of [1, 0]) {
        gl.uniform1f(this.textUniforms.uHaloPass, haloPass);
        gl.drawElements(gl.TRIANGLES, this.textMesh.indexCount, gl.UNSIGNED_INT, 0);
        drawCalls += 1;
      }
    }

    return drawCalls;
  }
}
