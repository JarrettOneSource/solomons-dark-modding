import menuGoldenJson from "../../tests/fixtures/webgame/menufix-preview-overlay/menu-goldens.json" with { type: "json" };
import inertControlsJson from "../../webgame-contracts/inert-controls.json" with { type: "json" };
import focusModelJson from "../../webgame-contracts/menu-focus-model.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import type { MenuNavIntent } from "../input/intent.js";
import { parseFocusModel } from "../input/focus-model.js";
import { parseInertControls } from "./inert-controls.js";
import { parseMenuCatalog } from "./menu-catalog.js";
import { ShellController } from "./shell-controller.js";

function nav(command: MenuNavIntent["command"], phase: MenuNavIntent["phase"] = "press") {
  return { kind: "menu_nav", command, phase } as const;
}

function harness() {
  let now = 100;
  const controller = new ShellController(
    parseMenuCatalog(menuGoldenJson),
    parseFocusModel(focusModelJson),
    parseInertControls(inertControlsJson),
    { clock: () => now },
  );
  return {
    controller,
    advance: (milliseconds: number) => {
      now += milliseconds;
    },
  };
}

function activate(controller: ShellController, actionId: string): void {
  controller.handle({ kind: "interact", target: actionId, phase: "press" });
}

describe("measured critical-path browser shell", () => {
  it("always boots a pristine session into the semantic beta dialog over the picker", () => {
    const { controller, advance } = harness();
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "native-loader" },
      inputSurface: "blocked",
      values: {},
    });
    controller.showMatchLoading();
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "loading-screen" });
    controller.completeBoot();
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "dialog-composite", compositeId: "beta_notice_first_boot" },
      focusId: "dialog.primary",
      inputGated: true,
    });
    activate(controller, "dialog.primary");
    expect(controller.snapshot().surface).toEqual({
      kind: "dialog-composite",
      compositeId: "beta_notice_first_boot",
    });
    advance(2000);
    activate(controller, "dialog.primary");
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "control-scheme-picker" },
      focusId: "control_scheme_picker.select_wasd",
      inputGated: false,
    });
  });

  it.each([
    "control_scheme_picker.select_arrows_mouse",
    "control_scheme_picker.select_wasd",
  ])("dispatches every control-scheme option: %s", (actionId) => {
    const { controller } = harness();
    controller.showLayoutForConformance("control-scheme-picker", actionId);
    activate(controller, actionId);
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "create-element" },
      values: { control_scheme: actionId },
    });
  });

  it.each([
    "create.select_element_ether",
    "create.select_element_earth",
    "create.select_element_fire",
    "create.select_element_water",
    "create.select_element_air",
  ])("dispatches every element option: %s", (actionId) => {
    const { controller } = harness();
    controller.showLayoutForConformance("create-element", actionId);
    activate(controller, actionId);
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "create-discipline" },
      values: { "create.element": actionId },
    });
  });

  it.each([
    "create.select_discipline_mind",
    "create.select_discipline_body",
    "create.select_discipline_arcane",
  ])("dispatches every discipline option: %s", (actionId) => {
    const { controller } = harness();
    controller.showLayoutForConformance("create-discipline", actionId);
    activate(controller, actionId);
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "hub-stub", endpointLayoutId: "hub_new_game" },
      values: { "create.discipline": actionId },
    });
  });

  it("opens and closes pause as an overlay and follows Leave Game to the in-session main menu", () => {
    const { controller } = harness();
    controller.showHubForConformance("hub_new_game");
    activate(controller, "pause");
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "pause-menu" });
    activate(controller, "pause_menu.resume_game");
    expect(controller.snapshot().surface).toEqual({
      kind: "hub-stub",
      endpointLayoutId: "hub_resumed",
    });

    activate(controller, "pause");
    activate(controller, "pause_menu.leave_game");
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "beta-notice" });
    activate(controller, "dialog.primary");
    expect(controller.snapshot()).toMatchObject({
      surface: { kind: "layout", layoutId: "main-menu-root" },
      focusId: "main_menu.play",
    });
  });

  it("serves Play, Last Game, and Back without inventing the missing New Game edge", () => {
    const { controller } = harness();
    controller.showLayoutForConformance("main-menu-root");
    activate(controller, "main_menu.play");
    expect(controller.snapshot().surface).toEqual({
      kind: "layout",
      layoutId: "profile-save-select",
    });

    const beforeNewGame = structuredClone(controller.snapshot());
    activate(controller, "main_menu.new_game");
    expect(controller.snapshot()).toEqual(beforeNewGame);

    activate(controller, "main_menu.resume_last_game");
    expect(controller.snapshot().surface).toEqual({
      kind: "hub-stub",
      endpointLayoutId: "hub_resumed",
    });

    controller.showLayoutForConformance("profile-save-select");
    activate(controller, "main_menu.back");
    expect(controller.snapshot().surface).toEqual({ kind: "layout", layoutId: "main-menu-root" });
  });

  it("keeps owner-descoped controls inert with byte-for-byte-equivalent snapshots", () => {
    const { controller } = harness();
    controller.showLayoutForConformance("main-menu-root", "main_menu.settings");
    const before = structuredClone(controller.snapshot());
    activate(controller, "main_menu.settings");
    expect(controller.snapshot()).toEqual(before);

    controller.showLayoutForConformance("game-over", "game_over.continue");
    const beforeGameOver = structuredClone(controller.snapshot());
    controller.handle(nav("confirm"));
    expect(controller.snapshot()).toEqual(beforeGameOver);
  });

  it("does not persist selections across pristine page-controller instances", () => {
    const first = harness().controller;
    first.showLayoutForConformance("control-scheme-picker");
    activate(first, "control_scheme_picker.select_wasd");
    expect(first.snapshot().values).toHaveProperty("control_scheme");

    const second = harness().controller;
    second.completeBoot();
    expect(second.snapshot().values).toEqual({});
    expect(second.snapshot().surface).toEqual({
      kind: "dialog-composite",
      compositeId: "beta_notice_first_boot",
    });
  });
});
