import { describe, expect, it } from "vitest";

import { canonicalJson } from "../canonical-json.js";

describe("canonicalJson", () => {
  it("sorts every object level and normalizes negative zero", () => {
    expect(canonicalJson({ z: -0, a: { y: 2, x: 1 } })).toBe(
      '{\n  "a": {\n    "x": 1,\n    "y": 2\n  },\n  "z": 0\n}\n',
    );
  });

  it("rejects values that JSON would silently erase", () => {
    expect(() => canonicalJson({ missing: undefined })).toThrow("$.missing is undefined");
    expect(() => canonicalJson(Number.NaN)).toThrow("$ contains a non-finite number");
  });
});
