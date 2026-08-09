import type { InputSurface } from "../input/gamepad-producer.js";
import type { Intent, Point2 } from "../input/intent.js";
import { HUB_ECONOMY_GOLDEN } from "./hub-contracts.js";
import {
  HUB_NPCS,
  HUB_PORTALS,
  REGION_ENTRY_POSITIONS,
  offersForService,
  type HubNpc,
  type HubPortal,
  type HubRegionId,
  type HubServiceId,
  type ShopOffer,
} from "./hub-data.js";
import {
  ActiveSessionTransition,
  resolveSessionEdge,
  type ActiveTransitionSnapshot,
} from "./session-flow.js";

export const PROVISIONAL_HUB_WALK_SPEED = 100;
const INTERACTION_PADDING = 55;

export type HubSurface =
  | Readonly<{ kind: "world" }>
  | Readonly<{ kind: "dialogue"; npcId: string; pageIndex: number }>
  | Readonly<{
    kind: "service";
    npcId: string;
    service: HubServiceId;
    focusIndex: number;
    status: string;
  }>
  | Readonly<{ kind: "transition"; destination: HubRegionId | "run-shell" | "courtyard" }>
  | Readonly<{ kind: "run-shell" }>;

export interface PurchaseReceipt {
  readonly service: HubServiceId;
  readonly offerId: string;
  readonly itemName: string;
  readonly price: number;
  readonly goldBefore: number;
  readonly goldAfter: number;
  readonly quantityBefore: number;
  readonly quantityAfter: number;
}

export interface HubSnapshot {
  readonly region: HubRegionId;
  readonly sessionState: string;
  readonly surface: HubSurface;
  readonly player: Readonly<{ x: number; y: number; heading: number; moving: boolean }>;
  readonly gold: number;
  readonly inventory: Readonly<Record<string, number>>;
  readonly stock: Readonly<Record<string, number>>;
  readonly nearestTargetId: string | null;
  readonly completedTalkFlows: readonly string[];
  readonly completedSessionEdges: readonly string[];
  readonly lastPurchase: PurchaseReceipt | null;
  readonly transition: ActiveTransitionSnapshot | null;
  readonly presentationMilliseconds: number;
}

interface HubCallbacks {
  readonly openPause: () => void;
  readonly openMapPicker: () => void;
}

type Listener = (snapshot: HubSnapshot) => void;

function regionState(region: HubRegionId): string {
  return `gameplay.${region}`;
}

function portalEdge(portal: HubPortal): string {
  if (portal.destination === "courtyard") {
    return "return_courtyard";
  }
  return `enter_${portal.destination}`;
}

function headingFor(vector: Point2, fallback: number): number {
  if (Math.hypot(vector.x, vector.y) < 0.0001) {
    return fallback;
  }
  const degrees = Math.atan2(vector.x, -vector.y) * 180 / Math.PI;
  return (degrees + 360) % 360;
}

function distanceSquared(left: Point2, right: Point2): number {
  const dx = left.x - right.x;
  const dy = left.y - right.y;
  return dx * dx + dy * dy;
}

function stockKey(offer: ShopOffer): string {
  return offer.id;
}

function inventoryKey(offer: ShopOffer): string {
  return `${offer.type_id}:${offer.variant_id ?? 0}:${offer.recipe_uid ?? 0}:${offer.selector ?? -1}`;
}

export class HubController {
  readonly #callbacks: HubCallbacks;
  readonly #listeners = new Set<Listener>();
  readonly #completedTalkFlows = new Set<string>();
  readonly #completedSessionEdges: string[] = [];
  readonly #inventory = new Map<string, number>();
  readonly #stock = new Map<string, number>();
  #region: HubRegionId = "courtyard";
  #sessionState = "gameplay.courtyard";
  #surface: HubSurface = { kind: "world" };
  #player = { ...REGION_ENTRY_POSITIONS.courtyard, heading: 180, moving: false };
  #movementVector: Point2 | null = null;
  #movementTarget: Point2 | null = null;
  #gold = HUB_ECONOMY_GOLDEN.freshGold;
  #lastPurchase: PurchaseReceipt | null = null;
  #transition: ActiveSessionTransition | null = null;
  #transitionDestination: HubRegionId | "run-shell" | "courtyard" | null = null;
  #presentationMilliseconds = 0;
  #presentationFrozenForCapture = false;

  public constructor(callbacks: HubCallbacks) {
    this.#callbacks = callbacks;
    for (const service of ["useful-thyngs", "perk-shop", "dowsing"] as const) {
      for (const offer of offersForService(service)) {
        if (this.#stock.has(stockKey(offer))) {
          throw new Error(`G8 pinned stock contains duplicate offer id ${offer.id}`);
        }
        this.#stock.set(stockKey(offer), offer.quantity);
      }
    }
  }

  public get inputSurface(): InputSurface {
    if (this.#surface.kind === "transition") {
      return "blocked";
    }
    if (this.#surface.kind === "dialogue" || this.#surface.kind === "service") {
      return "menu";
    }
    return "gameplay";
  }

  public subscribe(listener: Listener): () => void {
    this.#listeners.add(listener);
    listener(this.snapshot());
    return () => this.#listeners.delete(listener);
  }

  public snapshot(): HubSnapshot {
    return {
      region: this.#region,
      sessionState: this.#sessionState,
      surface: this.#surface,
      player: { ...this.#player },
      gold: this.#gold,
      inventory: Object.fromEntries([...this.#inventory.entries()].sort()),
      stock: Object.fromEntries([...this.#stock.entries()].sort()),
      nearestTargetId: this.interactTarget,
      completedTalkFlows: [...this.#completedTalkFlows].sort(),
      completedSessionEdges: [...this.#completedSessionEdges],
      lastPurchase: this.#lastPurchase,
      transition: this.#transition?.snapshot() ?? null,
      presentationMilliseconds: this.#presentationMilliseconds,
    };
  }

  public get interactTarget(): string | null {
    if (this.#surface.kind === "run-shell") {
      return "run-shell.return";
    }
    if (this.#surface.kind !== "world") {
      return null;
    }
    const candidates = [
      ...HUB_NPCS.filter((npc) => npc.region === this.#region).map((npc) => ({
        id: npc.id,
        x: npc.x,
        y: npc.y,
        reach: npc.radius + INTERACTION_PADDING,
      })),
      ...HUB_PORTALS.filter((portal) => portal.region === this.#region).map((portal) => ({
        id: portal.id,
        x: portal.x,
        y: portal.y,
        reach: INTERACTION_PADDING + 20,
      })),
    ].map((target) => ({
      ...target,
      distance: distanceSquared(this.#player, target),
    })).filter((target) => target.distance <= target.reach * target.reach)
      .sort((left, right) => left.distance - right.distance || left.id.localeCompare(right.id));
    const first = candidates[0];
    const second = candidates[1];
    if (first !== undefined && second !== undefined && first.distance === second.distance) {
      throw new Error(`hub interaction lookup is ambiguous between ${first.id} and ${second.id}`);
    }
    return first?.id ?? null;
  }

  public handle(intent: Intent): void {
    if (this.#surface.kind === "transition") {
      return;
    }
    if (this.#surface.kind === "world" || this.#surface.kind === "run-shell") {
      this.#handleGameplay(intent);
      return;
    }
    if (intent.kind === "menu_nav" && intent.phase === "press") {
      if (this.#surface.kind === "dialogue") {
        this.#handleDialogue(intent.command);
      } else {
        this.#handleService(intent.command);
      }
    }
  }

  public advance(milliseconds: number): void {
    if (!Number.isFinite(milliseconds) || milliseconds < 0 || milliseconds > 1000) {
      throw new Error("hub frame delta must be finite and within [0,1000] milliseconds");
    }
    if (!this.#presentationFrozenForCapture) {
      this.#presentationMilliseconds += milliseconds;
    }
    if (this.#transition !== null) {
      const transition = this.#transition.advance(milliseconds);
      const publishTarget = transition.replay.phaseEvents.find(
        (event) => event.phase === "publish target",
      );
      if (publishTarget === undefined) {
        throw new Error("G13 active transition lost its publish-target phase");
      }
      if (transition.elapsedMilliseconds >= publishTarget.milliseconds) {
        this.#sessionState = transition.replay.destination;
      }
      if (transition.complete) {
        this.#completeTransition();
      }
      this.#emit();
      return;
    }
    if (this.#surface.kind !== "world") {
      return;
    }
    const vector = this.#movementVector ?? this.#targetVector();
    if (vector === null) {
      if (this.#player.moving) {
        this.#player = { ...this.#player, moving: false };
        this.#emit();
      }
      return;
    }
    // PROVISIONAL P1 SHELL movement: docs/browser-rebuild-roadmap.md P1 says
    // G14 move.vector/move.target may move client shell state only. The P2
    // deterministic integrator belongs in webgame/sim/ and is intentionally
    // neither created nor imported here. The plausible 100 world-unit/s feel
    // is G1's documented base held-walk speed; this makes no fidelity or
    // determinism claim.
    const seconds = milliseconds / 1000;
    const x = Math.max(0, Math.min(2000, this.#player.x + vector.x * PROVISIONAL_HUB_WALK_SPEED * seconds));
    const y = Math.max(0, Math.min(1100, this.#player.y + vector.y * PROVISIONAL_HUB_WALK_SPEED * seconds));
    this.#player = {
      x,
      y,
      heading: headingFor(vector, this.#player.heading),
      moving: true,
    };
    if (this.#movementTarget !== null && distanceSquared(this.#player, this.#movementTarget) <= 1) {
      this.#player = { ...this.#player, ...this.#movementTarget, moving: false };
      this.#movementTarget = null;
    }
    this.#emit();
  }

  public beginRunEntry(): void {
    if (this.#region !== "courtyard" || this.#surface.kind !== "world") {
      throw new Error("G8 run entry is legal only from the Courtyard world surface");
    }
    this.#beginTransition("gameplay.courtyard", "start_run", "run-shell");
  }

  public setPresentationFrozenForCapture(frozen: boolean): void {
    this.#presentationFrozenForCapture = frozen;
    if (frozen) {
      this.#presentationMilliseconds = 0;
    }
    this.#emit();
  }

  public showCourtyardForConformance(): void {
    this.#region = "courtyard";
    this.#sessionState = "gameplay.courtyard";
    this.#surface = { kind: "world" };
    this.#player = { ...REGION_ENTRY_POSITIONS.courtyard, heading: 180, moving: false };
    this.#movementVector = null;
    this.#movementTarget = null;
    this.#transition = null;
    this.#transitionDestination = null;
    this.#emit();
  }

  public showNpcForConformance(npcId: string): void {
    const npc = this.#npc(npcId);
    this.#region = npc.region;
    this.#sessionState = regionState(npc.region);
    this.#player = { x: npc.x, y: npc.y, heading: 180, moving: false };
    this.#surface = { kind: "dialogue", npcId, pageIndex: 0 };
    this.#emit();
  }

  public showServiceForConformance(npcId: string): void {
    const npc = this.#npc(npcId);
    if (npc.service === undefined) {
      throw new Error(`hub NPC ${npcId} has no G8 service surface`);
    }
    this.#region = npc.region;
    this.#sessionState = regionState(npc.region);
    this.#player = { x: npc.x, y: npc.y, heading: 180, moving: false };
    this.#surface = { kind: "service", npcId, service: npc.service, focusIndex: 0, status: "" };
    this.#emit();
  }

  #targetVector(): Point2 | null {
    if (this.#movementTarget === null) {
      return null;
    }
    const dx = this.#movementTarget.x - this.#player.x;
    const dy = this.#movementTarget.y - this.#player.y;
    const magnitude = Math.hypot(dx, dy);
    if (magnitude <= 1) {
      this.#player = { ...this.#player, ...this.#movementTarget, moving: false };
      this.#movementTarget = null;
      return null;
    }
    return { x: dx / magnitude, y: dy / magnitude };
  }

  #handleGameplay(intent: Intent): void {
    if (intent.kind === "move" && this.#surface.kind === "world") {
      if (intent.phase === "stop") {
        this.#movementVector = null;
        return;
      }
      if (intent.move.type === "unit_vector") {
        this.#movementTarget = null;
        this.#movementVector = intent.move.vector;
      } else {
        this.#movementVector = null;
        this.#movementTarget = intent.move.point;
      }
      return;
    }
    if (intent.kind !== "interact" || intent.phase !== "press") {
      return;
    }
    if (intent.target === "pause" && this.#surface.kind === "world") {
      this.#movementVector = null;
      this.#movementTarget = null;
      this.#callbacks.openPause();
      return;
    }
    if (this.#surface.kind === "run-shell" && intent.target === "run-shell.return") {
      this.#beginTransition("gameplay.arena", "scripted_terminal_reset", "courtyard");
      return;
    }
    const nearest = this.interactTarget;
    if (nearest === null || intent.target !== nearest) {
      return;
    }
    const npc = HUB_NPCS.find((candidate) => candidate.id === nearest);
    if (npc !== undefined) {
      this.#movementVector = null;
      this.#movementTarget = null;
      this.#surface = { kind: "dialogue", npcId: npc.id, pageIndex: 0 };
      this.#emit();
      return;
    }
    const portal = HUB_PORTALS.find((candidate) => candidate.id === nearest);
    if (portal === undefined) {
      throw new Error(`hub interact target ${nearest} disappeared after proximity resolution`);
    }
    if (portal.kind === "map-picker") {
      this.#callbacks.openMapPicker();
      return;
    }
    if (portal.destination === undefined) {
      throw new Error(`hub portal ${portal.id} lost its destination`);
    }
    this.#beginTransition(regionState(this.#region), portalEdge(portal), portal.destination);
  }

  #handleDialogue(command: string): void {
    if (this.#surface.kind !== "dialogue") {
      return;
    }
    const npc = this.#npc(this.#surface.npcId);
    if (command === "back") {
      this.#surface = { kind: "world" };
      this.#emit();
      return;
    }
    if (command !== "confirm" && command !== "next") {
      return;
    }
    if (this.#surface.pageIndex + 1 < npc.pages.length) {
      this.#surface = { ...this.#surface, pageIndex: this.#surface.pageIndex + 1 };
      this.#emit();
      return;
    }
    this.#completedTalkFlows.add(npc.id);
    if (npc.service !== undefined) {
      this.#surface = {
        kind: "service",
        npcId: npc.id,
        service: npc.service,
        focusIndex: 0,
        status: "",
      };
    } else {
      this.#surface = { kind: "world" };
    }
    this.#emit();
  }

  #handleService(command: string): void {
    if (this.#surface.kind !== "service") {
      return;
    }
    const surface = this.#surface;
    const offers = offersForService(surface.service);
    const doneIndex = offers.length;
    if (command === "back") {
      this.#surface = { kind: "world" };
      this.#emit();
      return;
    }
    if (command === "up" || command === "previous") {
      this.#surface = {
        ...surface,
        focusIndex: (surface.focusIndex - 1 + doneIndex + 1) % (doneIndex + 1),
        status: "",
      };
      this.#emit();
      return;
    }
    if (command === "down" || command === "next") {
      this.#surface = {
        ...surface,
        focusIndex: (surface.focusIndex + 1) % (doneIndex + 1),
        status: "",
      };
      this.#emit();
      return;
    }
    if (command !== "confirm") {
      return;
    }
    if (surface.focusIndex === doneIndex) {
      this.#surface = { kind: "world" };
      this.#emit();
      return;
    }
    const offer = offers[surface.focusIndex];
    if (offer === undefined) {
      throw new Error(`G8 ${surface.service} focus no longer resolves to a pinned offer`);
    }
    this.#purchase(surface, offer);
  }

  #purchase(surface: Extract<HubSurface, { kind: "service" }>, offer: ShopOffer): void {
    const quantityBefore = this.#stock.get(stockKey(offer));
    if (quantityBefore === undefined) {
      throw new Error(`G8 pinned shop lost stock ledger entry ${offer.id}`);
    }
    if (quantityBefore <= 0) {
      this.#surface = { ...surface, status: `${offer.name.toUpperCase()} IS SOLD OUT` };
      this.#emit();
      return;
    }
    if (this.#gold < offer.price) {
      this.#surface = { ...surface, status: `NEED ${offer.price} GOLD · HAVE ${this.#gold}` };
      this.#emit();
      return;
    }
    const goldBefore = this.#gold;
    const key = inventoryKey(offer);
    this.#gold -= offer.price;
    this.#stock.set(stockKey(offer), quantityBefore - 1);
    this.#inventory.set(key, (this.#inventory.get(key) ?? 0) + 1);
    this.#lastPurchase = {
      service: surface.service,
      offerId: offer.id,
      itemName: offer.name,
      price: offer.price,
      goldBefore,
      goldAfter: this.#gold,
      quantityBefore,
      quantityAfter: quantityBefore - 1,
    };
    this.#surface = {
      ...surface,
      status: `BOUGHT ${offer.name.toUpperCase()} · -${offer.price} GOLD`,
    };
    this.#emit();
  }

  #beginTransition(
    source: string,
    edge: string,
    destination: HubRegionId | "run-shell" | "courtyard",
  ): void {
    this.#movementVector = null;
    this.#movementTarget = null;
    this.#transition = new ActiveSessionTransition(source, edge);
    this.#transitionDestination = destination;
    this.#surface = { kind: "transition", destination };
    this.#emit();
  }

  #completeTransition(): void {
    const destination = this.#transitionDestination;
    const transition = this.#transition?.snapshot();
    if (destination === null || transition === undefined) {
      throw new Error("G13 transition completed without a destination owner");
    }
    const replay = transition.replay;
    this.#completedSessionEdges.push(
      `${replay.source} --${replay.edge}--> ${replay.destination}`,
    );
    this.#transition = null;
    this.#transitionDestination = null;
    if (destination === "run-shell") {
      const materialized = resolveSessionEdge(replay.destination, "arena_materialized");
      if (materialized.destination !== "gameplay.arena") {
        throw new Error("G13 arena materialization no longer publishes the gameplay Arena state");
      }
      this.#completedSessionEdges.push(
        `${materialized.state} --${materialized.edge}--> ${materialized.destination}`,
      );
      this.#sessionState = materialized.destination;
      this.#surface = { kind: "run-shell" };
      return;
    }
    const region: HubRegionId = destination === "courtyard" ? "courtyard" : destination;
    this.#region = region;
    this.#sessionState = regionState(region);
    this.#player = { ...REGION_ENTRY_POSITIONS[region], heading: 180, moving: false };
    this.#surface = { kind: "world" };
  }

  #npc(id: string): HubNpc {
    const candidates = HUB_NPCS.filter((npc) => npc.id === id);
    if (candidates.length !== 1) {
      throw new Error(`hub NPC lookup ${id} is ${candidates.length === 0 ? "missing" : "ambiguous"}`);
    }
    const npc = candidates[0];
    if (npc === undefined) {
      throw new Error(`hub NPC ${id} disappeared after lookup`);
    }
    return npc;
  }

  #emit(): void {
    const snapshot = this.snapshot();
    for (const listener of this.#listeners) {
      listener(snapshot);
    }
  }
}
