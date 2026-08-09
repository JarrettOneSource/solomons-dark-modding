import { describe, expect, it } from "vitest";

import { createFireProjectile, fireFacingIndex, resolveCastGlyphEmitter, tickFireProjectile } from "./fire.js";
import { createSoloSimulation } from "./simulation.js";
import type { CastGlyphPoint, PlayerActorState } from "./types.js";

function player(): PlayerActorState {
  const state = createSoloSimulation({
    elapsed_app_ticks: 1485,
    position: { x: 100, y: 200 },
    heading_degrees: 359,
  });
  const actor = state.actors[0];
  if (actor?.family !== "player") {
    throw new Error("Fire unit setup did not create a player");
  }
  return actor;
}

describe("FIRE native mechanics", () => {
  it("uses truncation, one facing subtraction, and an unscaled Staff point", () => {
    const wizard = {
      ...player(),
      movement: { ...player().movement, move_speed_scale: 2 },
      sprite_set: { kind: "staff", object_type_id: 0x1b5c, pose: 7 } as const,
    };
    const points: readonly CastGlyphPoint[] = [{
      sprite_set: "staff",
      bank: 7,
      facing: 0,
      point_index: 1,
      point: { x: -4, y: -6 },
    }];
    expect(fireFacingIndex(359)).toBe(0);
    expect(fireFacingIndex(720)).toBe(24);
    expect(resolveCastGlyphEmitter(wizard, points)).toEqual({ x: 96, y: 194 });
  });

  it("refuses ambiguous or missing cast-glyph candidates", () => {
    const wizard = player();
    const point: CastGlyphPoint = {
      sprite_set: "staff",
      bank: 7,
      facing: 0,
      point_index: 1,
      point: { x: 1, y: 2 },
    };
    expect(() => resolveCastGlyphEmitter(wizard, [])).toThrow("resolved 0 candidates");
    expect(() => resolveCastGlyphEmitter(wizard, [point, point])).toThrow("resolved 2 candidates");
  });

  it("tests terrain only every fifth tick with a five-tick lookahead", () => {
    const wizard = { ...player(), heading_degrees: 90 };
    const points: readonly CastGlyphPoint[] = [{
      sprite_set: "staff",
      bank: 7,
      facing: 6,
      point_index: 1,
      point: { x: 0, y: 0 },
    }];
    let projectile = createFireProjectile(wizard, points, 2);
    const wall = [{ id: "east", min_x: 145, min_y: 150, max_x: 146, max_y: 250 }];
    for (let tick = 1; tick < 5; tick += 1) {
      projectile = tickFireProjectile(projectile, [projectile], wall, 100).projectile;
      expect(projectile.destroyed, `terrain cadence tick ${tick}`).toBe(false);
    }
    const fifth = tickFireProjectile(projectile, [projectile], wall, 100);
    expect(fifth.projectile.destroyed).toBe(true);
    expect(fifth.events).toEqual([{
      kind: "fire_removed",
      projectile_id: projectile.id,
      reason: "terrain_contact",
    }]);
  });
});
