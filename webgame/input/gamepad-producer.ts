import type { IntentSink, MenuNavIntent, Point2 } from "./intent.js";
import {
  applyRadialDeadzone,
  synthesizeAimPoint,
  type AimProjection,
} from "./twin-stick.js";

export interface GamepadButtonSnapshot {
  readonly pressed: boolean;
  readonly value: number;
}

export interface GamepadSnapshot {
  readonly axes: readonly number[];
  readonly buttons: readonly GamepadButtonSnapshot[];
  readonly connected: boolean;
}

export type InputSurface = "menu" | "gameplay" | "blocked";

export interface GamepadContext {
  readonly surface: InputSurface;
  readonly aimProjection?: AimProjection;
  readonly interactTarget?: string;
}

const BUTTON_SOUTH = 0;
const BUTTON_EAST = 1;
const BUTTON_WEST = 2;
const BUTTON_LEFT_BUMPER = 4;
const BUTTON_RIGHT_BUMPER = 5;
const BUTTON_RIGHT_TRIGGER = 7;
const BUTTON_START = 9;
const BUTTON_DPAD_UP = 12;
const BUTTON_DPAD_DOWN = 13;
const BUTTON_DPAD_LEFT = 14;
const BUTTON_DPAD_RIGHT = 15;

function button(snapshot: GamepadSnapshot, index: number): GamepadButtonSnapshot {
  return snapshot.buttons[index] ?? { pressed: false, value: 0 };
}

function axis(snapshot: GamepadSnapshot, index: number): number {
  const value = snapshot.axes[index] ?? 0;
  return Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0;
}

function edgeIntent(command: MenuNavIntent["command"], phase: "press" | "release"): MenuNavIntent {
  return { kind: "menu_nav", command, phase };
}

/**
 * G14/roadmap §4 producer. This file deliberately owns every Gamepad API name;
 * client and future sim code receive only Intent records.
 */
export class GamepadProducer {
  readonly #sink: IntentSink;
  readonly #context: () => GamepadContext;
  #lastButtons = new Map<number, boolean>();
  #lastMoveVector: Point2 | null = null;
  #lastAimDirection: Point2 | null = null;
  #menuStickCommand: MenuNavIntent["command"] | null = null;

  public constructor(sink: IntentSink, context: () => GamepadContext) {
    this.#sink = sink;
    this.#context = context;
  }

  public pollBrowserGamepads(): void {
    const connected = Array.from(navigator.getGamepads()).find(
      (candidate): candidate is Gamepad => candidate !== null && candidate.connected,
    );
    if (connected === undefined) {
      return;
    }
    this.sample({
      axes: [...connected.axes],
      buttons: connected.buttons.map((value) => ({
        pressed: value.pressed,
        value: value.value,
      })),
      connected: connected.connected,
    });
  }

  public sample(snapshot: GamepadSnapshot): void {
    const context = this.#context();
    if (!snapshot.connected || context.surface === "blocked") {
      this.#clearLevels();
      return;
    }
    if (context.surface === "menu") {
      this.#sampleMenu(snapshot);
      return;
    }
    this.#sampleGameplay(snapshot, context);
  }

  #sampleMenu(snapshot: GamepadSnapshot): void {
    const commands = new Map<number, MenuNavIntent["command"]>([
      [BUTTON_DPAD_UP, "up"],
      [BUTTON_DPAD_DOWN, "down"],
      [BUTTON_DPAD_LEFT, "left"],
      [BUTTON_DPAD_RIGHT, "right"],
      [BUTTON_SOUTH, "confirm"],
      [BUTTON_EAST, "back"],
      [BUTTON_LEFT_BUMPER, "previous"],
      [BUTTON_RIGHT_BUMPER, "next"],
    ]);
    for (const [index, command] of commands) {
      this.#emitButtonEdge(snapshot, index, (phase) => edgeIntent(command, phase));
    }

    const left = applyRadialDeadzone({ x: axis(snapshot, 0), y: axis(snapshot, 1) });
    const nextCommand = left === null || left.magnitude < 0.45
      ? null
      : Math.abs(left.direction.x) > Math.abs(left.direction.y)
        ? left.direction.x < 0 ? "left" : "right"
        : left.direction.y < 0 ? "up" : "down";
    if (nextCommand !== this.#menuStickCommand) {
      if (this.#menuStickCommand !== null) {
        this.#sink(edgeIntent(this.#menuStickCommand, "release"));
      }
      if (nextCommand !== null) {
        this.#sink(edgeIntent(nextCommand, "press"));
      }
      this.#menuStickCommand = nextCommand;
    }
    this.#lastMoveVector = null;
  }

  #sampleGameplay(snapshot: GamepadSnapshot, context: GamepadContext): void {
    const left = applyRadialDeadzone({ x: axis(snapshot, 0), y: axis(snapshot, 1) });
    if (left === null) {
      if (this.#lastMoveVector !== null) {
        this.#sink({
          kind: "move",
          phase: "stop",
          move: { type: "unit_vector", vector: this.#lastMoveVector },
        });
        this.#lastMoveVector = null;
      }
    } else {
      this.#sink({
        kind: "move",
        phase: this.#lastMoveVector === null ? "start" : "update",
        move: { type: "unit_vector", vector: left.vector },
      });
      this.#lastMoveVector = left.vector;
    }

    const right = applyRadialDeadzone({ x: axis(snapshot, 2), y: axis(snapshot, 3) });
    if (right !== null) {
      this.#lastAimDirection = right.direction;
    }
    // Roadmap §4.2: release never snaps aim to movement. Reproject the retained
    // direction from the current player torso anchor so camera/player motion
    // cannot change the heading while the stick is at rest.
    if (this.#lastAimDirection !== null && context.aimProjection !== undefined) {
      this.#sink({
        kind: "aim",
        point: synthesizeAimPoint(this.#lastAimDirection, context.aimProjection),
      });
    }

    this.#emitLevel(snapshot, BUTTON_RIGHT_TRIGGER, "primary");
    this.#emitLevel(snapshot, BUTTON_WEST, "secondary");
    this.#emitButtonEdge(snapshot, BUTTON_SOUTH, (phase) => ({
      kind: "interact",
      target: context.interactTarget ?? "world.primary",
      phase,
    }));
    this.#emitButtonEdge(snapshot, BUTTON_START, (phase) => ({
      kind: "interact",
      target: "pause",
      phase,
    }));
  }

  #emitLevel(
    snapshot: GamepadSnapshot,
    index: number,
    slot: "primary" | "secondary",
  ): void {
    const active = button(snapshot, index).value > 0.5 || button(snapshot, index).pressed;
    const previous = this.#lastButtons.get(index) ?? false;
    if (active) {
      this.#sink({ kind: "cast", slot, phase: previous ? "hold" : "press" });
    } else if (previous) {
      this.#sink({ kind: "cast", slot, phase: "release" });
    }
    this.#lastButtons.set(index, active);
  }

  #emitButtonEdge(
    snapshot: GamepadSnapshot,
    index: number,
    build: (phase: "press" | "release") => Parameters<IntentSink>[0],
  ): void {
    const active = button(snapshot, index).pressed;
    const previous = this.#lastButtons.get(index) ?? false;
    if (active !== previous) {
      this.#sink(build(active ? "press" : "release"));
      this.#lastButtons.set(index, active);
    }
  }

  #clearLevels(): void {
    if (this.#lastMoveVector !== null) {
      this.#sink({
        kind: "move",
        phase: "stop",
        move: { type: "unit_vector", vector: this.#lastMoveVector },
      });
    }
    this.#lastMoveVector = null;
    this.#lastButtons.clear();
    this.#menuStickCommand = null;
  }
}
