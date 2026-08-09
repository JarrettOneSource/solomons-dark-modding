import { SESSION_FLOW_GOLDEN, type SessionEdgeGolden } from "./hub-contracts.js";

export const G13_FIXED_TICK_MS = 10;
export const G13_SOLO_BARRIER_STABLE_MS = 250;
export const G13_BARRIER_TIMEOUT_MS = 25_000;
export const G13_PORTAL_FADE_OUT_TICKS = 101;
export const G13_ROOM_FADE_IN_TICKS = 41;
export const G13_CACHED_COURTYARD_FADE_IN_TICKS = 1;
export const G13_ARENA_FADE_IN_TICKS = 20;
export const G13_ARENA_RELEASE_TICKS_AFTER_SEAL = 26;

export const G13_PHASE_ORDER = [
  "fade-out endpoint",
  "seal if entering Arena",
  "transient participant cleanup",
  "slot detach",
  "cache sleep",
  "lifecycle unregister",
  "publish target",
  "wake",
  "attach",
  "old-region post callback",
  "target finalizer",
  "fade-in",
  "barrier release",
  "unseal",
] as const;

export type G13Phase = typeof G13_PHASE_ORDER[number];

export interface TransitionPhaseEvent {
  readonly index: number;
  readonly phase: G13Phase;
  readonly tick: number;
  readonly milliseconds: number;
  readonly applied: boolean;
}

export interface SoloBarrierReceipt {
  readonly expectedParticipantIds: readonly [0];
  readonly visibleParticipantIds: readonly [0];
  readonly stableMilliseconds: 250;
  readonly timeoutMilliseconds: 25_000;
  readonly releaseReason: "all-ready";
}

export interface TransitionReplay {
  readonly source: string;
  readonly edge: string;
  readonly destination: string;
  readonly entersArena: boolean;
  readonly fadeOutRatePerTick: number;
  readonly fadeInRatePerTick: number;
  readonly phaseEvents: readonly TransitionPhaseEvent[];
  readonly durationMilliseconds: number;
  readonly barrier: SoloBarrierReceipt | null;
}

const EDGE_KEYS = new Set(
  SESSION_FLOW_GOLDEN.edges.map((edge) => `${edge.state}\0${edge.edge}\0${edge.destination}`),
);
if (EDGE_KEYS.size !== 23) {
  throw new Error("G13 runtime edge registry no longer mirrors all twenty-three legal golden edges");
}

export function legalSessionEdges(): readonly SessionEdgeGolden[] {
  return SESSION_FLOW_GOLDEN.edges;
}

export function resolveSessionEdge(source: string, edgeName: string): SessionEdgeGolden {
  const candidates = SESSION_FLOW_GOLDEN.edges.filter((edge) => (
    edge.state === source && edge.edge === edgeName
  ));
  if (candidates.length !== 1) {
    throw new Error(
      `G13 transition ${source}/${edgeName} is ${candidates.length === 0 ? "illegal" : "ambiguous"}`,
    );
  }
  const edge = candidates[0];
  if (edge === undefined) {
    throw new Error(`G13 transition ${source}/${edgeName} disappeared after resolution`);
  }
  return edge;
}

interface TimingProfile {
  readonly fadeOutTicks: number;
  readonly fadeOutRate: number;
  readonly fadeInTicks: number;
  readonly fadeInRate: number;
  readonly barrierReleaseTicksAfterFadeOut: number;
}

function timingFor(edge: SessionEdgeGolden): TimingProfile {
  const entersArena = edge.edge === "start_run" || edge.edge === "arena_materialized";
  if (entersArena) {
    const startsAtCoveredLoadingSurface = edge.edge === "arena_materialized";
    return {
      // G13's onboarding trace records the stock +0.01 outgoing fade for 101
      // ticks. start_run owns that presentation before the covered loading
      // state; arena_materialized starts already covered.
      fadeOutTicks: startsAtCoveredLoadingSurface ? 0 : G13_PORTAL_FADE_OUT_TICKS,
      fadeOutRate: startsAtCoveredLoadingSurface ? 0 : 0.01,
      fadeInTicks: G13_ARENA_FADE_IN_TICKS,
      fadeInRate: -0.05,
      // G13's solo trace seals at tick 4373 and unseals at 4399. The exact
      // actor set is held for 250 ms while the 20-tick fade overlaps it.
      barrierReleaseTicksAfterFadeOut: G13_ARENA_RELEASE_TICKS_AFTER_SEAL,
    };
  }
  const returnsToCachedCourtyard = edge.edge === "return_courtyard";
  const ordinaryPortal = edge.edge.startsWith("enter_")
    || returnsToCachedCourtyard
    || edge.edge === "scripted_terminal_reset";
  const immediate = edge.edge === "boot_complete"
    || edge.edge === "terminal_death"
    || edge.edge === "open_hall_of_fame";
  const fadeInTicks = immediate
    ? 0
    : returnsToCachedCourtyard
      ? G13_CACHED_COURTYARD_FADE_IN_TICKS
      : G13_ROOM_FADE_IN_TICKS;
  return {
    fadeOutTicks: ordinaryPortal ? G13_PORTAL_FADE_OUT_TICKS : 0,
    fadeOutRate: ordinaryPortal ? 0.01 : 0,
    fadeInTicks,
    fadeInRate: fadeInTicks === 1 ? -0.01 : fadeInTicks === 0 ? 0 : -0.025,
    barrierReleaseTicksAfterFadeOut: 0,
  };
}

export function buildTransitionReplay(source: string, edgeName: string): TransitionReplay {
  const edge = resolveSessionEdge(source, edgeName);
  const timing = timingFor(edge);
  const entersArena = edge.edge === "start_run" || edge.edge === "arena_materialized";
  const endpointTick = timing.fadeOutTicks;
  const swapTick = endpointTick + 1;
  const fadeInEndpoint = swapTick + timing.fadeInTicks;
  const releaseTick = entersArena
    ? Math.max(fadeInEndpoint, endpointTick + timing.barrierReleaseTicksAfterFadeOut)
    : fadeInEndpoint;
  const applied = (phase: G13Phase): boolean => {
    if (phase === "seal if entering Arena" || phase === "target finalizer" || phase === "barrier release") {
      return entersArena;
    }
    if (phase === "unseal") {
      return entersArena;
    }
    return true;
  };
  const tickFor = (phase: G13Phase): number => {
    if (phase === "fade-out endpoint") {
      return endpointTick;
    }
    if (phase === "fade-in") {
      return fadeInEndpoint;
    }
    if (phase === "barrier release" || phase === "unseal") {
      return releaseTick;
    }
    return swapTick;
  };
  const phaseEvents = G13_PHASE_ORDER.map((phase, index): TransitionPhaseEvent => {
    const tick = tickFor(phase);
    return {
      index,
      phase,
      tick,
      milliseconds: tick * G13_FIXED_TICK_MS,
      applied: applied(phase),
    };
  });
  return {
    source,
    edge: edge.edge,
    destination: edge.destination,
    entersArena,
    fadeOutRatePerTick: timing.fadeOutRate,
    fadeInRatePerTick: timing.fadeInRate,
    phaseEvents,
    durationMilliseconds: releaseTick * G13_FIXED_TICK_MS,
    barrier: entersArena ? {
      expectedParticipantIds: [0],
      visibleParticipantIds: [0],
      stableMilliseconds: G13_SOLO_BARRIER_STABLE_MS,
      timeoutMilliseconds: G13_BARRIER_TIMEOUT_MS,
      releaseReason: "all-ready",
    } : null,
  };
}

export function replayEveryLegalEdge(): readonly TransitionReplay[] {
  const replays = SESSION_FLOW_GOLDEN.edges.map((edge) => buildTransitionReplay(edge.state, edge.edge));
  if (replays.length !== 23) {
    throw new Error("G13 transition replay failed to reach every legal edge");
  }
  return replays;
}

export interface ActiveTransitionSnapshot {
  readonly replay: TransitionReplay;
  readonly elapsedMilliseconds: number;
  readonly phaseIndex: number;
  readonly phase: G13Phase;
  readonly fadeAlpha: number;
  readonly inputSealed: boolean;
  readonly complete: boolean;
}

export class ActiveSessionTransition {
  readonly #replay: TransitionReplay;
  #elapsedMilliseconds = 0;

  public constructor(source: string, edgeName: string) {
    this.#replay = buildTransitionReplay(source, edgeName);
  }

  public advance(milliseconds: number): ActiveTransitionSnapshot {
    if (!Number.isFinite(milliseconds) || milliseconds < 0) {
      throw new Error("G13 transition clock cannot move backward or by a non-finite delta");
    }
    this.#elapsedMilliseconds = Math.min(
      this.#replay.durationMilliseconds,
      this.#elapsedMilliseconds + milliseconds,
    );
    return this.snapshot();
  }

  public snapshot(): ActiveTransitionSnapshot {
    const elapsedTicks = Math.floor(this.#elapsedMilliseconds / G13_FIXED_TICK_MS);
    let phaseIndex = 0;
    for (const event of this.#replay.phaseEvents) {
      if (event.tick <= elapsedTicks) {
        phaseIndex = event.index;
      }
    }
    const fadeOutEndpoint = this.#replay.phaseEvents[0]?.milliseconds ?? 0;
    const fadeInEndpoint = this.#replay.phaseEvents[11]?.milliseconds ?? fadeOutEndpoint;
    let fadeAlpha: number;
    if (fadeOutEndpoint > 0 && this.#elapsedMilliseconds < fadeOutEndpoint) {
      fadeAlpha = this.#elapsedMilliseconds / fadeOutEndpoint;
    } else if (fadeInEndpoint > fadeOutEndpoint && this.#elapsedMilliseconds < fadeInEndpoint) {
      fadeAlpha = 1 - (this.#elapsedMilliseconds - fadeOutEndpoint) / (fadeInEndpoint - fadeOutEndpoint);
    } else {
      fadeAlpha = 0;
    }
    return {
      replay: this.#replay,
      elapsedMilliseconds: this.#elapsedMilliseconds,
      phaseIndex,
      phase: G13_PHASE_ORDER[phaseIndex] ?? G13_PHASE_ORDER[0],
      fadeAlpha: Math.max(0, Math.min(1, fadeAlpha)),
      inputSealed: this.#replay.entersArena && this.#elapsedMilliseconds < this.#replay.durationMilliseconds,
      complete: this.#elapsedMilliseconds >= this.#replay.durationMilliseconds,
    };
  }
}
