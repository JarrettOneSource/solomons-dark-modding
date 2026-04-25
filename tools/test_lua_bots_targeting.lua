#!/usr/bin/env lua

local current_actors = {}
local casts = {}
local faces = {}
local face_targets = {}

_G.lua_bots_enable_test_hooks = true
_G.sd = {
  events = {
    on = function()
    end,
  },
  world = {
    get_state = function()
      return { wave = 1 }
    end,
    list_actors = function()
      return current_actors
    end,
  },
  gameplay = {
    get_combat_state = function()
      return { active = true }
    end,
  },
  bots = {
    cast = function(request)
      table.insert(casts, request)
      return true
    end,
    face = function(bot_id, heading)
      table.insert(faces, { id = bot_id, heading = heading })
      return true
    end,
    face_target = function(bot_id, actor_address, fallback_heading)
      table.insert(face_targets, {
        id = bot_id,
        actor_address = actor_address,
        fallback_heading = fallback_heading,
      })
      return true
    end,
  },
}

dofile("mods/lua_bots/scripts/main.lua")

local hooks = rawget(_G, "lua_bots_test_hooks")
assert(type(hooks) == "table", "lua_bots_test_hooks was not published")
assert(type(hooks.find_nearest_enemy) == "function", "find_nearest_enemy hook missing")
assert(type(hooks.issue_auto_attack) == "function", "issue_auto_attack hook missing")

local bot = {
  available = true,
  actor_address = 100,
  transform_valid = true,
  cast_ready = false,
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
  object_type_id = 1001,
  tracked_enemy = true,
  dead = false,
  hp = 100.0,
  max_hp = 100.0,
  x = 300.0,
  y = 0.0,
}

local enemy_b = {
  actor_address = 400,
  object_type_id = 1001,
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
    object_type_id = 1001,
    tracked_enemy = true,
    dead = false,
    hp = 100.0,
    max_hp = 100.0,
    x = bot.x,
    y = bot.y,
  },
  stale_npc,
  {
    actor_address = 250,
    object_type_id = 5010,
    tracked_enemy = true,
    dead = false,
    hp = 100.0,
    max_hp = 100.0,
    x = 10.0,
    y = 0.0,
  },
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

enemy_a.dead = false
enemy_a.hp = 100.0
enemy_a.x = 40.0
enemy_b.hp = 100.0
hooks.state.bot_id = 42

local attack_scene = { name = "testrun" }
local attack_ok = hooks.issue_auto_attack(1000, attack_scene, bot, nil)
assert(attack_ok == false, "cast_ready=false should not queue a cast")
assert(#casts == 0, "cast_ready=false queued a cast")
assert(#face_targets == 1, "bot should still face the current attack target while cast is not ready")
assert(face_targets[1].actor_address == enemy_a.actor_address, "not-ready facing should track closest enemy")

bot.cast_ready = true
attack_ok = hooks.issue_auto_attack(1100, attack_scene, bot, nil)
assert(attack_ok == true, "cast_ready=true should queue a cast")
assert(#casts == 1, "cast_ready=true did not queue exactly one cast")
assert(casts[1].target_actor_address == enemy_a.actor_address, "cast should target current closest enemy")

enemy_b.x = 20.0
bot.cast_ready = true
attack_ok = hooks.issue_auto_attack(1200, attack_scene, bot, nil)
assert(attack_ok == true, "closest-target retarget should not wait on a local cooldown")
assert(#casts == 2, "second ready attack should queue another cast")
assert(casts[2].target_actor_address == enemy_b.actor_address, "cast should switch to newly closest enemy")

print("lua_bots_targeting_ok=true")
