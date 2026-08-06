import menuGoldenJson from "../../tests/fixtures/webgame/menu-goldens.json" with { type: "json" };
import menuVisualGateJson from "../../webgame-contracts/menu-visual-gate.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import { parseMenuCatalog } from "../client/menu-catalog.js";
import { validateMenuVisualGate } from "./menu-visual-gate.js";

describe("temporary G11 visual waiver", () => {
  it("keeps the ordinary 18-screen rule and exactly ten enumerated stale waivers", () => {
    const result = validateMenuVisualGate(menuVisualGateJson, parseMenuCatalog(menuGoldenJson));
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
    expect(() => validateMenuVisualGate(scratch, parseMenuCatalog(menuGoldenJson)))
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
    expect(() => validateMenuVisualGate(menuVisualGateJson, parseMenuCatalog(scratchGolden)))
      .toThrow(`illegal stale visual waiver: ${fixture} no longer bears literal marker`);
  });

  it("rejects any extra tolerance field", () => {
    const scratch: Record<string, unknown> = {
      ...structuredClone(menuVisualGateJson),
      epsilon: 1,
    };
    expect(() => validateMenuVisualGate(scratch, parseMenuCatalog(menuGoldenJson)))
      .toThrow("menu visual gate has keys");
  });
});
