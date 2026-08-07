import { describe, expect, it } from "vitest";

import { BetaNoticeDialog } from "./beta-dialog.js";
import type { ResolvedAsset } from "./manifest-assets.js";
import type { NativeRect } from "./menu-catalog.js";
import { G12_LAYER_ORDER } from "./render-plan.js";
import type { AtlasTextDraw, DrawCommand, RenderPlan, SolidDraw, SpriteDraw } from "./render-plan.js";

function fakeAsset(id: string): ResolvedAsset {
  return {
    requestedId: id,
    canonicalId: id,
    entry: { rotated: false } as unknown as ResolvedAsset["entry"],
    atlas: { id: "TestAtlas" } as unknown as ResolvedAsset["atlas"],
  };
}

function layer(): { dialog: BetaNoticeDialog; requested: Set<string> } {
  const requested = new Set<string>();
  const dialog = new BetaNoticeDialog({
    resolve: (id) => {
      requested.add(id);
      return fakeAsset(id);
    },
  });
  return { dialog, requested };
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

function label(elementId: string, text: string, rectangle: NativeRect): AtlasTextDraw {
  return {
    kind: "atlas-text",
    elementId,
    layer: "screen-overlay",
    drawOrder: 0,
    rect: rectangle,
    unclippedRect: rectangle,
    fontId: "Fonts.216-307",
    text,
  };
}

function focusRing(rectangle: NativeRect): DrawCommand {
  return {
    kind: "focus",
    elementId: "shell.focus",
    layer: "screen-overlay",
    drawOrder: Number.MAX_SAFE_INTEGER,
    rect: rectangle,
    unclippedRect: rectangle,
    colorTop: [0.95, 0.78, 0.35, 0.9],
    colorBottom: [0.95, 0.78, 0.35, 0.9],
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

function betaNoticePlan(): RenderPlan {
  return plan("beta-notice", [
    sprite("beta_notice.art.ui_101.1", "UI.101", [708, 421.5, 904, 490], 73),
    sprite("beta_notice.art.ui_107.1", "UI.107", [516.5, 99.5, 601.5, 188.5], 88),
    sprite("beta_notice.art.ui_101.4", "UI.101", [702, 643.5, 898, 712], 100),
    label("beta_notice.text.play.1", "PLAY", [792, 442, 911, 472]),
    label("beta_notice.text.explore_the.1", "explore the", [792, 513, 929, 530]),
    label("beta_notice.text.dark_cloud.1", "DARK CLOUD", [788, 531, 940, 550]),
    label("beta_notice.text.settings.1", "SETTINGS", [790, 599, 917, 619]),
    label("beta_notice.text.hall_of_fame.1", "HALL of FAME", [793, 675, 947, 695]),
    label("beta_notice.text.quit.1", "quit", [1503, 853, 1558, 871]),
    focusRing([702, 643.5, 898, 712.5]),
  ]);
}

function synthetic(result: RenderPlan): DrawCommand[] {
  return result.commands.filter((command) => command.elementId.startsWith("dialog.")
    && command.kind !== "atlas-text");
}

describe("BetaNoticeDialog", () => {
  it("handles exactly the beta-notice dialog screen", () => {
    const { dialog } = layer();
    expect(dialog.handles("beta-notice")).toBe(true);
    expect(dialog.handles("main-menu-root")).toBe(false);
    expect(dialog.handles("controls")).toBe(false);
  });

  it("passes through screens with neither dialog nor stamp untouched", () => {
    const { dialog } = layer();
    const input = plan("controls", [sprite("controls.art.ui_54.1", "UI.54", [100, 100, 170, 185], 5)]);
    expect(dialog.apply(input)).toBe(input);
  });

  it("drops the menu labels the opaque panel natively covers and keeps quit", () => {
    const { dialog } = layer();
    const result = dialog.apply(betaNoticePlan());
    for (const covered of [
      "beta_notice.text.play.1",
      "beta_notice.text.explore_the.1",
      "beta_notice.text.dark_cloud.1",
      "beta_notice.text.settings.1",
      "beta_notice.text.hall_of_fame.1",
    ]) {
      expect(result.commands.some((command) => command.elementId === covered)).toBe(false);
    }
    expect(result.commands.some((command) => command.elementId === "beta_notice.text.quit.1")).toBe(true);
  });

  it("slots the reconstructed panel between menu content and dialog chrome", () => {
    const { dialog, requested } = layer();
    const result = dialog.apply(betaNoticePlan());

    const base = result.commands.find((command) => command.elementId === "dialog.panel.base");
    expect(base?.kind).toBe("solid");
    expect((base as SolidDraw).colorTop).toEqual([0.008, 0.008, 0.01, 1]);
    expect(base?.unclippedRect).toEqual([516.5, 99.5, 1083.5, 800.5]);

    const chains = result.commands.filter((command) => command.elementId.startsWith("dialog.chain."));
    expect(chains).toHaveLength(26);
    const leather = result.commands.filter((command) => command.elementId.startsWith("dialog.leather."));
    expect(leather).toHaveLength(6);
    const rules = result.commands.filter((command) => command.elementId.startsWith("dialog.rule."));
    expect(rules).toHaveLength(8);
    expect(requested.has("UI.79")).toBe(true);
    expect(requested.has("UI.49")).toBe(true);

    const indexOf = (elementId: string): number => (
      result.commands.findIndex((command) => command.elementId === elementId)
    );
    const menuIndex = indexOf("beta_notice.art.ui_101.1");
    const chromeIndex = indexOf("beta_notice.art.ui_107.1");
    for (const command of synthetic(result)) {
      expect(command.drawOrder).toBeGreaterThan(87);
      expect(command.drawOrder).toBeLessThan(88);
      const position = result.commands.indexOf(command);
      expect(position).toBeGreaterThan(menuIndex);
      expect(position).toBeLessThan(chromeIndex);
    }
  });

  it("clips edge leather tiles to the panel region while keeping full source tiles", () => {
    const { dialog } = layer();
    const result = dialog.apply(betaNoticePlan());
    const leather = result.commands.filter((command): command is SpriteDraw => (
      command.kind === "sprite" && command.elementId.startsWith("dialog.leather.")
    ));
    const clippedRight = leather.find((tile) => tile.rect[2] === 1051 && tile.unclippedRect[2] === 814 + 264);
    expect(clippedRight).toBeDefined();
    const clippedBottom = leather.find((tile) => tile.rect[3] === 768 && tile.unclippedRect[3] === 661 + 264);
    expect(clippedBottom).toBeDefined();
  });

  it("rebuilds the native dialog text with native colors, above sprites, below focus", () => {
    const { dialog } = layer();
    const result = dialog.apply(betaNoticePlan());
    const texts = result.commands.filter((command): command is AtlasTextDraw => command.kind === "atlas-text");

    const heading = texts.find((command) => command.elementId === "dialog.text.heading");
    expect(heading?.text).toBe("BETA VERSION V.0.72");
    expect(heading?.fontId).toBe("Fonts.308-349");
    expect(heading?.color).toEqual([1, 1, 1, 1]);

    const bullet = texts.find((command) => command.elementId === "dialog.text.list.1");
    expect(bullet?.text).toBe("ONE story level");
    expect(bullet?.color).toEqual([1, 1, 0, 1]);

    const ok = texts.find((command) => command.elementId === "dialog.text.ok");
    expect(ok?.text).toBe("OK");
    expect(ok?.color).toBeUndefined();

    // heading + 12 body lines + 7 list lines + OK, plus the version stamp.
    const bodyCount = texts.filter((command) => command.elementId.startsWith("dialog.text.")).length;
    expect(bodyCount).toBe(22);

    const lastSpriteIndex = result.commands.reduce((latest, command, index) => (
      command.kind === "sprite" || command.kind === "solid" ? index : latest
    ), -1);
    for (const command of texts) {
      expect(result.commands.indexOf(command)).toBeGreaterThan(lastSpriteIndex);
    }
    expect(result.commands.at(-1)?.kind).toBe("focus");
  });

  it("preserves the semantic elements identity", () => {
    const { dialog } = layer();
    const input = betaNoticePlan();
    expect(dialog.apply(input).elements).toBe(input.elements);
  });

  it("stamps the build version on exactly the natively stamped screens", () => {
    const { dialog } = layer();
    const stamped = dialog.apply(plan("main-menu-root", [
      sprite("main_menu.art.ui_101.1", "UI.101", [708, 421.5, 904, 490], 73),
      focusRing([708, 421.5, 904, 490]),
    ]));
    const stamp = stamped.commands.find((command) => command.elementId === "dialog.text.stamp");
    expect(stamp?.kind).toBe("atlas-text");
    expect((stamp as AtlasTextDraw).text).toBe("V.0.72BETA");
    expect((stamp as AtlasTextDraw).color).toBeUndefined();
    expect(stamped.commands.at(-1)?.kind).toBe("focus");
    expect(stamped.commands.some((command) => command.elementId === "dialog.panel.base")).toBe(false);

    const saves = dialog.apply(plan("profile-save-select", []));
    expect(saves.commands.some((command) => command.elementId === "dialog.text.stamp")).toBe(true);

    const settings = plan("game-settings-title", [sprite("gs.art.ui_101.1", "UI.101", [0, 0, 10, 10], 1)]);
    expect(dialog.apply(settings)).toBe(settings);
  });
});
