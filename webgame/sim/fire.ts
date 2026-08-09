import { FIRE, GAMEPLAY_CADENCE_TICKS } from "./constants.js";
import { f32 } from "./float32.js";
import type {
  ActorState,
  CastGlyphPoint,
  CastSpriteSet,
  CollisionRectangle,
  EnemyActorState,
  FireProjectileState,
  PlayerActorState,
  SimulationEvent,
  Vec2,
} from "./types.js";

export function fireFacingIndex(headingDegrees: number): number {
  if (!Number.isFinite(headingDegrees)) {
    throw new Error("cast-glyph facing requires a finite heading");
  }
  const truncatedHeading = Math.trunc(headingDegrees);
  let facing = Math.trunc((truncatedHeading + 7) / 15);
  if (facing >= 24) {
    facing -= 24;
  }
  return facing;
}

function castGlyphBank(spriteSet: CastSpriteSet): number {
  if (spriteSet.kind === "none") {
    return 0;
  }
  if (spriteSet.kind === "staff") {
    return Math.trunc(spriteSet.pose);
  }
  return Math.trunc(Math.max(0, Math.min(2, spriteSet.pose - 14)));
}

export function resolveCastGlyphEmitter(
  wizard: PlayerActorState,
  glyphPoints: readonly CastGlyphPoint[],
): Vec2 {
  const facing = fireFacingIndex(wizard.heading_degrees);
  const bank = castGlyphBank(wizard.sprite_set);
  const matches = glyphPoints.filter((entry) => (
    entry.sprite_set === wizard.sprite_set.kind
    && entry.bank === bank
    && entry.facing === facing
    && entry.point_index === 1
  ));
  if (matches.length !== 1) {
    throw new Error(
      `cast-glyph emitter lookup for ${wizard.sprite_set.kind} bank ${bank} facing ${facing} resolved ${matches.length} candidates`,
    );
  }
  const match = matches[0];
  if (match === undefined) {
    throw new Error("cast-glyph emitter lookup lost its unique candidate");
  }
  const scale = wizard.sprite_set.kind === "staff"
    ? 1
    : wizard.movement.move_speed_scale;
  return {
    x: f32(wizard.position.x + match.point.x * scale),
    y: f32(wizard.position.y + match.point.y * scale),
  };
}

export function aimUnitFromHeading(headingDegrees: number): Vec2 {
  const radians = headingDegrees * Math.PI / 180;
  return {
    x: f32(Math.sin(radians)),
    y: f32(-Math.cos(radians)),
  };
}

export function createFireProjectile(
  wizard: PlayerActorState,
  glyphPoints: readonly CastGlyphPoint[],
  insertionOrder: number,
): FireProjectileState {
  const emitter = resolveCastGlyphEmitter(wizard, glyphPoints);
  const aimUnit = aimUnitFromHeading(wizard.heading_degrees);
  return {
    id: `actor-${insertionOrder}`,
    insertion_order: insertionOrder,
    object_type_id: FIRE.object_type_id,
    family: "fire_projectile",
    owner_participant_id: wizard.participant_id,
    position: {
      x: f32(emitter.x + FIRE.local_offset_x + aimUnit.x * FIRE.forward_spawn_offset),
      y: f32(emitter.y + FIRE.local_offset_y + aimUnit.y * FIRE.forward_spawn_offset),
    },
    radius: FIRE.collision_radius,
    tracked_enemy: false,
    initialized: false,
    destroyed: false,
    aim_unit: aimUnit,
    age_ticks: 0,
  };
}

function sameSpatialCell(left: Vec2, right: Vec2, cellSize: number): boolean {
  if (!Number.isFinite(cellSize) || cellSize <= 0) {
    throw new Error("fire spatial cell size must be positive and finite");
  }
  return Math.floor(left.x / cellSize) === Math.floor(right.x / cellSize)
    && Math.floor(left.y / cellSize) === Math.floor(right.y / cellSize);
}

function findFireTarget(
  projectile: FireProjectileState,
  actors: readonly ActorState[],
  cellSize: number,
): EnemyActorState | null {
  for (const actor of actors) {
    if (
      actor.family !== "enemy"
      || !actor.tracked_enemy
      || actor.destroyed
      || actor.health <= 0
      || !sameSpatialCell(projectile.position, actor.position, cellSize)
    ) {
      continue;
    }
    const distance = Math.hypot(
      projectile.position.x - actor.position.x,
      projectile.position.y - actor.position.y,
    );
    const inNativeQuery = distance <= FIRE.target_query_radius + actor.radius;
    const circlesContact = distance <= projectile.radius + actor.radius;
    if (inNativeQuery && circlesContact) {
      return actor;
    }
  }
  return null;
}

function segmentIntersectsExpandedRectangle(
  start: Vec2,
  end: Vec2,
  radius: number,
  rectangle: CollisionRectangle,
): boolean {
  const minimum = { x: rectangle.min_x - radius, y: rectangle.min_y - radius };
  const maximum = { x: rectangle.max_x + radius, y: rectangle.max_y + radius };
  const delta = { x: end.x - start.x, y: end.y - start.y };
  let near = 0;
  let far = 1;
  for (const axis of ["x", "y"] as const) {
    const axisDelta = delta[axis];
    if (axisDelta === 0) {
      if (start[axis] < minimum[axis] || start[axis] > maximum[axis]) {
        return false;
      }
      continue;
    }
    const inverse = 1 / axisDelta;
    let first = (minimum[axis] - start[axis]) * inverse;
    let second = (maximum[axis] - start[axis]) * inverse;
    if (first > second) {
      [first, second] = [second, first];
    }
    near = Math.max(near, first);
    far = Math.min(far, second);
    if (near > far) {
      return false;
    }
  }
  return true;
}

export interface FireTickResult {
  readonly projectile: FireProjectileState;
  readonly actors: readonly ActorState[];
  readonly events: readonly SimulationEvent[];
}

export function tickFireProjectile(
  projectile: FireProjectileState,
  actors: readonly ActorState[],
  rectangles: readonly CollisionRectangle[],
  cellSize: number,
): FireTickResult {
  const moved: FireProjectileState = {
    ...projectile,
    position: {
      x: f32(projectile.position.x + projectile.aim_unit.x * FIRE.speed_per_tick),
      y: f32(projectile.position.y + projectile.aim_unit.y * FIRE.speed_per_tick),
    },
    age_ticks: projectile.age_ticks + 1,
  };

  const target = findFireTarget(moved, actors, cellSize);
  if (target !== null) {
    const resultingHealth = f32(Math.max(0, target.health - FIRE.contact_damage));
    const updatedActors = actors.map((actor) => (
      actor.id === target.id ? { ...target, health: resultingHealth } : actor
    ));
    return {
      projectile: { ...moved, destroyed: true },
      actors: updatedActors,
      events: [
        { kind: "fire_status", projectile_id: moved.id, target_id: target.id },
        {
          kind: "damage",
          projectile_id: moved.id,
          target_id: target.id,
          amount: FIRE.contact_damage,
          resulting_health: resultingHealth,
        },
        { kind: "fire_removed", projectile_id: moved.id, reason: "actor_contact" },
      ],
    };
  }

  if (moved.age_ticks % GAMEPLAY_CADENCE_TICKS.fire_terrain_contact === 0) {
    const lookahead = {
      x: moved.position.x + moved.aim_unit.x * FIRE.speed_per_tick * FIRE.terrain_lookahead_ticks,
      y: moved.position.y + moved.aim_unit.y * FIRE.speed_per_tick * FIRE.terrain_lookahead_ticks,
    };
    const terrainContact = rectangles.some((rectangle) => (
      segmentIntersectsExpandedRectangle(moved.position, lookahead, moved.radius, rectangle)
    ));
    if (terrainContact) {
      return {
        projectile: { ...moved, destroyed: true },
        actors,
        events: [{ kind: "fire_removed", projectile_id: moved.id, reason: "terrain_contact" }],
      };
    }
  }
  return { projectile: moved, actors, events: [] };
}
