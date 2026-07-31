local root = assert(arg[1], "repository root argument is required")

local function load_module(relative_path)
  local chunk, error_message =
    loadfile(root .. "/" .. relative_path)
  assert(chunk, error_message)
  return chunk()
end

local spec =
  load_module("mods/bot-brain/scripts/policy_spec.lua")
local geometry_module =
  load_module("mods/bot-brain/scripts/policy_geometry.lua")
local spell_module =
  load_module(
    "mods/bot-brain/scripts/policy_spell_descriptors.lua")
local enemy_module =
  load_module(
    "mods/bot-brain/scripts/policy_enemy_descriptors.lua")
local hazard_module =
  load_module("mods/bot-brain/scripts/policy_hazards.lua")
local inventory_module =
  load_module("mods/bot-brain/scripts/policy_inventory.lua")
local choice_module =
  load_module(
    "mods/bot-brain/scripts/policy_skill_choices.lua")
local skill_catalog =
  load_module(
    "mods/bot-brain/scripts/policy_skill_catalog.lua")
local observation =
  load_module(
    "mods/bot-brain/scripts/policy_observation.lua")
local training_module =
  load_module("mods/bot-brain/scripts/policy_training.lua")

assert(spec.model_version == 3)
assert(spec.observation_version == 3)
assert(spec.trajectory_version == 3)
assert(spec.choice_trajectory_version == 3)
assert(spec.architecture == "mlp-tanh-four-head-v3")
assert(spec.hidden_sizes[1] == 512)
assert(spec.hidden_sizes[2] == 256)
assert(#spec.observation_names == 1279)
assert(#spec.option_descriptor_names == 56)
assert(#spec.movement_actions == 9)
assert(#spec.target_actions == 9)
assert(#spec.ability_actions == 22)
assert(#spec.aim_actions == 9)
assert(spec.observation_names[395] ==
  "secondary_recharge_multiplier_scaled")
assert(spec.observation_names[396] ==
  "self_damage_x4_remaining_scaled")
assert(spec.observation_names[399] ==
  "enemy_1_species_index_scaled")
assert(spec.observation_names[615] ==
  "target_velocity_dx")
assert(spec.observation_names[619] ==
  "obstacle_1_present")
assert(spec.observation_names[731] ==
  "hazard_1_present")
assert(spec.observation_names[936] ==
  "potion_1_present")
assert(spec.observation_names[1166] ==
  "equipment_hat_present")
assert(spec.observation_names[1279] ==
  "inventory_unknown_count_scaled")

local geometry_calls = 0
local dynamic_revision = 1
local function collision_geometry()
  geometry_calls = geometry_calls + 1
  return {
    valid = true,
    scene_epoch = 7,
    run_nonce = 11,
    static_revision = 2,
    dynamic_revision = dynamic_revision,
    refresh_pending = false,
    observer_radius = 20.0,
    observer_radius_resolved = true,
    participant_collision_padding = 0.0,
    circles = {
      {
        geometry_id = 1,
        native_type_id = 100,
        x = 740.0,
        y = 500.0,
        radius = 20.0,
        path_blocks = true,
        destructible = false,
        destructible_resolved = true,
        dynamic = false,
      },
      {
        geometry_id = 2,
        native_type_id = 2061,
        x = 560.0,
        y = 500.0,
        radius = 20.0,
        path_blocks = false,
        pushable = true,
        destructible = true,
        destructible_resolved = true,
        dynamic = true,
      },
    },
    segments = {
      {
        geometry_id = 3,
        native_type_id = 200,
        start_x = 420.0,
        start_y = 350.0,
        end_x = 580.0,
        end_y = 350.0,
        path_blocks = true,
        destructible = false,
        destructible_resolved = true,
        dynamic = false,
      },
    },
    polygons = {
      {
        geometry_id = 4,
        native_type_id = 300,
        bounds_x = 300.0,
        bounds_y = 450.0,
        bounds_w = 60.0,
        bounds_h = 100.0,
        path_blocks = true,
        destructible = true,
        destructible_resolved = true,
        dynamic = false,
        points = {
          {x = 300.0, y = 450.0},
          {x = 360.0, y = 450.0},
          {x = 360.0, y = 550.0},
          {x = 300.0, y = 550.0},
        },
      },
    },
    participant_radii = {
      {
        participant_id = 42,
        radius = 20.0,
        radius_resolved = true,
      },
      {
        participant_id = 43,
        radius = 20.0,
        radius_resolved = true,
      },
    },
  }
end

local geometry =
  geometry_module.new(spec, collision_geometry)

local loadout_details = {
  primary = {
    entry_id = 16,
    combo_entry_id = -1,
    build_id = 16,
    build_id_resolved = true,
    mana_cost = 10.0,
    mana_cost_resolved = true,
    mana_charge_kind = "per_cast",
    range_min = 0.0,
    range_max = 600.0,
    range_resolved = true,
    range_source = "fixture",
  },
  secondaries = {
    {
      slot = 1,
      entry_id = 54,
      mana_cost = 20.0,
      mana_cost_resolved = true,
      cooldown_seconds = 0.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = false,
    },
    {
      slot = 2,
      entry_id = 27,
      mana_cost = 30.0,
      mana_cost_resolved = true,
      cooldown_seconds = 0.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = false,
    },
    {
      slot = 3,
      entry_id = 15,
      mana_cost = 30.0,
      mana_cost_resolved = true,
      cooldown_seconds = 1.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = true,
    },
    {
      slot = 4,
      entry_id = 45,
      mana_cost = 40.0,
      mana_cost_resolved = true,
      cooldown_seconds = 0.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = false,
    },
  },
  pending_weld_build_id = 1000,
  pending_weld_build_id_resolved = true,
}
for slot = 5, spec.secondary_slot_count do
  loadout_details.secondaries[slot] = {
    slot = slot,
    entry_id = -1,
    mana_cost_resolved = false,
    cooldown_resolved = false,
  }
end

local spell_descriptors = spell_module.new(
  spec,
  {
    read_details = function()
      return loadout_details
    end,
    read_choices = function()
      return {}
    end,
    list_spells = function()
      return {}
    end,
  })

local snapshot = {
  hp = 80.0,
  max_hp = 100.0,
  mp = 60.0,
  max_mp = 100.0,
  moving = true,
  cast_active = false,
  cast_pending = false,
  cast_ready = true,
  native_poison_remaining_ticks = 500,
  replicated_poison_remaining_ticks = 500,
  native_webbed_remaining_ticks = 0,
  native_damage_x4_remaining_ticks = 3000,
  replicated_damage_x4_remaining_ticks = 3000,
  native_persistent_status_flags = 1,
  native_transient_status_flags = 2,
}

local self_participant = {
  participant_id = 42,
  controller_kind = "LuaBrain",
  in_run = true,
  runtime_valid = true,
  x = 500.0,
  y = 500.0,
  life_current = 80.0,
  life_max = 100.0,
  mana_current = 60.0,
  mana_max = 100.0,
  move_speed = 350.0,
  level = 5,
  owned_progression = {
    ability_loadout = {
      primary_entry_index = 16,
      primary_combo_entry_index = -1,
      secondary_entry_indices =
        {54, 27, 15, 45, -1, -1, -1, -1},
    },
    progression_book_entries = {
      {
        entry_index = 16,
        active = 2,
        statbook_max_level = 3,
      },
      {
        entry_index = 52,
        active = 0,
        statbook_max_level = 0,
      },
      {
        entry_index = 64,
        active = 1,
        statbook_max_level = 1,
      },
    },
    derived_stats = {
      pickup_range = 2.0,
      offensive_damage_multiplier = 1.5,
      offensive_mana_multiplier = 0.75,
      cast_speed_multiplier = 1.25,
      secondary_recharge_multiplier = 1.1,
    },
  },
}

local participants = {
  self_participant,
  {
    participant_id = 43,
    controller_kind = "Native",
    in_run = true,
    x = 620.0,
    y = 500.0,
    life_current = 100.0,
    life_max = 100.0,
    mana_current = 90.0,
    mana_max = 100.0,
    movement_intent_x = 3.0,
    movement_intent_y = 4.0,
  },
}

local hazard_rows = {
  {
    hazard_id = 1001,
    native_type_id = 0x07DA,
    active = true,
    hostile = true,
    type_known = true,
    kind = "projectile",
    source_participant_id = 0,
    source_network_actor_id = 101,
    target_participant_id = 42,
    target_network_actor_id = 0,
    x = 650.0,
    y = 500.0,
    radius = 8.0,
    motion_resolved = true,
    motion_x = -100.0,
    motion_y = 0.0,
    lifetime_resolved = true,
    remaining_seconds = 3.0,
    homing = false,
  },
  {
    hazard_id = 1002,
    native_type_id = 0x0803,
    active = true,
    hostile = true,
    type_known = false,
    kind = "projectile",
    source_participant_id = 0,
    source_network_actor_id = 0,
    target_participant_id = 0,
    target_network_actor_id = 0,
    x = 700.0,
    y = 550.0,
    radius = 12.0,
    motion_resolved = true,
    motion_x = -60.0,
    motion_y = 0.0,
    lifetime_resolved = true,
    remaining_seconds = 5.0,
    homing = false,
  },
}

local hazard_resolver = hazard_module.new(
  spec,
  {
    read = function()
      return {
        valid = true,
        hazard_total_count = #hazard_rows,
        hazards = hazard_rows,
      }
    end,
  })

local inventory_details = {
  participant_id = 42,
  run_nonce = 11,
  inventory_revision = 5,
  equipment_revision = 3,
  descriptors_resolved = true,
  damage_x4_remaining_seconds = 30.0,
  poison_immunity_remaining_seconds = 4.0,
  all_concentration_remaining_seconds = 15.0,
  timers_resolved = true,
  potions = {
    {
      stock_subtype = 0,
      identity_key = "stock:potion:health",
      count = 12,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = true,
      restores_hp_fraction = 1.0,
      restores_mana_fraction = 0.0,
      damage_multiplier = 1.0,
    },
    {
      stock_subtype = 1,
      identity_key = "stock:potion:mana",
      count = 11,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = true,
      restores_hp_fraction = 0.0,
      restores_mana_fraction = 1.0,
      damage_multiplier = 1.0,
    },
    {
      stock_subtype = 2,
      identity_key = "stock:potion:wizard_chug",
      count = 10,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = false,
      damage_multiplier = 4.0,
      effect_duration_seconds = 60.0,
    },
    {
      stock_subtype = 3,
      identity_key = "stock:potion:antidote",
      count = 9,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = false,
      cures_poison = true,
      poison_immunity_duration_seconds = 10.0,
    },
    {
      stock_subtype = 4,
      identity_key = "stock:potion:mind_chug",
      count = 8,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = false,
      concentrates_all = true,
      effect_duration_seconds = 30.0,
    },
    {
      stock_subtype = 5,
      identity_key = "stock:potion:rejuvenation",
      count = 7,
      custom = false,
      effect_resolved = true,
      synthetic_use_supported = true,
      restores_hp_fraction = 1.0,
      restores_mana_fraction = 1.0,
      damage_multiplier = 1.0,
    },
    {
      stock_subtype = -1,
      content_id = 9001,
      identity_key = "fixture:custom:renewal",
      count = 6,
      custom = true,
      effect_resolved = true,
      synthetic_use_supported = true,
      restores_hp_fraction = 0.25,
      restores_mana_fraction = 0.0,
      damage_multiplier = 1.0,
    },
  },
  equipped = {
    {
      slot = "hat",
      present = true,
      identity_key = "stock:hat:cloudcover",
      catalog_index = 16,
      catalog_resolved = true,
      rarity_id = 2,
      level = 3,
      set_complete = false,
      offense_effect = 0.10,
      resource_effect = 0.0,
      mobility_effect = 0.0,
      defense_effect = 0.0,
      targeted_effect_present = true,
      target_kind = 2,
      target_magnitude = 0.10,
      special_feature_present = false,
    },
  },
  summary = {
    item_total_count = 99,
    potion_count = 63,
    equipment_count = 1,
    sack_count = 2,
    misc_count = 3,
    perk_count = 4,
    map_count = 5,
    registered_custom_count = 6,
    unknown_count = 7,
  },
}

local inventory_resolver = inventory_module.new(
  spec,
  {
    read = function()
      return inventory_details
    end,
    use_consumable = function()
      return true, {use_id = 77}
    end,
  })

local enemies = {
  {
    network_actor_id = 101,
    object_type_id = 1008,
    x = 600.0,
    y = 500.0,
    radius = 12.0,
    hp = 100.0,
    max_hp = 100.0,
    heading = 90.0,
    anim_drive_state = 0x1A,
    combat_status_resolved = true,
    slowed = false,
    slow_remaining_seconds = 0.0,
    frozen = false,
    frozen_remaining_seconds = 0.0,
    poisoned = false,
    poison_remaining_seconds = 0.0,
    webbed = false,
    webbed_remaining_seconds = 0.0,
    turn_undead_resolved = true,
    turn_undead = false,
    turn_undead_remaining_seconds = 0.0,
  },
  {
    network_actor_id = 102,
    object_type_id = 1002,
    x = 800.0,
    y = 500.0,
    radius = 10.0,
    hp = 90.0,
    max_hp = 100.0,
    heading = 180.0,
    anim_drive_state = 0,
    combat_status_resolved = true,
    turn_undead_resolved = true,
  },
}

local indexes = {}
for index, name in ipairs(spec.observation_names) do
  assert(indexes[name] == nil)
  indexes[name] = index
end

local segment_calls = 0
local builder = observation.new(
  spec,
  {
    geometry = geometry,
    spell_descriptors = spell_descriptors,
    enemy_descriptors = enemy_module.new(spec),
    hazards = hazard_resolver,
    inventory = inventory_resolver,
    get_snapshot = function()
      return snapshot
    end,
    get_multiplayer_state = function()
      return {participants = participants}
    end,
    get_loot = function()
      return {authority_participant_id = 1, drops = {}}
    end,
    test_segment = function()
      segment_calls = segment_calls + 1
      return true
    end,
  })

local context = {
  participant_id = 42,
  row = {element = "fire", discipline = "arcane"},
  policy_memory = observation.new_memory(),
  policy_geometry = geometry,
  policy_hazards = hazard_resolver,
}

local function frame(now_ms)
  return {
    now_ms = now_ms,
    simulation_tick = now_ms / 10,
    bot_x = 500.0,
    bot_y = 500.0,
    hp = snapshot.hp,
    max_hp = snapshot.max_hp,
    wave = {wave = 3},
    enemies = enemies,
    threat_radius = 340.0,
    edge_pressure = 0.1,
    suggested_move_x = 0.0,
    suggested_move_y = 1.0,
    arena = {
      center_x = 600.0,
      center_y = 600.0,
      half_width = 600.0,
      half_height = 600.0,
    },
    movement_lookahead = spec.movement_lookahead,
    offense_enabled = true,
    scene_key = "run:fixture",
    skill_choices = {
      pending = true,
      generation = 1,
      options = {
        {id = 52, apply_count = 0},
        {id = 64, apply_count = 1},
      },
    },
  }
end

local first = observation.capture(
  builder,
  context,
  frame(0))
assert(#first.values == 1279)
for index, value in ipairs(first.values) do
  assert(
    type(value) == "number" and value == value and
      value > -math.huge and value < math.huge,
    "non-finite " .. spec.observation_names[index])
end
assert(geometry_calls == 1)
assert(geometry:status().geometry_build_count == 1)
assert(geometry:walkable_at(500.0, 500.0, participants, 42))
assert(not geometry:walkable_at(620.0, 500.0, participants, 42))
assert(#first.obstacles >= 4)
assert(first.obstacles[1].is_participant == true)
assert(
  first.values[indexes.obstacle_1_is_participant] == 1.0)
assert(
  first.values[indexes.hazard_1_type_known] == 1.0)
assert(
  first.values[indexes.hazard_2_present] == 1.0)
assert(
  first.values[indexes.hazard_2_type_known] == 0.0)
assert(
  first.values[indexes.potion_3_stock_wizard_chug] == 1.0)
assert(
  first.values[indexes.potion_4_stock_antidote] == 1.0)
assert(
  first.values[indexes.potion_5_stock_mind_chug] == 1.0)
assert(first.values[indexes.equipment_hat_present] == 1.0)
assert(first.values[indexes.equipment_hat_catalog_known] == 1.0)
assert(
  first.values[indexes.inventory_item_total_count_scaled] == 1.0)
assert(segment_calls == 8)

local target = observation.select_target(
  builder,
  context,
  first,
  2)
assert(target.network_actor_id == 102)
local ability_mask = observation.build_ability_mask(
  builder,
  first,
  target)
assert(#ability_mask == 22)
assert(ability_mask[1] == true)
assert(ability_mask[2] == true)
assert(ability_mask[3] == true)
assert(ability_mask[4] == true)
assert(ability_mask[5] == true)
assert(ability_mask[6] == true)
assert(ability_mask[11] == true)
assert(ability_mask[12] == true)
assert(ability_mask[13] == false)
assert(ability_mask[14] == false)
assert(ability_mask[15] == false)
assert(ability_mask[16] == true)
assert(ability_mask[17] == true)

local none_aim =
  observation.build_aim_mask(builder, first, 0)
assert(none_aim[1] == true)
for index = 2, 9 do
  assert(none_aim[index] == false)
end
local primary_aim =
  observation.build_aim_mask(builder, first, 1)
for index = 1, 9 do
  assert(primary_aim[index] == true)
end
local center_secondary_aim =
  observation.build_aim_mask(builder, first, 2)
assert(center_secondary_aim[1] == true)
for index = 2, 9 do
  assert(center_secondary_aim[index] == false)
end
local free_secondary_aim =
  observation.build_aim_mask(builder, first, 3)
for index = 1, 9 do
  assert(free_secondary_aim[index] == true)
end
local phasing_aim =
  observation.build_aim_mask(builder, first, 4)
local golem_aim =
  observation.build_aim_mask(builder, first, 5)
for index = 1, 9 do
  assert(phasing_aim[index] == true)
  assert(golem_aim[index] == true)
end
local potion_aim =
  observation.build_aim_mask(builder, first, 10)
assert(potion_aim[1] == true)
for index = 2, 9 do
  assert(potion_aim[index] == false)
end
local aim_x, aim_y =
  observation.aim_point(builder, target, 1)
assert(aim_x == target.x + spec.aim_offset_world)
assert(aim_y == target.y)

-- Reorder by distance while retaining actor-ID target persistence and flip
-- semantic combat status/facing.
enemies[1].x = 900.0
enemies[1].slowed = true
enemies[1].slow_remaining_seconds = 30.0
enemies[2].x = 610.0
enemies[2].heading = 270.0
local second = observation.capture(
  builder,
  context,
  frame(100))
assert(geometry_calls == 1)
assert(geometry:status().geometry_build_count == 1)
assert(second.current_target.network_actor_id == 102)
assert(second.enemy_slots[1].network_actor_id == 102)
assert(
  second.values[indexes.target_velocity_dx] == -1.0)
assert(
  math.abs(second.values[indexes.target_facing_dx] + 1.0) <
    0.000001)
assert(
  second.values[indexes.enemy_2_slowed] == 1.0)
assert(
  second.values[indexes.enemy_2_slow_remaining_scaled] == 0.5)

-- Transition all dynamic semantic blocks to empty/zero without rebuilding
-- exact geometry per observation.
hazard_rows = {}
inventory_details.potions = {}
inventory_details.equipped = {}
inventory_details.summary = {}
inventory_details.damage_x4_remaining_seconds = 0.0
inventory_details.poison_immunity_remaining_seconds = 0.0
inventory_details.all_concentration_remaining_seconds = 0.0
participants = {self_participant}
local third = observation.capture(
  builder,
  context,
  frame(200))
assert(geometry_calls == 1)
assert(geometry:status().geometry_build_count == 1)
assert(third.values[indexes.hazard_1_present] == 0.0)
assert(third.values[indexes.potion_1_present] == 0.0)
assert(third.values[indexes.equipment_hat_present] == 0.0)
assert(third.values[indexes.ally_1_present] == 0.0)

-- The two-second refresh adopts an unchanged tuple without rebuilding; a
-- changed dynamic revision produces one deliberate rebuild.
observation.capture(builder, context, frame(2200))
assert(geometry_calls == 2)
assert(geometry:status().geometry_build_count == 1)
dynamic_revision = 2
observation.capture(builder, context, frame(4300))
assert(geometry_calls == 3)
assert(geometry:status().geometry_build_count == 2)

local choice_manager = choice_module.new(
  spec,
  skill_catalog,
  spell_descriptors,
  {
    choose_skill = function(request)
      assert(request.id == 42)
      assert(request.generation > 0)
      assert(request.option_index > 0)
      return true
    end,
  })

local choice_options_a = {
  pending = true,
  generation = 20,
  options = {
    {id = 52, apply_count = 0},
    {id = 64, apply_count = 1},
    {id = 999, apply_count = 0},
  },
}
local choice_options_b = {
  pending = true,
  generation = 21,
  options = {
    {id = 999, apply_count = 0},
    {id = 52, apply_count = 0},
    {id = 64, apply_count = 1},
  },
}
local event_a = choice_manager:capture(
  self_participant,
  first.values,
  first.loadout,
  choice_options_a,
  100,
  first.metrics)
local event_b = choice_manager:capture(
  self_participant,
  first.values,
  first.loadout,
  choice_options_b,
  120,
  nil)
assert(#event_a.option_descriptors == 3)
for _, row in ipairs(event_a.option_descriptors) do
  assert(#row == 56)
end
for index = 1, 56 do
  assert(
    event_a.option_descriptors[1][index] ==
      event_b.option_descriptors[2][index])
  assert(
    event_a.option_descriptors[2][index] ==
      event_b.option_descriptors[3][index])
  assert(
    event_a.option_descriptors[3][index] ==
      event_b.option_descriptors[1][index])
end
local descriptor_indexes = {}
for index, name in ipairs(spec.option_descriptor_names) do
  descriptor_indexes[name] = index
end
assert(
  event_a.option_descriptors[1][
    descriptor_indexes.is_weld] == 1.0)
assert(
  event_a.option_descriptors[1][
    descriptor_indexes.weld_element_ether] == 1.0)
assert(
  event_a.option_descriptors[1][
    descriptor_indexes.weld_element_fire] == 1.0)
assert(
  event_a.option_descriptors[2][
    descriptor_indexes.is_health_up] == 1.0)
assert(
  event_a.option_descriptors[3][
    descriptor_indexes.catalog_known] == 0.0)

local fake_runtime = {
  generation = 1,
}
function fake_runtime:set_seed() end
function fake_runtime:status()
  return {available = true, generation = self.generation}
end
function fake_runtime:load()
  self.generation = self.generation + 1
  return self.generation
end
function fake_runtime:forward_choice()
  return {
    choice_action = 1,
    log_probability = -0.5,
    value = 0.25,
    choice_probability = 0.6,
  }
end

local controller =
  training_module.new(spec, fake_runtime)
controller:enable({seed = 123, capacity = 128})
local training_context = {
  participant_id = 42,
  last_skill_choice_generation = -1,
  debug = {
    skill_choices_accepted = 0,
    last_error = "",
  },
}
assert(choice_manager:handle(
  training_context,
  event_a,
  "learned",
  fake_runtime,
  controller,
  function()
    return 1
  end,
  true))
assert(training_context.debug.skill_choice_option_id == 64)
assert(not choice_manager:handle(
  training_context,
  event_a,
  "learned",
  fake_runtime,
  controller,
  function()
    return 1
  end,
  true))

local main_capture = {
  values = first.values,
  movement_mask = first.movement_mask,
  target_mask = first.target_mask,
  ability_mask = ability_mask,
  aim_mask = primary_aim,
  metrics = {
    hp_ratio = 1.0,
    mana_ratio = 1.0,
    wave = 1,
    alive = true,
    enemy_count = 1,
    enemy_health = {[101] = 1.0},
  },
}
local main_decision = {
  movement_action = 1,
  target_action = 2,
  ability_action = 1,
  aim_action = 0,
  log_probability = -0.75,
  value = 0.25,
}
controller:record(
  training_context,
  main_capture,
  main_decision,
  100)
main_capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.9,
  wave = 1,
  alive = true,
  enemy_count = 1,
  enemy_health = {[101] = 0.8},
}
controller:record(
  training_context,
  main_capture,
  main_decision,
  110)
main_capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.8,
  wave = 2,
  alive = true,
  enemy_count = 0,
  enemy_health = {},
}
event_b.metrics = main_capture.metrics
assert(choice_manager:handle(
  training_context,
  event_b,
  "learned",
  fake_runtime,
  controller,
  function()
    return 1
  end,
  true))
controller:record(
  training_context,
  main_capture,
  main_decision,
  120)
local main_records = controller:drain(10).records
assert(#main_records == 2)
assert(main_records[1].trajectory_version == 3)
assert(#main_records[1].observation == 1279)
assert(#main_records[1].ability_mask == 22)
assert(#main_records[1].aim_mask == 9)
assert(main_records[1].ability_action == 1)
assert(main_records[1].aim_action == 0)
local choice_records =
  controller:drain_choices(10, false).records
assert(#choice_records == 1)
assert(choice_records[1].choice_trajectory_version == 3)
assert(choice_records[1].duration_steps == 2)
assert(#choice_records[1].rewards == 2)
assert(choice_records[1].choice_mode == "learned")
assert(choice_records[1].trainable == true)
assert(choice_records[1].accepted == true)

local scripted_controller =
  training_module.new(spec, fake_runtime)
scripted_controller:enable({seed = 456, capacity = 128})
local scripted_context = {
  participant_id = 42,
  last_skill_choice_generation = -1,
  debug = {
    skill_choices_accepted = 0,
    last_error = "",
  },
}
assert(choice_manager:handle(
  scripted_context,
  event_a,
  "scripted",
  fake_runtime,
  scripted_controller,
  function()
    return 1
  end,
  false))
scripted_controller:record(
  scripted_context,
  main_capture,
  main_decision,
  200)
scripted_controller:terminal(
  scripted_context,
  {
    hp_ratio = 0.0,
    mana_ratio = 0.0,
    wave = 2,
    alive = false,
    enemy_count = 0,
    enemy_health = {},
  })
assert(
  #scripted_controller:drain_choices(10, false).records == 0)
assert(
  scripted_controller:status().scripted_choice_excluded == 1)

print("observation_count=1279")
print("exact_order=true")
print("finite=true")
print("exact_geometry=true")
print("geometry_builds=" ..
  tostring(geometry:status().geometry_build_count))
print("geometry_requests=" ..
  tostring(geometry:status().request_count))
print("enemy_status_transition=true")
print("target_motion_facing=true")
print("obstacle_transition=true")
print("unknown_hazard_retained=true")
print("hazard_transition=true")
print("potion_transition=true")
print("equipment_transition=true")
print("permanent_potion_masks=true")
print("aim_family_masks=true")
print("target_conditioned_ability_masks=true")
print("choice_descriptor_count=56")
print("choice_permutation_invariant=true")
print("choice_generation_exactly_once=true")
print("choice_duration_steps=2")
print("scripted_choice_excluded=true")
print("trajectory_v3=true")
