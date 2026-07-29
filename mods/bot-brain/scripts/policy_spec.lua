local inverse_sqrt_two = 1.0 / math.sqrt(2.0)

local observation_names = {}

local function append(name)
  observation_names[#observation_names + 1] = name
end

-- Block A: self.
for _, name in ipairs({
  "self_hp_ratio",
  "self_mana_ratio",
  "self_level_scaled",
  "wave_scaled",
  "self_move_speed_scaled",
  "self_moving",
  "self_cast_active",
  "self_cast_ready",
  "self_poisoned",
  "self_webbed",
  "self_damage_x4",
  "self_status_active",
  "self_mana_current_scaled",
  "self_mana_max_scaled",
  "self_hp_max_scaled",
}) do
  append(name)
end

-- Block B: active primary.
for _, name in ipairs({
  "primary_element_fire",
  "primary_element_water",
  "primary_element_earth",
  "primary_element_air",
  "primary_element_ether",
  "primary_welded",
  "primary_build_index_scaled",
  "primary_mana_cost_scaled",
  "primary_range_min_scaled",
  "primary_range_max_scaled",
  "primary_affordable",
}) do
  append(name)
end

-- Block C: eight secondary slots.
for slot = 1, 8 do
  local prefix = "secondary_" .. tostring(slot) .. "_"
  for _, suffix in ipairs({
    "occupied",
    "element_fire",
    "element_water",
    "element_earth",
    "element_air",
    "element_ether",
    "band_index_scaled",
    "mana_cost_scaled",
    "range_scaled",
    "cooldown_scaled",
    "ready",
    "affordable",
    "in_range_of_target",
  }) do
    append(prefix .. suffix)
  end
end

-- Block D: eight nearest enemies.
for slot = 1, 8 do
  local prefix = "enemy_" .. tostring(slot) .. "_"
  for _, suffix in ipairs({
    "present",
    "dx",
    "dy",
    "distance_scaled",
    "hp_ratio",
    "radius_scaled",
    "velocity_dx",
    "velocity_dy",
    "in_primary_range",
    "is_current_target",
  }) do
    append(prefix .. suffix)
  end
end

-- Block E: policy-selected target.
for _, name in ipairs({
  "target_present",
  "target_dx",
  "target_dy",
  "target_distance_scaled",
  "target_contact_distance_scaled",
  "target_hp_ratio",
  "target_radius_scaled",
  "target_in_primary_range",
  "primary_min_range_scaled",
  "primary_max_range_scaled",
}) do
  append(name)
end

-- Block F: eight clearance rays and a 7x7 walkability patch with the
-- observing cell omitted.
for _, direction in ipairs({
  "east",
  "southeast",
  "south",
  "southwest",
  "west",
  "northwest",
  "north",
  "northeast",
}) do
  append("clearance_" .. direction .. "_scaled")
end
for row = 1, 7 do
  for column = 1, 7 do
    if row ~= 4 or column ~= 4 then
      append(
        "walkability_patch_row_" .. tostring(row) ..
        "_col_" .. tostring(column))
    end
  end
end

-- Block G: four nearest replicated pickups.
for slot = 1, 4 do
  local prefix = "pickup_" .. tostring(slot) .. "_"
  for _, suffix in ipairs({
    "present",
    "dx",
    "dy",
    "distance_scaled",
    "type_gold",
    "type_health_orb",
    "type_mana_orb",
    "type_item_carrier",
  }) do
    append(prefix .. suffix)
  end
end
append("pickup_count_scaled")

-- Block I: four nearest in-run allies, deliberately placed before Block H.
for slot = 1, 4 do
  local prefix = "ally_" .. tostring(slot) .. "_"
  for _, suffix in ipairs({
    "present",
    "dx",
    "dy",
    "distance_scaled",
    "hp_ratio",
    "mana_ratio",
    "alive",
    "is_human",
    "intent_dx",
    "intent_dy",
  }) do
    append(prefix .. suffix)
  end
end
append("ally_count_scaled")

-- Block H: retained aggregates/config/history, weld state, and the four
-- progression-derived combat multipliers adjudicated for v2.
for _, name in ipairs({
  "enemy_count_scaled",
  "threat_count_scaled",
  "nearest_enemy_dx",
  "nearest_enemy_dy",
  "nearest_enemy_distance_scaled",
  "nearest_threat_dx",
  "nearest_threat_dy",
  "nearest_threat_distance_scaled",
  "escape_dx",
  "escape_dy",
  "suggested_move_dx",
  "suggested_move_dy",
  "arena_center_dx",
  "arena_center_dy",
  "arena_center_distance_scaled",
  "arena_x_normalized",
  "arena_y_normalized",
  "edge_pressure",
  "element_fire",
  "element_water",
  "element_earth",
  "element_air",
  "element_ether",
  "discipline_mind",
  "discipline_body",
  "discipline_arcane",
  "hp_delta",
  "mana_delta",
  "target_hp_delta",
  "enemy_count_delta",
  "previous_move_dx",
  "previous_move_dy",
  "previous_cast_primary",
  "previous_cast_secondary",
  "time_since_damage_scaled",
  "time_since_cast_scaled",
  "time_since_move_scaled",
  "previous_target_action_scaled",
  "previous_target_switched",
  "has_spell_welding_skill",
  "weld_offer_pending",
  "offensive_damage_multiplier_scaled",
  "offensive_mana_multiplier_scaled",
  "cast_speed_multiplier_scaled",
  "secondary_recharge_multiplier_scaled",
}) do
  append(name)
end

assert(
  #observation_names == 395,
  "ML bot v2 observation contract must contain exactly 395 names")

return {
  model_format = "solomon-dark-bot-policy",
  model_version = 2,
  observation_version = 2,
  trajectory_version = 2,
  architecture = "mlp-tanh-three-head-v2",
  hidden_sizes = {192, 96},
  observation_names = observation_names,

  secondary_slot_count = 8,
  enemy_slot_count = 8,
  pickup_slot_count = 4,
  ally_slot_count = 4,

  -- Fixed v2 scales. These are contract constants, not batch statistics.
  --
  -- Native baseline max HP/MP is 50. Mana Up 56 tops out at +1250 and
  -- Health Up 64 at +650 (native-skill-catalog.json); the stock 25% Mana
  -- and Life Charms are documented in native-hagatha-perk-catalog.json.
  -- Thus the end-game maxima are 1625 MP and 875 HP, covered by 2000/1000.
  mana_scale = 2000.0,
  hp_scale = 1000.0,
  --
  -- Rush 67 tops out at +50% and its concentration bonus is +25%
  -- (native-skill-catalog.json); stock walk-speed equipment tops out at +50%
  -- (native-item-catalog.json), and Speed Charm adds +10%
  -- (native-hagatha-perk-catalog.json). The native movement-envelope probe in
  -- tests/re/run_live_bot_native_speed_probe.py measures actor deltas and
  -- rejects motion above the PlayerActorTick cap. Its fastest observed mover
  -- remains below 1000 world units/second; 1000 is the fixed round ceiling.
  velocity_scale = 1000.0,
  --
  -- Phase 2's live Teleport-48 probe resolved a 60.0-second cap; the native
  -- cooldown rows are already converted to seconds by get_loadout_details.
  cooldown_scale = 60.0,
  range_scale = 1000.0,
  radius_scale = 100.0,
  level_scale = 20.0,
  wave_scale = 20.0,
  enemy_count_scale = 16.0,
  threat_count_scale = 8.0,
  history_time_scale_ms = 5000.0,
  target_action_scale = 8.0,
  ray_range = 480.0,
  ray_step = 60.0,
  patch_spacing = 60.0,
  patch_radius = 3,
  nav_subdivisions = 4,
  nav_refresh_ms = 2000,
  movement_lookahead = 110.0,
  pickup_count_scale = 8.0,
  ally_count_scale = 50.0,
  multiplier_scale = 4.0,
  pickup_request_interval_ms = 500,

  -- primary_build_index_scaled uses native skill-band order for base
  -- primaries: Ether/Fire/Air/Water/Earth map to 0/.2/.4/.6/.8. Welds map
  -- exactly as (build_id - 1000) / 10, yielding 0 through .9. The element
  -- flags disambiguate intentional overlap between the two encodings.
  primary_build_index_encoding =
    "base_band_identity_or_weld_pair_index",

  weld_preferences = {
    prefer = true,
    avoid = true,
    auto = true,
  },

  movement_actions = {
    { name = "idle", x = 0.0, y = 0.0 },
    { name = "east", x = 1.0, y = 0.0 },
    {
      name = "southeast",
      x = inverse_sqrt_two,
      y = inverse_sqrt_two,
    },
    { name = "south", x = 0.0, y = 1.0 },
    {
      name = "southwest",
      x = -inverse_sqrt_two,
      y = inverse_sqrt_two,
    },
    { name = "west", x = -1.0, y = 0.0 },
    {
      name = "northwest",
      x = -inverse_sqrt_two,
      y = -inverse_sqrt_two,
    },
    { name = "north", x = 0.0, y = -1.0 },
    {
      name = "northeast",
      x = inverse_sqrt_two,
      y = -inverse_sqrt_two,
    },
  },
  target_actions = {
    { name = "keep_current", enemy_slot = 0 },
    { name = "enemy_1", enemy_slot = 1 },
    { name = "enemy_2", enemy_slot = 2 },
    { name = "enemy_3", enemy_slot = 3 },
    { name = "enemy_4", enemy_slot = 4 },
    { name = "enemy_5", enemy_slot = 5 },
    { name = "enemy_6", enemy_slot = 6 },
    { name = "enemy_7", enemy_slot = 7 },
    { name = "enemy_8", enemy_slot = 8 },
  },
  cast_actions = {
    { name = "none", skill_slot = -1 },
    { name = "primary", skill_slot = 0 },
    { name = "secondary_1", skill_slot = 1 },
    { name = "secondary_2", skill_slot = 2 },
    { name = "secondary_3", skill_slot = 3 },
    { name = "secondary_4", skill_slot = 4 },
    { name = "secondary_5", skill_slot = 5 },
    { name = "secondary_6", skill_slot = 6 },
    { name = "secondary_7", skill_slot = 7 },
    { name = "secondary_8", skill_slot = 8 },
  },
  trajectory_fields = {
    "trajectory_version",
    "episode_id",
    "participant_id",
    "simulation_tick",
    "observation",
    "movement_mask",
    "target_mask",
    "cast_mask",
    "movement_action",
    "target_action",
    "cast_action",
    "old_log_probability",
    "old_value",
    "reward",
    "done",
  },

  -- Skill upgrades remain deterministic in v2. A learned weld/upgrade head is
  -- intentionally deferred to v3 because level-up offers are too sparse at
  -- the 10 Hz combat decision cadence.
  learned_skill_choice_head = false,
}
