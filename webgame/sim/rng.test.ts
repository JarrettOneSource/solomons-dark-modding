import { describe, expect, it } from "vitest";

import { NATIVE_RNG } from "./constants.js";
import {
  createNativeRng,
  deriveNativeSeedFromElapsedTicks,
  drawNativeInteger,
  drawNativeScaledFloat,
  drawNativeUnitFloat,
} from "./rng.js";

describe("native RNG state and lifecycle", () => {
  it("derives the run seed only from explicit elapsed tick state", () => {
    expect(deriveNativeSeedFromElapsedTicks(1485)).toBe(5_683_095);
    expect(() => deriveNativeSeedFromElapsedTicks(-1)).toThrow("explicit non-negative");
  });

  it("constructs the 55-word Fibonacci ladder and preserves the zero-bound stream", () => {
    const state = createNativeRng(5_683_095);
    expect(state.index_a).toBe(0);
    expect(state.index_b).toBe(31);
    expect(state.state_words).toHaveLength(55);
    expect(state.state_words.slice(0, 6)).toEqual([
      5_683_095,
      1,
      5_683_096,
      5_683_097,
      11_366_193,
      17_049_290,
    ]);
    const zero = drawNativeInteger(state, 0);
    expect(zero.value).toBe(0);
    expect(zero.state).toBe(state);
    expect(state.state_words.every((word) => word >= 0 && word <= NATIVE_RNG.mask)).toBe(true);
  });

  it("charges signed integer and float requests for the second sign word", () => {
    const initial = createNativeRng(1);
    const integer = drawNativeInteger(initial, -100);
    const scaled = drawNativeScaledFloat(initial, 4.5, true);
    const unit = drawNativeUnitFloat(initial, true);
    expect(integer.state.index_a).toBe(2);
    expect(scaled.state.index_a).toBe(2);
    expect(unit.state.index_a).toBe(2);
  });
});
