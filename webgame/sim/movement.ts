import {
  COLLISION_RESPONSE,
  ENEMY_MOVEMENT,
  PLAYER_MOVEMENT,
} from "./constants.js";
import {
  moveCircle,
  moveCircleWithEnemySubsteps,
  movementCollisionTestCirclePlacement,
  resolveCirclePlacement,
} from "./collision.js";
import { f32 } from "./float32.js";
import { drawNativeScaledFloat } from "./rng.js";
import type {
  CollisionRectangle,
  EnemyActorState,
  EnemyFamily,
  NativeRngState,
  PlayerActorState,
  Vec2,
} from "./types.js";

export function normalizeAtMostOne(direction: Vec2): Vec2 {
  const magnitude = Math.hypot(direction.x, direction.y);
  if (magnitude <= 1) {
    return direction;
  }
  return { x: direction.x / magnitude, y: direction.y / magnitude };
}

function capVelocity(velocity: Vec2, cap: number): Vec2 {
  const magnitude = Math.hypot(velocity.x, velocity.y);
  if (magnitude <= cap) {
    return velocity;
  }
  return {
    x: f32(velocity.x / magnitude * cap),
    y: f32(velocity.y / magnitude * cap),
  };
}

export function tickPlayerMovement(
  actor: PlayerActorState,
  rectangles: readonly CollisionRectangle[],
): PlayerActorState {
  const input = normalizeAtMostOne(actor.movement.intent);
  const accumulatedExtended = {
    x: actor.movement.velocity.x + input.x / PLAYER_MOVEMENT.input_divisor,
    y: actor.movement.velocity.y + input.y / PLAYER_MOVEMENT.input_divisor,
  };
  const accumulated = {
    x: f32(accumulatedExtended.x),
    y: f32(accumulatedExtended.y),
  };
  const cap = actor.movement.transient_multiplier
    * actor.movement.move_speed_scale
    * actor.movement.progression_multiplier
    * PLAYER_MOVEMENT.global_cap_scale;
  const velocityBeforeDamping = capVelocity(accumulated, cap);
  const dampingSource = velocityBeforeDamping === accumulated
    ? accumulatedExtended
    : velocityBeforeDamping;
  const lengthSquared = velocityBeforeDamping.x * velocityBeforeDamping.x
    + velocityBeforeDamping.y * velocityBeforeDamping.y;

  let position = actor.position;
  if (lengthSquared > PLAYER_MOVEMENT.move_threshold_squared) {
    position = moveCircle(
      rectangles,
      actor.position,
      actor.radius,
      {
        x: velocityBeforeDamping.x * actor.movement.move_step_scale,
        y: velocityBeforeDamping.y * actor.movement.move_step_scale,
      },
      "alternate",
    );
  } else if (!movementCollisionTestCirclePlacement(rectangles, actor.position, actor.radius)) {
    position = resolveCirclePlacement(rectangles, actor.position, actor.radius);
  }

  const damping = actor.movement.controlled_damping
    ? PLAYER_MOVEMENT.controlled_damping
    : PLAYER_MOVEMENT.ordinary_damping;
  return {
    ...actor,
    position,
    movement: {
      ...actor.movement,
      velocity: {
        x: f32(dampingSource.x * damping),
        y: f32(dampingSource.y * damping),
      },
    },
  };
}

export function tickPlayerKnockback(
  actor: PlayerActorState,
  rectangles: readonly CollisionRectangle[],
): PlayerActorState {
  const knockback = actor.knockback;
  if (knockback === null || knockback.remaining_distance <= 0) {
    return actor;
  }
  const dx = actor.position.x - knockback.origin.x;
  const dy = actor.position.y - knockback.origin.y;
  const distance = Math.hypot(dx, dy);
  if (distance === 0) {
    throw new Error(`knockback ${actor.id} has no radial direction from its origin`);
  }
  const step = Math.min(knockback.remaining_distance, 10);
  const moved = moveCircle(
    rectangles,
    actor.position,
    actor.radius,
    { x: dx / distance * step, y: dy / distance * step },
    "alternate",
  );
  const separated = moveCircle(
    rectangles,
    moved,
    actor.radius * COLLISION_RESPONSE.knockback_radius_scale,
    { x: 0, y: 0 },
    "alternate",
  );
  const remainingDistance = f32(knockback.remaining_distance - step);
  return {
    ...actor,
    position: separated,
    knockback: remainingDistance > 0
      ? { ...knockback, remaining_distance: remainingDistance }
      : null,
  };
}

function skeletonBaseSpeed(rng: NativeRngState): { readonly value: number; readonly rng: NativeRngState } {
  const random = drawNativeScaledFloat(rng, 1, false);
  return {
    value: f32(f32(1.25 + random.value) * 1.25 * 1.25),
    rng: random.state,
  };
}

export function createEnemyBaseSpeed(
  family: EnemyFamily,
  rng: NativeRngState,
): { readonly value: number; readonly rng: NativeRngState } {
  if (family === "Imp" || family === "Green Imp") {
    return { value: 4.5, rng };
  }
  if (family === "Zombie") {
    return { value: f32(1 * 0.85), rng };
  }
  if (family === "Wraith") {
    return { value: 1, rng };
  }
  if (family === "Demon Skull") {
    return { value: 4, rng };
  }
  if (family === "Dire Faculty") {
    return { value: 2.75, rng };
  }
  if (family === "Spider") {
    const random = drawNativeScaledFloat(rng, 2, false);
    return { value: f32(3 + random.value), rng: random.state };
  }
  if (family === "Demon" || family === "Coffin") {
    return { value: f32(1 * 0.75), rng };
  }
  if (family === "Maggot") {
    const random = drawNativeScaledFloat(rng, 1, false);
    return { value: f32(1 + random.value), rng: random.state };
  }

  const skeleton = skeletonBaseSpeed(rng);
  if (family === "Skeleton") {
    return skeleton;
  }
  if (family === "Skeleton Archer") {
    return { value: f32(skeleton.value * 0.75), rng: skeleton.rng };
  }
  if (family === "Skeleton Mage") {
    return { value: f32(f32(skeleton.value * 0.75) * 0.65), rng: skeleton.rng };
  }
  return { value: f32(f32(skeleton.value * 0.65) * 0.75), rng: skeleton.rng };
}

export function tickEnemyMovement(
  actor: EnemyActorState,
  globalTick: number,
  rectangles: readonly CollisionRectangle[],
): EnemyActorState {
  const cadence = actor.movement_cadence_ticks;
  if (actor.insertion_order % cadence !== globalTick % cadence) {
    return actor;
  }
  const directionLength = Math.hypot(actor.movement_direction.x, actor.movement_direction.y);
  if (directionLength === 0) {
    return actor;
  }
  const scale = ENEMY_MOVEMENT.direct_step_scale
    * actor.base_speed
    * actor.local_speed_factor
    * actor.shared_status_multiplier
    * cadence;
  const position = moveCircleWithEnemySubsteps(
    rectangles,
    actor.position,
    actor.radius,
    {
      x: actor.movement_direction.x / directionLength * scale,
      y: actor.movement_direction.y / directionLength * scale,
    },
  );
  const localSpeedFactor = actor.local_speed_factor > ENEMY_MOVEMENT.local_factor_floor
    ? Math.max(
        ENEMY_MOVEMENT.local_factor_floor,
        f32(actor.local_speed_factor * ENEMY_MOVEMENT.local_factor_decay),
      )
    : actor.local_speed_factor;
  return { ...actor, position, local_speed_factor: localSpeedFactor };
}
