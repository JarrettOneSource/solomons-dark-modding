import { describe, expect, it } from "vitest";

import {
  G13_PHASE_ORDER,
  buildTransitionReplay,
  replayEveryLegalEdge,
  resolveSessionEdge,
} from "./session-flow.js";

describe("G13 P1 session transitions", () => {
  it("implements every one of the twenty-three golden graph edges", () => {
    const replays = replayEveryLegalEdge();
    expect(replays).toHaveLength(23);
    for (const replay of replays) {
      expect(replay.phaseEvents.map((event) => event.phase)).toEqual(G13_PHASE_ORDER);
      expect(replay.phaseEvents.map((event) => event.index)).toEqual(
        Array.from({ length: 14 }, (_, index) => index),
      );
    }
  });

  it("models the solo Arena handshake instead of skipping it", () => {
    const replay = buildTransitionReplay("gameplay.courtyard", "start_run");
    expect(replay.fadeOutRatePerTick).toBe(0.01);
    expect(replay.fadeInRatePerTick).toBe(-0.05);
    expect(replay.durationMilliseconds).toBe(1270);
    expect(replay.phaseEvents[0]?.tick).toBe(101);
    expect(replay.phaseEvents[11]?.tick).toBe(122);
    expect(replay.phaseEvents[12]?.tick).toBe(127);
    expect(replay.phaseEvents[13]?.tick).toBe(127);
    expect(replay.barrier).toEqual({
      expectedParticipantIds: [0],
      visibleParticipantIds: [0],
      stableMilliseconds: 250,
      timeoutMilliseconds: 25_000,
      releaseReason: "all-ready",
    });
  });

  it("composes the recorded stock fade with the exact room-specific fade-ins", () => {
    const library = buildTransitionReplay("gameplay.courtyard", "enter_library");
    expect(library.fadeOutRatePerTick).toBe(0.01);
    expect(library.fadeInRatePerTick).toBe(-0.025);
    expect(library.phaseEvents[0]?.tick).toBe(101);
    expect(library.phaseEvents[11]?.tick).toBe(143);
    const courtyard = buildTransitionReplay("gameplay.library", "return_courtyard");
    expect(courtyard.fadeInRatePerTick).toBe(-0.01);
    expect(courtyard.phaseEvents[0]?.tick).toBe(101);
    expect(courtyard.phaseEvents[11]?.tick).toBe(103);
  });

  it("refuses illegal and ambiguous edge lookup by source", () => {
    expect(() => resolveSessionEdge("gameplay.library", "enter_office")).toThrow(
      "G13 transition gameplay.library/enter_office is illegal",
    );
    expect(resolveSessionEdge("gameplay.library", "return_courtyard").destination)
      .toBe("gameplay.courtyard");
  });
});
