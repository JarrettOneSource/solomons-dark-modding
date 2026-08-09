import type { Intent } from "../input/intent.js";
import { createSoloSimulation, LOCAL_PARTICIPANT_ID, stepSimulation } from "../sim/simulation.js";
import type {
  IntentEnvelope,
  SimulationConfig,
  SimulationState,
  Vec2,
} from "../sim/types.js";

export const SCRIPTED_RUN_TICKS = 6_000;

export const SCRIPTED_RUN_CONFIG: SimulationConfig = {
  collision_rectangles: [
    { id: "north", min_x: -400, min_y: -410, max_x: 400, max_y: -400 },
    { id: "east", min_x: 400, min_y: -400, max_x: 410, max_y: 400 },
    { id: "south", min_x: -400, min_y: 400, max_x: 400, max_y: 410 },
    { id: "west", min_x: -410, min_y: -400, max_x: -400, max_y: 400 },
  ],
  cast_glyph_points: Array.from({ length: 24 }, (_, facing) => ({
    sprite_set: "staff" as const,
    bank: 7,
    facing,
    point_index: 1,
    point: { x: 0, y: 0 },
  })),
  spatial_cell_size: 100,
};

const movementDirections: readonly Vec2[] = [
  { x: 1, y: 0 },
  { x: 0, y: 1 },
  { x: -1, y: 0 },
  { x: 0, y: -1 },
];

const aimPoints: readonly Vec2[] = [
  { x: 1_000, y: 0 },
  { x: 0, y: 1_000 },
  { x: -1_000, y: 0 },
  { x: 0, y: -1_000 },
];

function envelope(intent: Intent): IntentEnvelope {
  return { participant_id: LOCAL_PARTICIPANT_ID, intent };
}

export function scriptedIntents(tick: number): readonly IntentEnvelope[] {
  const phaseTick = tick % 600;
  const directionIndex = Math.floor(tick / 600) % movementDirections.length;
  const direction = movementDirections[directionIndex];
  const aimPoint = aimPoints[directionIndex];
  if (direction === undefined || aimPoint === undefined) {
    throw new Error(`scripted intent direction lookup failed at tick ${tick}`);
  }
  const intents: IntentEnvelope[] = [];
  if (phaseTick === 0) {
    intents.push(envelope({
      kind: "move",
      phase: "start",
      move: { type: "unit_vector", vector: direction },
    }));
  }
  if (phaseTick === 100) {
    intents.push(envelope({ kind: "aim", point: aimPoint }));
  }
  if (phaseTick === 120) {
    intents.push(envelope({ kind: "cast", slot: "primary", phase: "press" }));
  }
  if (phaseTick === 121) {
    intents.push(envelope({ kind: "cast", slot: "primary", phase: "release" }));
  }
  if (phaseTick === 400) {
    intents.push(envelope({
      kind: "move",
      phase: "stop",
      move: { type: "unit_vector", vector: { x: 0, y: 0 } },
    }));
  }
  return intents;
}

export function runScriptedSimulation(tickCount: number): SimulationState {
  if (!Number.isSafeInteger(tickCount) || tickCount < 1) {
    throw new Error("scripted simulation tick count must be a positive safe integer");
  }
  let state = createSoloSimulation({
    elapsed_app_ticks: 1485,
    position: { x: 0, y: 0 },
    heading_degrees: 0,
  });
  for (let tick = 0; tick < tickCount; tick += 1) {
    state = stepSimulation(state, scriptedIntents(tick), SCRIPTED_RUN_CONFIG);
  }
  return state;
}
