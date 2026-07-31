local root = assert(arg[1], "repository root argument is required")

local input_state = {
  active = false,
  clean = true,
  owner_mod_id = "",
  target_actor_address = 0,
  target_valid = false,
  pending_movement_frames = 0,
  pending_mouse_left_frames = 0,
  pending_scancode_count = 0,
}
local calls = {
  takeover = {},
  targets = {},
  movement = {},
  mouse = {},
  bindings = {},
  draws = {},
  choices = {},
  pickups = {},
}
local key_down = false
local spectator_active = false
local player_hp = 100.0
local offer_valid = false

local function copy_state()
  local result = {}
  for key, value in pairs(input_state) do
    result[key] = value
  end
  return result
end

sd = {
  world = {
    get_scene = function()
      return { kind = "run", name = "testrun" }
    end,
    get_run_enemy_by_network_id = function(network_actor_id)
      assert(network_actor_id == 77)
      return { actor_address = 9000 }
    end,
    list_actors = function()
      return {
        {
          actor_address = 9100,
          tracked_enemy = true,
          dead = false,
          hp = 50.0,
          x = 140.0,
          y = 20.0,
        },
        {
          actor_address = 9200,
          tracked_enemy = true,
          dead = false,
          hp = 50.0,
          x = 400.0,
          y = 400.0,
        },
      }
    end,
    request_loot_pickup = function(network_drop_id)
      calls.pickups[#calls.pickups + 1] = network_drop_id
      return true, 12
    end,
  },
  runtime = {
    get_multiplayer_state = function()
      return {
        participants = {
          {
            kind = "LocalHuman",
            controller_kind = "Native",
            participant_id = 11,
            runtime_valid = true,
            in_run = true,
            life_current = player_hp,
          },
        },
        death_spectator = { active = spectator_active },
        active_level_up_offer = {
          valid = offer_valid,
          selection_submitted = false,
          target_participant_id = 11,
          offer_id = 44,
          options = {
            { id = 16, option_id = 16 },
            { id = 64, option_id = 64 },
          },
        },
      }
    end,
    choose_level_up_option = function(request)
      calls.choices[#calls.choices + 1] = request
      return true
    end,
  },
  player = {
    get_state = function()
      return {
        actor_address = 8000,
        actor_slot = 0,
        x = 10.0,
        y = 20.0,
        hp = player_hp,
        max_hp = 100.0,
      }
    end,
  },
  bots = {
    get_loadout_details = function(participant_id)
      assert(participant_id == 11)
      return {
        primary = { entry_id = 16 },
      }
    end,
  },
  settings = {
    is_keybind_down = function(key)
      assert(key == "play_for_me_toggle")
      return key_down
    end,
  },
  input = {
    set_local_player_takeover = function(active)
      calls.takeover[#calls.takeover + 1] = active
      input_state.active = active
      input_state.clean = not active
      input_state.owner_mod_id = active and "bot.brain" or ""
      if not active then
        input_state.target_actor_address = 0
        input_state.target_valid = false
        input_state.pending_movement_frames = 0
        input_state.pending_mouse_left_frames = 0
        input_state.pending_scancode_count = 0
      end
      return true
    end,
    set_local_player_takeover_target = function(actor, x, y)
      assert(input_state.active)
      input_state.target_actor_address = actor
      input_state.target_valid = true
      calls.targets[#calls.targets + 1] = {
        actor = actor,
        x = x,
        y = y,
      }
      return true
    end,
    get_local_player_takeover_state = copy_state,
    hold_movement_frames = function(x, y, frames)
      input_state.pending_movement_frames = frames
      calls.movement[#calls.movement + 1] = {
        x = x,
        y = y,
        frames = frames,
      }
      return true
    end,
    hold_mouse_left_frames = function(frames)
      input_state.pending_mouse_left_frames = frames
      calls.mouse[#calls.mouse + 1] = frames
      return true
    end,
    press_binding = function(binding)
      input_state.pending_scancode_count = 1
      calls.bindings[#calls.bindings + 1] = binding
      return true
    end,
  },
  draw = {
    get_viewport = function()
      return { width = 1280, height = 720 }
    end,
    rect = function(...)
      calls.draws[#calls.draws + 1] = { kind = "rect", ... }
      return true
    end,
    text = function(text, ...)
      calls.draws[#calls.draws + 1] = {
        kind = "text",
        text = text,
        ...,
      }
      return true
    end,
  },
}

local chunk, load_error = loadfile(
  root .. "/mods/bot-brain/scripts/local_player.lua")
assert(chunk, load_error)
local local_player = chunk()

local brain = {
  profiles = {
    skirmisher = true,
    guardian = true,
    striker = true,
    learned = true,
  },
}
local think_count = 0
function brain.new(row)
  return {
    row = row,
    participant_id = 0,
    bot = nil,
    debug = {
      active = false,
      mode = "waiting",
      element = row.element,
    },
  }
end
function brain.think(context)
  think_count = think_count + 1
  context.debug.active = true
  context.debug.mode = "kite"
  if think_count == 1 then
    assert(context.bot:move_to(110.0, 20.0))
    assert(context.bot:cast(
      0,
      120.0,
      20.0,
      80,
      { network_actor_id = 77, x = 120.0, y = 20.0 }))
  end
end
function brain.reset_run(context, started)
  context.debug.mode = started and "prewave" or "hub"
end

local controller = local_player.new(
  brain,
  {},
  {},
  true,
  "skirmisher")
local event = {
  tick_interval_ms = 10,
  tick_count = 1,
}
controller:tick(0, event)
assert(controller.active)
assert(controller.participant_id == 11)
assert(controller.element == "fire")
assert(#calls.takeover == 1 and calls.takeover[1] == true)
assert(#calls.targets == 1)
assert(calls.targets[1].actor == 9000)
assert(#calls.mouse == 1 and calls.mouse[1] == 3)
assert(#calls.movement == 1)
assert(calls.movement[1].frames == 1)
assert(math.abs(calls.movement[1].x - 1.0) < 0.000001)
assert(#calls.draws == 3)
assert(calls.draws[3].text == "BOT PLAYING  [F9]")

controller:set_desired(false, "contract toggle")
assert(not controller.active)
assert(controller.debug.release_clean)
assert(controller.debug.release_count == 1)
assert(controller.destination_x == nil)
assert(input_state.clean)
assert(input_state.pending_movement_frames == 0)
assert(input_state.pending_mouse_left_frames == 0)
assert(input_state.pending_scancode_count == 0)
assert(input_state.target_actor_address == 0)

controller:set_desired(true)
event.tick_count = 2
controller:tick(10, event)
assert(controller.active)
assert(controller.debug.activation_count == 2)

offer_valid = true
controller:update_runtime_state()
local choices = controller.context.read_skill_choices()
assert(choices.pending)
assert(choices.generation == 44)
assert(#choices.options == 2)
assert(controller.context.choose_skill(
  controller.context,
  2,
  choices.generation,
  choices.options[2]))
assert(#calls.choices == 1)
assert(calls.choices[1].offer_id == 44)
assert(calls.choices[1].option_index == 2)
assert(calls.choices[1].option_id == 64)
assert(controller.context.request_loot_pickup(
  controller.context,
  700))
assert(calls.pickups[1] == 700)

assert(controller.handle:cast(
  2,
  120.0,
  20.0,
  80,
  { network_actor_id = 77 }))
assert(calls.bindings[#calls.bindings] == "belt_slot_2")
assert(controller.handle:cast(
  0,
  140.0,
  20.0,
  80,
  { network_actor_id = 0, x = 140.0, y = 20.0 }))
assert(calls.targets[#calls.targets].actor == 9100)

spectator_active = true
event.tick_count = 3
controller:tick(20, event)
assert(not controller.active)
assert(controller.debug.release_clean)
spectator_active = false
event.tick_count = 4
controller:tick(30, event)
assert(controller.active)
assert(controller.debug.activation_count == 3)

key_down = true
event.tick_count = 5
controller:tick(40, event)
assert(not controller.desired)
assert(not controller.active)
assert(controller.debug.release_clean)
key_down = false
event.tick_count = 6
controller:tick(50, event)
assert(not controller.active)

controller:set_behavior("guardian")
assert(controller.behavior == "guardian")
assert(controller.context.row.behavior == "guardian")
controller:set_desired(true)
event.tick_count = 7
controller:tick(60, event)
assert(controller.active)
controller:reset_run(false)
assert(not controller.active)
assert(controller.debug.release_clean)

print("takeover_path=true")
print("movement_path=true")
print("primary_path=true")
print("secondary_path=true")
print("indicator_path=true")
print("skill_choice_path=true")
print("loot_path=true")
print("death_respawn_path=true")
print("clean_release=true")
print("shared_brain_thinks=" .. tostring(think_count))
