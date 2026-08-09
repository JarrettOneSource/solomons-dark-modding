import { describe, expect, it } from "vitest";

import {
  moveCircle,
  movementCollisionTestCirclePlacement,
  resolveCirclePlacement,
  validateCollisionRectangles,
} from "./collision.js";

const northWall = [{
  id: "north",
  min_x: -100,
  min_y: -100,
  max_x: 100,
  max_y: -15,
}];

describe("native circle placement response", () => {
  it("preserves tangent motion through the secondary alternate placement", () => {
    const first = moveCircle(northWall, { x: 0, y: 10.25 }, 25, { x: 0.5, y: -0.86 }, "alternate");
    expect(first).toEqual({ x: 0.5, y: Math.fround(9.39) });
    const second = moveCircle(northWall, first, 25, { x: 0.5, y: -0.86 }, "alternate");
    expect(second).toEqual({ x: 1, y: Math.fround(9.14) });
    expect(resolveCirclePlacement(northWall, second, 25)).toEqual({ x: 1, y: 10 });
  });

  it("supports primary, stop, and alternate responses without unordered lookup", () => {
    expect(moveCircle(northWall, { x: 0, y: 10 }, 25, { x: 0, y: -1 }, "primary"))
      .toEqual({ x: 0, y: 10 });
    expect(moveCircle(northWall, { x: 0, y: 10 }, 25, { x: 0, y: -1 }, "stop"))
      .toEqual({ x: 0, y: 10 });
    expect(moveCircle(northWall, { x: 0, y: 10 }, 25, { x: 0, y: -1 }, "alternate"))
      .toEqual({ x: 0, y: 9 });
    expect(movementCollisionTestCirclePlacement(northWall, { x: 0, y: 10 }, 25)).toBe(true);
    expect(movementCollisionTestCirclePlacement(northWall, { x: 0, y: 9 }, 25)).toBe(false);
  });

  it("refuses duplicate collision ids instead of picking one", () => {
    expect(() => {
      validateCollisionRectangles([...northWall, ...northWall]);
    })
      .toThrow("collision rectangle lookup is ambiguous for id north");
  });
});
