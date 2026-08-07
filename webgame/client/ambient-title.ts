import ambientJson from "./ambient-title-data.json" with { type: "json" };
import type { ResolvedAsset } from "./manifest-assets.js";
import type { NativeRect } from "./menu-catalog.js";
import { NATIVE_WIDTH } from "./render-plan.js";
import type { DrawCommand, RenderPlan, SpriteDraw } from "./render-plan.js";

// ATC-PREVIEW 2026-08-07: interim ambient layer for the four Title-backdrop
// screens, derived from the sealed v6 dual-instance traces (provenance and
// source sha256 pins live in ambient-title-data.json). The landed fixtures
// froze the title chrome UNDER the opaque sky bands and parked the ambient
// family mid-flight; this layer restores the native paint sequence on the
// trace-complete screens and replaces the ambient family with the derived
// motion model. Fixtures, conformance replay, and the semantic `elements`
// contract are untouched. Superseded by shellfix (#101), which owns the
// settled-capture fixture refresh.

/** Screens whose backdrop the preview animates, by treatment. `full` means
 * every non-ambient sprite in the fixture matched the trace static contract
 * by (art, rect), so the native paint order is restored outright; `pool`
 * screens carry content absent from the trace, so only the ambient family is
 * replaced, placed relative to the trace-matched anchors inside the block. */
const SCREEN_MODES: ReadonlyMap<string, "full" | "pool"> = new Map([
  ["beta-notice", "full"],
  ["main-menu-root", "full"],
  ["game-settings-title", "pool"],
  ["profile-save-select", "pool"],
]);

export interface SpriteResolver {
  resolve(id: string): ResolvedAsset;
}

interface AmbientBand {
  readonly art: string;
  readonly y0: number;
  readonly y1: number;
  readonly w: number;
  readonly v: number;
  readonly b0: number;
  readonly orderBase: number;
}

interface AmbientDrifter {
  readonly id: string;
  readonly art: string;
  readonly order: number;
  readonly gap: number;
  readonly x0: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
  readonly v: number;
}

interface FlameWindow {
  readonly start: number;
  readonly end: number;
}

interface AmbientFlame {
  readonly id: string;
  readonly art: string;
  readonly order: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
  readonly onWindows: readonly FlameWindow[];
}

interface BobberFrame {
  readonly t: number;
  readonly rect: NativeRect;
}

interface AmbientBobber {
  readonly id: string;
  readonly art: string;
  readonly order: number;
  readonly first: BobberFrame;
  readonly frames: readonly BobberFrame[];
}

interface AmbientModel {
  readonly loopMs: number;
  readonly timeBase: number;
  readonly bands: readonly AmbientBand[];
  readonly drifters: readonly AmbientDrifter[];
  readonly flames: readonly AmbientFlame[];
  readonly bobber: AmbientBobber;
  readonly staticOrder: ReadonlyMap<string, number>;
  readonly arts: ReadonlySet<string>;
  readonly maxTraceOrder: number;
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function rect(value: unknown, label: string): NativeRect {
  const values = array(value, label);
  if (values.length !== 4) {
    throw new Error(`${label} must be a native [left, top, right, bottom] rectangle`);
  }
  return [
    number(values[0], `${label}[0]`),
    number(values[1], `${label}[1]`),
    number(values[2], `${label}[2]`),
    number(values[3], `${label}[3]`),
  ];
}

function parseBand(value: unknown, index: number): AmbientBand {
  const source = object(value, `bands[${index}]`);
  const width = number(source.w, `bands[${index}].w`);
  if (width <= 0) {
    throw new Error(`bands[${index}] tile width must be positive`);
  }
  return {
    art: string(source.art, `bands[${index}].art`),
    y0: number(source.y0, `bands[${index}].y0`),
    y1: number(source.y1, `bands[${index}].y1`),
    w: width,
    v: number(source.v, `bands[${index}].v`),
    b0: number(source.b0, `bands[${index}].b0`),
    orderBase: number(source.orderBase, `bands[${index}].orderBase`),
  };
}

function parseDrifter(
  value: unknown,
  index: number,
  zoneGap: ReadonlyMap<number, number>,
): AmbientDrifter {
  const source = object(value, `drifters[${index}]`);
  const zone = number(source.zone, `drifters[${index}].zone`);
  const gap = zoneGap.get(zone);
  if (gap === undefined) {
    throw new Error(`drifters[${index}] names depth zone ${zone} without a respawn gap`);
  }
  const width = number(source.w, `drifters[${index}].w`);
  if (width <= 0) {
    throw new Error(`drifters[${index}] puff width must be positive`);
  }
  return {
    id: string(source.id, `drifters[${index}].id`),
    art: string(source.art, `drifters[${index}].art`),
    order: number(source.order, `drifters[${index}].order`),
    gap,
    x0: number(source.x0, `drifters[${index}].x0`),
    y: number(source.y, `drifters[${index}].y`),
    w: width,
    h: number(source.h, `drifters[${index}].h`),
    v: number(source.v, `drifters[${index}].v`),
  };
}

function parseFlame(value: unknown, index: number): AmbientFlame {
  const source = object(value, `flames[${index}]`);
  const onWindows = array(source.onWindows, `flames[${index}].onWindows`).map(
    (entry, windowIndex) => {
      const pair = array(entry, `flames[${index}].onWindows[${windowIndex}]`);
      if (pair.length !== 2) {
        throw new Error(`flames[${index}].onWindows[${windowIndex}] must be a [start, end] pair`);
      }
      const start = number(pair[0], `flames[${index}].onWindows[${windowIndex}][0]`);
      const end = number(pair[1], `flames[${index}].onWindows[${windowIndex}][1]`);
      if (end < start) {
        throw new Error(`flames[${index}].onWindows[${windowIndex}] must not end before it starts`);
      }
      return { start, end };
    },
  );
  return {
    id: string(source.id, `flames[${index}].id`),
    art: string(source.art, `flames[${index}].art`),
    order: number(source.order, `flames[${index}].order`),
    rect: rect(source.rect, `flames[${index}].rect`),
    unclippedRect: rect(source.unclippedRect, `flames[${index}].unclippedRect`),
    onWindows,
  };
}

function parseBobber(value: unknown): AmbientBobber {
  const source = object(value, "bobber");
  const frames = array(source.frames, "bobber.frames").map((entry, index) => ({
    t: number(object(entry, `bobber.frames[${index}]`).t, `bobber.frames[${index}].t`),
    rect: rect(object(entry, `bobber.frames[${index}]`).rect, `bobber.frames[${index}].rect`),
  }));
  const first = frames[0];
  if (first === undefined) {
    throw new Error("bobber must carry at least one keyframe");
  }
  for (let index = 1; index < frames.length; index += 1) {
    const previous = frames[index - 1];
    const current = frames[index];
    if (previous === undefined || current === undefined || current.t < previous.t) {
      throw new Error("bobber keyframes must be sorted by time");
    }
  }
  return {
    id: string(source.id, "bobber.id"),
    art: string(source.art, "bobber.art"),
    order: number(source.order, "bobber.order"),
    first,
    frames,
  };
}

function parseModel(value: unknown): AmbientModel {
  const root = object(value, "ambient title data");
  const loopMs = number(root.loopMs, "loopMs");
  if (loopMs <= 0) {
    throw new Error("ambient loop length must be positive");
  }
  const zoneGap = new Map<number, number>();
  for (const [key, raw] of Object.entries(object(root.zoneGapPx, "zoneGapPx"))) {
    const zone = Number.parseInt(key, 10);
    if (!Number.isSafeInteger(zone)) {
      throw new Error(`zoneGapPx key ${key} is not a depth zone`);
    }
    const gap = number(raw, `zoneGapPx.${key}`);
    if (gap < 0) {
      throw new Error(`zoneGapPx.${key} must not be negative`);
    }
    zoneGap.set(zone, gap);
  }
  const bands = array(root.bands, "bands").map(parseBand);
  const drifters = array(root.drifters, "drifters").map((entry, index) => (
    parseDrifter(entry, index, zoneGap)
  ));
  const flames = array(root.flames, "flames").map(parseFlame);
  const bobber = parseBobber(root.bobber);
  const staticOrder = new Map<string, number>();
  for (const [key, raw] of Object.entries(object(root.staticOrder, "staticOrder"))) {
    staticOrder.set(key, number(raw, `staticOrder.${key}`));
  }
  if (staticOrder.size === 0) {
    throw new Error("trace static paint order must not be empty");
  }
  const arts = new Set<string>();
  for (const band of bands) {
    arts.add(band.art);
  }
  for (const drifter of drifters) {
    arts.add(drifter.art);
  }
  for (const flame of flames) {
    arts.add(flame.art);
  }
  arts.add(bobber.art);
  const maxTraceOrder = Math.max(
    bobber.order,
    ...bands.map((band) => band.orderBase + 1),
    ...drifters.map((drifter) => drifter.order),
    ...flames.map((flame) => flame.order),
  );
  return {
    loopMs,
    timeBase: bobber.first.t,
    bands,
    drifters,
    flames,
    bobber,
    staticOrder,
    arts,
    maxTraceOrder,
  };
}

function positiveModulo(value: number, period: number): number {
  return ((value % period) + period) % period;
}

function staticKey(command: SpriteDraw): string {
  const encoded = command.rect.map((component) => component.toFixed(1)).join(",");
  return `${command.asset.requestedId}|${encoded}`;
}

function identityOrder(traceOrder: number): number {
  return traceOrder;
}

function lerp(from: number, to: number, factor: number): number {
  return from + (to - from) * factor;
}

interface OrderAnchor {
  readonly trace: number;
  readonly fixture: number;
}

type LayoutMode =
  | { readonly kind: "full"; readonly orders: ReadonlyMap<string, number> }
  | { readonly kind: "pool"; readonly transform: (traceOrder: number) => number };

export class AmbientTitleLayer {
  readonly #resolver: SpriteResolver;
  readonly #model: AmbientModel;
  readonly #assets = new Map<string, ResolvedAsset>();
  readonly #modes = new Map<string, LayoutMode>();

  public constructor(resolver: SpriteResolver, data: unknown = ambientJson) {
    this.#resolver = resolver;
    this.#model = parseModel(data);
  }

  public handles(layoutId: string): boolean {
    return SCREEN_MODES.has(layoutId);
  }

  /** Warm-up variant of a plan whose prepared asset set covers every ambient
   * art, so the per-frame synthesized sprites never reach an unprepared
   * texture. The appended commands are prepare-only and never rendered. */
  public augmentForPrepare(plan: RenderPlan): RenderPlan {
    const warmup = [...this.#model.arts].map((art, index) => (
      this.#sprite(`ambient.warmup.${index}`, art, [0, 0, 8, 8], 0)
    ));
    return { ...plan, commands: [...plan.commands, ...warmup] };
  }

  /** Rebuild the plan's draw commands for elapsed shell time `tMs`: the frozen
   * ambient family is replaced by the derived motion model, and on `full`
   * screens the surviving statics take their native trace paint order. The
   * semantic `elements` array passes through untouched. */
  public apply(plan: RenderPlan, tMs: number): RenderPlan {
    const mode = this.#mode(plan);
    if (mode === null) {
      return plan;
    }
    const base: DrawCommand[] = [];
    const text: DrawCommand[] = [];
    const tail: DrawCommand[] = [];
    for (const command of plan.commands) {
      if (command.kind === "atlas-text" || command.kind === "system-text") {
        text.push(command);
        continue;
      }
      if (command.kind === "focus") {
        tail.push(command);
        continue;
      }
      if (command.kind === "sprite" && this.#isAmbientArt(command)) {
        continue;
      }
      if (mode.kind === "full") {
        if (command.kind !== "sprite") {
          throw new Error(
            `${plan.layoutId} carries a ${command.kind} base draw outside the trace static contract (${command.elementId})`,
          );
        }
        const order = mode.orders.get(command.elementId);
        if (order === undefined) {
          throw new Error(`${plan.layoutId} sprite ${command.elementId} appeared after the paint order was derived`);
        }
        base.push({ ...command, drawOrder: order });
      } else {
        base.push(command);
      }
    }
    const transform = mode.kind === "full" ? identityOrder : mode.transform;
    base.push(...this.#ambientSprites(tMs, transform));
    base.sort((left, right) => left.drawOrder - right.drawOrder);
    return { ...plan, commands: [...base, ...text, ...tail] };
  }

  #mode(plan: RenderPlan): LayoutMode | null {
    const expected = SCREEN_MODES.get(plan.layoutId);
    if (expected === undefined) {
      return null;
    }
    const cached = this.#modes.get(plan.layoutId);
    if (cached !== undefined) {
      return cached;
    }
    const kept: SpriteDraw[] = [];
    const dropped: SpriteDraw[] = [];
    for (const command of plan.commands) {
      if (command.kind !== "sprite") {
        continue;
      }
      (this.#isAmbientArt(command) ? dropped : kept).push(command);
    }
    if (dropped.length === 0) {
      throw new Error(`ambient preview expected ${plan.layoutId} to carry frozen title-family members`);
    }
    let mode: LayoutMode;
    if (expected === "full") {
      const orders = new Map<string, number>();
      const missing: string[] = [];
      for (const command of kept) {
        const order = this.#model.staticOrder.get(staticKey(command));
        if (order === undefined) {
          missing.push(`${command.elementId} (${staticKey(command)})`);
        } else {
          orders.set(command.elementId, order);
        }
      }
      if (missing.length > 0) {
        throw new Error(
          `ambient preview cannot restore ${plan.layoutId} paint order; sprites missing from the trace static contract: ${missing.join("; ")}`,
        );
      }
      mode = { kind: "full", orders };
    } else {
      mode = { kind: "pool", transform: this.#poolTransform(kept, dropped) };
    }
    this.#modes.set(plan.layoutId, mode);
    return mode;
  }

  /** Piecewise-linear map from trace paint order into the fixture's vacated
   * ambient block, anchored on trace-matched statics (Title.6 tree line,
   * Title.3 tree top, Title.9 logo where present) so depth relations against
   * the kept backdrop survive on screens the trace never covered. */
  #poolTransform(
    kept: readonly SpriteDraw[],
    dropped: readonly SpriteDraw[],
  ): (traceOrder: number) => number {
    const orders = dropped.map((command) => command.drawOrder);
    const blockMin = Math.min(...orders);
    const blockMax = Math.max(...orders);
    const anchors: OrderAnchor[] = [{ trace: 0, fixture: blockMin - 0.5 }];
    const interior = kept
      .filter((command) => command.drawOrder > blockMin && command.drawOrder < blockMax)
      .flatMap((command) => {
        const trace = this.#model.staticOrder.get(staticKey(command));
        return trace === undefined ? [] : [{ trace, fixture: command.drawOrder }];
      })
      .sort((left, right) => left.trace - right.trace);
    for (const anchor of interior) {
      const last = anchors[anchors.length - 1];
      if (last !== undefined && anchor.trace > last.trace && anchor.fixture > last.fixture) {
        anchors.push(anchor);
      }
    }
    anchors.push({ trace: this.#model.maxTraceOrder + 1, fixture: blockMax + 0.5 });
    return (traceOrder: number): number => {
      const first = anchors[0];
      const final = anchors[anchors.length - 1];
      if (first === undefined || final === undefined) {
        throw new Error("ambient order anchors were lost");
      }
      const clamped = Math.min(Math.max(traceOrder, first.trace), final.trace);
      for (let index = 1; index < anchors.length; index += 1) {
        const left = anchors[index - 1];
        const right = anchors[index];
        if (left === undefined || right === undefined) {
          break;
        }
        if (clamped <= right.trace) {
          const span = right.trace - left.trace;
          const factor = span > 0 ? (clamped - left.trace) / span : 0;
          return lerp(left.fixture, right.fixture, factor);
        }
      }
      return final.fixture;
    };
  }

  #ambientSprites(tMs: number, transform: (traceOrder: number) => number): SpriteDraw[] {
    const model = this.#model;
    const sprites: SpriteDraw[] = [];
    for (const band of model.bands) {
      const boundary = band.b0 + band.v * tMs / 1000;
      let x = positiveModulo(boundary, band.w) - band.w;
      for (let index = 0; x < NATIVE_WIDTH; index += 1, x += band.w) {
        if (x + band.w <= 0) {
          continue;
        }
        sprites.push(this.#sprite(
          `ambient.${band.art}.tile${index}`,
          band.art,
          [x, band.y0, x + band.w, band.y1],
          transform(band.orderBase + index * 0.3),
        ));
      }
    }
    const traceNow = tMs + model.timeBase;
    for (const drifter of model.drifters) {
      const span = NATIVE_WIDTH + drifter.gap + drifter.w;
      const raw = drifter.x0 + drifter.v * traceNow / 1000;
      const x = -drifter.w + positiveModulo(raw + drifter.w, span);
      if (x >= NATIVE_WIDTH || x + drifter.w <= 0) {
        continue;
      }
      sprites.push(this.#sprite(
        `ambient.${drifter.id}`,
        drifter.art,
        [x, drifter.y, x + drifter.w, drifter.y + drifter.h],
        transform(drifter.order),
      ));
    }
    const cycleT = model.timeBase + positiveModulo(tMs, model.loopMs);
    for (const flame of model.flames) {
      if (!flame.onWindows.some((window) => cycleT >= window.start && cycleT <= window.end)) {
        continue;
      }
      sprites.push(this.#clippedSprite(
        `ambient.${flame.id}`,
        flame.art,
        flame.rect,
        flame.unclippedRect,
        transform(flame.order),
      ));
    }
    let from = model.bobber.first;
    let to = model.bobber.first;
    for (const frame of model.bobber.frames) {
      if (frame.t <= cycleT) {
        from = frame;
        to = frame;
      } else {
        to = frame;
        break;
      }
    }
    const factor = to.t > from.t ? (cycleT - from.t) / (to.t - from.t) : 0;
    sprites.push(this.#sprite(
      `ambient.${model.bobber.id}`,
      model.bobber.art,
      [
        lerp(from.rect[0], to.rect[0], factor),
        lerp(from.rect[1], to.rect[1], factor),
        lerp(from.rect[2], to.rect[2], factor),
        lerp(from.rect[3], to.rect[3], factor),
      ],
      transform(model.bobber.order),
    ));
    return sprites;
  }

  #isAmbientArt(command: SpriteDraw): boolean {
    return this.#model.arts.has(command.asset.requestedId)
      || this.#model.arts.has(command.asset.canonicalId);
  }

  #sprite(elementId: string, art: string, rectangle: NativeRect, drawOrder: number): SpriteDraw {
    return this.#clippedSprite(elementId, art, rectangle, rectangle, drawOrder);
  }

  #clippedSprite(
    elementId: string,
    art: string,
    clipped: NativeRect,
    unclipped: NativeRect,
    drawOrder: number,
  ): SpriteDraw {
    return {
      kind: "sprite",
      elementId,
      layer: "screen-overlay",
      drawOrder,
      rect: clipped,
      unclippedRect: unclipped,
      asset: this.#asset(art),
    };
  }

  #asset(art: string): ResolvedAsset {
    const present = this.#assets.get(art);
    if (present !== undefined) {
      return present;
    }
    const resolved = this.#resolver.resolve(art);
    this.#assets.set(art, resolved);
    return resolved;
  }
}
