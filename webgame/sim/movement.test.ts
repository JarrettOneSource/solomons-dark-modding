import { describe, expect, it } from "vitest";

import { NATIVE_OBJECT_TYPE, PLAYER_MOVEMENT } from "./constants.js";
import { createEnemyBaseSpeed, tickEnemyMovement, tickPlayerMovement } from "./movement.js";
import { createNativeRng } from "./rng.js";
import type { EnemyActorState, PlayerActorState } from "./types.js";

function player(): PlayerActorState {
  return {
    id: "actor-1",
    insertion_order: 1,
    object_type_id: NATIVE_OBJECT_TYPE.player,
    family: "player",
    participant_id: "1",
    slot: 0,
    position: { x: 0, y: 0 },
    radius: 25,
    tracked_enemy: false,
    initialized: true,
    destroyed: false,
    heading_degrees: 0,
    aim_point: { x: 0, y: -1 },
    sprite_set: { kind: "staff", object_type_id: 0x1b5c, pose: 7 },
    movement: {
      intent: { x: 1, y: 1 },
      velocity: { x: 0, y: 0 },
      transient_multiplier: 1,
      move_speed_scale: 1,
      progression_multiplier: 0.95,
      move_step_scale: 1,
      controlled_damping: false,
    },
    knockback: null,
  };
}

describe("native movement pipelines", () => {
  it("normalizes over-length input and applies collision before float32 damping", () => {
    const moved = tickPlayerMovement(player(), []);
    expect(moved.position.x).toBe(Math.fround(Math.SQRT1_2 / PLAYER_MOVEMENT.input_divisor));
    expect(moved.position.y).toBe(moved.position.x);
    expect(moved.movement.velocity.x).toBe(
      Math.fround(moved.position.x * PLAYER_MOVEMENT.ordinary_damping),
    );
  });

  it("phase-locks direct enemy movement and compensates for its cadence", () => {
    const enemy: EnemyActorState = {
      id: "actor-2",
      insertion_order: 2,
      object_type_id: NATIVE_OBJECT_TYPE.wave_enemy,
      family: "enemy",
      enemy_family: "Imp",
      enemy_type: 0,
      position: { x: 0, y: 0 },
      radius: 15,
      tracked_enemy: true,
      initialized: true,
      destroyed: false,
      health: 100,
      maximum_health: 100,
      movement_direction: { x: 1, y: 0 },
      movement_cadence_ticks: 2,
      base_speed: 4.5,
      local_speed_factor: 1,
      shared_status_multiplier: 1,
    };
    expect(tickEnemyMovement(enemy, 1, []).position.x).toBe(0);
    expect(tickEnemyMovement(enemy, 2, []).position.x).toBe(2.25);
  });

  it("owns randomized base speed in the constructor-family mapping", () => {
    const initial = createNativeRng(1);
    const spider = createEnemyBaseSpeed("Spider", initial);
    const skeleton = createEnemyBaseSpeed("Skeleton", initial);
    expect(spider.value).toBeGreaterThanOrEqual(3);
    expect(spider.value).toBeLessThanOrEqual(5);
    expect(skeleton.value).toBeGreaterThanOrEqual(1.953125);
    expect(skeleton.value).toBeLessThanOrEqual(3.515625);
    expect(spider.rng.index_a).toBe(1);
    expect(skeleton.rng.index_a).toBe(1);
  });
});
