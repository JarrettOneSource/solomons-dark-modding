import { NATIVE_OBJECT_TYPE, PLAYER_MOVEMENT } from "./constants.js";
import { validateCollisionRectangles } from "./collision.js";
import { createFireProjectile, tickFireProjectile } from "./fire.js";
import { f32 } from "./float32.js";
import { tickEnemyMovement, tickPlayerKnockback, tickPlayerMovement } from "./movement.js";
import { createNativeRng, deriveNativeSeedFromElapsedTicks } from "./rng.js";
import type {
  ActorState,
  CastSpriteSet,
  IntentEnvelope,
  ParticipantState,
  PlayerActorState,
  SimulationConfig,
  SimulationEvent,
  SimulationState,
  TrackedActorCenter,
  Vec2,
} from "./types.js";

export const LOCAL_PARTICIPANT_ID = "1";
export const FIRST_LUA_CONTROLLED_PARTICIPANT_ID = "1152921504606851072";

export interface CreateSoloSimulationOptions {
  readonly elapsed_app_ticks: number;
  readonly position: Vec2;
  readonly heading_degrees?: number;
  readonly radius?: number;
  readonly sprite_set?: CastSpriteSet;
}

function defaultPlayerMovement(): PlayerActorState["movement"] {
  return {
    intent: { x: 0, y: 0 },
    velocity: { x: 0, y: 0 },
    transient_multiplier: PLAYER_MOVEMENT.transient_multiplier,
    move_speed_scale: PLAYER_MOVEMENT.move_speed_scale,
    progression_multiplier: PLAYER_MOVEMENT.progression_multiplier,
    move_step_scale: PLAYER_MOVEMENT.move_step_scale,
    controlled_damping: false,
  };
}

export function createSoloSimulation(
  options: CreateSoloSimulationOptions,
): SimulationState {
  const headingDegrees = options.heading_degrees ?? 0;
  const participant: ParticipantState = {
    id: LOCAL_PARTICIPANT_ID,
    kind: "LocalHuman",
    controller: "Native",
    slot: 0,
    actor_id: "actor-1",
  };
  const player: PlayerActorState = {
    id: participant.actor_id,
    insertion_order: 1,
    object_type_id: NATIVE_OBJECT_TYPE.player,
    family: "player",
    participant_id: participant.id,
    slot: participant.slot,
    position: { x: f32(options.position.x), y: f32(options.position.y) },
    radius: options.radius ?? 25,
    tracked_enemy: false,
    initialized: true,
    destroyed: false,
    heading_degrees: f32(headingDegrees),
    aim_point: { x: f32(options.position.x), y: f32(options.position.y - 1) },
    sprite_set: options.sprite_set ?? { kind: "staff", object_type_id: 0x1b5c, pose: 7 },
    movement: defaultPlayerMovement(),
    knockback: null,
  };
  return {
    schema_version: 1,
    elapsed_app_ticks: options.elapsed_app_ticks,
    scene_tick: 0,
    rng: createNativeRng(deriveNativeSeedFromElapsedTicks(options.elapsed_app_ticks)),
    participants: [participant],
    slots: [participant.id, null, null, null],
    actors: [player],
    pending_actors: [],
    next_actor_serial: 2,
    tracked_actor_centers: [],
    events: [],
  };
}

function uniqueById(items: readonly { readonly id: string }[], label: string): void {
  const ids = new Set<string>();
  for (const item of items) {
    if (ids.has(item.id)) {
      throw new Error(`${label} lookup is ambiguous for id ${item.id}`);
    }
    ids.add(item.id);
  }
}

export function validateSimulationState(state: SimulationState): void {
  if (!Number.isSafeInteger(state.elapsed_app_ticks) || state.elapsed_app_ticks < 0) {
    throw new Error("simulation state requires an explicit non-negative elapsed_app_ticks");
  }
  uniqueById(state.participants, "participant");
  uniqueById([...state.actors, ...state.pending_actors], "actor");
  for (const participant of state.participants) {
    if (state.slots[participant.slot] !== participant.id) {
      throw new Error(`participant ${participant.id} does not own declared slot ${participant.slot}`);
    }
    const matches = state.actors.filter((actor) => actor.id === participant.actor_id);
    if (matches.length !== 1 || matches[0]?.family !== "player") {
      throw new Error(`participant ${participant.id} actor lookup did not resolve one player`);
    }
  }
}

function replaceActor(actors: readonly ActorState[], replacement: ActorState): readonly ActorState[] {
  let matches = 0;
  const updated = actors.map((actor) => {
    if (actor.id !== replacement.id) {
      return actor;
    }
    matches += 1;
    return replacement;
  });
  if (matches !== 1) {
    throw new Error(`actor replacement for ${replacement.id} resolved ${matches} candidates`);
  }
  return updated;
}

function headingToward(origin: Vec2, target: Vec2, previousHeading: number): number {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  if (dx === 0 && dy === 0) {
    return previousHeading;
  }
  const degrees = Math.atan2(dx, -dy) * 180 / Math.PI;
  return f32(degrees < 0 ? degrees + 360 : degrees);
}

function movementToward(origin: Vec2, target: Vec2): Vec2 {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  const distance = Math.hypot(dx, dy);
  return distance === 0 ? { x: 0, y: 0 } : { x: dx / distance, y: dy / distance };
}

interface IntentApplication {
  readonly actors: readonly ActorState[];
  readonly pending_actors: readonly ActorState[];
  readonly next_actor_serial: number;
}

function applyIntent(
  state: IntentApplication,
  participants: readonly ParticipantState[],
  envelope: IntentEnvelope,
  config: SimulationConfig,
): IntentApplication {
  const participantMatches = participants.filter((candidate) => candidate.id === envelope.participant_id);
  if (participantMatches.length !== 1) {
    throw new Error(
      `intent participant lookup for ${envelope.participant_id} resolved ${participantMatches.length} candidates`,
    );
  }
  const participant = participantMatches[0];
  if (participant === undefined) {
    throw new Error("intent participant lookup lost its unique candidate");
  }
  const actorMatches = state.actors.filter((candidate) => candidate.id === participant.actor_id);
  if (actorMatches.length !== 1 || actorMatches[0]?.family !== "player") {
    throw new Error(`intent actor lookup for ${participant.actor_id} did not resolve one player`);
  }
  const player = actorMatches[0];
  const intent = envelope.intent;
  if (intent.kind === "move") {
    const movementIntent = intent.phase === "stop"
      ? { x: 0, y: 0 }
      : intent.move.type === "unit_vector"
        ? intent.move.vector
        : movementToward(player.position, intent.move.point);
    return {
      ...state,
      actors: replaceActor(state.actors, {
        ...player,
        movement: { ...player.movement, intent: movementIntent },
      }),
    };
  }
  if (intent.kind === "aim") {
    return {
      ...state,
      actors: replaceActor(state.actors, {
        ...player,
        aim_point: intent.point,
        heading_degrees: headingToward(player.position, intent.point, player.heading_degrees),
      }),
    };
  }
  if (intent.kind === "cast") {
    if (intent.slot === "secondary") {
      throw new Error("secondary casting belongs to P3; P2 accepts FIRE primary only");
    }
    if (intent.phase !== "press") {
      return state;
    }
    const projectile = createFireProjectile(
      player,
      config.cast_glyph_points,
      state.next_actor_serial,
    );
    return {
      actors: state.actors,
      pending_actors: [...state.pending_actors, projectile],
      next_actor_serial: state.next_actor_serial + 1,
    };
  }
  // Interaction and menu intents are valid G14 timeline entries but have no P2
  // world-simulation effect. Their owning systems consume them outside sim/.
  return state;
}

function snapshotTrackedCenters(actors: readonly ActorState[]): readonly TrackedActorCenter[] {
  return actors
    .filter((actor) => actor.tracked_enemy || actor.family === "player")
    .map((actor) => ({ actor_id: actor.id, position: { ...actor.position } }));
}

function initializePendingActors(
  actors: readonly ActorState[],
  pendingActors: readonly ActorState[],
): readonly ActorState[] {
  return [
    ...actors,
    ...pendingActors.map((actor) => ({ ...actor, initialized: true })),
  ].sort((left, right) => left.insertion_order - right.insertion_order);
}

function tickActors(
  actorsAtStart: readonly ActorState[],
  sceneTick: number,
  config: SimulationConfig,
): { readonly actors: readonly ActorState[]; readonly events: readonly SimulationEvent[] } {
  let actors: readonly ActorState[] = actorsAtStart;
  const events: SimulationEvent[] = [];
  const orderedIds = actorsAtStart.map((actor) => actor.id);
  for (const actorId of orderedIds) {
    const matches = actors.filter((candidate) => candidate.id === actorId);
    if (matches.length !== 1) {
      throw new Error(`insertion-order actor lookup for ${actorId} resolved ${matches.length} candidates`);
    }
    const actor = matches[0];
    if (actor === undefined || actor.destroyed) {
      continue;
    }
    if (actor.family === "player") {
      const moved = tickPlayerMovement(actor, config.collision_rectangles);
      actors = replaceActor(actors, tickPlayerKnockback(moved, config.collision_rectangles));
      continue;
    }
    if (actor.family === "enemy") {
      actors = replaceActor(
        actors,
        tickEnemyMovement(actor, sceneTick, config.collision_rectangles),
      );
      continue;
    }
    const result = tickFireProjectile(
      actor,
      actors,
      config.collision_rectangles,
      config.spatial_cell_size,
    );
    actors = replaceActor(result.actors, result.projectile);
    events.push(...result.events);
  }
  return { actors, events };
}

export function stepSimulation(
  state: SimulationState,
  intents: readonly IntentEnvelope[],
  config: SimulationConfig,
): SimulationState {
  validateSimulationState(state);
  validateCollisionRectangles(config.collision_rectangles);

  let intentState: IntentApplication = {
    actors: state.actors,
    pending_actors: state.pending_actors,
    next_actor_serial: state.next_actor_serial,
  };
  for (const envelope of intents) {
    intentState = applyIntent(intentState, state.participants, envelope, config);
  }

  const trackedActorCenters = snapshotTrackedCenters(intentState.actors);
  const initializedActors = initializePendingActors(
    intentState.actors,
    intentState.pending_actors,
  );
  const ticked = tickActors(initializedActors, state.scene_tick, config);
  return {
    ...state,
    elapsed_app_ticks: state.elapsed_app_ticks + 1,
    scene_tick: state.scene_tick + 1,
    actors: ticked.actors.filter((actor) => !actor.destroyed),
    pending_actors: [],
    next_actor_serial: intentState.next_actor_serial,
    tracked_actor_centers: trackedActorCenters,
    events: ticked.events,
  };
}
