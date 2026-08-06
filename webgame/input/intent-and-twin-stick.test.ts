import { describe, expect, it } from "vitest";

import { parseIntent } from "./intent.js";
import {
  AIM_ANCHOR_Y_OFFSET_PX,
  applyRadialDeadzone,
  aimAnchorPx,
  deriveAimReachPx,
  synthesizeAimPoint,
} from "./twin-stick.js";

const projection = {
  playerWorld: { x: 100, y: 200 },
  projectedPlayerPx: { x: 800, y: 450 },
  viewportPx: { width: 1600, height: 900 },
  cameraScale: 2,
} as const;

describe("G14 Intent runtime union", () => {
  it.each([
    { kind: "move", phase: "start", move: { type: "world_target", point: { x: 12, y: -4 } } },
    { kind: "move", phase: "update", move: { type: "unit_vector", vector: { x: -1, y: 0.25 } } },
    { kind: "aim", point: { x: 99, y: 101 } },
    { kind: "cast", slot: "primary", phase: "hold" },
    { kind: "interact", target: "pause", phase: "press" },
    { kind: "menu_nav", command: "previous", phase: "release" },
  ])("accepts an exact union member", (intent) => {
    expect(parseIntent(intent)).toEqual(intent);
  });

  it("rejects fields outside the schema instead of silently dropping them", () => {
    expect(() => parseIntent({
      kind: "menu_nav",
      command: "confirm",
      phase: "press",
      rawButton: 0,
    })).toThrow("menu-nav Intent has fields");
  });

  it("rejects non-finite and out-of-range vectors", () => {
    expect(() => parseIntent({ kind: "aim", point: { x: Number.NaN, y: 0 } }))
      .toThrow("aim Intent.point.x must be finite");
    expect(() => parseIntent({
      kind: "move",
      phase: "start",
      move: { type: "unit_vector", vector: { x: 1.01, y: 0 } },
    })).toThrow("leaves the G14 component range [-1,1]");
  });
});

describe("roadmap section 4.2 twin-stick math", () => {
  it("drops the complete radial inner deadzone", () => {
    expect(applyRadialDeadzone({ x: 0.12, y: 0.16 })).toBeNull();
  });

  it("re-normalizes magnitude between the 0.2 and 0.95 radial edges", () => {
    const halfway = applyRadialDeadzone({ x: 0.575, y: 0 });
    expect(halfway?.direction).toEqual({ x: 1, y: 0 });
    expect(halfway?.magnitude).toBeCloseTo(0.5, 12);
    expect(halfway?.vector.x).toBeCloseTo(0.5, 12);
    expect(applyRadialDeadzone({ x: 1, y: 0 })?.magnitude).toBe(1);
  });

  it("normalizes diagonal direction radially rather than per axis", () => {
    const result = applyRadialDeadzone({ x: 0.6, y: 0.8 });
    expect(result?.direction.x).toBeCloseTo(0.6, 12);
    expect(result?.direction.y).toBeCloseTo(0.8, 12);
    expect(result?.magnitude).toBe(1);
  });

  it("rejects invalid deadzone bands", () => {
    expect(() => applyRadialDeadzone({ x: 1, y: 0 }, 0.8, 0.2))
      .toThrow("0 <= inner < outer <= 1");
  });

  it("anchors aim at project(player) plus the exact negative 25 screen pixels", () => {
    expect(AIM_ANCHOR_Y_OFFSET_PX).toBe(-25);
    expect(aimAnchorPx(projection)).toEqual({ x: 800, y: 425 });
    expect(deriveAimReachPx(projection)).toBe(425);
  });

  it("projects the retained direction through camera scale from the torso anchor", () => {
    expect(synthesizeAimPoint({ x: 0, y: 4 }, projection)).toEqual({
      x: 100,
      y: 400,
    });
  });
});
