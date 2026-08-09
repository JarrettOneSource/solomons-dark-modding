import { describe, expect, it } from "vitest";

import { float32Bits } from "../sim/float32.js";
import {
  createNativeRng,
  drawNativeInteger,
  drawNativeScaledFloat,
  drawNativeUnitFloat,
} from "../sim/rng.js";
import type { NativeRngState } from "../sim/types.js";
import {
  fixtureArray,
  fixtureBoolean,
  fixtureInteger,
  fixtureRecord,
  fixtureString,
  readRepositoryJson,
} from "./fixture-reader.js";

function integerArray(value: unknown, label: string): readonly number[] {
  return fixtureArray(value, label).map((item, index) => fixtureInteger(item, `${label}[${index}]`));
}

function words(value: unknown, label: string): readonly number[] {
  const parsed = integerArray(value, label);
  expect(parsed, `${label} must cover all native RNG words`).toHaveLength(55);
  return parsed;
}

function numberFromFloat32Bits(bits: string): number {
  if (!/^0x[0-9A-Fa-f]{8}$/.test(bits)) {
    throw new Error(`float fixture magnitude ${bits} is not one binary32 word`);
  }
  const storage = new ArrayBuffer(4);
  const view = new DataView(storage);
  view.setUint32(0, Number.parseInt(bits.slice(2), 16), false);
  return view.getFloat32(0, false);
}

function expectRngState(state: NativeRngState, fixture: Record<string, unknown>, label: string): void {
  expect(state.index_a, `${label} index_a`).toBe(fixtureInteger(fixture.index_a, `${label}.index_a`));
  expect(state.index_b, `${label} index_b`).toBe(fixtureInteger(fixture.index_b, `${label}.index_b`));
  expect(state.divisor, `${label} divisor`).toBe(fixtureInteger(fixture.divisor, `${label}.divisor`));
  expect(state.state_words, `${label} 55-word state`).toEqual(words(fixture.state_words, `${label}.state_words`));
}

describe("native RNG conformance", () => {
  it("reproduces the landed bounded-integer corpus and final ring state exactly", async () => {
    const root = fixtureRecord(
      await readRepositoryJson("tests/fixtures/webgame/rng-goldens.json"),
      "integer RNG fixture",
    );
    const sequences = fixtureArray(root.sequences, "integer RNG fixture.sequences");
    expect(sequences, "integer RNG fixture must retain all four recorded sequences").toHaveLength(4);
    for (const [sequenceIndex, value] of sequences.entries()) {
      const sequence = fixtureRecord(value, `integer sequence[${sequenceIndex}]`);
      const seed = fixtureInteger(sequence.seed, `integer sequence[${sequenceIndex}].seed`);
      const range = fixtureInteger(sequence.range, `integer sequence[${sequenceIndex}].range`);
      const expectedOutputs = integerArray(sequence.outputs, `integer sequence[${sequenceIndex}].outputs`);
      let state = createNativeRng(seed);
      const actual: number[] = [];
      for (const expected of expectedOutputs) {
        const draw = drawNativeInteger(state, range);
        actual.push(draw.value);
        state = draw.state;
        expect(draw.value).toBe(expected);
      }
      expect(actual).toEqual(expectedOutputs);
      expect(state.index_a).toBe(fixtureInteger(sequence.final_index_a, "final_index_a"));
      expect(state.index_b).toBe(fixtureInteger(sequence.final_index_b, "final_index_b"));
      expect(state.state_words).toEqual(integerArray(sequence.final_state_words, "final_state_words"));
    }
  });

  it("consumes the SEALED float corpus with exact bits, rounding points, and sign draws", async () => {
    const root = fixtureRecord(
      await readRepositoryJson("tests/fixtures/webgame/float-rng-goldens.json"),
      "sealed float RNG fixture",
    );
    const nativeContract = fixtureRecord(root.native_contract, "sealed float RNG fixture.native_contract");
    expect(fixtureInteger(nativeContract.scaled_float32_rounding_points, "scaled rounding points")).toBe(3);
    expect(fixtureInteger(nativeContract.unit_float32_rounding_points, "unit rounding points")).toBe(2);
    const captures = fixtureArray(root.captures, "sealed float RNG fixture.captures");
    const labels = captures.map((value, index) => {
      const capture = fixtureRecord(value, `float capture[${index}]`);
      const request = fixtureRecord(capture.request, `float capture[${index}].request`);
      return fixtureString(request.label, `float capture[${index}].request.label`);
    });
    expect(new Set(labels)).toEqual(new Set([
      "scaled-magnitude-1-unsigned",
      "scaled-magnitude-3-unsigned",
      "scaled-magnitude-4_5-signed",
      "scaled-endpoint-zero",
      "scaled-endpoint-positive",
      "unit-unsigned",
      "unit-signed",
      "unit-endpoint-zero",
      "unit-endpoint-positive",
    ]));

    for (const [captureIndex, value] of captures.entries()) {
      const capture = fixtureRecord(value, `float capture[${captureIndex}]`);
      const request = fixtureRecord(capture.request, `float capture[${captureIndex}].request`);
      const label = fixtureString(request.label, `float capture[${captureIndex}].request.label`);
      const primitive = fixtureString(request.primitive, `${label}.primitive`);
      const signed = fixtureBoolean(request.signed, `${label}.signed`);
      const magnitude = numberFromFloat32Bits(
        fixtureString(request.magnitude_float32_bits, `${label}.magnitude_float32_bits`),
      );
      let state = createNativeRng(fixtureInteger(request.seed, `${label}.seed`));
      const draws = fixtureArray(capture.draws, `${label}.draws`);
      expect(draws.length, `${label} draw count`).toBe(fixtureInteger(request.count, `${label}.count`));
      for (const [drawIndex, drawValue] of draws.entries()) {
        const expected = fixtureRecord(drawValue, `${label}.draws[${drawIndex}]`);
        expectRngState(state, fixtureRecord(expected.pre_call, `${label}.pre_call`), `${label} pre ${drawIndex}`);
        const draw = primitive === "scaled"
          ? drawNativeScaledFloat(state, magnitude, signed)
          : drawNativeUnitFloat(state, signed);
        expect(float32Bits(draw.value), `${label} draw ${drawIndex} returned bits`).toBe(
          fixtureString(expected.returned_float32_bits, `${label}.returned_float32_bits`),
        );
        state = draw.state;
        expectRngState(state, fixtureRecord(expected.post_call, `${label}.post_call`), `${label} post ${drawIndex}`);
      }
    }
  });
});
