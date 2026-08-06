import { describe, expect, it } from "vitest";

import type { Intent } from "./intent.js";
import {
  GamepadProducer,
  type GamepadButtonSnapshot,
  type GamepadContext,
  type GamepadSnapshot,
} from "./gamepad-producer.js";

function snapshot(
  axes: readonly number[] = [0, 0, 0, 0],
  pressed: readonly number[] = [],
  values: Readonly<Record<number, number>> = {},
): GamepadSnapshot {
  const buttons: GamepadButtonSnapshot[] = Array.from({ length: 16 }, (_, index) => ({
    pressed: pressed.includes(index),
    value: values[index] ?? (pressed.includes(index) ? 1 : 0),
  }));
  return { axes, buttons, connected: true };
}

const projection = {
  playerWorld: { x: 0, y: 0 },
  projectedPlayerPx: { x: 800, y: 450 },
  viewportPx: { width: 1600, height: 900 },
  cameraScale: 1,
} as const;

describe("gamepad Intent producer", () => {
  it("emits menu button press and release edges without a cursor", () => {
    const intents: Intent[] = [];
    const producer = new GamepadProducer((intent) => intents.push(intent), () => ({ surface: "menu" }));
    producer.sample(snapshot(undefined, [0]));
    producer.sample(snapshot());
    expect(intents).toEqual([
      { kind: "menu_nav", command: "confirm", phase: "press" },
      { kind: "menu_nav", command: "confirm", phase: "release" },
    ]);
  });

  it("turns a menu-stick direction change into paired release and press edges", () => {
    const intents: Intent[] = [];
    const producer = new GamepadProducer((intent) => intents.push(intent), () => ({ surface: "menu" }));
    producer.sample(snapshot([1, 0, 0, 0]));
    producer.sample(snapshot([0, -1, 0, 0]));
    producer.sample(snapshot());
    expect(intents).toEqual([
      { kind: "menu_nav", command: "right", phase: "press" },
      { kind: "menu_nav", command: "right", phase: "release" },
      { kind: "menu_nav", command: "up", phase: "press" },
      { kind: "menu_nav", command: "up", phase: "release" },
    ]);
  });

  it("emits re-normalized movement start, update, and stop", () => {
    const intents: Intent[] = [];
    const producer = new GamepadProducer((intent) => intents.push(intent), () => ({
      surface: "gameplay",
      aimProjection: projection,
    }));
    producer.sample(snapshot([0.575, 0, 0, 0]));
    producer.sample(snapshot([0.95, 0, 0, 0]));
    producer.sample(snapshot());
    expect(intents.map((intent) => intent.kind === "move" ? intent.phase : intent.kind))
      .toEqual(["start", "update", "stop"]);
    const first = intents[0];
    expect(first?.kind).toBe("move");
    if (first?.kind === "move" && first.move.type === "unit_vector") {
      expect(first.move.vector.x).toBeCloseTo(0.5, 12);
    }
  });

  it("holds the last aim direction after right-stick release", () => {
    const intents: Intent[] = [];
    let context: GamepadContext = { surface: "gameplay", aimProjection: projection };
    const producer = new GamepadProducer((intent) => intents.push(intent), () => context);
    producer.sample(snapshot([0, 0, 1, 0]));
    context = {
      surface: "gameplay",
      aimProjection: { ...projection, playerWorld: { x: 10, y: 20 } },
    };
    producer.sample(snapshot());
    const aims = intents.filter((intent) => intent.kind === "aim");
    expect(aims).toHaveLength(2);
    expect(aims[0]).toEqual({ kind: "aim", point: { x: 425, y: -25 } });
    expect(aims[1]).toEqual({ kind: "aim", point: { x: 435, y: -5 } });
  });

  it("maps trigger and west button levels to exact cast phases", () => {
    const intents: Intent[] = [];
    const producer = new GamepadProducer((intent) => intents.push(intent), () => ({
      surface: "gameplay",
      aimProjection: projection,
    }));
    producer.sample(snapshot(undefined, [2], { 7: 0.75 }));
    producer.sample(snapshot(undefined, [2], { 7: 0.75 }));
    producer.sample(snapshot());
    expect(intents.filter((intent) => intent.kind === "cast")).toEqual([
      { kind: "cast", slot: "primary", phase: "press" },
      { kind: "cast", slot: "secondary", phase: "press" },
      { kind: "cast", slot: "primary", phase: "hold" },
      { kind: "cast", slot: "secondary", phase: "hold" },
      { kind: "cast", slot: "primary", phase: "release" },
      { kind: "cast", slot: "secondary", phase: "release" },
    ]);
  });

  it("stops active movement when the input surface becomes blocked", () => {
    const intents: Intent[] = [];
    let context: GamepadContext = { surface: "gameplay", aimProjection: projection };
    const producer = new GamepadProducer((intent) => intents.push(intent), () => context);
    producer.sample(snapshot([1, 0, 0, 0]));
    context = { surface: "blocked" };
    producer.sample(snapshot([1, 0, 0, 0]));
    expect(intents.at(-1)).toMatchObject({ kind: "move", phase: "stop" });
  });
});
