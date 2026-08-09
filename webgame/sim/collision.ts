import { COLLISION_RESPONSE } from "./constants.js";
import { f32 } from "./float32.js";
import type { CollisionRectangle, Vec2 } from "./types.js";

export type SecondaryCollisionResponse = "primary" | "stop" | "alternate";

export function validateCollisionRectangles(
  rectangles: readonly CollisionRectangle[],
): void {
  const ids = new Set<string>();
  for (const rectangle of rectangles) {
    if (ids.has(rectangle.id)) {
      throw new Error(`collision rectangle lookup is ambiguous for id ${rectangle.id}`);
    }
    ids.add(rectangle.id);
    if (
      !Number.isFinite(rectangle.min_x)
      || !Number.isFinite(rectangle.min_y)
      || !Number.isFinite(rectangle.max_x)
      || !Number.isFinite(rectangle.max_y)
      || rectangle.min_x >= rectangle.max_x
      || rectangle.min_y >= rectangle.max_y
    ) {
      throw new Error(`collision rectangle ${rectangle.id} has invalid ordered bounds`);
    }
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function closestPoint(position: Vec2, rectangle: CollisionRectangle): Vec2 {
  return {
    x: clamp(position.x, rectangle.min_x, rectangle.max_x),
    y: clamp(position.y, rectangle.min_y, rectangle.max_y),
  };
}

function overlap(position: Vec2, radius: number, rectangle: CollisionRectangle): boolean {
  const closest = closestPoint(position, rectangle);
  const dx = position.x - closest.x;
  const dy = position.y - closest.y;
  return dx * dx + dy * dy < radius * radius;
}

export function movementCollisionTestCirclePlacement(
  rectangles: readonly CollisionRectangle[],
  position: Vec2,
  radius: number,
): boolean {
  if (!Number.isFinite(radius) || radius <= 0) {
    throw new Error("circle placement requires a positive finite actor radius");
  }
  return rectangles.every((rectangle) => !overlap(position, radius, rectangle));
}

function resolveInsideRectangle(
  position: Vec2,
  radius: number,
  rectangle: CollisionRectangle,
): Vec2 {
  const choices = [
    { distance: position.x - rectangle.min_x, point: { x: rectangle.min_x - radius, y: position.y } },
    { distance: rectangle.max_x - position.x, point: { x: rectangle.max_x + radius, y: position.y } },
    { distance: position.y - rectangle.min_y, point: { x: position.x, y: rectangle.min_y - radius } },
    { distance: rectangle.max_y - position.y, point: { x: position.x, y: rectangle.max_y + radius } },
  ];
  let selected = choices[0];
  if (selected === undefined) {
    throw new Error("inside-rectangle resolver has no boundary choices");
  }
  for (const choice of choices.slice(1)) {
    if (choice.distance < selected.distance) {
      selected = choice;
    }
  }
  return { x: f32(selected.point.x), y: f32(selected.point.y) };
}

function resolveOne(
  position: Vec2,
  radius: number,
  rectangle: CollisionRectangle,
): Vec2 {
  const closest = closestPoint(position, rectangle);
  const dx = position.x - closest.x;
  const dy = position.y - closest.y;
  const distanceSquared = dx * dx + dy * dy;
  if (distanceSquared >= radius * radius) {
    return position;
  }
  if (distanceSquared === 0) {
    return resolveInsideRectangle(position, radius, rectangle);
  }
  const distance = Math.sqrt(distanceSquared);
  return {
    x: f32(closest.x + dx / distance * radius),
    y: f32(closest.y + dy / distance * radius),
  };
}

export function resolveCirclePlacement(
  rectangles: readonly CollisionRectangle[],
  position: Vec2,
  radius: number,
): Vec2 {
  let resolved = { x: f32(position.x), y: f32(position.y) };
  for (let iteration = 0; iteration < COLLISION_RESPONSE.iteration_limit; iteration += 1) {
    let changed = false;
    for (const rectangle of rectangles) {
      const next = resolveOne(resolved, radius, rectangle);
      if (next.x !== resolved.x || next.y !== resolved.y) {
        changed = true;
        resolved = next;
      }
    }
    if (!changed) {
      break;
    }
  }
  return resolved;
}

export function moveCircle(
  rectangles: readonly CollisionRectangle[],
  position: Vec2,
  radius: number,
  delta: Vec2,
  secondaryResponse: SecondaryCollisionResponse,
): Vec2 {
  const tentative = {
    x: f32(position.x + delta.x),
    y: f32(position.y + delta.y),
  };
  if (movementCollisionTestCirclePlacement(rectangles, tentative, radius)) {
    return tentative;
  }
  if (secondaryResponse === "primary") {
    return resolveCirclePlacement(rectangles, tentative, radius);
  }
  if (secondaryResponse === "stop") {
    return { x: f32(position.x), y: f32(position.y) };
  }

  // Native 0x00522B20 restores the origin before the 0x00522A30 alternate.
  // Advancing the ordered, legalized origin preserves the requested tangent.
  const legalOrigin = resolveCirclePlacement(rectangles, position, radius);
  return {
    x: f32(legalOrigin.x + delta.x),
    y: f32(legalOrigin.y + delta.y),
  };
}

export function moveCircleWithEnemySubsteps(
  rectangles: readonly CollisionRectangle[],
  position: Vec2,
  radius: number,
  delta: Vec2,
): Vec2 {
  const length = Math.hypot(delta.x, delta.y);
  const maximumStep = radius - COLLISION_RESPONSE.enemy_substep_radius_margin;
  const stepCount = maximumStep > 0 ? Math.max(1, Math.ceil(length / maximumStep)) : 1;
  const step = { x: delta.x / stepCount, y: delta.y / stepCount };
  let result = position;
  for (let index = 0; index < stepCount; index += 1) {
    result = moveCircle(rectangles, result, radius, step, "alternate");
  }
  return result;
}
