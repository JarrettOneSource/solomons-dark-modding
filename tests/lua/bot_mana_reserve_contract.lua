local root = assert(arg[1], "repository root argument is required")

local snapshots = {
  [42] = {
    mp = 10.0,
    max_mp = 100.0,
    mana_reserve_active = false,
  },
  [43] = {
    mp = 10.0,
    max_mp = 100.0,
    mana_reserve_active = true,
  },
}
local choices = {
  [42] = {
    pending = true,
    generation = 7,
    options = {{id = 16}},
  },
  [43] = {},
}
local chosen_participants = {}

sd = {
  bots = {
    get_participant_state = function(participant_id)
      return snapshots[participant_id]
    end,
    get_skill_choices = function(participant_id)
      return choices[participant_id]
    end,
    choose_skill = function(participant_id, option_index, generation)
      assert(option_index == 1)
      assert(generation == 7)
      chosen_participants[#chosen_participants + 1] = participant_id
      return true
    end,
  },
  waves = {
    get_state = function()
      return {wave = 3, phase = "active"}
    end,
  },
}

local chunk, load_error =
  loadfile(root .. "/mods/bot-brain/scripts/brain.lua")
assert(chunk, load_error)
local brain = chunk()

local function context(participant_id)
  return {
    participant_id = participant_id,
    bot = {},
    row = {element = "fire"},
    shared = {log = function() end},
    last_skill_choice_generation = -1,
    mana_sample_valid = false,
    mana_cast_hold = false,
    debug = {
      wave = 0,
      last_error = "",
      skill_choices_accepted = 0,
      mana_sample_valid = false,
      mana_cast_hold = false,
      mana_hold_start_count = 0,
      mana_hold_end_count = 0,
    },
  }
end

local pending_choice_bot = context(42)
local reserve_bot = context(43)

assert(brain.update_mana_cast_hold(pending_choice_bot))
assert(not pending_choice_bot.mana_cast_hold)
assert(brain.update_mana_cast_hold(reserve_bot))
assert(reserve_bot.mana_cast_hold)
assert(reserve_bot.debug.mana_hold_start_count == 1)

assert(brain.poll_skill_choice(pending_choice_bot))
assert(not brain.poll_skill_choice(reserve_bot))
assert(#chosen_participants == 1)
assert(chosen_participants[1] == 42)
assert(pending_choice_bot.debug.skill_choices_accepted == 1)
assert(reserve_bot.debug.skill_choices_accepted == 0)
assert(reserve_bot.mana_cast_hold)

snapshots[43].mp = 80.0
snapshots[43].mana_reserve_active = false
assert(brain.update_mana_cast_hold(reserve_bot))
assert(not reserve_bot.mana_cast_hold)
assert(reserve_bot.debug.mana_hold_end_count == 1)

snapshots[42].mana_reserve_active = true
assert(brain.update_mana_cast_hold(pending_choice_bot))
assert(pending_choice_bot.mana_cast_hold)

local local_mp = 10.0
local local_context = context(1)
local_context.local_player = true
local_context.bot = {
  mp = function()
    return local_mp
  end,
  max_mp = function()
    return 100.0
  end,
}
assert(brain.update_mana_cast_hold(local_context))
assert(local_context.mana_cast_hold)
local_mp = 80.0
assert(brain.update_mana_cast_hold(local_context))
assert(not local_context.mana_cast_hold)

print("participant_scoped_choices=true")
print("native_reserve_source=true")
print("exact_boundaries=true")
print("local_player_fallback=true")
