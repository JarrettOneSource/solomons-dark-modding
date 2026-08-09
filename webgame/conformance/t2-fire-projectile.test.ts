import { describe, expect, it } from "vitest";

import { FIRE, NATIVE_OBJECT_TYPE } from "../sim/constants.js";
import { createFireProjectile, tickFireProjectile } from "../sim/fire.js";
import { createSoloSimulation, stepSimulation } from "../sim/simulation.js";
import type {
  ActorState,
  CastGlyphPoint,
  EnemyActorState,
  PlayerActorState,
  SimulationConfig,
} from "../sim/types.js";
import {
  fixtureArray,
  fixtureNumber,
  fixtureRecord,
  readRepositoryJson,
} from "./fixture-reader.js";

interface FireTrajectoryRow {
  readonly tick_index: number;
  readonly x: number;
  readonly y: number;
  readonly radius: number;
  readonly age_ticks: number;
  readonly velocity_x: number;
  readonly velocity_y: number;
  readonly wizard_x: number;
  readonly wizard_y: number;
  readonly wizard_heading_degrees: number;
}

function fireRow(value: unknown, label: string): FireTrajectoryRow {
  const row = fixtureArray(value, label);
  if (row.length !== 14) {
    throw new Error(`${label} must contain all 14 Fire trajectory columns`);
  }
  return {
    tick_index: fixtureNumber(row[0], `${label}.tickIndex`),
    x: fixtureNumber(row[4], `${label}.x`),
    y: fixtureNumber(row[5], `${label}.y`),
    radius: fixtureNumber(row[6], `${label}.radius`),
    age_ticks: fixtureNumber(row[7], `${label}.ageTicks`),
    velocity_x: fixtureNumber(row[8], `${label}.velocityX`),
    velocity_y: fixtureNumber(row[9], `${label}.velocityY`),
    wizard_x: fixtureNumber(row[10], `${label}.wizardX`),
    wizard_y: fixtureNumber(row[11], `${label}.wizardY`),
    wizard_heading_degrees: fixtureNumber(row[12], `${label}.wizardHeadingDegrees`),
  };
}

const staffBank7Facing19: readonly CastGlyphPoint[] = [{
  sprite_set: "staff",
  bank: 7,
  facing: 19,
  point_index: 1,
  point: { x: -41.5, y: -34.5 },
}];

function wizardFromRow(row: FireTrajectoryRow): PlayerActorState {
  const state = createSoloSimulation({
    elapsed_app_ticks: 1485,
    position: { x: row.wizard_x, y: row.wizard_y },
    heading_degrees: row.wizard_heading_degrees,
  });
  const actor = state.actors[0];
  if (actor?.family !== "player") {
    throw new Error("solo Fire conformance setup did not create one player actor");
  }
  return actor;
}

function trackedEnemy(id: string, x: number, y: number): EnemyActorState {
  return {
    id,
    insertion_order: 2,
    object_type_id: NATIVE_OBJECT_TYPE.wave_enemy,
    family: "enemy",
    enemy_family: "Skeleton",
    enemy_type: 0,
    position: { x, y },
    radius: 15,
    tracked_enemy: true,
    initialized: true,
    destroyed: false,
    health: 100,
    maximum_health: 100,
    movement_direction: { x: 0, y: 0 },
    movement_cadence_ticks: 2,
    base_speed: 1.953125,
    local_speed_factor: 1,
    shared_status_multiplier: 1,
  };
}

describe("T2 native FIRE projectile replay", () => {
  it("matches every comparable landed rank-1 and rank-2 trajectory tick", async () => {
    const root = fixtureRecord(
      await readRepositoryJson("tests/fixtures/webgame/projectile-goldens.json"),
      "projectile fixture",
    );
    const capture = fixtureRecord(root.capture, "projectile fixture.capture");
    const epsilonJustification = fixtureRecord(
      capture.epsilonJustification,
      "projectile fixture.capture.epsilonJustification",
    );
    const epsilon = fixtureNumber(
      epsilonJustification.trajectoryWorldUnits,
      "Fire trajectory epsilon",
    );
    const trajectories = fixtureRecord(root.trajectories, "projectile fixture.trajectories");
    const fire = fixtureRecord(trajectories.fire, "projectile fixture.trajectories.fire");

    for (const rankName of ["rank1", "rank2"] as const) {
      const rank = fixtureRecord(fire[rankName], `fire.${rankName}`);
      const samples = fixtureRecord(rank.samples, `fire.${rankName}.samples`);
      const rows = fixtureArray(samples.rows, `fire.${rankName}.samples.rows`)
        .map((value, index) => fireRow(value, `fire.${rankName}.rows[${index}]`));
      expect(rows, `${rankName} must retain the 399-row recorder window`).toHaveLength(399);
      const first = rows[0];
      if (first === undefined) {
        throw new Error(`${rankName} has no first Fire row`);
      }
      const wizard = wizardFromRow(first);
      let projectile = createFireProjectile(wizard, staffBank7Facing19, 2);

      // Row 398 is the recorder's explicit frozen tombstone after removal.
      // Rows 0..397 are the comparable live native actor trajectory.
      for (let index = 0; index < rows.length - 1; index += 1) {
        const expected = rows[index];
        if (expected === undefined) {
          throw new Error(`${rankName} Fire row lookup failed at ${index}`);
        }
        projectile = tickFireProjectile(projectile, [projectile], [], 100).projectile;
        expect(Math.abs(projectile.position.x - expected.x), `${rankName} tick ${index} x`)
          .toBeLessThanOrEqual(epsilon);
        expect(Math.abs(projectile.position.y - expected.y), `${rankName} tick ${index} y`)
          .toBeLessThanOrEqual(epsilon);
        expect(projectile.radius, `${rankName} tick ${index} radius`).toBe(expected.radius);
        expect(projectile.age_ticks, `${rankName} tick ${index} age`).toBe(expected.age_ticks);
        expect(Math.abs(projectile.aim_unit.x - expected.velocity_x), `${rankName} aim x`)
          .toBeLessThanOrEqual(epsilon);
        expect(Math.abs(projectile.aim_unit.y - expected.velocity_y), `${rankName} aim y`)
          .toBeLessThanOrEqual(epsilon);
      }
      const penultimate = rows[397];
      const tombstone = rows[398];
      if (penultimate === undefined || tombstone === undefined) {
        throw new Error(`${rankName} lacks its terminal Fire recorder rows`);
      }
      expect(tombstone.x).toBe(penultimate.x);
      expect(tombstone.y).toBe(penultimate.y);
      expect(tombstone.age_ticks).toBe(penultimate.age_ticks);

      const noInventedLifetime = tickFireProjectile(projectile, [projectile], [], 100).projectile;
      expect(noInventedLifetime.age_ticks).toBe(399);
      expect(noInventedLifetime.destroyed).toBe(false);
      expect(noInventedLifetime.position).not.toEqual(projectile.position);
    }
  });

  it("matches the landed first-tick contact and produces no residual HP damage", async () => {
    const root = fixtureRecord(
      await readRepositoryJson("tests/fixtures/webgame/projectile-goldens.json"),
      "projectile fixture",
    );
    const contacts = fixtureArray(root.contacts, "projectile fixture.contacts");
    const fireCandidates = contacts
      .map((value, index) => fixtureRecord(value, `contact[${index}]`))
      .filter((contact) => contact.element === "fire");
    expect(fireCandidates, "Fire contact lookup must refuse missing or duplicate candidates").toHaveLength(1);
    const contact = fireCandidates[0];
    if (contact === undefined) {
      throw new Error("Fire contact lookup lost its unique fixture candidate");
    }
    const firstSample = fixtureRecord(contact.firstSample, "Fire contact.firstSample");
    const wizardX = fixtureNumber(firstSample.wizardX, "Fire contact wizardX");
    const wizardY = fixtureNumber(firstSample.wizardY, "Fire contact wizardY");
    const wizard = wizardFromRow({
      tick_index: 0,
      x: fixtureNumber(firstSample.projectileX, "Fire contact projectileX"),
      y: fixtureNumber(firstSample.projectileY, "Fire contact projectileY"),
      radius: fixtureNumber(firstSample.projectileRadius, "Fire contact projectileRadius"),
      age_ticks: fixtureNumber(firstSample.projectileAgeTicks, "Fire contact projectileAgeTicks"),
      velocity_x: -0.953208208,
      velocity_y: -0.30231452,
      wizard_x: wizardX,
      wizard_y: wizardY,
      wizard_heading_degrees: 287.59668,
    });
    const target = trackedEnemy(
      "actor-2",
      fixtureNumber(firstSample.targetX, "Fire contact targetX"),
      fixtureNumber(firstSample.targetY, "Fire contact targetY"),
    );
    const projectile = { ...createFireProjectile(wizard, staffBank7Facing19, 3), initialized: true };
    const direct = tickFireProjectile(projectile, [wizard, target, projectile], [], 100);
    expect(direct.projectile.position.x).toBeCloseTo(
      fixtureNumber(firstSample.projectileX, "Fire first projectileX"),
      4,
    );
    expect(direct.projectile.position.y).toBeCloseTo(
      fixtureNumber(firstSample.projectileY, "Fire first projectileY"),
      4,
    );
    expect(direct.projectile.destroyed).toBe(true);
    expect(direct.events.map((event) => event.kind)).toEqual([
      "fire_status",
      "damage",
      "fire_removed",
    ]);
    const damage = direct.events.find((event) => event.kind === "damage");
    expect(damage?.amount).toBe(fixtureNumber(contact.observedDamage, "Fire observedDamage"));
    expect(damage?.resulting_health).toBe(fixtureNumber(contact.afterHp, "Fire afterHp"));

    const solo = createSoloSimulation({
      elapsed_app_ticks: 1485,
      position: { x: wizardX, y: wizardY },
      heading_degrees: 287.59668,
    });
    const stateWithContact = {
      ...solo,
      actors: [solo.actors[0], target, projectile].filter((actor): actor is ActorState => actor !== undefined),
      next_actor_serial: 4,
    };
    const config: SimulationConfig = {
      collision_rectangles: [],
      cast_glyph_points: staffBank7Facing19,
      spatial_cell_size: 100,
    };
    let state = stepSimulation(stateWithContact, [], config);
    expect(state.actors.some((actor) => actor.object_type_id === FIRE.object_type_id)).toBe(false);
    for (let tick = 0; tick < fixtureNumber(contact.residualObservationTicks, "residual ticks"); tick += 1) {
      state = stepSimulation(state, [], config);
    }
    const remainingTarget = state.actors.find((actor) => actor.id === target.id);
    expect(remainingTarget?.family).toBe("enemy");
    expect(remainingTarget?.family === "enemy" ? remainingTarget.health : undefined).toBe(96);
    expect(fixtureNumber(contact.subsequentHpDamage, "subsequentHpDamage")).toBe(0);
  });
});
