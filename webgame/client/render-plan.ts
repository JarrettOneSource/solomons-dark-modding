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
  readonly layer: G12Layer;
  readonly drawOrder: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
}

export interface SpriteDraw extends DrawBase {
  readonly kind: "sprite";
  readonly asset: ResolvedAsset;
  readonly flipX: boolean;
  readonly flipY: boolean;
}

export type ScreenQuad = readonly [
  number, number,
  number, number,
  number, number,
  number, number,
];

export interface SceneSpriteDraw extends DrawBase {
  readonly kind: "scene-sprite";
  readonly asset: ResolvedAsset;
  readonly screenQuad: ScreenQuad;
  readonly tint: readonly [number, number, number, number];
  readonly blend: Readonly<{
    enabled: boolean;
    source: number;
    destination: number;
    operation: number;
  }>;
  readonly sourceSpriteId: string;
  readonly nativeTransform: unknown;
  readonly sortKey: unknown;
}

export interface SceneSpecialDraw extends DrawBase {
  readonly kind: "scene-special";
  readonly specialKind: "framebuffer-clear" | "textured-quad";
  readonly screenQuad: ScreenQuad;
  readonly tint: readonly [number, number, number, number];
  readonly blend: SceneSpriteDraw["blend"];
  readonly sourceSpriteId: string;
  readonly nativeTransform: unknown;
  readonly sortKey: unknown;
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
  readonly tint: readonly [number, number, number, number];
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

export type DrawCommand =
  | SpriteDraw
  | SceneSpriteDraw
  | SceneSpecialDraw
  | SolidDraw
  | AtlasTextDraw
  | SystemTextDraw
  | FocusDraw;

export interface PlannedElement {
  readonly id: string;
  readonly kind: string;
  readonly text: string;
  readonly artId: string;
  readonly fontId: string;
  readonly textStyle: string;
  readonly visible: boolean;
  readonly interactive: boolean;
  readonly actionId: string;
  readonly drawOrder: number;
  readonly rect: NativeRect;
  readonly unclippedRect: NativeRect;
  readonly color?: string;
  readonly colorTop?: string;
  readonly colorBottom?: string;
  readonly fontHeight?: number;
  readonly fontWeight?: number;
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
    text: element.text,
    artId: element.artId,
    fontId: element.fontId,
    textStyle: element.textStyle,
    visible: element.visible,
    interactive: element.interactive,
    actionId: element.actionId,
    drawOrder: element.drawOrder,
    rect: element.rect,
    unclippedRect: element.unclippedRect,
    ...(element.color === undefined ? {} : { color: element.color }),
    ...(element.colorTop === undefined ? {} : { colorTop: element.colorTop }),
    ...(element.colorBottom === undefined ? {} : { colorBottom: element.colorBottom }),
    ...(element.fontHeight === undefined ? {} : { fontHeight: element.fontHeight }),
    ...(element.fontWeight === undefined ? {} : { fontWeight: element.fontWeight }),
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

function panel(element: MenuElement): SolidDraw {
  return {
    kind: "solid",
    elementId: element.id,
    layer: "screen-overlay",
    drawOrder: element.drawOrder,
    rect: element.rect,
    unclippedRect: element.unclippedRect,
    colorTop: [0, 0, 0, 0.72],
    colorBottom: [0, 0, 0, 0.72],
  };
}

function visualCommand(element: MenuElement, assets: ManifestAssets): DrawCommand | null {
  if (!element.visible) {
    return null;
  }
  if (element.kind === "art") {
    const centerX = (element.unclippedRect[0] + element.unclippedRect[2]) / 2;
    const centerY = (element.unclippedRect[1] + element.unclippedRect[3]) / 2;
    return {
      kind: "sprite",
      elementId: element.id,
      layer: "screen-overlay",
      drawOrder: element.drawOrder,
      rect: element.rect,
      unclippedRect: element.unclippedRect,
      asset: assets.resolve(element.artId),
      // Native reuses these left/top frame pieces through presentation-space
      // reflection. The aggregate preserves the shared art id and measured
      // destination rectangles, so derive the reflection for the whole family.
      flipX: (element.artId === "UI.17" || element.artId === "UI.54") && centerX > NATIVE_WIDTH / 2,
      flipY: element.artId === "UI.17" && centerY > NATIVE_HEIGHT / 2,
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
  if (element.kind === "panel") {
    return panel(element);
  }
  if (element.kind === "text" && element.fontId.length > 0) {
    const font = assets.font(element.fontId);
    if ("glyphs" in font) {
      const dialogBullet = /^(?:ONE|UNLIMITED|LIMITED|UNREFINED|PLACEHOLDER|UNFINISHED)\b/i.test(element.text);
      const tint: AtlasTextDraw["tint"] = element.text.startsWith("BETA VERSION")
        ? [1, 1, 1, 1]
        : dialogBullet
          ? [1, 0.92, 0, 1]
          : element.fontId === "Fonts.93-184"
            ? [1, 1, 1, 1]
            : [0.86, 0.74, 0.42, 1];
      return {
        kind: "atlas-text",
        elementId: element.id,
        layer: "screen-overlay",
        drawOrder: element.drawOrder,
        rect: element.rect,
        unclippedRect: element.unclippedRect,
        fontId: element.fontId,
        text: element.text,
        tint,
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
  if (element.kind === "text" || element.kind === "control") {
    return null;
  }
  throw new Error(`${element.id} has unsupported visible G11 draw kind ${element.kind}`);
}

function measuredDialogBacking(
  elements: readonly MenuElement[],
): SolidDraw | null {
  const corners = elements.filter((element) => (
    element.visible && ["UI.107", "UI.108", "UI.109", "UI.110"].includes(element.artId)
  ));
  const innerFrame = elements.filter((element) => element.visible && element.artId === "UI.17");
  if (
    corners.length !== 4
    || innerFrame.length < 4
    || !elements.some((element) => element.kind === "text" && element.text.startsWith("BETA VERSION"))
  ) {
    return null;
  }
  const rectangle: NativeRect = [
    Math.min(...innerFrame.map((element) => element.rect[0])),
    Math.min(...innerFrame.map((element) => element.rect[1])),
    Math.max(...innerFrame.map((element) => element.rect[2])),
    Math.max(...innerFrame.map((element) => element.rect[3])),
  ];
  return {
    kind: "solid",
    elementId: "semantic-dialog.backing",
    layer: "screen-overlay",
    drawOrder: Math.min(...corners.map((element) => element.drawOrder)) - 0.25,
    rect: rectangle,
    unclippedRect: rectangle,
    colorTop: [0.055, 0.055, 0.055, 1],
    colorBottom: [0.012, 0.012, 0.012, 1],
  };
}

function measuredDialogFrameConnectors(elements: readonly MenuElement[]): SolidDraw[] {
  const corners = elements.filter((element) => (
    element.visible && ["UI.107", "UI.108", "UI.109", "UI.110"].includes(element.artId)
  ));
  if (corners.length !== 4) {
    return [];
  }
  const left = Math.min(...corners.map((element) => element.rect[0])) + 18;
  const top = Math.min(...corners.map((element) => element.rect[1])) + 17;
  const right = Math.max(...corners.map((element) => element.rect[2])) - 18;
  const bottom = Math.max(...corners.map((element) => element.rect[3])) - 17;
  const drawOrder = Math.min(...corners.map((element) => element.drawOrder)) - 0.125;
  const rectangles: NativeRect[] = [
    [left, top, right, top + 2],
    [left, bottom - 2, right, bottom],
    [left, top, left + 2, bottom],
    [right - 2, top, right, bottom],
  ];
  return rectangles.map((rectangle, index) => ({
    kind: "solid",
    elementId: `semantic-dialog.frame-connector.${index}`,
    layer: "screen-overlay",
    drawOrder,
    rect: rectangle,
    unclippedRect: rectangle,
    colorTop: [0.58, 0.46, 0.2, 1],
    colorBottom: [0.58, 0.46, 0.2, 1],
  }));
}

function measuredInnerFrameConnectors(elements: readonly MenuElement[]): SolidDraw[] {
  const outerCorners = elements.filter((element) => (
    element.visible && ["UI.107", "UI.108", "UI.109", "UI.110"].includes(element.artId)
  ));
  const corners = elements.filter((element) => element.visible && element.artId === "UI.17");
  if (corners.length !== 4) {
    return [];
  }
  const left = Math.min(...corners.map((element) => element.rect[0])) + 20;
  const top = Math.min(...corners.map((element) => element.rect[1])) + 18;
  const right = Math.max(...corners.map((element) => element.rect[2])) - 20;
  const bottom = Math.max(...corners.map((element) => element.rect[3])) - 18;
  const drawOrder = Math.min(...corners.map((element) => element.drawOrder)) - 0.125;
  const rectangles: NativeRect[] = [
    [left, top, right, top + 2],
    [left, bottom - 2, right, bottom],
    [left, top, left + 2, bottom],
    [right - 2, top, right, bottom],
  ];
  return rectangles.map((rectangle, index) => ({
    kind: "solid",
    elementId: `semantic-${outerCorners.length === 4 ? "dialog" : "menu"}.inner-frame.${index}`,
    layer: "screen-overlay",
    drawOrder,
    rect: rectangle,
    unclippedRect: rectangle,
    colorTop: [0.58, 0.46, 0.2, 1],
    colorBottom: [0.58, 0.46, 0.2, 1],
  }));
}

function createBackdrop(layout: MenuLayout): SolidDraw | null {
  if (layout.screenId !== "create_element" && layout.screenId !== "create_discipline") {
    return null;
  }
  const rectangle: NativeRect = [0, 0, NATIVE_WIDTH, NATIVE_HEIGHT];
  return {
    kind: "solid",
    elementId: `${layout.id}.measured-family-backdrop`,
    layer: "screen-overlay",
    drawOrder: -1,
    rect: rectangle,
    unclippedRect: rectangle,
    colorTop: [0, 0, 0, 1],
    colorBottom: [0.25, 0.25, 0.25, 1],
  };
}

function missingControlLabels(elements: readonly MenuElement[]): AtlasTextDraw[] {
  const textElements = elements.filter((element) => element.kind === "text" && element.visible);
  const sameMeasuredRect = (left: NativeRect, right: NativeRect): boolean => left.every((coordinate, index) => {
    const rightCoordinate = right[index];
    return rightCoordinate !== undefined && Math.abs(coordinate - rightCoordinate) <= 1;
  });
  return elements.flatMap((element) => {
    if (
      element.kind !== "control"
      || !element.visible
      || element.text.length === 0
      || element.text !== element.text.toUpperCase()
    ) {
      return [];
    }
    const hasMeasuredPanel = elements.some((candidate) => (
      candidate.kind === "art"
      && candidate.artId === "UI.101"
      && candidate.visible
      && sameMeasuredRect(candidate.rect, element.rect)
    ));
    const hasMeasuredLabel = textElements.some((candidate) => (
      candidate.text.trim().toUpperCase() === element.text.trim().toUpperCase()
      || (
        candidate.rect[0] >= element.rect[0]
        && candidate.rect[1] >= element.rect[1]
        && candidate.rect[2] <= element.rect[2]
        && candidate.rect[3] <= element.rect[3]
      )
    ));
    if (!hasMeasuredPanel || hasMeasuredLabel) {
      return [];
    }
    const [left, top, right, bottom] = element.rect;
    const rectangle: NativeRect = [left + 45, (top + bottom) / 2 - 11, right - 45, (top + bottom) / 2 + 11];
    return [{
      kind: "atlas-text",
      elementId: `${element.id}.measured-panel-label`,
      layer: "screen-overlay",
      drawOrder: element.drawOrder + 0.75,
      rect: rectangle,
      unclippedRect: rectangle,
      fontId: "Fonts.216-307",
      text: element.text,
      tint: [0.86, 0.74, 0.42, 1],
    }];
  });
}

export function buildRenderPlan(
  layout: MenuLayout,
  assets: ManifestAssets,
  focused: Readonly<{ id: string; rect: NativeRect }> | null,
  showFocus: boolean,
): RenderPlan {
  const renderElements = [
    ...layout.elements,
    ...layout.ambientElements,
    ...layout.semanticDialogElements,
  ];
  const commands = renderElements
    .map((element) => visualCommand(element, assets))
    .filter((command): command is DrawCommand => command !== null);
  const dialogBacking = measuredDialogBacking(renderElements);
  const backdrop = createBackdrop(layout);
  if (backdrop !== null) {
    commands.push(backdrop);
  }
  if (dialogBacking !== null) {
    commands.push(dialogBacking);
  }
  commands.push(...measuredDialogFrameConnectors(renderElements));
  commands.push(...measuredInnerFrameConnectors(renderElements));
  commands.push(...missingControlLabels(renderElements));
  const base = commands
    .filter((command) => command.kind !== "atlas-text" && command.kind !== "system-text")
    .sort((left, right) => left.drawOrder - right.drawOrder);
  const text = commands
    .filter((command) => command.kind === "atlas-text" || command.kind === "system-text")
    .sort((left, right) => left.drawOrder - right.drawOrder);
  let ordered: DrawCommand[] = [...base, ...text];
  if (dialogBacking !== null) {
    const isDialogBase = (command: DrawCommand): boolean => (
      command.elementId.startsWith("semantic-dialog.")
      || layout.dialogElementIds.has(command.elementId)
    );
    const isDialogText = (command: DrawCommand): boolean => (
      layout.dialogElementIds.has(command.elementId)
    );
    const baseWithoutBacking = base.filter((command) => command.elementId !== dialogBacking.elementId);
    ordered = [
      ...baseWithoutBacking.filter((command) => !isDialogBase(command)),
      ...text.filter((command) => !isDialogText(command)),
      dialogBacking,
      ...baseWithoutBacking.filter(isDialogBase),
      ...text.filter(isDialogText),
    ];
  }
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
    tint: [0.86, 0.74, 0.42, 1],
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
    tint: [0.86, 0.74, 0.42, 1],
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
    tint: [0.86, 0.74, 0.42, 1],
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
