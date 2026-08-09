import { NATIVE_RNG } from "./constants.js";
import { f32 } from "./float32.js";
import type { NativeRngState } from "./types.js";

function validateSeed(seed: number): void {
  if (!Number.isSafeInteger(seed)) {
    throw new Error("native RNG seed must be a safe integer");
  }
}

function validateState(state: NativeRngState): void {
  if (state.state_words.length !== NATIVE_RNG.state_word_count) {
    throw new Error("native RNG state must contain exactly 55 words");
  }
  if (
    !Number.isInteger(state.index_a)
    || state.index_a < 0
    || state.index_a >= NATIVE_RNG.state_word_count
    || !Number.isInteger(state.index_b)
    || state.index_b < 0
    || state.index_b >= NATIVE_RNG.state_word_count
  ) {
    throw new Error("native RNG ring indices must address the 55-word state");
  }
  if (!Number.isSafeInteger(state.divisor) || state.divisor <= 0) {
    throw new Error("native RNG divisor must be a positive integer");
  }
}

export function deriveNativeSeedFromElapsedTicks(elapsedAppTicks: number): number {
  if (!Number.isSafeInteger(elapsedAppTicks) || elapsedAppTicks < 0) {
    throw new Error("elapsed app ticks must be an explicit non-negative safe integer");
  }
  return Math.imul(elapsedAppTicks, NATIVE_RNG.seed_tick_multiplier);
}

export function createNativeRng(seed: number): NativeRngState {
  validateSeed(seed);
  const stateWords = new Array<number>(NATIVE_RNG.state_word_count);
  stateWords[0] = seed & NATIVE_RNG.mask;
  stateWords[1] = 1;
  for (let index = 2; index < NATIVE_RNG.state_word_count; index += 1) {
    const previous = stateWords[index - 1];
    const beforePrevious = stateWords[index - 2];
    if (previous === undefined || beforePrevious === undefined) {
      throw new Error("native RNG seed ladder lost a required predecessor");
    }
    stateWords[index] = (previous + beforePrevious) & NATIVE_RNG.mask;
  }
  return {
    index_a: NATIVE_RNG.initial_index_a,
    index_b: NATIVE_RNG.initial_index_b,
    state_words: stateWords,
    divisor: NATIVE_RNG.stock_divisor,
  };
}

export interface NativeRngDraw<T> {
  readonly value: T;
  readonly state: NativeRngState;
}

export function drawNativeWord(state: NativeRngState): NativeRngDraw<number> {
  validateState(state);
  const left = state.state_words[state.index_a];
  const right = state.state_words[state.index_b];
  if (left === undefined || right === undefined) {
    throw new Error("native RNG ring lookup did not resolve exactly one word per index");
  }
  const word = (left + right) & NATIVE_RNG.mask;
  const stateWords = [...state.state_words];
  stateWords[state.index_a] = word;
  return {
    value: word,
    state: {
      index_a: (state.index_a + 1) % NATIVE_RNG.state_word_count,
      index_b: (state.index_b + 1) % NATIVE_RNG.state_word_count,
      state_words: stateWords,
      divisor: state.divisor,
    },
  };
}

function positiveInteger(state: NativeRngState, bound: number): NativeRngDraw<number> {
  let powerOfTwo = 2;
  while (powerOfTwo < bound) {
    powerOfTwo *= 2;
  }
  const draw = drawNativeWord(state);
  return {
    value: ((draw.value >>> 6) & (powerOfTwo - 1)) % bound,
    state: draw.state,
  };
}

export function drawNativeInteger(
  state: NativeRngState,
  bound: number,
): NativeRngDraw<number> {
  if (!Number.isSafeInteger(bound)) {
    throw new Error("native RNG integer bound must be a safe integer");
  }
  if (bound === 0) {
    return { value: 0, state };
  }
  if (bound > 0) {
    return positiveInteger(state, bound);
  }
  const magnitude = positiveInteger(state, -bound);
  const sign = positiveInteger(magnitude.state, 2);
  return {
    value: sign.value === 0 ? magnitude.value : -magnitude.value,
    state: sign.state,
  };
}

function drawUnitMagnitude(state: NativeRngState): NativeRngDraw<number> {
  const integer = drawNativeInteger(state, state.divisor + 1);
  const narrowedInteger = f32(integer.value);
  return {
    value: f32(narrowedInteger / state.divisor),
    state: integer.state,
  };
}

function applyNativeSign(state: NativeRngState, value: number): NativeRngDraw<number> {
  const sign = drawNativeInteger(state, 2);
  return {
    value: sign.value === 0 ? value : -value,
    state: sign.state,
  };
}

export function drawNativeUnitFloat(
  state: NativeRngState,
  signed: boolean,
): NativeRngDraw<number> {
  const magnitude = drawUnitMagnitude(state);
  return signed ? applyNativeSign(magnitude.state, magnitude.value) : magnitude;
}

export function drawNativeScaledFloat(
  state: NativeRngState,
  requestedMagnitude: number,
  signed: boolean,
): NativeRngDraw<number> {
  if (!Number.isFinite(requestedMagnitude)) {
    throw new Error("native RNG float magnitude must be finite");
  }
  const unit = drawUnitMagnitude(state);
  const scaled = f32(unit.value * f32(requestedMagnitude));
  return signed ? applyNativeSign(unit.state, scaled) : { value: scaled, state: unit.state };
}
