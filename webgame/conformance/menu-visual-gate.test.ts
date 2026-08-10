import menuGoldenJson from "../../tests/fixtures/webgame/menu-goldens.json" with { type: "json" };
import previewGoldenJson from "../../tests/fixtures/webgame/menufix-preview-overlay/menu-goldens.json" with { type: "json" };
import menuVisualGateJson from "../../webgame-contracts/menu-visual-gate.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import { parseMenuCatalog } from "../client/menu-catalog.js";
import { validateMenuVisualGate } from "./menu-visual-gate.js";

function legacyWaiverCatalog(value: typeof menuGoldenJson) {
  return {
    layouts: new Map(value.layouts.map((wrapper) => [wrapper.fixture, {
      fixture: wrapper.fixture,
      captureMethod: wrapper.layout.capture_method,
    }])),
  };
}

describe("temporary G11 visual waiver", () => {
  it("keeps the ordinary 18-screen rule and exactly ten enumerated stale waivers", () => {
    const result = validateMenuVisualGate(menuVisualGateJson, legacyWaiverCatalog(menuGoldenJson));
    expect(result.status).toBe("pass_with_enumerated_waiver");
    expect(result.reviewedPassFixtures).toHaveLength(18);
    expect(result.waivedDivergentFixtures).toHaveLength(10);
    expect(result.corrective).toBe("menufix task #97");
  });

  it("rejects an eleventh, unlisted visual divergence by fixture name", () => {
    const scratch = structuredClone(menuVisualGateJson);
    const fixture = "menu-layouts/main-menu-root.json";
    scratch.reviewed_pass_fixtures = scratch.reviewed_pass_fixtures.filter(
      (candidate) => candidate !== fixture,
    );
    scratch.reviewed_divergent_fixtures.push(fixture);
    expect(() => validateMenuVisualGate(scratch, legacyWaiverCatalog(menuGoldenJson)))
      .toThrow(`unwaived visual divergence: ${fixture}`);
  });

  it("rejects a still-listed fixture once a scratch recapture loses the stale marker", () => {
    const scratchGolden = structuredClone(menuGoldenJson);
    const fixture = "menu-layouts/controls.json";
    const wrapper = scratchGolden.layouts.find((candidate) => candidate.fixture === fixture);
    expect(wrapper).toBeDefined();
    if (wrapper === undefined) {
      throw new Error(`scratch G11 corpus lost ${fixture}`);
    }
    wrapper.layout.capture_method = wrapper.layout.capture_method.replace(
      "stale controls omitted",
      "settle-gated machine-derived provenance",
    );
    expect(() => validateMenuVisualGate(menuVisualGateJson, legacyWaiverCatalog(scratchGolden)))
      .toThrow(`illegal stale visual waiver: ${fixture} no longer bears literal marker`);
  });

  it("rejects any extra tolerance field", () => {
    const scratch: Record<string, unknown> = {
      ...structuredClone(menuVisualGateJson),
      epsilon: 1,
    };
    expect(() => validateMenuVisualGate(scratch, legacyWaiverCatalog(menuGoldenJson)))
      .toThrow("menu visual gate has keys");
  });

  it("does not apply any legacy waiver to a critical preview-overlay layout", () => {
    const catalog = parseMenuCatalog(previewGoldenJson);
    const criticalLayoutIds = [
      "native-loader",
      "loading-screen",
      "control-scheme-picker",
      "create-element",
      "create-discipline",
      "hub_new_game",
      "hub_resumed",
      "pause-menu",
      "beta-notice",
      "main-menu-root",
      "profile-save-select",
    ];
    const waived = new Set(menuVisualGateJson.waiver.entries.map((entry) => entry.fixture));
    for (const layoutId of criticalLayoutIds) {
      const layout = catalog.layouts.get(layoutId);
      expect(layout, layoutId).toBeDefined();
      if (layout === undefined) {
        throw new Error(`${layoutId} was not parsed`);
      }
      expect(waived.has(layout.fixture), layoutId).toBe(false);
      expect(layout.captureMethod, layoutId).not.toContain("stale controls omitted");
    }
    expect(catalog.dialogComposites.get("beta_notice_first_boot")?.residualMemberCount).toBe(0);
  });
});
