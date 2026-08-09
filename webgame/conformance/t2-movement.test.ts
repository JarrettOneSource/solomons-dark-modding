import { describe, expect, it } from "vitest";

import { NATIVE_OBJECT_TYPE, PLAYER_MOVEMENT } from "../sim/constants.js";
import { tickPlayerKnockback, tickPlayerMovement } from "../sim/movement.js";
import type { CollisionRectangle, PlayerActorState } from "../sim/types.js";
import {
  fixtureArray,
  fixtureBoolean,
  fixtureNumber,
  fixtureRecord,
  fixtureString,
  readRepositoryJson,
} from "./fixture-reader.js";

interface MovementSample {
  readonly applied_input_x: number;
  readonly applied_input_y: number;
  readonly index: number;
  readonly knockback_present: boolean;
  readonly radius: number;
  readonly speed_scalar: number;
  readonly vx: number;
  readonly vy: number;
  readonly x: number;
  readonly y: number;
}

function movementSample(value: unknown, label: string): MovementSample {
  const sample = fixtureRecord(value, label);
  return {
    applied_input_x: fixtureNumber(sample.applied_input_x, `${label}.applied_input_x`),
    applied_input_y: fixtureNumber(sample.applied_input_y, `${label}.applied_input_y`),
    index: fixtureNumber(sample.index, `${label}.index`),
    knockback_present: fixtureBoolean(sample.knockback_present, `${label}.knockback_present`),
    radius: fixtureNumber(sample.radius, `${label}.radius`),
    speed_scalar: fixtureNumber(sample.speed_scalar, `${label}.speed_scalar`),
    vx: fixtureNumber(sample.vx, `${label}.vx`),
    vy: fixtureNumber(sample.vy, `${label}.vy`),
    x: fixtureNumber(sample.x, `${label}.x`),
    y: fixtureNumber(sample.y, `${label}.y`),
  };
}

function playerFromSample(sample: MovementSample): PlayerActorState {
  return {
    id: "actor-1",
    insertion_order: 1,
    object_type_id: NATIVE_OBJECT_TYPE.player,
    family: "player",
    participant_id: "1",
    slot: 0,
    position: { x: sample.x, y: sample.y },
    radius: sample.radius,
    tracked_enemy: false,
    initialized: true,
    destroyed: false,
    heading_degrees: 0,
    aim_point: { x: sample.x, y: sample.y - 1 },
    sprite_set: { kind: "staff", object_type_id: 0x1b5c, pose: 7 },
    movement: {
      intent: { x: 0, y: 0 },
      velocity: { x: sample.vx, y: sample.vy },
      transient_multiplier: PLAYER_MOVEMENT.transient_multiplier,
      move_speed_scale: PLAYER_MOVEMENT.move_speed_scale,
      progression_multiplier: PLAYER_MOVEMENT.progression_multiplier,
      move_step_scale: sample.speed_scalar,
      controlled_damping: false,
    },
    knockback: null,
  };
}

const northWall: readonly CollisionRectangle[] = [{
  id: "movement-fixture-north-wall",
  min_x: -10_000,
  min_y: -10_000,
  max_x: 10_000,
  max_y: -15,
}];

describe("T2 native movement replay", () => {
  it("matches every landed player movement, wall response, and knockback sample", async () => {
    const root = fixtureRecord(
      await readRepositoryJson("tests/fixtures/webgame/movement-goldens.json"),
      "movement fixture",
    );
    const header = fixtureRecord(root.header, "movement fixture.header");
    const epsilon = fixtureRecord(header.epsilon, "movement fixture.header.epsilon");
    const positionEpsilon = fixtureNumber(epsilon.position_absolute, "position epsilon");
    const scalarEpsilon = fixtureNumber(epsilon.scalar_absolute, "scalar epsilon");
    const scenarios = fixtureArray(root.scenarios, "movement fixture.scenarios");
    expect(scenarios).toHaveLength(9);

    for (const [scenarioIndex, scenarioValue] of scenarios.entries()) {
      const scenario = fixtureRecord(scenarioValue, `scenario[${scenarioIndex}]`);
      const id = fixtureString(scenario.id, `scenario[${scenarioIndex}].id`);
      const samples = fixtureArray(scenario.samples, `${id}.samples`).map((value, index) => (
        movementSample(value, `${id}.samples[${index}]`)
      ));
      expect(samples.length, `${id} must contain real recorded ticks`).toBeGreaterThan(100);
      const first = samples[0];
      if (first === undefined) {
        throw new Error(`${id} has no first movement sample`);
      }
      let actor = playerFromSample(first);
      const rectangles = id.startsWith("wall_") ? northWall : [];

      for (let index = 0; index < samples.length - 1; index += 1) {
        const current = samples[index];
        const expected = samples[index + 1];
        if (current === undefined || expected === undefined) {
          throw new Error(`${id} movement row lookup failed at ${index}`);
        }
        actor = tickPlayerMovement({
          ...actor,
          movement: {
            ...actor.movement,
            intent: {
              x: current.applied_input_x,
              y: current.applied_input_y,
            },
          },
        }, rectangles);
        if (current.knockback_present) {
          actor = tickPlayerKnockback(actor, rectangles);
        }
        if (id === "knockback_contact" && expected.index === 2) {
          actor = {
            ...actor,
            knockback: { origin: { x: 950, y: 1050 }, remaining_distance: 20 },
          };
        }

        expect(actor.position.x, `${id} tick ${expected.index} x`).toBeCloseTo(
          expected.x,
          Math.ceil(-Math.log10(positionEpsilon)),
        );
        expect(actor.position.y, `${id} tick ${expected.index} y`).toBeCloseTo(
          expected.y,
          Math.ceil(-Math.log10(positionEpsilon)),
        );
        expect(Math.abs(actor.movement.velocity.x - expected.vx), `${id} tick ${expected.index} vx`)
          .toBeLessThanOrEqual(scalarEpsilon);
        expect(Math.abs(actor.movement.velocity.y - expected.vy), `${id} tick ${expected.index} vy`)
          .toBeLessThanOrEqual(scalarEpsilon);
        expect(actor.radius, `${id} tick ${expected.index} radius`).toBe(expected.radius);
        expect(actor.knockback !== null, `${id} tick ${expected.index} knockback presence`)
          .toBe(expected.knockback_present);
      }
    }
  });
});
