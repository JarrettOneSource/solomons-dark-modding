local inverse_sqrt_two = 1.0 / math.sqrt(2.0)

local observation_names = {}

local function append(name)
  observation_names[#observation_names + 1] = name
end

-- V2 Blocks A-I remain byte-for-byte ordered at positions 1-395.

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

-- Block H: aggregates, config, history, weld, and combat multipliers.
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
  "ML bot v3 must preserve the exact 395-value v2 prefix")

-- Block J: participant-scoped potion timers.
for _, name in ipairs({
  "self_damage_x4_remaining_scaled",
  "self_poison_immunity_remaining_scaled",
  "self_all_concentration_remaining_scaled",
}) do
  append(name)
end

-- Block K: identity, facing, telegraph, and combat status for the existing
-- eight enemy slots.
local enemy_extension_suffixes = {
  "species_index_scaled",
  "species_known",
  "role_melee",
  "role_ranged",
  "role_caster",
  "role_spawner",
  "role_exploder",
  "role_boss",
  "role_flying",
  "role_stationary",
  "facing_dx",
  "facing_dy",
  "anim_state_scaled",
  "telegraph_known",
  "winding_up",
  "attack_active",
  "recovering",
  "slowed",
  "slow_remaining_scaled",
  "frozen",
  "frozen_remaining_scaled",
  "poisoned",
  "poison_remaining_scaled",
  "webbed",
  "webbed_remaining_scaled",
  "turn_undead",
  "turn_undead_remaining_scaled",
}
for slot = 1, 8 do
  local prefix = "enemy_" .. tostring(slot) .. "_"
  for _, suffix in ipairs(enemy_extension_suffixes) do
    append(prefix .. suffix)
  end
end

-- Block L: persisted target motion and facing.
for _, name in ipairs({
  "target_velocity_dx",
  "target_velocity_dy",
  "target_facing_dx",
  "target_facing_dy",
}) do
  append(name)
end

-- Block M: eight nearest exact collision primitives.
local obstacle_suffixes = {
  "present",
  "nearest_dx",
  "nearest_dy",
  "clearance_scaled",
  "normal_dx",
  "normal_dy",
  "radius_scaled",
  "extent_x_scaled",
  "extent_y_scaled",
  "kind_circle",
  "kind_segment",
  "kind_polygon",
  "is_participant",
  "is_destructible",
}
for slot = 1, 8 do
  local prefix = "obstacle_" .. tostring(slot) .. "_"
  for _, suffix in ipairs(obstacle_suffixes) do
    append(prefix .. suffix)
  end
end

-- Block N: twelve nearest hostile hazards. Unknown hostile classes remain
-- present and carry type_known=0.
local hazard_suffixes = {
  "present",
  "hazard_type_index_scaled",
  "type_known",
  "dx",
  "dy",
  "distance_scaled",
  "velocity_dx",
  "velocity_dy",
  "radius_scaled",
  "time_to_contact_scaled",
  "remaining_time_scaled",
  "kind_projectile",
  "kind_area",
  "kind_beam",
  "homing",
  "targeting_self",
  "source_enemy",
}
for slot = 1, 12 do
  local prefix = "hazard_" .. tostring(slot) .. "_"
  for _, suffix in ipairs(hazard_suffixes) do
    append(prefix .. suffix)
  end
end
append("hazard_count_scaled")

-- Block O: twelve count-ranked potion descriptors plus overflow context.
local potion_suffixes = {
  "present",
  "count_scaled",
  "stock_health",
  "stock_mana",
  "stock_wizard_chug",
  "stock_antidote",
  "stock_mind_chug",
  "stock_rejuvenation",
  "custom",
  "restores_hp_fraction",
  "restores_mana_fraction",
  "damage_multiplier_scaled",
  "cures_poison",
  "poison_immunity_duration_scaled",
  "concentrates_all",
  "effect_duration_scaled",
  "custom_effect_known",
  "identity_hash_a",
  "identity_hash_b",
}
for slot = 1, 12 do
  local prefix = "potion_" .. tostring(slot) .. "_"
  for _, suffix in ipairs(potion_suffixes) do
    append(prefix .. suffix)
  end
end
append("potion_type_count_scaled")
append("potion_total_count_scaled")

-- Block P: seven equipped-item descriptors.
local equipment_suffixes = {
  "present",
  "catalog_known",
  "identity_hash_a",
  "identity_hash_b",
  "rarity_scaled",
  "level_scaled",
  "set_complete",
  "offense_effect_scaled",
  "resource_effect_scaled",
  "mobility_effect_scaled",
  "defense_effect_scaled",
  "targeted_effect_present",
  "target_kind_scaled",
  "target_magnitude_scaled",
  "special_feature_present",
}
for _, slot in ipairs({
  "hat",
  "robe",
  "weapon",
  "ring_1",
  "ring_2",
  "ring_3",
  "amulet",
}) do
  local prefix = "equipment_" .. slot .. "_"
  for _, suffix in ipairs(equipment_suffixes) do
    append(prefix .. suffix)
  end
end

-- Block Q: bounded inventory taxonomy totals.
for _, name in ipairs({
  "inventory_item_total_count_scaled",
  "inventory_potion_count_scaled",
  "inventory_equipment_count_scaled",
  "inventory_sack_count_scaled",
  "inventory_misc_count_scaled",
  "inventory_perk_count_scaled",
  "inventory_map_count_scaled",
  "inventory_registered_custom_count_scaled",
  "inventory_unknown_count_scaled",
}) do
  append(name)
end

assert(
  #observation_names == 1279,
  "ML bot v3 observation contract must contain exactly 1279 names")

local option_descriptor_names = {
  "present",
  "option_id_index_scaled",
  "catalog_known",
  "apply_count_scaled",
  "learned_rank_scaled",
  "effective_rank_scaled",
  "cap_rank_scaled",
  "max_rank_scaled",
  "band_index_scaled",
  "family_element",
  "family_discipline",
  "family_ether",
  "family_fire",
  "family_air",
  "family_water",
  "family_earth",
  "family_arcane",
  "family_mind",
  "family_body",
  "family_advanced",
  "family_runtime_only",
  "is_primary",
  "is_secondary",
  "is_passive",
  "is_utility",
  "is_weld",
  "is_health_up",
  "is_mana_up",
  "weld_element_ether",
  "weld_element_fire",
  "weld_element_air",
  "weld_element_water",
  "weld_element_earth",
  "weld_build_index_scaled",
  "mana_cost_scaled",
  "damage_min_scaled",
  "damage_max_scaled",
  "range_scaled",
  "cooldown_scaled",
  "radius_scaled",
  "duration_scaled",
  "value_scaled",
  "concentration_scaled",
  "chance_scaled",
  "quantity_or_strength_scaled",
  "mana_cost_present",
  "damage_min_present",
  "damage_max_present",
  "range_present",
  "cooldown_present",
  "radius_present",
  "duration_present",
  "value_present",
  "concentration_present",
  "chance_present",
  "quantity_or_strength_present",
}

assert(
  #option_descriptor_names == 56,
  "ML bot v3 choice option descriptor must contain 56 names")

local movement_actions = {
  {name = "idle", x = 0.0, y = 0.0},
  {name = "east", x = 1.0, y = 0.0},
  {name = "southeast", x = inverse_sqrt_two, y = inverse_sqrt_two},
  {name = "south", x = 0.0, y = 1.0},
  {name = "southwest", x = -inverse_sqrt_two, y = inverse_sqrt_two},
  {name = "west", x = -1.0, y = 0.0},
  {name = "northwest", x = -inverse_sqrt_two, y = -inverse_sqrt_two},
  {name = "north", x = 0.0, y = -1.0},
  {name = "northeast", x = inverse_sqrt_two, y = -inverse_sqrt_two},
}

local target_actions = {
  {name = "keep_current", enemy_slot = 0},
}
for slot = 1, 8 do
  target_actions[#target_actions + 1] = {
    name = "enemy_" .. tostring(slot),
    enemy_slot = slot,
  }
end

local ability_actions = {
  {name = "none", kind = "none", skill_slot = -1},
  {name = "primary", kind = "cast", skill_slot = 0},
}
for slot = 1, 8 do
  ability_actions[#ability_actions + 1] = {
    name = "secondary_" .. tostring(slot),
    kind = "cast",
    skill_slot = slot,
  }
end
for slot = 1, 12 do
  ability_actions[#ability_actions + 1] = {
    name = "drink_potion_" .. tostring(slot),
    kind = "potion",
    potion_slot = slot,
  }
end

local aim_actions = {
  {name = "center", x = 0.0, y = 0.0},
}
for index = 2, #movement_actions do
  local direction = movement_actions[index]
  aim_actions[#aim_actions + 1] = {
    name = direction.name,
    x = direction.x,
    y = direction.y,
  }
end

assert(#movement_actions == 9)
assert(#target_actions == 9)
assert(#ability_actions == 22)
assert(#aim_actions == 9)

return {
  model_format = "solomon-dark-bot-policy",
  model_version = 3,
  observation_version = 3,
  trajectory_version = 3,
  choice_trajectory_version = 3,
  architecture = "mlp-tanh-four-head-v3",
  hidden_sizes = {512, 256},
  choice_hidden_size = 128,
  observation_names = observation_names,
  option_descriptor_names = option_descriptor_names,

  secondary_slot_count = 8,
  enemy_slot_count = 8,
  pickup_slot_count = 4,
  ally_slot_count = 4,
  obstacle_slot_count = 8,
  hazard_slot_count = 12,
  potion_slot_count = 12,
  equipment_slot_count = 7,
  max_choice_options = 16,

  -- Fixed v3 scales. These are source-evidenced constants rather than batch
  -- statistics. V2's maxima remain documented in the accepted v2 contract.
  mana_scale = 2000.0,
  hp_scale = 1000.0,
  velocity_scale = 1000.0,
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
  nav_refresh_ms = 2000,
  movement_lookahead = 110.0,
  pickup_count_scale = 8.0,
  ally_count_scale = 50.0,
  multiplier_scale = 4.0,
  pickup_request_interval_ms = 500,

  -- Native modifier and consumable timers run at 100 Hz. The accepted live
  -- Teleport cap is 60 seconds and covers every currently exposed timer.
  status_duration_scale_seconds = 60.0,
  hazard_lifetime_scale_seconds = 60.0,
  hazard_time_to_contact_scale_seconds = 10.0,

  enemy_species_scale = 19.0,
  enemy_animation_state_scale = 255.0,
  hazard_type_scale = 38.0,
  equipment_catalog_scale = 46.0,
  equipment_rarity_scale = 2.0,
  equipment_target_kind_scale = 8.0,
  equipment_effect_scale = 4.0,

  -- Adjudication 13 fixes every inventory count to log1p saturation at 99.
  inventory_count_saturation = 99.0,

  aim_offset_world = 60.0,

  -- Catalog maxima from native-skill-catalog.json: Damage 500, Cooldown 60,
  -- Radius 20, Duration 30, Value 1250, Concentration 25, Chance 100, and
  -- max(Quantity, Strength) 2100. Mana and range reuse the v2 scales.
  skill_id_scale = 81.0,
  skill_rank_scale = 20.0,
  skill_band_scale = 8.0,
  skill_damage_scale = 500.0,
  skill_radius_scale = 20.0,
  skill_duration_scale = 30.0,
  skill_value_scale = 1250.0,
  skill_concentration_scale = 25.0,
  skill_chance_scale = 100.0,
  skill_quantity_or_strength_scale = 2100.0,

  choice_entropy_coefficient = 0.05,
  choice_exploration_temperature = 1.25,
  choice_final_temperature = 1.0,
  choice_coverage_threshold = 20,

  primary_build_index_encoding =
    "base_band_identity_or_weld_pair_index",

  movement_actions = movement_actions,
  target_actions = target_actions,
  ability_actions = ability_actions,
  aim_actions = aim_actions,

  main_trajectory_fields = {
    "trajectory_version",
    "episode_id",
    "participant_id",
    "simulation_tick",
    "observation",
    "movement_mask",
    "target_mask",
    "ability_mask",
    "aim_mask",
    "movement_action",
    "target_action",
    "ability_action",
    "aim_action",
    "old_log_probability",
    "old_value",
    "reward",
    "done",
  },
  choice_trajectory_fields = {
    "choice_trajectory_version",
    "episode_id",
    "participant_id",
    "generation",
    "simulation_tick",
    "observation",
    "option_descriptors",
    "option_mask",
    "selected_option",
    "old_log_probability",
    "old_value",
    "next_value",
    "duration_steps",
    "rewards",
    "done",
    "choice_mode",
    "trainable",
    "accepted",
  },

  learned_skill_choice_head = true,
  skill_choice_modes = {
    learned = true,
    scripted = true,
  },
}
