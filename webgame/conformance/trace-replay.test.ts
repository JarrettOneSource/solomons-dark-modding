import { describe, expect, it } from "vitest";

import { createSoloSimulation } from "../sim/simulation.js";
import {
  corruptTraceSingleBit,
  createSelfTrace,
  parseTraceTimeline,
  REPLAY_DIVERGENCE_BUDGETS,
  replayTrace,
} from "./trace-replay.js";

describe("simulation trace replay", () => {
  it("declares zero self-trace budgets and replays a scripted timeline exactly", () => {
    expect(REPLAY_DIVERGENCE_BUDGETS).toEqual({
      clock: 0,
      participants: 0,
      rng: 0,
      movement: 0,
      fire: 0,
      actor_model: 0,
    });
    const initial = createSoloSimulation({
      elapsed_app_ticks: 1485,
      position: { x: 0, y: 0 },
      heading_degrees: 0,
    });
    const trace = createSelfTrace(initial, 600);
    const parsed = parseTraceTimeline(JSON.parse(JSON.stringify(trace)) as unknown);
    expect(replayTrace(parsed).ticks_replayed).toBe(600);
  });

  it("fails loudly on a single-bit recorded-state corruption", () => {
    const initial = createSoloSimulation({
      elapsed_app_ticks: 1485,
      position: { x: 0, y: 0 },
      heading_degrees: 0,
    });
    const trace = createSelfTrace(initial, 20);
    expect(() => replayTrace(corruptTraceSingleBit(trace))).toThrow(
      "rng divergence at tick 10 $.state_words[0]",
    );
  });
});
