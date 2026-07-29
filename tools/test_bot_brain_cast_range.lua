#!/usr/bin/env lua

local active_enemy = nil
local attack_range = 205.0
local moves = {}
local casts = {}

_G.sd = {
  bots = {
    get_primary_attack_window = function()
      return {
        min_range = 0.0,
        max_range = attack_range,
        native_backed = true,
        source = "native_frost_jet_query_range",
      }
    end,
    get_skill_choices = function()
      return {pending = false, generation = 0, options = {}}
    end,
    choose_skill = function()
      return true
    end,
  },
  nav = {
    get_grid = function()
      return nil
    end,
    test_segment = function()
      return true
    end,
  },
  runtime = {
    get_multiplayer_state = function()
      return {participants = {}}
    end,
  },
  waves = {
    get_state = function()
      return {wave = 2, phase = "spawning"}
    end,
  },
  world = {
    get_scene = function()
      return {name = "testrun", kind = "run"}
    end,
    get_replicated_actors = function()
      return {actors = active_enemy and {active_enemy} or {}}
    end,
  },
}

local steering = dofile("mods/bot-brain/scripts/steering.lua")
local brain = dofile("mods/bot-brain/scripts/brain.lua")

local shared = {
  spawn_retry_ms = 1000,
  nav_refresh_ms = 1000,
  attack_window_refresh_ms = 100,
  approach_move_interval_ms = 100,
  kite_move_interval_ms = 100,
  orbit_move_interval_ms = 100,
  flee_move_interval_ms = 100,
  threat_radius = 340.0,
  flee_threat_radius = 900.0,
  normal_lookahead = 120.0,
  flee_lookahead = 180.0,
  offense_enabled = true,
  cast_hold_ms = 80,
  log = function() end,
}

local function new_context(hp)
  local bot = {
    position = function()
      return 0.0, 0.0
    end,
    hp = function()
      return hp or 100.0
    end,
    max_hp = function()
      return 100.0
    end,
    alive = function()
      return true
    end,
    move_to = function(_, x, y)
      table.insert(moves, {x = x, y = y})
      return true
    end,
    cast = function(_, slot, x, y, hold_ms)
      table.insert(casts, {
        slot = slot,
        x = x,
        y = y,
        hold_ms = hold_ms,
      })
      return true
    end,
  }
  local context = brain.new({
    name = "Brook",
    element = "water",
    behavior = "skirmisher",
    discipline = "arcane",
  }, 1, shared, steering)
  context.bot = bot
  context.participant_id = 1001
  return context
end

local function enemy_at(distance, radius)
  return {
    tracked_enemy = true,
    dead = false,
    network_actor_id = 2001,
    x = distance,
    y = 0.0,
    radius = radius or 0.0,
    hp = 10.0,
    max_hp = 10.0,
  }
end

local function reset_observations()
  moves = {}
  casts = {}
end

-- The owner-condition regression: the enemy is already inside the broader
-- kite threat radius but remains outside Frost Jet's native query range.
-- Threat detection must not prevent the existing approach path.
reset_observations()
active_enemy = enemy_at(250.0, 0.0)
local outside = new_context()
brain.think(outside, 1000, true)
assert(outside.debug.threat_count == 1, "outside-range enemy should be a kite threat")
assert(outside.debug.mode == "approach", "outside-range threat must use existing approach movement")
assert(#moves == 1 and moves[1].x > 0.0,
  "outside-range bot did not move toward its target")
assert(#casts == 0, "outside-range bot cast before reaching native range")

-- Native query range is center-to-center. An enemy radius must not turn an
-- out-of-range center into an eligible cast.
reset_observations()
active_enemy = enemy_at(220.0, 30.0)
local radius_edge = new_context()
brain.think(radius_edge, 1000, true)
assert(radius_edge.debug.mode == "approach", "enemy radius incorrectly bypassed native cast range")
assert(#casts == 0, "bot cast with target center outside native spell range")

-- Once the target center is inside the native range, preserve normal kite
-- steering and the existing cast cadence.
reset_observations()
active_enemy = enemy_at(190.0, 30.0)
local inside = new_context()
brain.think(inside, 1000, true)
assert(inside.debug.mode == "kite", "in-range bot should preserve kite behavior")
assert(#casts == 1, "in-range bot did not cast")
assert(inside.debug.target_distance <= attack_range, "cast target exceeded native spell range")

-- Existing flee behavior remains dominant even when the enemy is outside the
-- spell window.
reset_observations()
active_enemy = enemy_at(250.0, 0.0)
local fleeing = new_context(20.0)
brain.think(fleeing, 1000, true)
assert(fleeing.debug.mode == "flee", "low-HP flee behavior was replaced by approach")
assert(#casts == 0, "fleeing bot cast")

print("bot brain cast-range behavior: ok")
