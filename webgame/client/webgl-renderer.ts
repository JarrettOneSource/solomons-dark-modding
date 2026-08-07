import type { AssetEntry, AtlasDescriptor, FontGroup } from "../assets/types.js";
import type { NativeRect } from "./menu-catalog.js";
import type { ManifestAssets } from "./manifest-assets.js";
import type {
  AtlasTextDraw,
  DrawCommand,
  RenderPlan,
  SolidDraw,
  SpriteDraw,
  SystemTextDraw,
} from "./render-plan.js";

interface TextureRecord {
  readonly texture: WebGLTexture;
  readonly width: number;
  readonly height: number;
}

const VERTEX_SHADER = `#version 300 es
in vec2 a_position;
in vec2 a_texcoord;
in vec4 a_color;
uniform vec2 u_resolution;
out vec2 v_texcoord;
out vec4 v_color;
void main() {
  vec2 normalized = a_position / u_resolution;
  vec2 clip = normalized * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  v_texcoord = a_texcoord;
  v_color = a_color;
}`;

const FRAGMENT_SHADER = `#version 300 es
precision mediump float;
uniform sampler2D u_texture;
in vec2 v_texcoord;
in vec4 v_color;
out vec4 out_color;
void main() {
  out_color = texture(u_texture, v_texcoord) * v_color;
}`;

function shader(gl: WebGL2RenderingContext, kind: number, source: string): WebGLShader {
  const result = gl.createShader(kind);
  if (result === null) {
    throw new Error("WebGL2 could not allocate a shell shader");
  }
  gl.shaderSource(result, source);
  gl.compileShader(result);
  if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
    throw new Error(`WebGL2 shell shader failed to compile: ${gl.getShaderInfoLog(result) ?? "unknown"}`);
  }
  return result;
}

function program(gl: WebGL2RenderingContext): WebGLProgram {
  const result = gl.createProgram();
  gl.attachShader(result, shader(gl, gl.VERTEX_SHADER, VERTEX_SHADER));
  gl.attachShader(result, shader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
  gl.linkProgram(result);
  if (!gl.getProgramParameter(result, gl.LINK_STATUS)) {
    throw new Error(`WebGL2 shell program failed to link: ${gl.getProgramInfoLog(result) ?? "unknown"}`);
  }
  return result;
}

function location(gl: WebGL2RenderingContext, linked: WebGLProgram, name: string): number {
  const result = gl.getAttribLocation(linked, name);
  if (result < 0) {
    throw new Error(`WebGL2 shell program lost attribute ${name}`);
  }
  return result;
}

function uniform(
  gl: WebGL2RenderingContext,
  linked: WebGLProgram,
  name: string,
): WebGLUniformLocation {
  const result = gl.getUniformLocation(linked, name);
  if (result === null) {
    throw new Error(`WebGL2 shell program lost uniform ${name}`);
  }
  return result;
}

function imageUrl(baseUrl: string, atlas: AtlasDescriptor): string {
  return `${baseUrl.replace(/\/$/, "")}/${atlas.file}`;
}

function loadImage(url: string, atlasId: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener("load", () => {
      resolve(image);
    }, { once: true });
    image.addEventListener(
      "error",
      () => {
        reject(new Error(`assetpack atlas ${atlasId} failed to load from ${url}`));
      },
      { once: true },
    );
    image.src = url;
  });
}

function rectVertices(
  rectangle: NativeRect,
  uv: readonly [number, number, number, number, number, number, number, number],
  topColor: readonly [number, number, number, number],
  bottomColor: readonly [number, number, number, number],
): Float32Array {
  const [left, top, right, bottom] = rectangle;
  const [u0, v0, u1, v1, u2, v2, u3, v3] = uv;
  return new Float32Array([
    left, top, u0, v0, ...topColor,
    right, top, u1, v1, ...topColor,
    left, bottom, u3, v3, ...bottomColor,
    left, bottom, u3, v3, ...bottomColor,
    right, top, u1, v1, ...topColor,
    right, bottom, u2, v2, ...bottomColor,
  ]);
}

interface SpriteSlice {
  readonly rectangle: NativeRect;
  readonly uv: readonly [number, number, number, number, number, number, number, number];
}

function spriteSlice(
  clipped: NativeRect,
  unclipped: NativeRect,
  quarterTurn: boolean,
  flip: readonly [boolean, boolean],
): SpriteSlice | null {
  const [unclippedLeft, unclippedTop, unclippedRight, unclippedBottom] = unclipped;
  const width = unclippedRight - unclippedLeft;
  const height = unclippedBottom - unclippedTop;
  if (!(width > 0) || !(height > 0)) {
    return null;
  }
  const left = Math.max(0, clipped[0], Math.min(unclippedLeft, unclippedRight));
  const top = Math.max(0, clipped[1], Math.min(unclippedTop, unclippedBottom));
  const right = Math.min(1600, clipped[2], Math.max(unclippedLeft, unclippedRight));
  const bottom = Math.min(900, clipped[3], Math.max(unclippedTop, unclippedBottom));
  if (!(right > left) || !(bottom > top)) {
    return null;
  }

  // Mirroring reflects the normalized source coordinates before uv assembly, so
  // it stays exact for clipped sprites and composes with the quarter turn.
  let x0 = (left - unclippedLeft) / width;
  let x1 = (right - unclippedLeft) / width;
  let y0 = (top - unclippedTop) / height;
  let y1 = (bottom - unclippedTop) / height;
  if (flip[0]) {
    x0 = 1 - x0;
    x1 = 1 - x1;
  }
  if (flip[1]) {
    y0 = 1 - y0;
    y1 = 1 - y1;
  }
  const uv = quarterTurn
    ? [y0, 1 - x0, y0, 1 - x1, y1, 1 - x1, y1, 1 - x0] as const
    : [x0, y0, x1, y0, x1, y1, x0, y1] as const;
  return { rectangle: [left, top, right, bottom], uv };
}

function glyphAdvance(entry: AssetEntry): number {
  return Math.max(1, entry.logicalSize.width);
}

function kerning(font: FontGroup, left: number, right: number): number {
  return font.kerning.find((pair) => pair.leftGlyphId === left && pair.rightGlyphId === right)?.adjustment ?? 0;
}

export class WebGlShellRenderer {
  readonly #gl: WebGL2RenderingContext;
  readonly #assets: ManifestAssets;
  readonly #baseUrl: string;
  readonly #program: WebGLProgram;
  readonly #buffer: WebGLBuffer;
  readonly #resolution: WebGLUniformLocation;
  readonly #atlasImages = new Map<string, HTMLImageElement>();
  readonly #loading = new Map<string, Promise<HTMLImageElement>>();
  readonly #assetTextures = new Map<string, TextureRecord>();
  readonly #systemTextures = new Map<string, TextureRecord>();
  readonly #whiteTexture: TextureRecord;

  public constructor(
    canvas: HTMLCanvasElement,
    assets: ManifestAssets,
    baseUrl = "/assetpack",
  ) {
    const gl = canvas.getContext("webgl2", {
      alpha: false,
      antialias: false,
      depth: false,
      premultipliedAlpha: false,
      preserveDrawingBuffer: true,
      stencil: false,
    });
    if (gl === null) {
      throw new Error("WebGL2 is required for the Solomon Dark browser shell");
    }
    this.#gl = gl;
    this.#assets = assets;
    this.#baseUrl = baseUrl;
    this.#program = program(gl);
    const buffer = gl.createBuffer();
    this.#buffer = buffer;
    this.#resolution = uniform(gl, this.#program, "u_resolution");

    gl.useProgram(this.#program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.#buffer);
    const stride = 8 * Float32Array.BYTES_PER_ELEMENT;
    const position = location(gl, this.#program, "a_position");
    const texcoord = location(gl, this.#program, "a_texcoord");
    const color = location(gl, this.#program, "a_color");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(texcoord);
    gl.vertexAttribPointer(texcoord, 2, gl.FLOAT, false, stride, 2 * Float32Array.BYTES_PER_ELEMENT);
    gl.enableVertexAttribArray(color);
    gl.vertexAttribPointer(color, 4, gl.FLOAT, false, stride, 4 * Float32Array.BYTES_PER_ELEMENT);
    gl.uniform1i(uniform(gl, this.#program, "u_texture"), 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.#whiteTexture = this.#createPixelTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
  }

  public async prepare(plan: RenderPlan): Promise<void> {
    const requestedAssets = new Map<string, SpriteDraw["asset"]>();
    for (const command of plan.commands) {
      if (command.kind === "sprite") {
        requestedAssets.set(command.asset.canonicalId, command.asset);
      }
    }
    for (const command of plan.commands) {
      if (command.kind !== "atlas-text") {
        continue;
      }
      for (const character of command.text) {
        const glyph = this.#assets.glyph(command.fontId, character);
        if (glyph !== null) {
          requestedAssets.set(glyph.canonicalId, glyph);
        }
      }
    }
    const atlasIds = new Set([...requestedAssets.values()].map((asset) => asset.atlas.id));
    await Promise.all([...atlasIds].map(async (atlasId) => {
      const atlas = this.#assets.manifest.atlases.find((candidate) => candidate.id === atlasId);
      if (atlas === undefined) {
        throw new Error(`render plan names absent assetpack atlas ${atlasId}`);
      }
      await this.#atlasImage(atlas);
    }));
    for (const asset of requestedAssets.values()) {
      this.#assetTexture(asset);
    }
  }

  public render(plan: RenderPlan): void {
    const gl = this.#gl;
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
    gl.clearColor(...plan.clearColor);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.#program);
    gl.uniform2f(this.#resolution, plan.nativeViewport[0], plan.nativeViewport[1]);
    for (const command of plan.commands) {
      this.#draw(command);
    }
  }

  #draw(command: DrawCommand): void {
    if (command.kind === "sprite") {
      this.#drawSprite(command);
    } else if (command.kind === "solid") {
      this.#drawSolid(command);
    } else if (command.kind === "atlas-text") {
      this.#drawAtlasText(command);
    } else if (command.kind === "system-text") {
      this.#drawSystemText(command);
    } else {
      const [left, top, right, bottom] = command.rect;
      const thickness = 3;
      const bars: NativeRect[] = [
        [left, top, right, top + thickness],
        [left, bottom - thickness, right, bottom],
        [left, top, left + thickness, bottom],
        [right - thickness, top, right, bottom],
      ];
      for (const rectangle of bars) {
        this.#drawQuad(
          rectangle,
          [0, 0, 1, 1, 1, 1, 0, 0],
          command.colorTop,
          command.colorBottom,
          this.#whiteTexture,
        );
      }
    }
  }

  #drawSprite(command: SpriteDraw): void {
    const texture = this.#assetTextures.get(command.asset.canonicalId);
    if (texture === undefined) {
      throw new Error(`assetpack sprite ${command.asset.requestedId} was not prepared before drawing ${command.elementId}`);
    }
    const [left, top, right, bottom] = command.unclippedRect;
    const sourceAspect = texture.width / texture.height;
    const destinationAspect = Math.abs((right - left) / (bottom - top));
    const quarterTurn = command.asset.entry.rotated || (
      Math.abs(Math.log(destinationAspect * sourceAspect))
      < Math.abs(Math.log(destinationAspect / sourceAspect))
    );
    const slice = spriteSlice(command.rect, command.unclippedRect, quarterTurn, command.flip ?? [false, false]);
    if (slice === null) {
      return;
    }
    const movingTitleScenery = /^Title\.(1[6-9]|2[0-4])$/.test(command.asset.canonicalId);
    const titleSky = /^Title\.[0-4]$/.test(command.asset.canonicalId);
    const tint: readonly [number, number, number, number] = movingTitleScenery
      ? [0.56, 0.59, 0.72, 1]
      : titleSky
        ? [0.62, 0.64, 0.75, 1]
        : [1, 1, 1, 1];
    this.#drawQuad(
      slice.rectangle,
      slice.uv,
      tint,
      tint,
      texture,
    );
  }

  #drawSolid(command: SolidDraw): void {
    this.#drawQuad(
      command.unclippedRect,
      [0, 0, 1, 0, 1, 1, 0, 1],
      command.colorTop,
      command.colorBottom,
      this.#whiteTexture,
    );
  }

  #drawAtlasText(command: AtlasTextDraw): void {
    const font = this.#assets.font(command.fontId);
    if (!("glyphs" in font)) {
      throw new Error(`${command.elementId} expected an assetpack bitmap font group`);
    }
    const glyphs = Array.from(command.text, (character) => ({
      character,
      asset: this.#assets.glyph(command.fontId, character),
    }));
    const rawWidth = glyphs.reduce((total, glyph, index) => {
      const previous = glyphs[index - 1];
      const kern = previous === undefined
        ? 0
        : kerning(font, previous.character.codePointAt(0) ?? 0, glyph.character.codePointAt(0) ?? 0);
      return total + kern + (glyph.asset === null ? font.metrics[1] : glyphAdvance(glyph.asset.entry));
    }, 0);
    if (rawWidth <= 0) {
      return;
    }
    const [left, top, right, bottom] = command.unclippedRect;
    const scale = (right - left) / rawWidth;
    let x = left;
    for (const [index, glyph] of glyphs.entries()) {
      const previous = glyphs[index - 1];
      if (previous !== undefined) {
        x += kerning(font, previous.character.codePointAt(0) ?? 0, glyph.character.codePointAt(0) ?? 0) * scale;
      }
      const width = (glyph.asset === null ? font.metrics[1] : glyphAdvance(glyph.asset.entry)) * scale;
      if (glyph.asset !== null) {
        const texture = this.#assetTextures.get(glyph.asset.canonicalId);
        if (texture === undefined) {
          throw new Error(`assetpack glyph ${glyph.asset.requestedId} was not prepared for ${command.elementId}`);
        }
        const tint = command.color ?? [0.86, 0.74, 0.42, 1];
        this.#drawQuad(
          [x, top, x + width, bottom],
          [0, 0, 1, 0, 1, 1, 0, 1],
          tint,
          tint,
          texture,
        );
      }
      x += width;
    }
  }

  #drawSystemText(command: SystemTextDraw): void {
    const width = Math.max(1, Math.ceil(command.unclippedRect[2] - command.unclippedRect[0]));
    const height = Math.max(1, Math.ceil(command.unclippedRect[3] - command.unclippedRect[1]));
    const key = `${command.fontId}\0${command.fontWeight}\0${command.fontHeight}\0${command.text}\0${command.color.join(",")}\0${width}x${height}`;
    let texture = this.#systemTextures.get(key);
    if (texture === undefined) {
      const canvas = new OffscreenCanvas(width, height);
      const context = canvas.getContext("2d");
      if (context === null) {
        throw new Error(`system-font special draw could not allocate ${command.elementId}`);
      }
      context.clearRect(0, 0, width, height);
      const [red, green, blue, alpha] = command.color;
      context.fillStyle = `rgba(${Math.round(red * 255)}, ${Math.round(green * 255)}, ${Math.round(blue * 255)}, ${alpha})`;
      context.font = `${command.fontWeight} ${command.fontHeight}px "Segoe UI", sans-serif`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(command.text, width / 2, height / 2);
      const pixels = context.getImageData(0, 0, width, height).data;
      texture = this.#createPixelTexture(new Uint8Array(pixels), width, height);
      this.#systemTextures.set(key, texture);
    }
    this.#drawQuad(
      command.unclippedRect,
      [0, 0, 1, 0, 1, 1, 0, 1],
      [1, 1, 1, 1],
      [1, 1, 1, 1],
      texture,
    );
  }

  #drawQuad(
    rectangle: NativeRect,
    uv: readonly [number, number, number, number, number, number, number, number],
    topColor: readonly [number, number, number, number],
    bottomColor: readonly [number, number, number, number],
    texture: TextureRecord,
  ): void {
    const gl = this.#gl;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture.texture);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.#buffer);
    gl.bufferData(gl.ARRAY_BUFFER, rectVertices(rectangle, uv, topColor, bottomColor), gl.STREAM_DRAW);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  #atlasImage(atlas: AtlasDescriptor): Promise<HTMLImageElement> {
    const present = this.#atlasImages.get(atlas.id);
    if (present !== undefined) {
      return Promise.resolve(present);
    }
    const pending = this.#loading.get(atlas.id);
    if (pending !== undefined) {
      return pending;
    }
    const promise = loadImage(imageUrl(this.#baseUrl, atlas), atlas.id).then((image) => {
      if (image.naturalWidth !== atlas.width || image.naturalHeight !== atlas.height) {
        throw new Error(
          `assetpack atlas ${atlas.id} dimensions ${image.naturalWidth}x${image.naturalHeight} do not match manifest ${atlas.width}x${atlas.height}`,
        );
      }
      this.#atlasImages.set(atlas.id, image);
      return image;
    });
    this.#loading.set(atlas.id, promise);
    return promise;
  }

  #assetTexture(asset: SpriteDraw["asset"]): TextureRecord {
    const present = this.#assetTextures.get(asset.canonicalId);
    if (present !== undefined) {
      return present;
    }
    const image = this.#atlasImages.get(asset.atlas.id);
    if (image === undefined) {
      throw new Error(`assetpack atlas ${asset.atlas.id} was not loaded before cropping ${asset.requestedId}`);
    }
    const source = asset.entry.rect;
    const canvas = new OffscreenCanvas(source.width, source.height);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (context === null) {
      throw new Error(`assetpack sprite ${asset.requestedId} could not allocate a crop surface`);
    }
    context.clearRect(0, 0, source.width, source.height);
    context.drawImage(
      image,
      source.x,
      source.y,
      source.width,
      source.height,
      0,
      0,
      source.width,
      source.height,
    );
    const pixels = context.getImageData(0, 0, source.width, source.height).data;
    const texture = this.#createPixelTexture(new Uint8Array(pixels), source.width, source.height);
    this.#assetTextures.set(asset.canonicalId, texture);
    return texture;
  }

  #createPixelTexture(bytes: Uint8Array, width: number, height: number): TextureRecord {
    const gl = this.#gl;
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
    this.#setTextureParameters();
    return { texture, width, height };
  }

  #setTextureParameters(): void {
    const gl = this.#gl;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }
}
