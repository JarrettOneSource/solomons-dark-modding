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
local descriptor_module =
  load_module(
    "mods/bot-brain/scripts/policy_spell_descriptors.lua")
local observation =
  load_module(
    "mods/bot-brain/scripts/policy_observation.lua")
local training =
  load_module("mods/bot-brain/scripts/policy_training.lua")
local steering =
  load_module("mods/bot-brain/scripts/steering.lua")

assert(#spec.observation_names == 395)
assert(spec.observation_names[1] == "self_hp_ratio")
assert(spec.observation_names[309] == "pickup_count_scaled")
assert(spec.observation_names[310] == "ally_1_present")
assert(spec.observation_names[350] == "ally_count_scaled")
assert(spec.observation_names[351] == "enemy_count_scaled")
assert(
  spec.observation_names[395] ==
    "secondary_recharge_multiplier_scaled")

local far_guardian_step =
  steering.constrain_to_guardian_leash(
    3500.0,
    0.0,
    {x = 3360.0, y = 0.0},
    {x = 0.0, y = 0.0},
    260.0)
assert(
  far_guardian_step.x == 3360.0 and
    far_guardian_step.y == 0.0,
  "an out-of-leash guardian must keep a short step toward its ward")

local function ready_grid(refresh_pending)
  local subdivisions = spec.nav_subdivisions
  local grid = {
    width = 12,
    height = 12,
    cell_width = 100.0,
    cell_height = 100.0,
    subdivisions = subdivisions,
    requested_subdivisions = subdivisions,
    refresh_pending = refresh_pending,
    cells = {},
  }
  if refresh_pending then
    return grid
  end
  for grid_x = 0, grid.width - 1 do
    for grid_y = 0, grid.height - 1 do
      local cell = {
        grid_x = grid_x,
        grid_y = grid_y,
        center_x = (grid_y + 0.5) * grid.cell_width,
        center_y = (grid_x + 0.5) * grid.cell_height,
        traversable = true,
        path_traversable = true,
        samples = {},
      }
      for sample_x = 0, subdivisions - 1 do
        for sample_y = 0, subdivisions - 1 do
          cell.samples[#cell.samples + 1] = {
            sample_x = sample_x,
            sample_y = sample_y,
            world_x =
              grid_y * grid.cell_width +
              ((sample_y + 0.5) / subdivisions) *
                grid.cell_width,
            world_y =
              grid_x * grid.cell_height +
              ((sample_x + 0.5) / subdivisions) *
                grid.cell_height,
            traversable = true,
          }
        end
      end
      grid.cells[#grid.cells + 1] = cell
    end
  end
  return grid
end

local grid_calls = 0
local geometry = geometry_module.new(
  spec,
  function()
    grid_calls = grid_calls + 1
    return ready_grid(grid_calls == 1)
  end)

local details = {
  primary = {
    entry_id = 8,
    combo_entry_id = -1,
    build_id = 8,
    build_id_resolved = true,
    mana_cost = 10.0,
    mana_cost_resolved = true,
    mana_charge_kind = "per_cast",
    range_min = 0.0,
    range_max = 200.0,
    range_resolved = true,
    range_source = "fixture",
  },
  secondaries = {
    {
      slot = 1,
      entry_id = 15,
      mana_cost = 20.0,
      mana_cost_resolved = true,
      cooldown_seconds = 1.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = true,
    },
    {
      slot = 2,
      entry_id = 9001,
      mana_cost = 0.0,
      mana_cost_resolved = false,
      cooldown_seconds = 0.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = false,
    },
    {
      slot = 3,
      entry_id = 24,
      mana_cost = 200.0,
      mana_cost_resolved = true,
      cooldown_seconds = 0.0,
      cooldown_remaining_seconds = 0.0,
      cooldown_resolved = false,
    },
  },
  pending_weld_build_id = 1000,
  pending_weld_build_id_resolved = true,
}
for slot = 4, spec.secondary_slot_count do
  details.secondaries[slot] = {
    slot = slot,
    entry_id = -1,
    mana_cost = 0.0,
    mana_cost_resolved = false,
    cooldown_seconds = 0.0,
    cooldown_remaining_seconds = 0.0,
    cooldown_resolved = false,
  }
end

local descriptor_resolver = descriptor_module.new(
  spec,
  {
    read_details = function()
      return details
    end,
    read_choices = function()
      return {}
    end,
    list_spells = function()
      return {
        {
          id = 9001,
          slot = "secondary",
          cfg = {
            name = "Fixture Bolt",
            mana_cost = 30.0,
            range = 250.0,
            cooldown_ms = 2000,
          },
        },
      }
    end,
  })

local snapshot = {
  hp = 100.0,
  max_hp = 100.0,
  mp = 80.0,
  max_mp = 100.0,
  moving = true,
  cast_active = false,
  cast_pending = false,
  cast_ready = true,
  native_poison_remaining_ticks = 0,
  replicated_poison_remaining_ticks = 0,
  native_webbed_remaining_ticks = 0,
  native_damage_x4_remaining_ticks = 0,
  replicated_damage_x4_remaining_ticks = 0,
  native_persistent_status_flags = 0,
  native_transient_status_flags = 0,
}

local function self_participant()
  return {
    participant_id = 42,
    controller_kind = "LuaBrain",
    in_run = true,
    runtime_valid = true,
    x = 550.0,
    y = 550.0,
    life_current = 100.0,
    life_max = 100.0,
    mana_current = 80.0,
    mana_max = 100.0,
    move_speed = 350.0,
    level = 5,
    owned_progression = {
      ability_loadout = {
        primary_entry_index = 8,
        primary_combo_entry_index = -1,
        secondary_entry_indices =
          {15, 9001, 24, -1, -1, -1, -1, -1},
      },
      progression_book_entries = {
        {entry_index = 8, active = 1},
        {entry_index = 16, active = 1},
        {entry_index = 52, active = 1},
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
end

snapshot.cast_ready = false
local custom_cooldown_fallback = descriptor_resolver:capture(
  42,
  snapshot,
  self_participant(),
  {})
assert(
  custom_cooldown_fallback.secondaries[2].cooldown_seconds ==
    2.0)
assert(
  custom_cooldown_fallback.secondaries[2].cooldown_resolved ==
    false)
assert(custom_cooldown_fallback.secondaries[2].ready == false)
snapshot.cast_ready = true

local participants = {
  self_participant(),
  {
    participant_id = 1,
    controller_kind = "Native",
    is_owner = true,
    in_run = true,
    x = 560.0,
    y = 550.0,
    life_current = 90.0,
    life_max = 100.0,
    mana_current = 40.0,
    mana_max = 80.0,
    movement_intent_x = 3.0,
    movement_intent_y = 4.0,
  },
  {
    participant_id = 2,
    controller_kind = "LuaBrain",
    in_run = true,
    x = 570.0,
    y = 550.0,
    life_current = 0.0,
    life_max = 100.0,
    mana_current = 0.0,
    mana_max = 100.0,
    movement_intent_x = 0.0,
    movement_intent_y = 0.0,
  },
  {
    participant_id = 3,
    controller_kind = "LuaBrain",
    in_run = true,
    x = 580.0,
    y = 550.0,
    life_current = 100.0,
    life_max = 100.0,
    mana_current = 100.0,
    mana_max = 100.0,
  },
  {
    participant_id = 4,
    controller_kind = "LuaBrain",
    in_run = true,
    x = 590.0,
    y = 550.0,
    life_current = 100.0,
    life_max = 100.0,
    mana_current = 100.0,
    mana_max = 100.0,
  },
  {
    participant_id = 5,
    controller_kind = "LuaBrain",
    in_run = true,
    x = 600.0,
    y = 550.0,
    life_current = 100.0,
    life_max = 100.0,
    mana_current = 100.0,
    mana_max = 100.0,
  },
}

local loot = {
  authority_participant_id = 1,
  drops = {
    {
      network_drop_id = 11,
      kind = "Orb",
      resource_kind = 0,
      active = true,
      x = 560.0,
      y = 550.0,
    },
    {
      network_drop_id = 12,
      kind = "Orb",
      resource_kind = 1,
      active = true,
      x = 570.0,
      y = 550.0,
    },
    {
      network_drop_id = 13,
      kind = "Gold",
      active = true,
      x = 580.0,
      y = 550.0,
    },
    {
      network_drop_id = 14,
      kind = "Item",
      active = true,
      x = 590.0,
      y = 550.0,
    },
    {
      network_drop_id = 15,
      kind = "Potion",
      active = true,
      x = 600.0,
      y = 550.0,
    },
  },
}

local segment_calls = 0
local builder = observation.new(
  spec,
  {
    geometry = geometry,
    spell_descriptors = descriptor_resolver,
    get_snapshot = function()
      return snapshot
    end,
    get_multiplayer_state = function()
      return {participants = participants}
    end,
    get_loot = function()
      return loot
    end,
    test_segment = function(_, _, to_x)
      segment_calls = segment_calls + 1
      return to_x >= 500.0
    end,
  })

local context = {
  participant_id = 42,
  row = {
    element = "fire",
    discipline = "arcane",
  },
  policy_memory = observation.new_memory(),
}
local enemies = {
  {
    network_actor_id = 101,
    x = 650.0,
    y = 550.0,
    radius = 10.0,
    hp = 100.0,
    max_hp = 100.0,
  },
  {
    network_actor_id = 102,
    x = 850.0,
    y = 550.0,
    radius = 10.0,
    hp = 80.0,
    max_hp = 100.0,
  },
}

local function frame(now_ms)
  return {
    now_ms = now_ms,
    simulation_tick = now_ms / 10,
    bot_x = 550.0,
    bot_y = 550.0,
    hp = 100.0,
    max_hp = 100.0,
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
      options = {{id = 52}, {id = 64}},
    },
  }
end

local pending_capture =
  observation.capture(builder, context, frame(0))
assert(geometry:status().ready == false)
assert(geometry:status().pending_count == 1)
assert(#pending_capture.values == 395)

local capture =
  observation.capture(builder, context, frame(500))
assert(geometry:status().ready == true)
assert(geometry:status().adoption_count == 1)
assert(geometry:status().grid_build_count == 1)
assert(grid_calls == 2)
assert(#capture.values == #spec.observation_names)
for index, value in ipairs(capture.values) do
  assert(
    type(value) == "number" and value == value and
      value > -math.huge and value < math.huge,
    "non-finite observation " ..
      tostring(spec.observation_names[index]))
end
assert(capture.target_mask[1] == false)
assert(capture.target_mask[2] == true)
assert(capture.target_mask[3] == true)
assert(
  capture.values[
    builder.indexes.pickup_1_type_health_orb] == 1.0)
assert(
  capture.values[
    builder.indexes.pickup_2_type_mana_orb] == 1.0)
assert(
  capture.values[builder.indexes.pickup_count_scaled] ==
    5.0 / spec.pickup_count_scale)
assert(#capture.allies == 5)
assert(capture.allies[2].alive == false)
assert(
  math.abs(
    capture.values[builder.indexes.ally_1_intent_dx] -
      0.6) < 0.000001)
assert(
  math.abs(
    capture.values[builder.indexes.ally_1_intent_dy] -
      0.8) < 0.000001)
assert(
  capture.values[builder.indexes.ally_count_scaled] ==
    5.0 / spec.ally_count_scale)
assert(
  capture.values[builder.indexes.weld_offer_pending] ==
    1.0)

local far_target = observation.select_target(
  builder,
  context,
  capture,
  2)
assert(far_target.network_actor_id == 102)
local far_cast_mask =
  observation.build_cast_mask(
    builder,
    capture,
    far_target)
assert(far_cast_mask[1] == true)
assert(far_cast_mask[2] == false)
assert(far_cast_mask[3] == true)
assert(far_cast_mask[4] == false)
assert(far_cast_mask[5] == false)

enemies = {
  {
    network_actor_id = 101,
    x = 900.0,
    y = 550.0,
    radius = 10.0,
    hp = 95.0,
    max_hp = 100.0,
  },
  {
    network_actor_id = 102,
    x = 625.0,
    y = 550.0,
    radius = 10.0,
    hp = 70.0,
    max_hp = 100.0,
  },
}
local persisted =
  observation.capture(builder, context, frame(600))
assert(grid_calls == 2)
assert(geometry:status().grid_build_count == 1)
assert(
  persisted.current_target.network_actor_id == 102)
assert(
  persisted.enemy_slots[1].network_actor_id == 102)
assert(persisted.target_mask[1] == true)
assert(
  persisted.values[
    builder.indexes.enemy_1_is_current_target] == 1.0)
assert(
  persisted.values[
    builder.indexes.enemy_1_velocity_dx] == -1.0)
local kept = observation.select_target(
  builder,
  context,
  persisted,
  0)
local near_cast_mask =
  observation.build_cast_mask(
    builder,
    persisted,
    kept)
assert(near_cast_mask[2] == true)
assert(near_cast_mask[3] == true)
assert(near_cast_mask[4] == true)
assert(near_cast_mask[5] == false)

participants = {
  self_participant(),
  participants[2],
}
local ally_transition =
  observation.capture(builder, context, frame(700))
assert(grid_calls == 2)
assert(#ally_transition.allies == 1)
assert(
  ally_transition.values[
    builder.indexes.ally_count_scaled] ==
      1.0 / spec.ally_count_scale)
assert(
  ally_transition.values[
    builder.indexes.ally_2_present] == 0.0)
assert(segment_calls == 8 * 4)

details.primary.combo_entry_id = 16
details.primary.build_id = 1000
local welded_capture =
  observation.capture(builder, context, frame(800))
assert(
  welded_capture.values[
    builder.indexes.primary_welded] == 1.0)
assert(
  welded_capture.values[
    builder.indexes.primary_element_ether] == 1.0)
assert(
  welded_capture.values[
    builder.indexes.primary_element_fire] == 1.0)
assert(
  welded_capture.values[
    builder.indexes.primary_element_water] == 0.0)
details.primary.combo_entry_id = -1
details.primary.build_id = 8

local pickup_requests = 0
local pickup_request_participant_id = 0
local chosen_options = {}
local mana_current = 100.0
local mana_maximum = 100.0
_G.sd = {
  runtime = {
    get_multiplayer_state = function()
      return {participants = participants}
    end,
  },
  bots = {
    get_loadout_details = function()
      return details
    end,
    choose_skill = function(_, option_index)
      chosen_options[#chosen_options + 1] = option_index
      return true
    end,
    get_participant_state = function(participant_id)
      assert(participant_id == 42)
      return {
        mp = mana_current,
        max_mp = mana_maximum,
      }
    end,
  },
  world = {
    request_loot_pickup = function(_, participant_id)
      pickup_requests = pickup_requests + 1
      pickup_request_participant_id = participant_id
      return true, pickup_requests
    end,
  },
}
local brain =
  load_module("mods/bot-brain/scripts/brain.lua")
local brain_logs = {}
local assist_context = {
  participant_id = 42,
  row = {element = "fire"},
  shared = {
    policy_spell_descriptors = descriptor_resolver,
    policy_spec = spec,
    log = function(_, message)
      brain_logs[#brain_logs + 1] = message
    end,
  },
  policy_memory = observation.new_memory(),
  last_skill_choice_generation = -1,
  debug = {
    last_error = "",
    wave = 7,
    skill_choices_accepted = 0,
    mana_sample_valid = false,
    mana_cast_hold = false,
    mana_hold_start_count = 0,
    mana_hold_end_count = 0,
    pickup_request_issued = 0,
    pickup_request_accepted = 0,
    last_pickup_request_sequence = 0,
    last_pickup_error = "",
  },
}
local original_random = math.random
local random_indexes = {2, 1}
math.random = function(minimum, maximum)
  assert(minimum == 1 and maximum == 2)
  return table.remove(random_indexes, 1)
end
brain.choose_pending_skill(
  assist_context,
  {
    pending = true,
    generation = 10,
    options = {{id = 52}, {id = 64}},
  })
assert(chosen_options[1] == 2)
brain.choose_pending_skill(
  assist_context,
  {
    pending = true,
    generation = 11,
    options = {{id = 52}, {id = 64}},
  })
assert(chosen_options[2] == 1)
math.random = original_random
assert(string.find(brain_logs[1], "wave=7", 1, true))
assert(string.find(brain_logs[1], "offered=[52,64]", 1, true))
assert(string.find(brain_logs[1], "chosen_id=64", 1, true))

assist_context.bot = {}
assist_context.mana_sample_valid = false
assist_context.mana_cast_hold = false
mana_current = 9.0
assert(brain.update_mana_cast_hold(assist_context))
assert(assist_context.mana_cast_hold)
assert(assist_context.debug.mana_hold_start_count == 1)
mana_current = 50.0
assert(brain.update_mana_cast_hold(assist_context))
assert(assist_context.mana_cast_hold)
assert(assist_context.debug.mana_hold_end_count == 0)
mana_current = 80.0
assert(brain.update_mana_cast_hold(assist_context))
assert(not assist_context.mana_cast_hold)
assert(assist_context.debug.mana_hold_end_count == 1)
assert(brain.cast_mana_hold_low_ratio == 0.10)
assert(brain.cast_mana_resume_high_ratio == 0.80)

brain.request_nearby_pickup(
  assist_context,
  capture,
  1000)
brain.request_nearby_pickup(
  assist_context,
  capture,
  1100)
assert(pickup_requests == 1)
assert(pickup_request_participant_id == 42)
capture.pickups = {}
brain.request_nearby_pickup(
  assist_context,
  capture,
  1600)
assert(pickup_requests == 1)

loot = {
  authority_participant_id = 1,
  drops = {},
}
local pickup_removed =
  observation.capture(builder, context, frame(1700))
assert(
  pickup_removed.values[
    builder.indexes.pickup_1_present] == 0.0)
assert(
  pickup_removed.values[
    builder.indexes.pickup_count_scaled] == 0.0)

local fake_runtime = {
  seed = 0,
  generation = 1,
}
function fake_runtime:set_seed(seed)
  self.seed = seed
end
function fake_runtime:status()
  return {
    available = true,
    generation = self.generation,
  }
end
function fake_runtime:load()
  self.generation = self.generation + 1
  return self.generation
end

local controller = training.new(spec, fake_runtime)
local training_context = {participant_id = 42}
local decision = {
  movement_action = 1,
  target_action = 2,
  cast_action = 1,
  log_probability = -0.75,
  value = 0.25,
}
capture.values = persisted.values
capture.movement_mask = persisted.movement_mask
capture.target_mask = persisted.target_mask
capture.cast_mask = near_cast_mask
capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 1.0,
  wave = 1,
  alive = true,
  enemy_count = 1,
  enemy_health = {[102] = 1.0},
}
controller:enable({seed = 123, capacity = 128})
controller:record(training_context, capture, decision, 10)
capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.9,
  wave = 1,
  alive = true,
  enemy_count = 1,
  enemy_health = {[102] = 0.8},
}
controller:record(training_context, capture, decision, 20)
capture.metrics = {
  hp_ratio = 1.0,
  mana_ratio = 0.8,
  wave = 2,
  alive = true,
  enemy_count = 0,
  enemy_health = {},
}
controller:record(training_context, capture, decision, 30)
local drained = controller:drain(2)
assert(#drained.records == 2)
assert(drained.records[1].trajectory_version == 2)
assert(#drained.records[1].observation == 395)
assert(#drained.records[1].target_mask == 9)
assert(drained.records[1].target_action == 2)
assert(#drained.records[1].cast_mask == 10)
assert(drained.records[1].reward > 0.0)
assert(
  drained.records[2].reward >
    drained.records[1].reward)
capture.metrics.hp_ratio = 0.0
capture.metrics.alive = false
controller:terminal(training_context, capture.metrics)
local terminal = controller:drain(1)
assert(#terminal.records == 1)
assert(terminal.records[1].done == true)
assert(terminal.records[1].reward < -3.0)

print("observation_count=395")
print("exact_order=true")
print("finite=true")
print("target_conditioned_masks=true")
print("actor_id_persistence=true")
print("ally_transition=true")
print("weld_transition=true")
print("pickup_transition=true")
print("guardian_far_return=true")
print("nav_grid_builds=" ..
  tostring(geometry:status().grid_build_count))
print("trajectory_v2=true")
