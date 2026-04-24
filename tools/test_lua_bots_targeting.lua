#!/usr/bin/env lua

local current_actors = {}

_G.lua_bots_enable_test_hooks = true
_G.sd = {
  events = {
    on = function()
    end,
  },
  world = {
    list_actors = function()
      return current_actors
    end,
  },
  bots = {},
}

dofile("mods/lua_bots/scripts/main.lua")

local hooks = rawget(_G, "lua_bots_test_hooks")
assert(type(hooks) == "table", "lua_bots_test_hooks was not published")
assert(type(hooks.find_nearest_enemy) == "function", "find_nearest_enemy hook missing")

local bot = {
  actor_address = 100,
  x = 0.0,
  y = 0.0,
}

local stale_npc = {
  actor_address = 200,
  object_type_id = 5009,
  tracked_enemy = false,
  dead = false,
  hp = 100.0,
  max_hp = 100.0,
  x = 5.0,
  y = 0.0,
}

local enemy_a = {
  actor_address = 300,
  object_type_id = 5010,
  tracked_enemy = true,
  dead = false,
  hp = 100.0,
  max_hp = 100.0,
  x = 300.0,
  y = 0.0,
}

local enemy_b = {
  actor_address = 400,
  object_type_id = 5010,
  tracked_enemy = true,
  dead = false,
  hp = 100.0,
  max_hp = 100.0,
  x = 120.0,
  y = 0.0,
}

current_actors = {
  {
    actor_address = bot.actor_address,
    object_type_id = 5010,
    tracked_enemy = true,
    dead = false,
    hp = 100.0,
    max_hp = 100.0,
    x = bot.x,
    y = bot.y,
  },
  stale_npc,
  enemy_a,
  enemy_b,
}

local nearest, gap = hooks.find_nearest_enemy(bot)
assert(nearest == enemy_b, "nearest enemy should be enemy_b initially")
assert(math.abs(gap - 120.0) < 0.001, "initial nearest gap mismatch")

enemy_a.x = 40.0
nearest, gap = hooks.find_nearest_enemy(bot)
assert(nearest == enemy_a, "nearest enemy should switch to enemy_a after it moves closer")
assert(math.abs(gap - 40.0) < 0.001, "switched nearest gap mismatch")

enemy_a.dead = true
nearest, gap = hooks.find_nearest_enemy(bot)
assert(nearest == enemy_b, "dead closer enemy should be ignored")
assert(math.abs(gap - 120.0) < 0.001, "post-death nearest gap mismatch")

enemy_b.hp = 0.0
nearest, gap = hooks.find_nearest_enemy(bot)
assert(nearest == nil, "zero-hp enemy should be ignored")
assert(gap == nil, "gap should be nil when no target exists")

print("lua_bots_targeting_ok=true")
