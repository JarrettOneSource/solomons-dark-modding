export interface Point2 {
  readonly x: number;
  readonly y: number;
}

export type MoveIntent = {
  readonly kind: "move";
  readonly phase: "start" | "update" | "stop";
  readonly move:
    | { readonly type: "world_target"; readonly point: Point2 }
    | { readonly type: "unit_vector"; readonly vector: Point2 };
};

export type AimIntent = {
  readonly kind: "aim";
  readonly point: Point2;
};

export type CastIntent = {
  readonly kind: "cast";
  readonly slot: "primary" | "secondary";
  readonly phase: "press" | "hold" | "release";
};

export type InteractIntent = {
  readonly kind: "interact";
  readonly target: string;
  readonly phase: "press" | "release";
};

export type MenuNavIntent = {
  readonly kind: "menu_nav";
  readonly command:
    | "up"
    | "down"
    | "left"
    | "right"
    | "confirm"
    | "back"
    | "next"
    | "previous";
  readonly phase: "press" | "release";
};

export type Intent = MoveIntent | AimIntent | CastIntent | InteractIntent | MenuNavIntent;
export type IntentSink = (intent: Intent) => void;

const movePhases = new Set<MoveIntent["phase"]>(["start", "update", "stop"]);
const castPhases = new Set<CastIntent["phase"]>(["press", "hold", "release"]);
const edgePhases = new Set<InteractIntent["phase"]>(["press", "release"]);
const menuCommands = new Set<MenuNavIntent["command"]>([
  "up",
  "down",
  "left",
  "right",
  "confirm",
  "back",
  "next",
  "previous",
]);

function object(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new Error(`${label} has fields ${actual.join(",")}; expected ${wanted.join(",")}`);
  }
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be finite`);
  }
  return value;
}

function point(value: unknown, label: string, bounded: boolean): Point2 {
  const candidate = object(value, label);
  exactKeys(candidate, ["x", "y"], label);
  const x = finiteNumber(candidate.x, `${label}.x`);
  const y = finiteNumber(candidate.y, `${label}.y`);
  if (bounded && (x < -1 || x > 1 || y < -1 || y > 1)) {
    throw new Error(`${label} leaves the G14 component range [-1,1]`);
  }
  return { x, y };
}

function enumValue<T extends string>(value: unknown, allowed: ReadonlySet<T>, label: string): T {
  if (typeof value !== "string" || !allowed.has(value as T)) {
    throw new Error(`${label} is not in the G14 vocabulary`);
  }
  return value as T;
}

/** Runtime mirror of webgame-contracts/intent-schema.json. */
export function parseIntent(value: unknown): Intent {
  const candidate = object(value, "Intent");
  const kind = candidate.kind;
  if (kind === "move") {
    exactKeys(candidate, ["kind", "move", "phase"], "move Intent");
    const move = object(candidate.move, "move Intent.move");
    const type = move.type;
    if (type === "world_target") {
      exactKeys(move, ["point", "type"], "move world target");
      return {
        kind,
        phase: enumValue(candidate.phase, movePhases, "move Intent.phase"),
        move: { type, point: point(move.point, "move world target.point", false) },
      };
    }
    if (type === "unit_vector") {
      exactKeys(move, ["type", "vector"], "move vector");
      return {
        kind,
        phase: enumValue(candidate.phase, movePhases, "move Intent.phase"),
        move: { type, vector: point(move.vector, "move vector.vector", true) },
      };
    }
    throw new Error("move Intent.move has no G14 move type");
  }
  if (kind === "aim") {
    exactKeys(candidate, ["kind", "point"], "aim Intent");
    return { kind, point: point(candidate.point, "aim Intent.point", false) };
  }
  if (kind === "cast") {
    exactKeys(candidate, ["kind", "phase", "slot"], "cast Intent");
    if (candidate.slot !== "primary" && candidate.slot !== "secondary") {
      throw new Error("cast Intent.slot is not primary or secondary");
    }
    return {
      kind,
      slot: candidate.slot,
      phase: enumValue(candidate.phase, castPhases, "cast Intent.phase"),
    };
  }
  if (kind === "interact") {
    exactKeys(candidate, ["kind", "phase", "target"], "interact Intent");
    if (
      typeof candidate.target !== "string"
      || candidate.target.length === 0
      || candidate.target.length > 128
    ) {
      throw new Error("interact Intent.target must contain 1..128 characters");
    }
    return {
      kind,
      target: candidate.target,
      phase: enumValue(candidate.phase, edgePhases, "interact Intent.phase"),
    };
  }
  if (kind === "menu_nav") {
    exactKeys(candidate, ["command", "kind", "phase"], "menu-nav Intent");
    return {
      kind,
      command: enumValue(candidate.command, menuCommands, "menu-nav Intent.command"),
      phase: enumValue(candidate.phase, edgePhases, "menu-nav Intent.phase"),
    };
  }
  throw new Error("Intent.kind is not in the G14 union");
}
