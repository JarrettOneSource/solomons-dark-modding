import { parseIntent } from "../input/intent.js";
import { serializeSimulationState } from "../sim/serialize.js";
import { stepSimulation, validateSimulationState } from "../sim/simulation.js";
import type {
  IntentEnvelope,
  SimulationConfig,
  SimulationState,
} from "../sim/types.js";
import { scriptedIntents, SCRIPTED_RUN_CONFIG } from "./scripted-run.js";

export const REPLAY_DIVERGENCE_BUDGETS = {
  clock: 0,
  participants: 0,
  rng: 0,
  movement: 0,
  fire: 0,
  actor_model: 0,
} as const;

export interface TraceTick {
  readonly tick: number;
  readonly intents: readonly IntentEnvelope[];
  readonly expected_state: SimulationState;
}

export interface TraceTimeline {
  readonly schema: "solomon-dark-sim-trace-v1";
  readonly tick_rate_hz: 100;
  readonly initial_state: SimulationState;
  readonly config: SimulationConfig;
  readonly timeline: readonly TraceTick[];
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value)) {
    throw new Error(`${label} must be a safe integer`);
  }
  return value as number;
}

function parseState(value: unknown, label: string): SimulationState {
  const candidate = record(value, label) as unknown as SimulationState;
  validateSimulationState(candidate);
  return candidate;
}

function parseConfig(value: unknown): SimulationConfig {
  const candidate = record(value, "trace.config");
  array(candidate.collision_rectangles, "trace.config.collision_rectangles");
  array(candidate.cast_glyph_points, "trace.config.cast_glyph_points");
  if (typeof candidate.spatial_cell_size !== "number" || !Number.isFinite(candidate.spatial_cell_size)) {
    throw new Error("trace.config.spatial_cell_size must be finite");
  }
  return candidate as unknown as SimulationConfig;
}

export function parseTraceTimeline(value: unknown): TraceTimeline {
  const candidate = record(value, "trace");
  if (candidate.schema !== "solomon-dark-sim-trace-v1") {
    throw new Error("trace.schema must be solomon-dark-sim-trace-v1");
  }
  if (candidate.tick_rate_hz !== 100) {
    throw new Error("trace.tick_rate_hz must pin the native 100 Hz clock");
  }
  const timelineValues = array(candidate.timeline, "trace.timeline");
  if (timelineValues.length === 0) {
    throw new Error("trace.timeline must contain recorded state");
  }
  const timeline = timelineValues.map((valueAtTick, index) => {
    const entry = record(valueAtTick, `trace.timeline[${index}]`);
    const tick = integer(entry.tick, `trace.timeline[${index}].tick`);
    if (tick !== index) {
      throw new Error(`trace timeline tick ${tick} is not contiguous at index ${index}`);
    }
    const intents = array(entry.intents, `trace.timeline[${index}].intents`).map(
      (rawEnvelope, intentIndex): IntentEnvelope => {
        const intentEnvelope = record(rawEnvelope, `trace.timeline[${index}].intents[${intentIndex}]`);
        if (typeof intentEnvelope.participant_id !== "string") {
          throw new Error(`trace tick ${index} intent ${intentIndex} lacks participant_id`);
        }
        return {
          participant_id: intentEnvelope.participant_id,
          intent: parseIntent(intentEnvelope.intent),
        };
      },
    );
    return {
      tick,
      intents,
      expected_state: parseState(entry.expected_state, `trace.timeline[${index}].expected_state`),
    };
  });
  return {
    schema: candidate.schema,
    tick_rate_hz: candidate.tick_rate_hz,
    initial_state: parseState(candidate.initial_state, "trace.initial_state"),
    config: parseConfig(candidate.config),
    timeline,
  };
}

function subsystemProjection(state: SimulationState, subsystem: keyof typeof REPLAY_DIVERGENCE_BUDGETS): unknown {
  if (subsystem === "clock") {
    return { elapsed_app_ticks: state.elapsed_app_ticks, scene_tick: state.scene_tick };
  }
  if (subsystem === "participants") {
    return { participants: state.participants, slots: state.slots };
  }
  if (subsystem === "rng") {
    return state.rng;
  }
  if (subsystem === "movement") {
    return {
      actors: state.actors
        .filter((actor) => actor.family === "player" || actor.family === "enemy")
        .map((actor) => ({
          id: actor.id,
          position: actor.position,
          movement: actor.family === "player" ? actor.movement : {
            direction: actor.movement_direction,
            cadence: actor.movement_cadence_ticks,
            local_speed_factor: actor.local_speed_factor,
          },
          knockback: actor.family === "player" ? actor.knockback : null,
        })),
      tracked_actor_centers: state.tracked_actor_centers,
    };
  }
  if (subsystem === "fire") {
    return {
      projectiles: state.actors.filter((actor) => actor.family === "fire_projectile"),
      pending_projectiles: state.pending_actors.filter((actor) => actor.family === "fire_projectile"),
      events: state.events,
    };
  }
  return {
    actors: state.actors.map((actor) => ({
      id: actor.id,
      insertion_order: actor.insertion_order,
      object_type_id: actor.object_type_id,
      family: actor.family,
      tracked_enemy: actor.tracked_enemy,
      initialized: actor.initialized,
      destroyed: actor.destroyed,
      health: actor.family === "enemy" ? actor.health : null,
    })),
    pending_actor_ids: state.pending_actors.map((actor) => actor.id),
    next_actor_serial: state.next_actor_serial,
  };
}

function compareValue(
  actual: unknown,
  expected: unknown,
  budget: number,
  path: string,
  subsystem: string,
  tick: number,
): void {
  if (typeof actual === "number" && typeof expected === "number") {
    if (Math.abs(actual - expected) > budget) {
      throw new Error(
        `${subsystem} divergence at tick ${tick} ${path}: expected ${expected}, actual ${actual}, budget ${budget}`,
      );
    }
    return;
  }
  if (Array.isArray(actual) && Array.isArray(expected)) {
    if (actual.length !== expected.length) {
      throw new Error(
        `${subsystem} divergence at tick ${tick} ${path}.length: expected ${expected.length}, actual ${actual.length}`,
      );
    }
    for (let index = 0; index < actual.length; index += 1) {
      compareValue(actual[index], expected[index], budget, `${path}[${index}]`, subsystem, tick);
    }
    return;
  }
  if (
    actual !== null
    && expected !== null
    && typeof actual === "object"
    && typeof expected === "object"
    && !Array.isArray(actual)
    && !Array.isArray(expected)
  ) {
    const actualRecord = actual as Record<string, unknown>;
    const expectedRecord = expected as Record<string, unknown>;
    const actualKeys = Object.keys(actualRecord).sort();
    const expectedKeys = Object.keys(expectedRecord).sort();
    if (actualKeys.join("\0") !== expectedKeys.join("\0")) {
      throw new Error(
        `${subsystem} divergence at tick ${tick} ${path} keys: expected ${expectedKeys.join(",")}, actual ${actualKeys.join(",")}`,
      );
    }
    for (const key of actualKeys) {
      compareValue(actualRecord[key], expectedRecord[key], budget, `${path}.${key}`, subsystem, tick);
    }
    return;
  }
  if (!Object.is(actual, expected)) {
    throw new Error(
      `${subsystem} divergence at tick ${tick} ${path}: expected ${String(expected)}, actual ${String(actual)}`,
    );
  }
}

export interface ReplayResult {
  readonly ticks_replayed: number;
  readonly final_serialized_state: string;
}

export function replayTrace(trace: TraceTimeline): ReplayResult {
  let state = trace.initial_state;
  for (const entry of trace.timeline) {
    state = stepSimulation(state, entry.intents, trace.config);
    for (const subsystem of Object.keys(REPLAY_DIVERGENCE_BUDGETS) as Array<keyof typeof REPLAY_DIVERGENCE_BUDGETS>) {
      compareValue(
        subsystemProjection(state, subsystem),
        subsystemProjection(entry.expected_state, subsystem),
        REPLAY_DIVERGENCE_BUDGETS[subsystem],
        "$",
        subsystem,
        entry.tick,
      );
    }
  }
  return {
    ticks_replayed: trace.timeline.length,
    final_serialized_state: serializeSimulationState(state),
  };
}

export function createSelfTrace(initialState: SimulationState, tickCount: number): TraceTimeline {
  if (!Number.isSafeInteger(tickCount) || tickCount < 1) {
    throw new Error("self-trace tick count must be a positive safe integer");
  }
  let state = initialState;
  const timeline: TraceTick[] = [];
  for (let tick = 0; tick < tickCount; tick += 1) {
    const intents = scriptedIntents(tick);
    state = stepSimulation(state, intents, SCRIPTED_RUN_CONFIG);
    timeline.push({ tick, intents, expected_state: state });
  }
  return {
    schema: "solomon-dark-sim-trace-v1",
    tick_rate_hz: 100,
    initial_state: initialState,
    config: SCRIPTED_RUN_CONFIG,
    timeline,
  };
}

export function corruptTraceSingleBit(trace: TraceTimeline): TraceTimeline {
  const copy = JSON.parse(JSON.stringify(trace)) as unknown;
  const parsed = parseTraceTimeline(copy);
  const targetIndex = Math.floor(parsed.timeline.length / 2);
  const target = parsed.timeline[targetIndex];
  if (target === undefined) {
    throw new Error("corruption control found no midpoint trace state");
  }
  const firstWord = target.expected_state.rng.state_words[0];
  if (firstWord === undefined) {
    throw new Error("corruption control found no first RNG state word");
  }
  const corruptedState: SimulationState = {
    ...target.expected_state,
    rng: {
      ...target.expected_state.rng,
      state_words: [firstWord ^ 1, ...target.expected_state.rng.state_words.slice(1)],
    },
  };
  const timeline = [...parsed.timeline];
  timeline[targetIndex] = { ...target, expected_state: corruptedState };
  return { ...parsed, timeline };
}
