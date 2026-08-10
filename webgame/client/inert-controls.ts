import type { FocusModel, FocusScreenRule } from "../input/focus-model.js";

export type InertDisposition = "owner_descoped" | "pending_capture";

export interface InertControl {
  readonly screen: string;
  readonly control: string;
  readonly actionId: string;
  readonly disposition: InertDisposition;
  readonly reason: string;
}

export interface InertControlCatalog {
  readonly entries: readonly InertControl[];
  readonly byScreen: ReadonlyMap<string, readonly InertControl[]>;
  has(screen: string, actionId: string): boolean;
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function disposition(value: unknown, label: string): InertDisposition {
  if (value !== "owner_descoped" && value !== "pending_capture") {
    throw new Error(`${label} must be owner_descoped or pending_capture`);
  }
  return value;
}

/** Parse the one runtime/test-owned list of controls that deliberately do nothing. */
export function parseInertControls(value: unknown): InertControlCatalog {
  const root = object(value, "inert controls manifest");
  if (root.schema !== "solomon-dark-webgame-inert-controls-v1") {
    throw new Error("inert controls manifest has the wrong schema");
  }
  if (!Array.isArray(root.entries)) {
    throw new Error("inert controls manifest entries must be an array");
  }
  const reasons = object(root.disposition_reasons, "inert controls disposition reasons");
  const dispositionReasons: Readonly<Record<InertDisposition, string>> = {
    owner_descoped: string(reasons.owner_descoped, "owner_descoped disposition reason"),
    pending_capture: string(reasons.pending_capture, "pending_capture disposition reason"),
  };
  const entries = root.entries.map((value, index): InertControl => {
    const label = `inert controls manifest entries[${index}]`;
    const entry = object(value, label);
    const entryDisposition = disposition(entry.disposition, `${label}.disposition`);
    return {
      screen: string(entry.screen, `${label}.screen`),
      control: string(entry.control, `${label}.control`),
      actionId: string(entry.action_id, `${label}.action_id`),
      disposition: entryDisposition,
      reason: dispositionReasons[entryDisposition],
    };
  });
  const keys = entries.map((entry) => `${entry.screen}\0${entry.actionId}`);
  if (new Set(keys).size !== entries.length) {
    throw new Error("inert controls manifest has duplicate screen/action entries");
  }
  const controls = entries.map((entry) => `${entry.screen}\0${entry.control}`);
  if (new Set(controls).size !== entries.length) {
    throw new Error("inert controls manifest has duplicate screen/control entries");
  }
  const byScreen = new Map<string, InertControl[]>();
  for (const entry of entries) {
    const screen = byScreen.get(entry.screen) ?? [];
    screen.push(entry);
    byScreen.set(entry.screen, screen);
  }
  return {
    entries,
    byScreen,
    has: (screen, actionId) => (
      byScreen.get(screen)?.some((entry) => entry.actionId === actionId) ?? false
    ),
  };
}

/**
 * Inert controls remain controller-focusable and mouse-clickable. Their
 * manifest rows extend the designed focus list, while dispatch suppression
 * stays in ShellController.
 */
export function withInertControls(
  model: FocusModel,
  inert: InertControlCatalog,
): FocusModel {
  const screens = new Map<string, FocusScreenRule>();
  for (const [layoutId, rule] of model.screens) {
    const inertActions = inert.byScreen.get(layoutId)?.map((entry) => entry.actionId) ?? [];
    screens.set(layoutId, {
      ...rule,
      focusOrder: [...rule.focusOrder, ...inertActions],
    });
  }
  const unknownScreens = [...inert.byScreen.keys()].filter((screen) => !screens.has(screen));
  if (unknownScreens.length > 0) {
    throw new Error(`inert controls name screens absent from the focus model: ${unknownScreens.join(", ")}`);
  }
  return { ...model, screens };
}
