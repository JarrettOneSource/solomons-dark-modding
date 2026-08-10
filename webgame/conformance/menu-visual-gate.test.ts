import path from "node:path";

import menuBaselineJson from "../../webgame-contracts/menu-baseline.json" with { type: "json" };
import menuGoldenJson from "../../webgame-contracts/baseline-snapshots/menu-goldens.json" with { type: "json" };
import menuVisualGateJson from "../../webgame-contracts/menu-visual-gate.json" with { type: "json" };
import { describe, expect, it } from "vitest";

import { parseMenuCatalog } from "../client/menu-catalog.js";
import { verifyMenuBaseline } from "./menu-baseline.js";
import { validateMenuVisualGate } from "./menu-visual-gate.js";

const repository = path.resolve(import.meta.dirname, "..", "..");
const catalog = parseMenuCatalog(menuGoldenJson);
const canonicalFixtures = new Set(
  [...catalog.layouts.values()].map((layout) => layout.fixture),
);

async function baseline() {
  return verifyMenuBaseline(menuBaselineJson, repository, canonicalFixtures);
}

describe("G11 shellfix baseline-snapshot interregnum", () => {
  it("preserves 28 exact visual attestations while all 29 settled states await shellfix", async () => {
    const result = validateMenuVisualGate(menuVisualGateJson, catalog, await baseline());
    expect(result.status).toBe("pass_against_baseline_snapshots");
    expect(result.reviewedPassFixtures).toHaveLength(18);
    expect(result.reviewedDivergentFixtures).toHaveLength(10);
    expect(result.pendingShellfixFixtures).toHaveLength(29);
    expect(result.corrective).toBe("shellfix task #101");
  });

  it("rejects a dropped pending_shellfix entry by the exact 29-state census", async () => {
    const scratch = structuredClone(menuVisualGateJson);
    scratch.pending_shellfix.pop();
    const verified = await baseline();
    expect(() => validateMenuVisualGate(scratch, catalog, verified))
      .toThrow("menu visual gate pending_shellfix census must remain exactly 29");
  });

  it("rejects a pending entry pinned to the wrong settled fixture hash", async () => {
    const scratch = structuredClone(menuVisualGateJson);
    const pending = scratch.pending_shellfix.at(0);
    if (pending === undefined) {
      throw new Error("pending-hash mutation lost its first fixture witness");
    }
    pending.settled_fixture_sha256 = "0".repeat(64);
    const verified = await baseline();
    expect(() => validateMenuVisualGate(scratch, catalog, verified))
      .toThrow("pins the wrong settled fixture hash");
  });

  it("rejects a review record no longer bound to its exact baseline snapshot", async () => {
    const scratch = structuredClone(menuVisualGateJson);
    const reviewed = scratch.reviewed_pass_snapshots.at(0);
    if (reviewed === undefined) {
      throw new Error("review-hash mutation lost its first fixture witness");
    }
    reviewed.baseline_snapshot_sha256 = "0".repeat(64);
    const verified = await baseline();
    expect(() => validateMenuVisualGate(scratch, catalog, verified))
      .toThrow("is not bound to its baseline snapshot hash");
  });

  it("rejects any extra tolerance field", async () => {
    const scratch: Record<string, unknown> = {
      ...structuredClone(menuVisualGateJson),
      epsilon: 1,
    };
    const verified = await baseline();
    expect(() => validateMenuVisualGate(scratch, catalog, verified))
      .toThrow("menu visual gate has keys");
  });
});
