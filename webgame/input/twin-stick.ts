import type { Point2 } from "./intent.js";

export interface DeadzoneResult {
  readonly direction: Point2;
  readonly magnitude: number;
  readonly vector: Point2;
}

export interface AimProjection {
  readonly playerWorld: Point2;
  readonly projectedPlayerPx: Point2;
  readonly viewportPx: { readonly width: number; readonly height: number };
  readonly cameraScale: number;
}

export const GAMEPAD_INNER_DEADZONE = 0.2;
export const GAMEPAD_OUTER_DEADZONE = 0.95;
export const AIM_ANCHOR_Y_OFFSET_PX = -25;

// G12 §P0 controller aim reach: the default 1600x900 camera projects the
// player at (800,450). The retail torso anchor is (800,425), so the largest
// direction-independent inscribed radius is min(800,800,425,475) = 425 px.
// At the captured default hub scale 1.20000005 this is 354.166652 world units.
export const DEFAULT_AIM_REACH_PX = 425;
export const DEFAULT_HUB_CAMERA_SCALE = 1.20000005;
export const DEFAULT_AIM_REACH_WORLD = DEFAULT_AIM_REACH_PX / DEFAULT_HUB_CAMERA_SCALE;

export function applyRadialDeadzone(
  raw: Point2,
  inner = GAMEPAD_INNER_DEADZONE,
  outer = GAMEPAD_OUTER_DEADZONE,
): DeadzoneResult | null {
  if (!(inner >= 0 && inner < outer && outer <= 1)) {
    throw new Error("radial deadzone requires 0 <= inner < outer <= 1");
  }
  const rawMagnitude = Math.hypot(raw.x, raw.y);
  if (!Number.isFinite(rawMagnitude)) {
    throw new Error("gamepad stick components must be finite");
  }
  if (rawMagnitude <= inner) {
    return null;
  }
  const direction = { x: raw.x / rawMagnitude, y: raw.y / rawMagnitude };
  const magnitude = Math.min(1, (rawMagnitude - inner) / (outer - inner));
  return {
    direction,
    magnitude,
    vector: { x: direction.x * magnitude, y: direction.y * magnitude },
  };
}

export function aimAnchorPx(projection: AimProjection): Point2 {
  return {
    x: projection.projectedPlayerPx.x,
    y: projection.projectedPlayerPx.y + AIM_ANCHOR_Y_OFFSET_PX,
  };
}

export function deriveAimReachPx(projection: AimProjection): number {
  const anchor = aimAnchorPx(projection);
  const reach = Math.min(
    anchor.x,
    projection.viewportPx.width - anchor.x,
    anchor.y,
    projection.viewportPx.height - anchor.y,
  );
  if (!(reach > 0) || !Number.isFinite(reach)) {
    throw new Error("projected player torso anchor is outside the aim viewport");
  }
  return reach;
}

export function synthesizeAimPoint(direction: Point2, projection: AimProjection): Point2 {
  if (!(projection.cameraScale > 0) || !Number.isFinite(projection.cameraScale)) {
    throw new Error("camera scale must be positive and finite");
  }
  const magnitude = Math.hypot(direction.x, direction.y);
  if (!(magnitude > 0) || !Number.isFinite(magnitude)) {
    throw new Error("aim direction must be nonzero and finite");
  }
  const normalized = { x: direction.x / magnitude, y: direction.y / magnitude };
  const reachWorld = deriveAimReachPx(projection) / projection.cameraScale;
  return {
    x: projection.playerWorld.x + normalized.x * reachWorld,
    y:
      projection.playerWorld.y
      + AIM_ANCHOR_Y_OFFSET_PX / projection.cameraScale
      + normalized.y * reachWorld,
  };
}
