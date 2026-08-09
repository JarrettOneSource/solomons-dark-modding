/**
 * Native fixed-tick order from docs/reverse-engineering/native-movement-and-tick.md.
 * Presentation and transport cadences are deliberately outside this graph.
 */
export const TICK_RATE_HZ = 100;
export const TICK_INTERVAL_MS = 10;

export const TICK_SYSTEM_ORDER = [
  "application_actor_world",
  "scene_dispatch",
  "game_pre_world",
  "tracked_actor_snapshot",
  "game_state",
  "initialize_pending_actors",
  "tick_actors_in_insertion_order",
  "remove_destroyed_actors",
  "game_post_world",
  "scene_tick_counter_and_timers",
] as const;

export const GAMEPLAY_CADENCE_TICKS = {
  native_fixed_simulation: 1,
  normal_badguy_movement: 2,
  badguy_alternate_5: 5,
  badguy_alternate_10: 10,
  badguy_alternate_15: 15,
  fire_target_contact: 1,
  fire_terrain_contact: 5,
} as const;

export const PLAYER_MOVEMENT = {
  input_divisor: 10,
  transient_multiplier: 1,
  move_speed_scale: 1,
  progression_multiplier: 0.95,
  global_cap_scale: 1.25,
  resulting_cap: 1.1875,
  move_step_scale: 1,
  move_threshold_squared: 0.01,
  ordinary_damping: Math.fround(0.9),
  controlled_damping: Math.fround(0.95),
} as const;

export const COLLISION_RESPONSE = {
  common_actor_radius: 15,
  movement_fixture_player_radius: 25,
  knockback_radius_scale: 0.6,
  enemy_substep_radius_margin: 1,
  half_step: 0.5,
  placement_epsilon: Math.fround(0.01),
  iteration_limit: 8,
} as const;

export const ENEMY_MOVEMENT = {
  direct_step_scale: 0.25,
  local_factor_floor: 1,
  local_factor_decay: Math.fround(0.995),
} as const;

export const NATIVE_RNG = {
  mask: 0x3fffffff,
  state_word_count: 55,
  initial_index_a: 0,
  initial_index_b: 31,
  stock_divisor: 100_000,
  seed_tick_multiplier: 0x0ef3,
} as const;

export const FIRE = {
  object_type_id: 0x07d4,
  skill_id: 16,
  local_offset_x: 0,
  local_offset_y: 10,
  forward_spawn_offset: 20,
  speed_per_tick: 4.5,
  collision_radius: 22.5,
  target_query_radius: 20,
  terrain_lookahead_ticks: 5,
  contact_damage: 4,
} as const;

export const FIRE_DAMAGE_SOURCE_DOCS = [
  "docs/reverse-engineering/multiplayer-element-damage-2026-07-26.md",
  "docs/reverse-engineering/multiplayer-fireball-contact-2026-07-26.md",
] as const;

export const NATIVE_OBJECT_TYPE = {
  player: 0x0001,
  wave_enemy: 0x03e9,
  fire_projectile: FIRE.object_type_id,
  knockback: 0x07e9,
} as const;

export type TickSystem = (typeof TICK_SYSTEM_ORDER)[number];
