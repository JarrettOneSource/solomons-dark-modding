import { describe, expect, it } from "vitest";

import type { ResolvedAsset } from "./manifest-assets.js";
import type { NativeRect } from "./menu-catalog.js";
import { orientNativeChrome } from "./native-orientation.js";
import { G12_LAYER_ORDER } from "./render-plan.js";
import type { DrawCommand, RenderPlan, SpriteDraw } from "./render-plan.js";

function fakeAsset(id: string): ResolvedAsset {
  return {
    requestedId: id,
    canonicalId: id,
    entry: { rotated: false } as unknown as ResolvedAsset["entry"],
    atlas: { id: "TestAtlas" } as unknown as ResolvedAsset["atlas"],
  };
}

function sprite(elementId: string, artId: string, rectangle: NativeRect, drawOrder = 1): SpriteDraw {
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

function plan(commands: readonly DrawCommand[]): RenderPlan {
  return {
    layoutId: "beta-notice",
    nativeViewport: [1600, 900],
    layerOrder: G12_LAYER_ORDER,
    clearColor: [0, 0, 0, 1],
    elements: [],
    commands,
  };
}

function flipOf(result: RenderPlan, elementId: string): readonly [boolean, boolean] | undefined {
  const command = result.commands.find((candidate) => candidate.elementId === elementId);
  if (command === undefined || command.kind !== "sprite") {
    throw new Error(`expected sprite ${elementId}`);
  }
  return command.flip;
}

describe("orientNativeChrome", () => {
  it("mirrors the right cap of same-row UI.54 slab pairs", () => {
    const result = orientNativeChrome(plan([
      sprite("slab.left", "UI.54", [696, 637.5, 766, 722.5]),
      sprite("slab.right", "UI.54", [834, 637.5, 904, 722.5]),
    ]));
    expect(flipOf(result, "slab.left")).toBeUndefined();
    expect(flipOf(result, "slab.right")).toEqual([true, false]);
  });

  it("treats each slab row independently", () => {
    const result = orientNativeChrome(plan([
      sprite("row1.left", "UI.54", [640, 415, 710, 500]),
      sprite("row1.right", "UI.54", [890, 415, 960, 500]),
      sprite("row2.left", "UI.54", [640, 491, 710, 576]),
      sprite("row2.right", "UI.54", [890, 491, 960, 576]),
    ]));
    expect(flipOf(result, "row1.right")).toEqual([true, false]);
    expect(flipOf(result, "row2.right")).toEqual([true, false]);
    expect(flipOf(result, "row1.left")).toBeUndefined();
    expect(flipOf(result, "row2.left")).toBeUndefined();
  });

  it("mirrors the right cap of the UI.53 quit pair", () => {
    const result = orientNativeChrome(plan([
      sprite("quit.left", "UI.53", [1474, 828, 1501, 890]),
      sprite("quit.right", "UI.53", [1559, 828, 1586, 890]),
    ]));
    expect(flipOf(result, "quit.right")).toEqual([true, false]);
  });

  it("leaves cap singletons and trios untouched", () => {
    const untouched = plan([
      sprite("lone", "UI.54", [696, 637.5, 766, 722.5]),
      sprite("trio.1", "UI.53", [100, 100, 127, 162]),
      sprite("trio.2", "UI.53", [200, 100, 227, 162]),
      sprite("trio.3", "UI.53", [300, 100, 327, 162]),
    ]);
    expect(orientNativeChrome(untouched)).toBe(untouched);
  });

  it("mirrors the right column of side-by-side UI.18 pairs and spares the crest banner", () => {
    const result = orientNativeChrome(plan([
      sprite("column.left", "UI.18", [599.5, 440, 666.5, 702]),
      sprite("column.right", "UI.18", [1033.5, 440, 1100.5, 702]),
      sprite("crest", "UI.18", [669, 51, 931, 118]),
    ]));
    expect(flipOf(result, "column.left")).toBeUndefined();
    expect(flipOf(result, "column.right")).toEqual([true, false]);
    expect(flipOf(result, "crest")).toBeUndefined();
  });

  it("mirrors UI.17 filigree toward the corner-group centroid", () => {
    const result = orientNativeChrome(plan([
      sprite("corner.tl", "UI.17", [535, 117, 615, 200]),
      sprite("corner.tr", "UI.17", [985, 117, 1065, 200]),
      sprite("corner.bl", "UI.17", [535, 700, 615, 783]),
      sprite("corner.br", "UI.17", [985, 700, 1065, 783]),
    ]));
    expect(flipOf(result, "corner.tl")).toBeUndefined();
    expect(flipOf(result, "corner.tr")).toEqual([true, false]);
    expect(flipOf(result, "corner.bl")).toEqual([false, true]);
    expect(flipOf(result, "corner.br")).toEqual([true, true]);
  });

  it("never rewrites other arts, non-sprites, or pre-oriented flips", () => {
    const preset: SpriteDraw = {
      ...sprite("preset", "UI.54", [696, 637.5, 766, 722.5]),
      flip: [false, true],
    };
    const result = orientNativeChrome(plan([
      preset,
      sprite("partner", "UI.54", [834, 637.5, 904, 722.5]),
      sprite("skull", "UI.8", [706.6, 783, 743.4, 867]),
      sprite("stone", "UI.107", [516.5, 99.5, 601.5, 188.5]),
      {
        kind: "solid",
        elementId: "scrim",
        layer: "screen-overlay",
        drawOrder: 2,
        rect: [0, 0, 10, 10],
        unclippedRect: [0, 0, 10, 10],
        colorTop: [0, 0, 0, 1],
        colorBottom: [0, 0, 0, 1],
      },
    ]));
    expect(flipOf(result, "preset")).toEqual([false, true]);
    expect(flipOf(result, "partner")).toBeUndefined();
    expect(flipOf(result, "skull")).toBeUndefined();
    expect(flipOf(result, "stone")).toBeUndefined();
  });

  it("returns the same plan reference when nothing mirrors", () => {
    const input = plan([sprite("skull", "UI.8", [706.6, 783, 743.4, 867])]);
    expect(orientNativeChrome(input)).toBe(input);
  });
});
