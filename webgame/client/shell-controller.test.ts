import menuGoldenJson from "../../tests/fixtures/webgame/menu-goldens.json" with { type: "json" };
import focusModelJson from "../../webgame-contracts/menu-focus-model.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import type { MenuNavIntent } from "../input/intent.js";
import { parseFocusModel } from "../input/focus-model.js";
import { parseMenuCatalog } from "./menu-catalog.js";
import { ShellController, type ShellStore } from "./shell-controller.js";

function nav(command: MenuNavIntent["command"], phase: MenuNavIntent["phase"] = "press") {
  return { kind: "menu_nav", command, phase } as const;
}

function harness() {
  let now = 100;
  const values = new Map<string, string>();
  const store: ShellStore = {
    get: (key) => values.get(key) ?? null,
    set: (key, value) => values.set(key, value),
  };
  const controller = new ShellController(
    parseMenuCatalog(menuGoldenJson),
    parseFocusModel(focusModelJson),
    { clock: () => now, store },
  );
  return {
    controller,
    values,
    advance: (milliseconds: number) => {
      now += milliseconds;
    },
  };
}

describe("sim-less browser shell state", () => {
  it("runs loader to beta, enforces the exact two-second title input gate, then enters main", () => {
    const { controller, advance } = harness();
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "native-loader" },
      inputSurface: "blocked",
    });
    controller.completeBoot(false);
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "beta-notice" },
      inputGated: true,
    });
    controller.handle(nav("confirm"));
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "beta-notice" });
    advance(2000);
    controller.handle(nav("confirm"));
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "main-menu-root" },
      focusId: "main_menu.play",
      inputGated: false,
    });
  });

  it("routes first boot through the persisted control-scheme prerequisite", () => {
    const { controller, advance, values } = harness();
    controller.completeBoot(true);
    advance(2000);
    controller.handle(nav("back"));
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "control-scheme-picker" },
      focusId: "control_scheme_picker.select_wasd",
    });
    controller.handle(nav("confirm"));
    expect(values.get("control_scheme")).toBe("control_scheme_picker.select_wasd");
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "create-element" });
  });

  it("opens title settings and preserves its invoking context on Done", () => {
    const { controller } = harness();
    controller.showLayoutForConformance("main-menu-root", "main_menu.settings");
    controller.handle(nav("confirm"));
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "game-settings-title" },
      focusId: "settings.sound_volume",
    });
    controller.handle(nav("back"));
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "main-menu-root" });
  });

  it("traps a Dark Cloud modal and restores the exact invoking control on Back", () => {
    const { controller } = harness();
    controller.showLayoutForConformance("dark-cloud-browser", "dark_cloud_browser.search");
    controller.handle({
      kind: "interact",
      target: "dark_cloud_browser.search",
      phase: "press",
    });
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "dark-cloud-search" },
      focusId: "dark_cloud_search.name",
    });
    controller.handle(nav("back"));
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "dark-cloud-browser" },
      focusId: "dark_cloud_browser.search",
    });
  });

  it("omits disabled resume and capability-gated controls from traversal", () => {
    const { controller } = harness();
    controller.showLayoutForConformance("profile-save-select");
    controller.setEligibilityForConformance({ resumeAvailable: false });
    expect(controller.snapshot().focusId).toBe("main_menu.new_game");
    expect(controller.snapshot().focusNodes.find(
      (node) => node.id === "main_menu.resume_last_game",
    )?.enabled).toBe(false);

    controller.showLayoutForConformance("performance");
    expect(controller.snapshot().focusNodes.find(
      (node) => node.id === "performance.light_quality",
    )?.enabled).toBe(false);
    controller.setEligibilityForConformance({ lightQualityAvailable: true });
    expect(controller.snapshot().focusNodes.find(
      (node) => node.id === "performance.light_quality",
    )?.enabled).toBe(true);
  });

  it("persists the real-input Dark Name but never persists the password", () => {
    const { controller, values } = harness();
    controller.showLayoutForConformance("dark-cloud-login-settings");
    controller.setTextValue("dark_account.dark_name", "DeckWizard");
    controller.setTextValue("dark_account.password", "secret");
    expect(controller.snapshot().values).toMatchObject({
      "dark_account.dark_name": "DeckWizard",
      "dark_account.password": "secret",
    });
    expect(values.get("dark_account.dark_name")).toBe("DeckWizard");
    expect(values.has("dark_account.password")).toBe(false);
  });

  it("arms Game Over only after its one-second state threshold", () => {
    const { controller, advance } = harness();
    controller.showLayoutForConformance("game-over");
    expect(controller.snapshot().focusId).toBeNull();
    advance(999);
    controller.tick();
    expect(controller.snapshot().focusId).toBeNull();
    advance(1);
    controller.tick();
    expect(controller.snapshot().focusId).toBe("game_over.continue");
    controller.handle(nav("confirm"));
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "hall-of-fame" });
  });

  it("ends map Start at an explicit gameplay-out-of-scope surface", () => {
    const { controller } = harness();
    controller.showLayoutForConformance("map-picker");
    controller.handle(nav("confirm"));
    const surface = controller.snapshot().surface;
    expect(surface.kind).toBe("out-of-scope");
    if (surface.kind === "out-of-scope") {
      expect(surface.message).toContain("outside P0");
    }
  });
});
