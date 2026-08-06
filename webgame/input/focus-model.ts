import type { MenuNavIntent, Point2 } from "./intent.js";

// docs/reverse-engineering/native-menus-and-boot.md
// § "Focus — designed controller navigation": retail has no focus order, so
// every rule below must retain its DESIGN_NOT_OBSERVED provenance marker.
export type FocusStrategy =
  | "none"
  | "single"
  | "horizontal"
  | "vertical"
  | "vertical_then_corner"
  | "spatial_with_stable_linear_fallback"
  | "vertical_rows"
  | "vertical_form"
  | "spatial_regions"
  | "inherit_dark_cloud_browser"
  | "modal_vertical"
  | "modal_single"
  | "modal_vertical_form"
  | "dynamic_horizontal"
  | "dynamic_spatial"
  | "single_when_armed";

export interface FocusScreenRule {
  readonly layoutId: string;
  readonly provenance: "DESIGN_NOT_OBSERVED";
  readonly strategy: FocusStrategy;
  readonly focusOrder: readonly string[];
  readonly defaultFocus: string | null;
  readonly wrap: string;
  readonly back: string;
}

export interface FocusModel {
  readonly screens: ReadonlyMap<string, FocusScreenRule>;
  readonly trapModalFocus: true;
  readonly restoreInvokerFocus: true;
  readonly blockUnderlayNavigation: true;
}

export interface FocusNode {
  readonly id: string;
  readonly enabled: boolean;
  readonly rect?: Readonly<{ x: number; y: number; width: number; height: number }>;
  readonly region?: "login" | "tabs" | "rows" | "footer" | "menu";
}

export type FocusAction =
  | { readonly kind: "none" }
  | { readonly kind: "focus"; readonly id: string }
  | { readonly kind: "activate"; readonly id: string }
  | { readonly kind: "adjust"; readonly id: string; readonly direction: "left" | "right" }
  | { readonly kind: "back" };

type JsonObject = Record<string, unknown>;

function asObject(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function asString(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string`);
  }
  return value;
}

function asBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function asStringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    throw new Error(`${label} must be a string array`);
  }
  return value as string[];
}

const strategies = new Set<FocusStrategy>([
  "none",
  "single",
  "horizontal",
  "vertical",
  "vertical_then_corner",
  "spatial_with_stable_linear_fallback",
  "vertical_rows",
  "vertical_form",
  "spatial_regions",
  "inherit_dark_cloud_browser",
  "modal_vertical",
  "modal_single",
  "modal_vertical_form",
  "dynamic_horizontal",
  "dynamic_spatial",
  "single_when_armed",
]);

function parseStrategy(value: unknown, label: string): FocusStrategy {
  const strategy = asString(value, label);
  if (!strategies.has(strategy as FocusStrategy)) {
    throw new Error(`${label} names an unsupported G11 navigation strategy`);
  }
  return strategy as FocusStrategy;
}

/** Strict runtime view of webgame-contracts/menu-focus-model.json. */
export function parseFocusModel(value: unknown): FocusModel {
  const root = asObject(value, "G11 focus model");
  const rawScreens = root.screens;
  if (!Array.isArray(rawScreens) || rawScreens.length !== 28) {
    throw new Error("G11 focus model must define all 28 shell layouts");
  }
  const screens = new Map<string, FocusScreenRule>();
  for (const [index, rawScreen] of rawScreens.entries()) {
    const screen = asObject(rawScreen, `G11 focus model screens[${index}]`);
    const layoutId = asString(screen.layout_id, `G11 focus model screens[${index}].layout_id`);
    if (screens.has(layoutId)) {
      throw new Error(`G11 focus model ambiguously defines ${layoutId} twice`);
    }
    if (screen.provenance !== "DESIGN_NOT_OBSERVED") {
      throw new Error(`${layoutId} must retain the G11 DESIGN_NOT_OBSERVED marker`);
    }
    screens.set(layoutId, {
      layoutId,
      provenance: screen.provenance,
      strategy: parseStrategy(screen.strategy, `${layoutId}.strategy`),
      focusOrder: asStringArray(screen.focus_order, `${layoutId}.focus_order`),
      defaultFocus: screen.default_focus === null
        ? null
        : asString(screen.default_focus, `${layoutId}.default_focus`),
      wrap: asString(screen.wrap, `${layoutId}.wrap`),
      back: asString(screen.back, `${layoutId}.back`),
    });
  }
  const modal = asObject(root.modal_policy, "G11 focus model modal_policy");
  if (
    !asBoolean(modal.trap_focus, "G11 modal trap_focus")
    || !asBoolean(modal.restore_invoker_focus_on_close, "G11 modal restore_invoker_focus_on_close")
    || !asBoolean(modal.block_underlay_navigation, "G11 modal block_underlay_navigation")
  ) {
    throw new Error("G11 modal policy must trap focus, block the underlay, and restore the invoker");
  }
  return {
    screens,
    trapModalFocus: true,
    restoreInvokerFocus: true,
    blockUnderlayNavigation: true,
  };
}

function expands(orderEntry: string, nodeId: string): boolean {
  if (orderEntry === nodeId) {
    return true;
  }
  if (orderEntry.startsWith("skill_picker.option[")) {
    return /^skill_picker\.option\[\d+\]$/.test(nodeId);
  }
  if (orderEntry.startsWith("map_picker.story[")) {
    return /^map_picker\.story\[\d+\]$/.test(nodeId);
  }
  if (orderEntry === "dark_cloud_browser.level_rows") {
    return /^dark_cloud_browser\.level_row\[\d+\]$/.test(nodeId);
  }
  return false;
}

export function effectiveFocusOrder(rule: FocusScreenRule): readonly string[] {
  if (rule.strategy !== "inherit_dark_cloud_browser") {
    return rule.focusOrder;
  }
  const inheritedPrefix = [
    "dark_cloud_browser.login",
    "dark_cloud_browser.recent",
    "dark_cloud_browser.online_levels",
    "dark_cloud_browser.my_levels",
    "dark_cloud_browser.level_rows",
  ];
  const inheritedIds = new Set(inheritedPrefix);
  return [
    ...inheritedPrefix,
    ...rule.focusOrder.filter((entry) => !inheritedIds.has(entry)),
  ];
}

function numericSuffix(nodeId: string): number {
  const matched = /\[(\d+)\]$/.exec(nodeId);
  return matched === null ? 0 : Number(matched[1]);
}

function orderNodes(rule: FocusScreenRule, available: readonly FocusNode[]): FocusNode[] {
  const eligible = available.filter((node) => node.enabled);
  const result: FocusNode[] = [];
  for (const entry of effectiveFocusOrder(rule)) {
    const matches = eligible
      .filter((node) => expands(entry, node.id))
      .sort((left, right) => numericSuffix(left.id) - numericSuffix(right.id));
    for (const node of matches) {
      if (!result.includes(node)) {
        result.push(node);
      }
    }
  }
  const unknown = eligible.filter((node) => !result.includes(node));
  if (unknown.length > 0) {
    throw new Error(
      `${rule.layoutId} exposes focus nodes absent from the G11 order: ${unknown.map((node) => node.id).join(", ")}`,
    );
  }
  return result;
}

function explicitDefault(rule: FocusScreenRule, nodes: readonly FocusNode[]): FocusNode | undefined {
  if (rule.defaultFocus === null) {
    return undefined;
  }
  const ids = rule.defaultFocus.match(/[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+(?:\[\d+\])?/g) ?? [];
  return ids
    .map((id) => nodes.find((node) => node.id === id))
    .find((node): node is FocusNode => node !== undefined);
}

function center(node: FocusNode): Point2 {
  if (node.rect === undefined) {
    throw new Error(`${node.id} needs a rectangle for G11 spatial navigation`);
  }
  return {
    x: node.rect.x + node.rect.width / 2,
    y: node.rect.y + node.rect.height / 2,
  };
}

function wrapIndex(index: number, length: number): number {
  return (index + length) % length;
}

function linearNeighbor(
  nodes: readonly FocusNode[],
  currentIndex: number,
  delta: -1 | 1,
): FocusNode | undefined {
  if (nodes.length === 0) {
    return undefined;
  }
  return nodes[wrapIndex(currentIndex + delta, nodes.length)];
}

function spatialNeighbor(
  nodes: readonly FocusNode[],
  current: FocusNode,
  direction: "up" | "down" | "left" | "right",
): FocusNode | undefined {
  const origin = center(current);
  const horizontal = direction === "left" || direction === "right";
  const sign = direction === "left" || direction === "up" ? -1 : 1;
  const candidates = nodes
    .filter((node) => node !== current)
    .map((node) => {
      const target = center(node);
      const primary = horizontal ? (target.x - origin.x) * sign : (target.y - origin.y) * sign;
      const secondary = Math.abs(horizontal ? target.y - origin.y : target.x - origin.x);
      return { node, primary, secondary };
    })
    .filter((candidate) => candidate.primary > 0)
    .sort((left, right) => (
      left.secondary / left.primary - right.secondary / right.primary
      || left.primary - right.primary
      || left.secondary - right.secondary
    ));
  if (candidates[0] !== undefined) {
    return candidates[0].node;
  }

  // G11 DESIGN_NOT_OBSERVED: native-menus-and-boot.md
  // "Focus & designed controller navigation" requires an edge wrap rather
  // than synthesizing a cursor. Keep the stable secondary-axis tie break.
  return nodes
    .filter((node) => node !== current)
    .map((node) => {
      const target = center(node);
      const primary = horizontal ? target.x * sign : target.y * sign;
      const secondary = Math.abs(horizontal ? target.y - origin.y : target.x - origin.x);
      return { node, primary, secondary };
    })
    .sort((left, right) => right.primary - left.primary || left.secondary - right.secondary)[0]?.node;
}

const regionOrder: readonly NonNullable<FocusNode["region"]>[] = [
  "login",
  "tabs",
  "rows",
  "footer",
  "menu",
];

function regionalNeighbor(
  nodes: readonly FocusNode[],
  current: FocusNode,
  command: "up" | "down" | "left" | "right",
): FocusNode | undefined {
  if (current.region === undefined) {
    throw new Error(`${current.id} needs a G11 dark-cloud focus region`);
  }
  const inRegion = nodes.filter((node) => node.region === current.region);
  if (command === "left" || command === "right") {
    const currentIndex = inRegion.indexOf(current);
    return linearNeighbor(inRegion, currentIndex, command === "left" ? -1 : 1);
  }
  const regionIndex = regionOrder.indexOf(current.region);
  for (let offset = 1; offset <= regionOrder.length; offset += 1) {
    const targetRegion = regionOrder[
      wrapIndex(regionIndex + (command === "up" ? -offset : offset), regionOrder.length)
    ];
    const candidates = nodes.filter((node) => node.region === targetRegion);
    if (candidates.length > 0) {
      const origin = center(current);
      return [...candidates].sort((left, right) => (
        Math.abs(center(left).x - origin.x) - Math.abs(center(right).x - origin.x)
      ))[0];
    }
  }
  return undefined;
}

export class FocusNavigator {
  readonly #model: FocusModel;
  #rule: FocusScreenRule | null = null;
  #nodes: FocusNode[] = [];
  #focusedId: string | null = null;

  public constructor(model: FocusModel) {
    this.#model = model;
  }

  public get focusedId(): string | null {
    return this.#focusedId;
  }

  public enter(layoutId: string, available: readonly FocusNode[], preferredId?: string): string | null {
    const rule = this.#model.screens.get(layoutId);
    if (rule === undefined) {
      throw new Error(`G11 focus model has no rule for ${layoutId}`);
    }
    this.#rule = rule;
    this.#nodes = orderNodes(rule, available);
    this.#focusedId = (
      this.#nodes.find((node) => node.id === preferredId)
      ?? explicitDefault(rule, this.#nodes)
      ?? this.#nodes[0]
    )?.id ?? null;
    return this.#focusedId;
  }

  public updateAvailable(available: readonly FocusNode[]): string | null {
    const rule = this.#requireRule();
    const previousIndex = this.#nodes.findIndex((node) => node.id === this.#focusedId);
    this.#nodes = orderNodes(rule, available);
    if (this.#nodes.some((node) => node.id === this.#focusedId)) {
      return this.#focusedId;
    }
    this.#focusedId = this.#nodes[Math.min(Math.max(previousIndex, 0), this.#nodes.length - 1)]?.id ?? null;
    return this.#focusedId;
  }

  public handle(intent: MenuNavIntent): FocusAction {
    if (intent.phase !== "press") {
      return { kind: "none" };
    }
    const rule = this.#requireRule();
    if (intent.command === "back") {
      return { kind: "back" };
    }
    if (this.#focusedId === null) {
      return { kind: "none" };
    }
    const currentIndex = this.#nodes.findIndex((node) => node.id === this.#focusedId);
    const current = this.#nodes[currentIndex];
    if (current === undefined) {
      throw new Error(`${rule.layoutId} lost its current G11 focus node`);
    }
    if (intent.command === "confirm") {
      return { kind: "activate", id: current.id };
    }

    let next: FocusNode | undefined;
    if (intent.command === "next" || intent.command === "previous") {
      if (
        rule.strategy === "spatial_regions"
        || rule.strategy === "inherit_dark_cloud_browser"
      ) {
        const tabs = this.#nodes.filter((node) => node.region === "tabs");
        const tabIndex = tabs.indexOf(current);
        next = linearNeighbor(
          tabs,
          tabIndex < 0 ? 0 : tabIndex,
          intent.command === "previous" ? -1 : 1,
        );
      } else {
        next = linearNeighbor(this.#nodes, currentIndex, intent.command === "previous" ? -1 : 1);
      }
    } else if (
      rule.strategy === "vertical_rows"
      && (intent.command === "left" || intent.command === "right")
    ) {
      return { kind: "adjust", id: current.id, direction: intent.command };
    } else if (
      rule.strategy === "spatial_with_stable_linear_fallback"
      || rule.strategy === "dynamic_spatial"
    ) {
      next = spatialNeighbor(this.#nodes, current, intent.command);
    } else if (
      rule.strategy === "spatial_regions"
      || rule.strategy === "inherit_dark_cloud_browser"
    ) {
      next = regionalNeighbor(this.#nodes, current, intent.command);
    } else {
      const horizontal = rule.strategy === "horizontal" || rule.strategy === "dynamic_horizontal";
      const wanted = horizontal
        ? intent.command === "left" || intent.command === "right"
        : intent.command === "up" || intent.command === "down";
      if (wanted) {
        const decrement = intent.command === "left" || intent.command === "up";
        next = linearNeighbor(this.#nodes, currentIndex, decrement ? -1 : 1);
      }
    }
    if (next === undefined) {
      return { kind: "none" };
    }
    this.#focusedId = next.id;
    return { kind: "focus", id: next.id };
  }

  #requireRule(): FocusScreenRule {
    if (this.#rule === null) {
      throw new Error("FocusNavigator cannot navigate before entering a G11 screen");
    }
    return this.#rule;
  }
}
