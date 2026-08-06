import type { IntentSink, MenuNavIntent, Point2 } from "./intent.js";
import type { InputSurface } from "./gamepad-producer.js";

export interface KeyboardMouseContext {
  readonly surface: InputSurface;
  readonly screenToWorld: (screen: Point2) => Point2;
  readonly menuTargetAt: (screen: Point2) => string | null;
}

const movementKeys: Readonly<Record<string, Point2>> = {
  KeyW: { x: 0, y: -1 },
  KeyS: { x: 0, y: 1 },
  KeyA: { x: -1, y: 0 },
  KeyD: { x: 1, y: 0 },
  ArrowUp: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 },
  ArrowLeft: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 },
};

const menuKeys: Readonly<Record<string, MenuNavIntent["command"]>> = {
  ArrowUp: "up",
  KeyW: "up",
  ArrowDown: "down",
  KeyS: "down",
  ArrowLeft: "left",
  KeyA: "left",
  ArrowRight: "right",
  KeyD: "right",
  Enter: "confirm",
  Space: "confirm",
  Escape: "back",
  Tab: "next",
};

/** G14 mouse+keyboard producer; no client or future sim module receives DOM events. */
export class KeyboardMouseProducer {
  readonly #sink: IntentSink;
  readonly #context: () => KeyboardMouseContext;
  readonly #pressedMovement = new Set<string>();
  #lastMove: Point2 | null = null;
  #lastPointer: Point2 | null = null;
  #leftHeld = false;
  #rightHeld = false;
  #started = false;

  public constructor(sink: IntentSink, context: () => KeyboardMouseContext) {
    this.#sink = sink;
    this.#context = context;
  }

  public start(): void {
    if (this.#started) {
      return;
    }
    window.addEventListener("keydown", this.#onKeyDown);
    window.addEventListener("keyup", this.#onKeyUp);
    window.addEventListener("mousemove", this.#onMouseMove);
    window.addEventListener("mousedown", this.#onMouseDown);
    window.addEventListener("mouseup", this.#onMouseUp);
    window.addEventListener("contextmenu", this.#onContextMenu);
    this.#started = true;
  }

  public stop(): void {
    if (!this.#started) {
      return;
    }
    window.removeEventListener("keydown", this.#onKeyDown);
    window.removeEventListener("keyup", this.#onKeyUp);
    window.removeEventListener("mousemove", this.#onMouseMove);
    window.removeEventListener("mousedown", this.#onMouseDown);
    window.removeEventListener("mouseup", this.#onMouseUp);
    window.removeEventListener("contextmenu", this.#onContextMenu);
    this.#pressedMovement.clear();
    this.#started = false;
  }

  public tick(): void {
    if (this.#context().surface !== "gameplay") {
      return;
    }
    if (this.#leftHeld) {
      this.#sink({ kind: "cast", slot: "primary", phase: "hold" });
    }
    if (this.#rightHeld) {
      this.#sink({ kind: "cast", slot: "secondary", phase: "hold" });
    }
    if (this.#lastPointer !== null && (this.#leftHeld || this.#rightHeld)) {
      this.#sink({ kind: "aim", point: this.#context().screenToWorld(this.#lastPointer) });
    }
  }

  readonly #onKeyDown = (event: KeyboardEvent): void => {
    const context = this.#context();
    if (context.surface === "blocked" || event.repeat) {
      return;
    }
    if (context.surface === "menu") {
      let command = menuKeys[event.code];
      if (event.code === "Tab" && event.shiftKey) {
        command = "previous";
      }
      if (command !== undefined) {
        event.preventDefault();
        this.#sink({ kind: "menu_nav", command, phase: "press" });
      }
      return;
    }
    if (movementKeys[event.code] !== undefined) {
      this.#pressedMovement.add(event.code);
      this.#emitMovement();
    }
    if (event.code === "Escape") {
      this.#sink({ kind: "interact", target: "pause", phase: "press" });
    }
  };

  readonly #onKeyUp = (event: KeyboardEvent): void => {
    const context = this.#context();
    if (context.surface === "blocked") {
      return;
    }
    if (context.surface === "menu") {
      let command = menuKeys[event.code];
      if (event.code === "Tab" && event.shiftKey) {
        command = "previous";
      }
      if (command !== undefined) {
        event.preventDefault();
        this.#sink({ kind: "menu_nav", command, phase: "release" });
      }
      return;
    }
    if (movementKeys[event.code] !== undefined) {
      this.#pressedMovement.delete(event.code);
      this.#emitMovement();
    }
    if (event.code === "Escape") {
      this.#sink({ kind: "interact", target: "pause", phase: "release" });
    }
  };

  readonly #onMouseMove = (event: MouseEvent): void => {
    this.#lastPointer = { x: event.clientX, y: event.clientY };
    if (this.#context().surface === "gameplay") {
      this.#sink({ kind: "aim", point: this.#context().screenToWorld(this.#lastPointer) });
    }
  };

  readonly #onMouseDown = (event: MouseEvent): void => {
    const context = this.#context();
    const screen = { x: event.clientX, y: event.clientY };
    this.#lastPointer = screen;
    if (context.surface === "blocked") {
      return;
    }
    if (context.surface === "menu") {
      const target = context.menuTargetAt(screen);
      if (target !== null && event.button === 0) {
        this.#sink({ kind: "interact", target, phase: "press" });
      }
      return;
    }
    if (event.button === 0) {
      this.#leftHeld = true;
      this.#sink({ kind: "aim", point: context.screenToWorld(screen) });
      this.#sink({ kind: "cast", slot: "primary", phase: "press" });
    } else if (event.button === 2) {
      this.#rightHeld = true;
      this.#sink({ kind: "aim", point: context.screenToWorld(screen) });
      this.#sink({ kind: "cast", slot: "secondary", phase: "press" });
    }
  };

  readonly #onMouseUp = (event: MouseEvent): void => {
    const context = this.#context();
    const screen = { x: event.clientX, y: event.clientY };
    if (context.surface === "blocked") {
      this.#leftHeld = false;
      this.#rightHeld = false;
      return;
    }
    if (context.surface === "menu") {
      const target = context.menuTargetAt(screen);
      if (target !== null && event.button === 0) {
        this.#sink({ kind: "interact", target, phase: "release" });
      }
      return;
    }
    if (event.button === 0 && this.#leftHeld) {
      this.#leftHeld = false;
      this.#sink({ kind: "cast", slot: "primary", phase: "release" });
    } else if (event.button === 2 && this.#rightHeld) {
      this.#rightHeld = false;
      this.#sink({ kind: "cast", slot: "secondary", phase: "release" });
    }
  };

  readonly #onContextMenu = (event: MouseEvent): void => {
    event.preventDefault();
  };

  #emitMovement(): void {
    let x = 0;
    let y = 0;
    for (const code of this.#pressedMovement) {
      const direction = movementKeys[code];
      if (direction !== undefined) {
        x += direction.x;
        y += direction.y;
      }
    }
    const length = Math.hypot(x, y);
    if (length === 0) {
      if (this.#lastMove !== null) {
        this.#sink({
          kind: "move",
          phase: "stop",
          move: { type: "unit_vector", vector: this.#lastMove },
        });
        this.#lastMove = null;
      }
      return;
    }
    const vector = { x: x / length, y: y / length };
    this.#sink({
      kind: "move",
      phase: this.#lastMove === null ? "start" : "update",
      move: { type: "unit_vector", vector },
    });
    this.#lastMove = vector;
  }
}
