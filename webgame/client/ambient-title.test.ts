import { describe, expect, it } from "vitest";

import ambientJson from "./ambient-title-data.json" with { type: "json" };
import { AmbientTitleLayer } from "./ambient-title.js";
import type { ResolvedAsset } from "./manifest-assets.js";
import type { NativeRect } from "./menu-catalog.js";
import { G12_LAYER_ORDER } from "./render-plan.js";
import type { DrawCommand, RenderPlan, SpriteDraw } from "./render-plan.js";

interface AmbientData {
  readonly staticOrder: Record<string, number>;
  readonly bands: readonly { art: string; v: number; w: number; b0: number; orderBase: number }[];
  readonly drifters: readonly { id: string; art: string; v: number; x0: number; w: number }[];
}

const data = ambientJson as unknown as AmbientData;

function fakeAsset(id: string): ResolvedAsset {
  return {
    requestedId: id,
    canonicalId: id,
    entry: { rotated: false } as unknown as ResolvedAsset["entry"],
    atlas: { id: "TestAtlas" } as unknown as ResolvedAsset["atlas"],
  };
}

function layer(): { layer: AmbientTitleLayer; requested: Set<string> } {
  const requested = new Set<string>();
  const built = new AmbientTitleLayer({
    resolve: (id) => {
      requested.add(id);
      return fakeAsset(id);
    },
  });
  return { layer: built, requested };
}

function sprite(elementId: string, artId: string, rectangle: NativeRect, drawOrder: number): SpriteDraw {
  return {
    kind: "sprite",
    elementId,
    layer: "screen-overlay",
    drawOrder,
    rect: rectangle,
    unclippedRect: rectangle,
    asset: fakeAsset(artId),
  };
}

function plan(layoutId: string, commands: readonly DrawCommand[]): RenderPlan {
  return {
    layoutId,
    nativeViewport: [1600, 900],
    layerOrder: G12_LAYER_ORDER,
    clearColor: [0, 0, 0, 1],
    elements: [],
    commands,
  };
}

function traceStatic(artPrefix: string): { key: string; artId: string; rect: NativeRect; order: number } {
  const key = Object.keys(data.staticOrder).find((candidate) => candidate.startsWith(`${artPrefix}|`));
  if (key === undefined) {
    throw new Error(`test expects a ${artPrefix} entry in the trace static contract`);
  }
  const [artId, encoded] = key.split("|");
  const parts = (encoded ?? "").split(",").map(Number);
  const order = data.staticOrder[key];
  if (artId === undefined || parts.length !== 4 || order === undefined) {
    throw new Error(`trace static key ${key} did not round-trip`);
  }
  return {
    key,
    artId,
    rect: [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, parts[3] ?? 0],
    order,
  };
}

function band(art: string): { art: string; v: number; w: number; b0: number; orderBase: number } {
  const found = data.bands.find((candidate) => candidate.art === art);
  if (found === undefined) {
    throw new Error(`test expects scroll band ${art}`);
  }
  return found;
}

function tiles(result: RenderPlan, art: string): SpriteDraw[] {
  return result.commands.filter((command): command is SpriteDraw => (
    command.kind === "sprite" && command.elementId.startsWith(`ambient.${art}.tile`)
  ));
}

function wrapDelta(later: number, earlier: number, period: number): number {
  let delta = later - earlier;
  if (delta < -period / 2) {
    delta += period;
  }
  if (delta > period / 2) {
    delta -= period;
  }
  return delta;
}

describe("AmbientTitleLayer", () => {
  it("covers exactly the four Title-backdrop screens", () => {
    const { layer: ambient } = layer();
    expect(ambient.handles("beta-notice")).toBe(true);
    expect(ambient.handles("main-menu-root")).toBe(true);
    expect(ambient.handles("game-settings-title")).toBe(true);
    expect(ambient.handles("profile-save-select")).toBe(true);
    expect(ambient.handles("controls")).toBe(false);
    expect(ambient.handles("native-loader")).toBe(false);
  });

  it("rejects malformed ambient data outright", () => {
    expect(() => new AmbientTitleLayer({ resolve: fakeAsset }, {})).toThrow();
  });

  it("warms up every ambient art for texture preparation", () => {
    const { layer: ambient, requested } = layer();
    const input = plan("beta-notice", [sprite("beta_notice.art.ui_18.1", "UI.18", [669, 51, 931, 118], 9)]);
    const augmented = ambient.augmentForPrepare(input);
    expect(augmented.commands.length).toBeGreaterThan(input.commands.length);
    for (const art of [
      "Title.0", "Title.1", "Title.2", "Title.4", "Title.5", "Title.8",
      "Title.11", "Title.12", "Title.13", "Title.14", "Title.15",
      "Title.16", "Title.17", "Title.18", "Title.19", "Title.20",
      "Title.21", "Title.22", "Title.23", "Title.24",
    ]) {
      expect(requested.has(art)).toBe(true);
    }
  });

  it("restores the native paint order on trace-complete screens", () => {
    const { layer: ambient } = layer();
    const tree = traceStatic("Title.6");
    const chrome = traceStatic("UI.18");
    const input = plan("beta-notice", [
      sprite("beta_notice.art.title_6.1", tree.artId, tree.rect, 19),
      sprite("beta_notice.art.ui_18.1", chrome.artId, chrome.rect, 9),
      sprite("beta_notice.art.title_0.1", "Title.0", [0, 0, 649.4, 553], 16),
      sprite("beta_notice.art.title_16.1", "Title.16", [934, 444, 990.8, 555.9], 30),
      {
        kind: "atlas-text",
        elementId: "beta_notice.text.title",
        layer: "screen-overlay",
        drawOrder: 5,
        rect: [600, 200, 1000, 240],
        unclippedRect: [600, 200, 1000, 240],
        fontId: "Fonts.308-349",
        text: "BETA",
      },
    ]);
    const result = ambient.apply(input, 0);

    expect(result.elements).toBe(input.elements);
    expect(result.commands.some((command) => command.elementId === "beta_notice.art.title_0.1")).toBe(false);
    expect(result.commands.some((command) => command.elementId === "beta_notice.art.title_16.1")).toBe(false);

    const keptTree = result.commands.find((command) => command.elementId === "beta_notice.art.title_6.1");
    const keptChrome = result.commands.find((command) => command.elementId === "beta_notice.art.ui_18.1");
    expect(keptTree?.drawOrder).toBe(tree.order);
    expect(keptChrome?.drawOrder).toBe(chrome.order);

    const skyBand = band("Title.0");
    const skyTiles = tiles(result, "Title.0");
    expect(skyTiles.length).toBeGreaterThanOrEqual(2);
    const firstTile = skyTiles[0];
    expect(firstTile).toBeDefined();
    const expectedFirstEdge = ((skyBand.b0 % skyBand.w) + skyBand.w) % skyBand.w - skyBand.w;
    expect(Math.abs((firstTile?.rect[0] ?? Number.NaN) - expectedFirstEdge)).toBeLessThan(0.01);
    for (const tile of skyTiles) {
      expect(chrome.order).toBeGreaterThan(tile.drawOrder);
    }

    const last = result.commands.at(-1);
    expect(last?.kind).toBe("atlas-text");
    const baseOrders = result.commands
      .filter((command) => command.kind === "sprite")
      .map((command) => command.drawOrder);
    const sortedOrders = [...baseOrders].sort((left, right) => left - right);
    expect(baseOrders).toEqual(sortedOrders);
  });

  it("scrolls bands and drifters at the derived native velocities", () => {
    const { layer: ambient } = layer();
    const tree = traceStatic("Title.6");
    const chrome = traceStatic("UI.18");
    const input = plan("main-menu-root", [
      sprite("main_menu.art.title_6.1", tree.artId, tree.rect, 19),
      sprite("main_menu.art.ui_18.1", chrome.artId, chrome.rect, 9),
      sprite("main_menu.art.title_2.1", "Title.2", [0, 0, 800, 553], 20),
    ]);
    const atStart = ambient.apply(input, 0);
    const atOneSecond = ambient.apply(input, 1000);

    const scrollBand = band("Title.2");
    const startTile = tiles(atStart, "Title.2")[0];
    const laterTile = tiles(atOneSecond, "Title.2")[0];
    expect(startTile).toBeDefined();
    expect(laterTile).toBeDefined();
    const bandShift = wrapDelta(laterTile?.rect[0] ?? Number.NaN, startTile?.rect[0] ?? Number.NaN, scrollBand.w);
    expect(Math.abs(bandShift - scrollBand.v)).toBeLessThan(0.01);

    const drifter = data.drifters.find((candidate) => candidate.id === "title_16.1");
    expect(drifter).toBeDefined();
    const startPuff = atStart.commands.find((command) => command.elementId === "ambient.title_16.1");
    const laterPuff = atOneSecond.commands.find((command) => command.elementId === "ambient.title_16.1");
    expect(startPuff).toBeDefined();
    expect(laterPuff).toBeDefined();
    const puffShift = (laterPuff?.rect[0] ?? Number.NaN) - (startPuff?.rect[0] ?? Number.NaN);
    expect(Math.abs(puffShift - (drifter?.v ?? Number.NaN))).toBeLessThan(0.01);
  });

  it("refuses to reorder a trace-complete screen with an unknown sprite", () => {
    const { layer: ambient } = layer();
    const input = plan("beta-notice", [
      sprite("beta_notice.art.mystery.1", "UI.999", [10, 10, 40, 40], 3),
      sprite("beta_notice.art.title_0.1", "Title.0", [0, 0, 649.4, 553], 16),
    ]);
    expect(() => ambient.apply(input, 0)).toThrow(/trace static contract/);
  });

  it("keeps pool screens' own content and slots ambient depth around the anchors", () => {
    const { layer: ambient } = layer();
    const tree = traceStatic("Title.6");
    const input = plan("game-settings-title", [
      sprite("game_settings.art.title_6.1", tree.artId, tree.rect, 19),
      sprite("game_settings.art.panel.1", "UI.999", [200, 200, 1400, 700], 40),
      sprite("game_settings.art.title_0.1", "Title.0", [0, 0, 649.4, 553], 16),
      sprite("game_settings.art.title_24.1", "Title.24", [700, 300, 1000, 600], 85),
    ]);
    const result = ambient.apply(input, 0);

    expect(result.elements).toBe(input.elements);
    const panel = result.commands.find((command) => command.elementId === "game_settings.art.panel.1");
    expect(panel?.drawOrder).toBe(40);
    const anchor = result.commands.find((command) => command.elementId === "game_settings.art.title_6.1");
    expect(anchor?.drawOrder).toBe(19);

    const synthetic = result.commands.filter((command) => command.elementId.startsWith("ambient."));
    expect(synthetic.length).toBeGreaterThan(20);
    for (const command of synthetic) {
      expect(command.drawOrder).toBeGreaterThan(15.4);
      expect(command.drawOrder).toBeLessThan(85.6);
    }
    for (const tile of tiles(result, "Title.0")) {
      expect(tile.drawOrder).toBeLessThan(19);
    }
    const bobber = result.commands.find((command) => command.elementId === "ambient.title_8.1");
    expect(bobber).toBeDefined();
    expect(bobber?.drawOrder ?? 0).toBeGreaterThan(19);
  });
});
