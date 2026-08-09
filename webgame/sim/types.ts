import type { Intent } from "../input/intent.js";

export interface Vec2 {
  readonly x: number;
  readonly y: number;
}

export type ParticipantKind = "LocalHuman" | "RemoteParticipant";
export type ParticipantControllerKind = "Native" | "LuaBrain";

export interface ParticipantState {
  readonly id: string;
  readonly kind: ParticipantKind;
  readonly controller: ParticipantControllerKind;
  readonly slot: number;
  readonly actor_id: string;
}

export interface PlayerMovementState {
  readonly intent: Vec2;
  readonly velocity: Vec2;
  readonly transient_multiplier: number;
  readonly move_speed_scale: number;
  readonly progression_multiplier: number;
  readonly move_step_scale: number;
  readonly controlled_damping: boolean;
}

export interface KnockbackState {
  readonly origin: Vec2;
  readonly remaining_distance: number;
}

interface ActorBase {
  readonly id: string;
  readonly insertion_order: number;
  readonly object_type_id: number;
  readonly position: Vec2;
  readonly radius: number;
  readonly tracked_enemy: boolean;
  readonly initialized: boolean;
  readonly destroyed: boolean;
}

export interface PlayerActorState extends ActorBase {
  readonly family: "player";
  readonly participant_id: string;
  readonly slot: number;
  readonly heading_degrees: number;
  readonly aim_point: Vec2;
  readonly sprite_set: CastSpriteSet;
  readonly movement: PlayerMovementState;
  readonly knockback: KnockbackState | null;
}

export type EnemyFamily =
  | "Imp"
  | "Green Imp"
  | "Zombie"
  | "Wraith"
  | "Demon Skull"
  | "Dire Faculty"
  | "Spider"
  | "Skeleton"
  | "Demon"
  | "Coffin"
  | "Maggot"
  | "Skeleton Archer"
  | "Skeleton Mage"
  | "Heartmonger";

export interface EnemyActorState extends ActorBase {
  readonly family: "enemy";
  readonly enemy_family: EnemyFamily;
  readonly enemy_type: number;
  readonly health: number;
  readonly maximum_health: number;
  readonly movement_direction: Vec2;
  readonly movement_cadence_ticks: 2 | 5 | 10 | 15;
  readonly base_speed: number;
  readonly local_speed_factor: number;
  readonly shared_status_multiplier: number;
}

export interface FireProjectileState extends ActorBase {
  readonly family: "fire_projectile";
  readonly owner_participant_id: string;
  readonly aim_unit: Vec2;
  readonly age_ticks: number;
}

export type ActorState = PlayerActorState | EnemyActorState | FireProjectileState;

export type CastSpriteSet =
  | { readonly kind: "none" }
  | { readonly kind: "staff"; readonly object_type_id: 0x1b5c; readonly pose: number }
  | { readonly kind: "wand"; readonly pose: number };

export interface CastGlyphPoint {
  readonly sprite_set: CastSpriteSet["kind"];
  readonly bank: number;
  readonly facing: number;
  readonly point_index: number;
  readonly point: Vec2;
}

export interface CollisionRectangle {
  readonly id: string;
  readonly min_x: number;
  readonly min_y: number;
  readonly max_x: number;
  readonly max_y: number;
}

export interface SimulationConfig {
  readonly collision_rectangles: readonly CollisionRectangle[];
  readonly cast_glyph_points: readonly CastGlyphPoint[];
  readonly spatial_cell_size: number;
}

export interface NativeRngState {
  readonly index_a: number;
  readonly index_b: number;
  readonly state_words: readonly number[];
  readonly divisor: number;
}

export interface TrackedActorCenter {
  readonly actor_id: string;
  readonly position: Vec2;
}

export type SimulationEvent =
  | {
      readonly kind: "fire_status";
      readonly projectile_id: string;
      readonly target_id: string;
    }
  | {
      readonly kind: "damage";
      readonly projectile_id: string;
      readonly target_id: string;
      readonly amount: number;
      readonly resulting_health: number;
    }
  | {
      readonly kind: "fire_removed";
      readonly projectile_id: string;
      readonly reason: "actor_contact" | "terrain_contact";
    };

export interface SimulationState {
  readonly schema_version: 1;
  readonly elapsed_app_ticks: number;
  readonly scene_tick: number;
  readonly rng: NativeRngState;
  readonly participants: readonly ParticipantState[];
  readonly slots: readonly (string | null)[];
  readonly actors: readonly ActorState[];
  readonly pending_actors: readonly ActorState[];
  readonly next_actor_serial: number;
  readonly tracked_actor_centers: readonly TrackedActorCenter[];
  readonly events: readonly SimulationEvent[];
}

export interface IntentEnvelope {
  readonly participant_id: string;
  readonly intent: Intent;
}
