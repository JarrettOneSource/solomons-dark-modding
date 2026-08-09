import { describe, expect, it } from "vitest";

import { NATIVE_RNG, TICK_SYSTEM_ORDER } from "./constants.js";
import { serializeSimulationState } from "./serialize.js";
import {
  createSoloSimulation,
  FIRST_LUA_CONTROLLED_PARTICIPANT_ID,
  LOCAL_PARTICIPANT_ID,
  stepSimulation,
} from "./simulation.js";

const config = {
  collision_rectangles: [],
  cast_glyph_points: [{
    sprite_set: "staff" as const,
    bank: 7,
    facing: 0,
    point_index: 1,
    point: { x: 0, y: 0 },
  }],
  spatial_cell_size: 100,
};

describe("shared deterministic simulation", () => {
  it("uses one participant/slot model with string-safe native ids", () => {
    const state = createSoloSimulation({ elapsed_app_ticks: 1485, position: { x: 0, y: 0 } });
    expect(LOCAL_PARTICIPANT_ID).toBe("1");
    expect(FIRST_LUA_CONTROLLED_PARTICIPANT_ID).toBe("1152921504606851072");
    expect(state.participants[0]).toMatchObject({
      kind: "LocalHuman",
      controller: "Native",
      slot: 0,
    });
    expect(state.slots[0]).toBe(state.participants[0]?.id);
    expect(state.rng.state_words[0]).toBe(Math.imul(1485, NATIVE_RNG.seed_tick_multiplier));
  });

  it("consumes G14 movement and FIRE intents without mutating its input state", () => {
    const initial = createSoloSimulation({ elapsed_app_ticks: 1485, position: { x: 0, y: 0 } });
    const before = serializeSimulationState(initial);
    const moved = stepSimulation(initial, [{
      participant_id: LOCAL_PARTICIPANT_ID,
      intent: {
        kind: "move",
        phase: "start",
        move: { type: "unit_vector", vector: { x: 1, y: 0 } },
      },
    }], config);
    expect(serializeSimulationState(initial)).toBe(before);
    expect(moved.actors[0]?.position.x).toBeCloseTo(0.1, 5);

    const cast = stepSimulation(moved, [{
      participant_id: LOCAL_PARTICIPANT_ID,
      intent: { kind: "cast", slot: "primary", phase: "press" },
    }], config);
    expect(cast.actors.some((actor) => actor.family === "fire_projectile")).toBe(true);
    expect(cast.pending_actors).toEqual([]);
  });

  it("pins the native fixed-tick graph instead of a solo/server fork", () => {
    expect(TICK_SYSTEM_ORDER).toEqual([
      "application_actor_world",
      "scene_dispatch",
      "game_pre_world",
      "tracked_actor_snapshot",
      "game_state",
      "initialize_pending_actors",
      "tick_actors_in_insertion_order",
      "remove_destroyed_actors",
      "game_post_world",
      "scene_tick_counter_and_timers",
    ]);
  });
});
