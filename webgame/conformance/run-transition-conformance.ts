import assert from "node:assert/strict";

import sessionGoldenJson from "../../tests/fixtures/webgame/session-flow-goldens.json" with { type: "json" };
import {
  G13_ARENA_FADE_IN_TICKS,
  G13_ARENA_RELEASE_TICKS_AFTER_SEAL,
  G13_CACHED_COURTYARD_FADE_IN_TICKS,
  G13_PHASE_ORDER,
  G13_PORTAL_FADE_OUT_TICKS,
  G13_ROOM_FADE_IN_TICKS,
  buildTransitionReplay,
  replayEveryLegalEdge,
} from "../client/session-flow.js";

function uniqueStep(
  steps: readonly Record<string, unknown>[],
  stepName: string,
  occurrence: "first" | "last" = "first",
): Record<string, unknown> {
  const candidates = steps.filter((step) => step.step === stepName);
  assert(candidates.length > 0, `G13 golden timeline lost required ${stepName} witness`);
  const result = occurrence === "first" ? candidates[0] : candidates.at(-1);
  assert(result !== undefined, `G13 golden timeline could not resolve ${stepName}`);
  return result;
}

function tick(step: Record<string, unknown>, claim: string): number {
  assert(typeof step.tick === "number" && Number.isSafeInteger(step.tick), claim);
  return step.tick;
}

function replayTick(
  replay: ReturnType<typeof buildTransitionReplay>,
  index: number,
  claim: string,
): number {
  const event = replay.phaseEvents[index];
  assert(event !== undefined, claim);
  return event.tick;
}

const replays = replayEveryLegalEdge();
assert.equal(replays.length, 23, "G13 conformance did not replay every legal graph edge");
for (const replay of replays) {
  assert.deepEqual(
    replay.phaseEvents.map((event) => event.phase),
    G13_PHASE_ORDER,
    `G13 edge ${replay.source}/${replay.edge} changed the normative fourteen-phase order`,
  );
  for (const [index, event] of replay.phaseEvents.entries()) {
    assert.equal(event.index, index, `G13 edge ${replay.edge} changed phase index ${index}`);
    if (index > 0) {
      assert(
        event.tick >= (replay.phaseEvents[index - 1]?.tick ?? -1),
        `G13 edge ${replay.edge} moved phase ${event.phase} before its predecessor`,
      );
    }
  }
}

const startRun = buildTransitionReplay("gameplay.courtyard", "start_run");
assert.deepEqual(
  startRun.barrier,
  {
    expectedParticipantIds: [0],
    visibleParticipantIds: [0],
    stableMilliseconds: 250,
    timeoutMilliseconds: 25_000,
    releaseReason: "all-ready",
  },
  "G13 solo run entry skipped or weakened the exact-set stable barrier",
);

const recorded = sessionGoldenJson.session_timeline.transitions;
assert.equal(recorded.length, 6, "G13 raw replay did not reach all six landed timelines");
const byEdge = (edge: string) => {
  const candidates = recorded.filter((transition) => transition.edge === edge);
  assert.equal(candidates.length, 1, `G13 raw replay refuses ambiguous ${edge} timelines`);
  const transition = candidates[0];
  assert(transition !== undefined, `G13 raw replay lost timeline ${edge}`);
  return transition.ordered_lifecycle_steps as readonly Record<string, unknown>[];
};

const library = byEdge("enter_library");
const recordedLibraryFadeInTicks = tick(
  uniqueStep(library, "presentation.fade_in.endpoint"),
  "G13 Library fade endpoint lost its tick",
) - tick(
  uniqueStep(library, "presentation.fade_in.begin"),
  "G13 Library fade begin lost its tick",
);
assert.equal(recordedLibraryFadeInTicks, G13_ROOM_FADE_IN_TICKS,
  "G13 Library fade-in no longer takes the exact recorded 41 ticks",
);
const returnCourtyard = byEdge("return_courtyard");
const recordedCourtyardFadeInTicks = tick(
  uniqueStep(returnCourtyard, "presentation.fade_in.endpoint"),
  "G13 cached Courtyard fade endpoint lost its tick",
) - tick(
  uniqueStep(returnCourtyard, "presentation.fade_in.begin"),
  "G13 cached Courtyard fade begin lost its tick",
);
assert.equal(recordedCourtyardFadeInTicks, G13_CACHED_COURTYARD_FADE_IN_TICKS,
  "G13 cached Courtyard fade-in no longer takes the exact recorded one tick",
);
const run = byEdge("start_run_pipeline");
const sealTick = tick(uniqueStep(run, "input.seal"), "G13 Arena seal lost its tick");
const sleepTick = tick(uniqueStep(run, "region.cache.sleep.begin"), "G13 Arena sleep lost its tick");
const fadeEndpointTick = tick(
  uniqueStep(run, "presentation.fade_in.endpoint"),
  "G13 Arena fade endpoint lost its tick",
);
const unsealTick = tick(uniqueStep(run, "input.unseal"), "G13 Arena unseal lost its tick");
const recordedArenaTiming = [sleepTick - sealTick, fadeEndpointTick - sleepTick, unsealTick - sealTick];
assert.deepEqual(
  recordedArenaTiming,
  [1, G13_ARENA_FADE_IN_TICKS, G13_ARENA_RELEASE_TICKS_AFTER_SEAL],
  "G13 Arena seal, swap, 20-tick fade, and 26-tick release timing drifted",
);

const startup = byEdge("startup_office_then_return_courtyard");
const recordedFadeOutTicks = tick(
  uniqueStep(startup, "presentation.fade_out.endpoint"),
  "G13 startup fade-out endpoint lost its tick",
) - tick(
  uniqueStep(startup, "presentation.fade_out.begin"),
  "G13 startup fade-out begin lost its tick",
);
assert.equal(recordedFadeOutTicks, G13_PORTAL_FADE_OUT_TICKS,
  "G13 onboarding Office fade-out no longer takes the exact recorded 101 ticks",
);

const implementedLibrary = buildTransitionReplay("gameplay.courtyard", "enter_library");
const implementedLibraryFadeOut = replayTick(
  implementedLibrary,
  0,
  "implemented Library portal lost its fade-out phase",
);
assert.equal(
  implementedLibraryFadeOut,
  recordedFadeOutTicks,
  "implemented Library portal no longer presents the exact recorded stock fade-out duration",
);
assert.equal(
  replayTick(implementedLibrary, 11, "implemented Library portal lost its fade-in phase")
    - implementedLibraryFadeOut - 1,
  recordedLibraryFadeInTicks,
  "implemented Library portal no longer presents the exact recorded 41-tick fade-in after the swap tick",
);
const implementedReturn = buildTransitionReplay("gameplay.library", "return_courtyard");
const implementedReturnFadeOut = replayTick(
  implementedReturn,
  0,
  "implemented Courtyard return lost its fade-out phase",
);
assert.equal(
  replayTick(implementedReturn, 11, "implemented Courtyard return lost its fade-in phase")
    - implementedReturnFadeOut - 1,
  recordedCourtyardFadeInTicks,
  "implemented cached-Courtyard return no longer presents the exact recorded one-tick fade-in after the swap tick",
);
assert.equal(
  replayTick(startRun, 11, "implemented Arena entry lost its fade-in phase")
    - replayTick(startRun, 0, "implemented Arena entry lost its fade-out phase") - 1,
  recordedArenaTiming[1],
  "implemented Arena entry no longer presents the exact recorded 20-tick fade-in after the swap tick",
);
assert.equal(
  replayTick(startRun, 13, "implemented Arena entry lost its unseal phase")
    - replayTick(startRun, 0, "implemented Arena entry lost its seal boundary"),
  recordedArenaTiming[2],
  "implemented Arena entry no longer holds the exact recorded 26-tick seal-to-unseal interval",
);

process.stdout.write([
  "G13 P1 TRANSITION CONFORMANCE: PASS",
  `graph_edges=${replays.length}/23`,
  `phase_order=${G13_PHASE_ORDER.join(" -> ")}`,
  "fixture_tolerance_ticks=0",
  "library_fade_in_ticks=41",
  "cached_courtyard_fade_in_ticks=1",
  "portal_fade_out_ticks=101; room_fade_in_ticks=41; cached_courtyard_fade_in_ticks=1",
  "arena=101_tick_cover+1_tick_swap+20_tick_fade+250ms_exact_set_barrier+unseal_26_ticks_after_seal",
  "onboarding_office_fade_out_ticks=101",
  "",
].join("\n"));
