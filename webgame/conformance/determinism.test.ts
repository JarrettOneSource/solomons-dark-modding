import { describe, expect, it } from "vitest";

import { proveCrossProcessDeterminism } from "./determinism.js";

describe("serialized state determinism", () => {
  it("is byte-identical across two independent processes and detects one changed bit", async () => {
    const receipt = await proveCrossProcessDeterminism(1_000);
    expect(receipt.process_ids[0]).not.toBe(receipt.process_ids[1]);
    expect(receipt.byte_identical).toBe(true);
    expect(receipt.single_bit_diverged).toBe(true);
    expect(receipt.sha256).not.toBe(receipt.single_bit_control_sha256);
  }, 30_000);
});
