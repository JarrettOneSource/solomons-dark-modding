import type { ManifestAssets, ResolvedAsset } from "./manifest-assets.js";
import type { MenuElement, MenuLayout, NativeRect } from "./menu-catalog.js";

export const NATIVE_WIDTH = 1600;
export const NATIVE_HEIGHT = 900;

export const G12_LAYER_ORDER = [
  "framebuffer-clear",
  "scene-underlay",
  "world-sorted",
  "scene-overdraw",
  "screen-overlay",
] as const;

export type G12Layer = typeof G12_LAYER_ORDER[number];

interface DrawBase {
  readonly elementId: string;
  readonly layer: "screen-overlay";
  readonly drawOrder: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
}

export interface SpriteDraw extends DrawBase {
  readonly kind: "sprite";
  readonly asset: ResolvedAsset;
  // [flip-x, flip-y]. The G11 payload schema has no orientation field, so natively
  // mirrored placements capture as identical un-flipped draws; the ATC-preview
  // orientation layer (native-orientation.ts) restores the mirrors at render time.
  readonly flip?: readonly [boolean, boolean];
  // Placement quarter turn, set only by a plan layer that knows the native
  // placement (the renderer never guesses orientation from aspect ratios).
  readonly quarterTurn?: boolean;
}

export interface SolidDraw extends DrawBase {
  readonly kind: "solid";
  readonly colorTop: readonly [number, number, number, number];
  readonly colorBottom: readonly [number, number, number, number];
}

export interface AtlasTextDraw extends DrawBase {
  readonly kind: "atlas-text";
  readonly fontId: string;
  readonly text: string;
  // Glyph tint; absent means the native menu gold. The beta-notice dialog body is
  // the one captured surface with white/yellow text (see beta-dialog.ts).
  readonly color?: readonly [number, number, number, number];
  // Measured per-glyph placement (native 1600x900 content-box corners) from
  // text-layout.ts. Absent means the renderer's rect-anchored model layout.
  readonly glyphLayout?: readonly { readonly ch: string; readonly x: number; readonly y: number }[];
}

export interface SystemTextDraw extends DrawBase {
  readonly kind: "system-text";
  readonly fontId: "Segoe UI";
  readonly text: string;
  readonly color: readonly [number, number, number, number];
  readonly fontHeight: number;
  readonly fontWeight: number;
}

export interface FocusDraw {
  readonly kind: "focus";
  readonly elementId: "shell.focus";
  readonly layer: "screen-overlay";
  readonly drawOrder: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
  readonly colorTop: readonly [number, number, number, number];
  readonly colorBottom: readonly [number, number, number, number];
}

export type DrawCommand = SpriteDraw | SolidDraw | AtlasTextDraw | SystemTextDraw | FocusDraw;

export interface PlannedElement {
  readonly id: string;
  readonly kind: string;
  readonly artId: string;
  readonly fontId: string;
  readonly visible: boolean;
  readonly interactive: boolean;
  readonly actionId: string;
  readonly drawOrder: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
}

export interface RenderPlan {
  readonly layoutId: string;
  readonly nativeViewport: readonly [1600, 900];
  readonly layerOrder: typeof G12_LAYER_ORDER;
  readonly clearColor: readonly [number, number, number, number];
  readonly elements: readonly PlannedElement[];
  readonly commands: readonly DrawCommand[];
}

function parseArgb(value: string, consequence: string): readonly [number, number, number, number] {
  const match = /^#([0-9A-Fa-f]{8})$/.exec(value);
  if (match?.[1] === undefined) {
    throw new Error(`${consequence} requires a #AARRGGBB color, received ${value}`);
  }
  const encoded = match[1];
  return [
    Number.parseInt(encoded.slice(2, 4), 16) / 255,
    Number.parseInt(encoded.slice(4, 6), 16) / 255,
    Number.parseInt(encoded.slice(6, 8), 16) / 255,
    Number.parseInt(encoded.slice(0, 2), 16) / 255,
  ];
}

function semanticElement(element: MenuElement): PlannedElement {
  return {
    id: element.id,
    kind: element.kind,
    artId: element.artId,
    fontId: element.fontId,
    visible: element.visible,
    interactive: element.interactive,
    actionId: element.actionId,
    drawOrder: element.drawOrder,
    rect: element.rect,
    unclippedRect: element.unclippedRect,
  };
}

function primitive(element: MenuElement): SolidDraw {
  const fallback = element.color ?? "#FFFFFFFF";
  return {
    kind: "solid",
    elementId: element.id,
    layer: "screen-overlay",
    drawOrder: element.drawOrder,
    rect: element.rect,
    unclippedRect: element.unclippedRect,
    colorTop: parseArgb(element.colorTop ?? fallback, `${element.id} top edge`),
    colorBottom: parseArgb(element.colorBottom ?? fallback, `${element.id} bottom edge`),
  };
}

function visualCommand(element: MenuElement, assets: ManifestAssets): DrawCommand | null {
  if (!element.visible) {
    return null;
  }
  if (element.kind === "art") {
    return {
      kind: "sprite",
      elementId: element.id,
      layer: "screen-overlay",
      drawOrder: element.drawOrder,
      rect: element.rect,
      unclippedRect: element.unclippedRect,
      asset: assets.resolve(element.artId),
    };
  }
  if (
    element.kind === "gradient_scrim"
    || element.kind === "progress_border"
    || element.kind === "progress_track"
    || element.kind === "progress_fill"
  ) {
    return primitive(element);
  }
  if (element.kind === "text" && element.fontId.length > 0) {
    const font = assets.font(element.fontId);
    if ("glyphs" in font) {
      return {
        kind: "atlas-text",
        elementId: element.id,
        layer: "screen-overlay",
        drawOrder: element.drawOrder,
        rect: element.rect,
        unclippedRect: element.unclippedRect,
        fontId: element.fontId,
        text: element.text,
      };
    }
    if (font.kind !== "system-font" || element.fontId !== "Segoe UI") {
      throw new Error(`${element.id} requests unsupported manifest special draw ${element.fontId}`);
    }
    return {
      kind: "system-text",
      elementId: element.id,
      layer: "screen-overlay",
      drawOrder: element.drawOrder,
      rect: element.rect,
      unclippedRect: element.unclippedRect,
      fontId: "Segoe UI",
      text: element.text,
      color: parseArgb(element.color ?? "#FFFFFFFF", `${element.id} system text`),
      fontHeight: Math.abs(element.fontHeight ?? -24),
      fontWeight: element.fontWeight ?? 400,
    };
  }
  if (element.kind === "text" || element.kind === "control" || element.kind === "panel") {
    return null;
  }
  throw new Error(`${element.id} has unsupported visible G11 draw kind ${element.kind}`);
}

export function buildRenderPlan(
  layout: MenuLayout,
  assets: ManifestAssets,
  focused: Readonly<{ id: string; rect: NativeRect }> | null,
  showFocus: boolean,
): RenderPlan {
  const commands = layout.elements
    .map((element) => visualCommand(element, assets))
    .filter((command): command is DrawCommand => command !== null);
  const base = commands
    .filter((command) => command.kind !== "atlas-text" && command.kind !== "system-text")
    .sort((left, right) => left.drawOrder - right.drawOrder);
  const text = commands
    .filter((command) => command.kind === "atlas-text" || command.kind === "system-text")
    .sort((left, right) => left.drawOrder - right.drawOrder);
  const ordered: DrawCommand[] = [...base, ...text];
  if (showFocus && focused !== null) {
    const rectangle = focused.rect;
    ordered.push({
      kind: "focus",
      elementId: "shell.focus",
      layer: "screen-overlay",
      drawOrder: Number.MAX_SAFE_INTEGER,
      rect: rectangle,
      unclippedRect: rectangle,
      colorTop: [0.95, 0.78, 0.35, 0.9],
      colorBottom: [0.95, 0.78, 0.35, 0.9],
    });
  }
  return {
    layoutId: layout.id,
    nativeViewport: [NATIVE_WIDTH, NATIVE_HEIGHT],
    layerOrder: G12_LAYER_ORDER,
    clearColor: layout.id === "native-loader" ? [0, 0, 0.33, 1] : [0, 0, 0, 1],
    elements: layout.elements.map(semanticElement),
    commands: ordered,
  };
}

export function withLoaderProgress(plan: RenderPlan, ratio: number): RenderPlan {
  if (plan.layoutId !== "native-loader") {
    throw new Error("real startup progress can only modify the native-loader plan");
  }
  const clamped = Math.max(0, Math.min(1, ratio));
  return {
    ...plan,
    commands: plan.commands.map((command) => {
      if (command.elementId !== "native_loader.art.loader_0.3") {
        return command;
      }
      const [left, top, right, bottom] = command.unclippedRect;
      const progressed: NativeRect = [left, top, left + (right - left) * clamped, bottom];
      return { ...command, rect: progressed, unclippedRect: progressed };
    }),
  };
}

export function buildOutOfScopePlan(message: string, title = "P0 SHELL BOUNDARY"): RenderPlan {
  const background: SolidDraw = {
    kind: "solid",
    elementId: "shell.boundary.background",
    layer: "screen-overlay",
    drawOrder: 1,
    rect: [0, 0, NATIVE_WIDTH, NATIVE_HEIGHT],
    unclippedRect: [0, 0, NATIVE_WIDTH, NATIVE_HEIGHT],
    colorTop: [0.035, 0.045, 0.075, 1],
    colorBottom: [0.005, 0.008, 0.018, 1],
  };
  const heading: AtlasTextDraw = {
    kind: "atlas-text",
    elementId: "shell.boundary.title",
    layer: "screen-overlay",
    drawOrder: 2,
    rect: [480, 300, 1120, 350],
    unclippedRect: [480, 300, 1120, 350],
    fontId: "Fonts.308-349",
    text: title,
  };
  const detail: AtlasTextDraw = {
    kind: "atlas-text",
    elementId: "shell.boundary.message",
    layer: "screen-overlay",
    drawOrder: 3,
    rect: [280, 405, 1320, 437],
    unclippedRect: [280, 405, 1320, 437],
    fontId: "Fonts.216-307",
    text: message.toUpperCase(),
  };
  const hint: AtlasTextDraw = {
    kind: "atlas-text",
    elementId: "shell.boundary.hint",
    layer: "screen-overlay",
    drawOrder: 4,
    rect: [520, 525, 1080, 553],
    unclippedRect: [520, 525, 1080, 553],
    fontId: "Fonts.216-307",
    text: "PRESS MENU FOR PAUSE",
  };
  return {
    layoutId: "shell-out-of-scope",
    nativeViewport: [NATIVE_WIDTH, NATIVE_HEIGHT],
    layerOrder: G12_LAYER_ORDER,
    clearColor: [0, 0, 0, 1],
    elements: [],
    commands: [background, heading, detail, hint],
  };
}
