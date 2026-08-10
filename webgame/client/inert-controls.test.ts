import menuGoldenJson from "../../tests/fixtures/webgame/menufix-preview-overlay/menu-goldens.json" with { type: "json" };
import inertControlsJson from "../../webgame-contracts/inert-controls.json" with { type: "json" };
import focusModelJson from "../../webgame-contracts/menu-focus-model.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import { parseFocusModel } from "../input/focus-model.js";
import { buildFocusNodes } from "./focus-nodes.js";
import { parseInertControls, withInertControls } from "./inert-controls.js";
import { parseMenuCatalog } from "./menu-catalog.js";

const catalog = parseMenuCatalog(menuGoldenJson);
const inert = parseInertControls(inertControlsJson);
const focusModel = withInertControls(parseFocusModel(focusModelJson), inert);

function functional(screen: string, actionId: string): boolean {
  return (
    (screen === "beta-notice" && actionId === "dialog.primary")
    || (screen === "control-scheme-picker" && actionId.startsWith("control_scheme_picker.select_"))
    || (screen === "create-element" && actionId.startsWith("create.select_element_"))
    || (screen === "create-discipline" && actionId.startsWith("create.select_discipline_"))
    || (screen === "main-menu-root" && actionId === "main_menu.play")
    || (
      screen === "profile-save-select"
      && (actionId === "main_menu.resume_last_game" || actionId === "main_menu.back")
    )
    || (
      screen === "pause-menu"
      && (actionId === "pause_menu.resume_game" || actionId === "pause_menu.leave_game")
    )
  );
}

const eligibility = {
  resumeAvailable: true,
  lightQualityAvailable: true,
  darkCloudSignedIn: true,
  selectedBoneyardCompatible: true,
  gameOverArmed: true,
  offeredSkillCount: 3 as const,
  unlockedStoryIndices: [0],
};

describe("inert controls manifest", () => {
  it("keeps pending capture distinct from the owner-descoped worklist", () => {
    const pending = inert.entries.filter((entry) => entry.disposition === "pending_capture");
    expect(pending).toEqual([{
      screen: "profile-save-select",
      control: "profile_save_select.control.main_menu_new_game.1",
      actionId: "main_menu.new_game",
      disposition: "pending_capture",
      reason: "main_menu.new_game destination unmeasured in corrected graph; capture queued with menufix; un-inert in Phase 2 when the edge lands",
    }]);
    expect(inert.entries.some((entry) => entry.disposition === "owner_descoped")).toBe(true);
  });

  it("classifies every corrected interactive control exactly once", () => {
    for (const layoutId of catalog.standardLayoutIds) {
      const layout = catalog.layouts.get(layoutId);
      expect(layout, layoutId).toBeDefined();
      if (layout === undefined) {
        throw new Error(`${layoutId} was not parsed`);
      }
      for (const element of layout.elements) {
        if (!element.visible || !element.interactive || element.actionId.length === 0) {
          continue;
        }
        expect(
          functional(layoutId, element.actionId) || inert.has(layoutId, element.actionId),
          `${layoutId}/${element.actionId}`,
        ).toBe(true);
      }
    }
    for (const entry of inert.entries.filter((candidate) => !candidate.control.startsWith("focus-proxy:"))) {
      expect(catalog.layouts.get(entry.screen)?.elements).toContainEqual(expect.objectContaining({
        id: entry.control,
        actionId: entry.actionId,
        visible: true,
        interactive: true,
      }));
    }
  });

  it("makes every manifest row clickable and exposes no unclassified focus action", () => {
    for (const layoutId of catalog.standardLayoutIds) {
      const layout = catalog.layouts.get(layoutId);
      expect(layout, layoutId).toBeDefined();
      if (layout === undefined) {
        throw new Error(`${layoutId} was not parsed`);
      }
      const nodes = buildFocusNodes(layout, focusModel, eligibility);
      for (const entry of inert.byScreen.get(layoutId) ?? []) {
        expect(nodes.map((node) => node.id), `${layoutId}/${entry.actionId}`)
          .toContain(entry.actionId);
      }
      for (const node of nodes) {
        expect(
          functional(layoutId, node.id) || inert.has(layoutId, node.id),
          `${layoutId}/${node.id}`,
        ).toBe(true);
      }
    }
  });
});
