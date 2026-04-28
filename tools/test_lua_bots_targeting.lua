#!/usr/bin/env lua

local current_actors = {}
local casts = {}
local faces = {}
local face_targets = {}
local creates = {}
local updates = {}
local event_handlers = {}
local bot_store = {}
local next_bot_id = 1000
local current_scene = {
  name = "hub",
  kind = "hub",
  world_id = 0x1000,
  transitioning = false,
}
local current_player = {
  x = 100.0,
  y = 100.0,
  heading = 180.0,
}

_G.lua_bots_enable_test_hooks = true
_G.sd = {
  events = {
    on = function(name, callback)
      event_handlers[name] = callback
    end,
  },
  world = {
    get_scene = function()
      return current_scene
    end,
    get_state = function()
      return { wave = 1 }
    end,
    list_actors = function()
      return current_actors
    end,
  },
  player = {
    get_state = function()
      return current_player
    end,
  },
  debug = {
    get_nav_grid = function()
      return {
        valid = true,
        world_id = current_scene.world_id,
        width = 4,
        height = 4,
        cells = {
          {
            grid_x = 1,
            grid_y = 1,
            traversable = true,
            samples = {
              { world_x = 150.0, world_y = 40.0, traversable = true },
              { world_x = 150.0, world_y = 80.0, traversable = true },
              { world_x = 150.0, world_y = 120.0, traversable = true },
              { world_x = 150.0, world_y = 160.0, traversable = true },
              { world_x = 150.0, world_y = 200.0, traversable = true },
              { world_x = 150.0, world_y = 240.0, traversable = true },
              { world_x = 150.0, world_y = 280.0, traversable = true },
              { world_x = 1006.0, world_y = 448.0, traversable = true },
              { world_x = 1006.0, world_y = 488.0, traversable = true },
              { world_x = 1006.0, world_y = 528.0, traversable = true },
              { world_x = 1006.0, world_y = 568.0, traversable = true },
            },
          },
        },
      }
    end,
  },
  gameplay = {
    get_combat_state = function()
      return { active = true }
    end,
  },
  bots = {
    create = function(request)
      next_bot_id = next_bot_id + 1
      local bot = {
        id = next_bot_id,
        name = request.name,
        available = true,
        actor_address = 0xABC000 + next_bot_id,
        transform_valid = true,
        hp = 100.0,
        max_hp = 100.0,
        cast_ready = true,
        scene = request.scene,
        x = request.position.x,
        y = request.position.y,
        moving = false,
        has_target = false,
      }
      bot_store[next_bot_id] = bot
      table.insert(creates, request)
      return next_bot_id
    end,
    get_state = function(bot_id)
      if bot_id ~= nil then
        return bot_store[bot_id]
      end
      local bots = {}
      for _, bot in pairs(bot_store) do
        table.insert(bots, bot)
      end
      table.sort(bots, function(a, b)
        return a.id < b.id
      end)
      return bots
    end,
    update = function(request)
      local bot = bot_store[request.id]
      if bot == nil then
        return false
      end
      bot.scene = request.scene
      bot.x = request.position.x
      bot.y = request.position.y
      table.insert(updates, request)
      return true
    end,
    destroy = function(bot_id)
      bot_store[bot_id] = nil
      return true
    end,
    move_to = function(bot_id, x, y)
      local bot = bot_store[bot_id]
      if bot == nil then
        return false
      end
      bot.target_x = x
      bot.target_y = y
      bot.moving = true
      bot.has_target = true
      return true
    end,
    stop = function(bot_id)
      local bot = bot_store[bot_id]
      if bot == nil then
        return false
      end
      bot.moving = false
      bot.has_target = false
      return true
    end,
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
assert(type(hooks.snap_target_to_nav) == "function", "snap_target_to_nav hook missing")
assert(type(hooks.state.bots) == "table", "managed bot contexts missing")
assert(#hooks.state.bots == 4, "lua_bots should manage one bot for each non-fire element")
assert(hooks.state.bots[1].bot_name == "Lua Bot Water", "first managed bot should be the water wizard")
assert(hooks.state.bots[2].bot_name == "Lua Bot Earth", "second managed bot should be the earth wizard")
assert(hooks.state.bots[3].bot_name == "Lua Bot Air", "third managed bot should be the air wizard")
assert(hooks.state.bots[4].bot_name == "Lua Bot Ether", "fourth managed bot should be the ether wizard")
assert(hooks.follow_stop_distance == 50.0, "follow stop distance should preserve the close deadzone")
assert(hooks.follow_resume_distance == 100.0, "follow resume distance should preserve the <100-unit contract")
assert(hooks.follow_settle_distance == 58.0, "follow settle distance should allow native arrival tolerance")
assert(type(event_handlers["runtime.tick"]) == "function", "runtime.tick handler missing")
assert(type(event_handlers["run.started"]) == "function", "run.started handler missing")

event_handlers["runtime.tick"]({ monotonic_milliseconds = 1000 })
assert(#creates == 4, "hub tick should create exactly four non-fire bot participants")
assert(creates[1].name == "Lua Bot Water", "hub first create should be water bot")
assert(creates[2].name == "Lua Bot Earth", "hub second create should be earth bot")
assert(creates[3].name == "Lua Bot Air", "hub third create should be air bot")
assert(creates[4].name == "Lua Bot Ether", "hub fourth create should be ether bot")
assert(math.abs(creates[1].position.x - 1006.0) < 0.001, "water hub spawn should use default hub x plus bot offset")
assert(math.abs(creates[1].position.y - 448.0) < 0.001, "water hub spawn should use default hub y plus bot offset")
assert(math.abs(creates[2].position.x - 1006.0) < 0.001, "earth hub spawn should use default hub x plus bot offset")
assert(math.abs(creates[2].position.y - 488.0) < 0.001, "earth hub spawn should use default hub y plus bot offset")
assert(math.abs(creates[3].position.x - 1006.0) < 0.001, "air hub spawn should use default hub x plus bot offset")
assert(math.abs(creates[3].position.y - 528.0) < 0.001, "air hub spawn should use default hub y plus bot offset")
assert(math.abs(creates[4].position.x - 1006.0) < 0.001, "ether hub spawn should use default hub x plus bot offset")
assert(math.abs(creates[4].position.y - 568.0) < 0.001, "ether hub spawn should use default hub y plus bot offset")
assert(hooks.state.bots[1].bot_id ~= nil, "water bot id was not tracked")
assert(hooks.state.bots[2].bot_id ~= nil, "earth bot id was not tracked")
assert(hooks.state.bots[3].bot_id ~= nil, "air bot id was not tracked")
assert(hooks.state.bots[4].bot_id ~= nil, "ether bot id was not tracked")
local seen_bot_ids = {}
local seen_spawn_y = {}
for _, bot_context in ipairs(hooks.state.bots) do
  assert(seen_bot_ids[bot_context.bot_id] ~= true, "managed bots should be distinct participants")
  seen_bot_ids[bot_context.bot_id] = true
  local bot = bot_store[bot_context.bot_id]
  assert(bot ~= nil, "managed bot store entry missing")
  assert(seen_spawn_y[bot.y] ~= true, "bot spawn offsets should not overlap")
  seen_spawn_y[bot.y] = true
end

event_handlers["run.started"]()
current_scene = {
  name = "testrun",
  kind = "testrun",
  world_id = 0x2000,
  transitioning = false,
}
current_player = {
  x = 200.0,
  y = 220.0,
  heading = 90.0,
}
event_handlers["runtime.tick"]({ monotonic_milliseconds = 1200 })
assert(#updates >= 4, "run promotion should update every managed bot participant")
local seen_run_spawn_y = {}
for _, bot_context in ipairs(hooks.state.bots) do
  local bot = bot_store[bot_context.bot_id]
  assert(bot.scene.kind == "run", bot_context.bot_name .. " should be promoted into run scene")
  assert(seen_run_spawn_y[bot.y] ~= true, "run promotion spawn offsets should not overlap")
  seen_run_spawn_y[bot.y] = true
end
casts = {}
faces = {}
face_targets = {}

local hub_spawn_grid = {
  width = 8,
  height = 14,
  cells = {
    {
      grid_x = 0,
      grid_y = 7,
      traversable = true,
      samples = {
        { world_x = 1087.5, world_y = 112.5, traversable = true },
      },
    },
    {
      grid_x = 1,
      grid_y = 6,
      traversable = false,
      samples = {
        { world_x = 1012.5, world_y = 187.5, traversable = true },
      },
    },
    {
      grid_x = 1,
      grid_y = 7,
      traversable = true,
      samples = {
        { world_x = 1087.5, world_y = 187.5, traversable = true },
      },
    },
  },
}

local snapped_spawn = hooks.snap_target_to_nav(
  hub_spawn_grid,
  { x = 1002.5, y = 163.6 },
  { prefer_traversable_cell = true, avoid_outer_rows = true })
assert(snapped_spawn ~= nil, "hub spawn snap should find a traversable sample")
assert(math.abs(snapped_spawn.x - 1087.5) < 0.001, "hub spawn snap chose wrong x")
assert(math.abs(snapped_spawn.y - 187.5) < 0.001, "hub spawn snap chose wrong y")

local snapped_follow = hooks.snap_target_to_nav(
  hub_spawn_grid,
  { x = 1002.5, y = 173.6 },
  { avoid_outer_rows = true })
assert(snapped_follow ~= nil, "hub follow snap should find a traversable sample")
assert(math.abs(snapped_follow.x - 1012.5) < 0.001, "hub follow snap chose wrong x")
assert(math.abs(snapped_follow.y - 187.5) < 0.001, "hub follow snap chose wrong y")

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
bot.cast_ready = false
attack_ok = hooks.issue_auto_attack(1200, attack_scene, bot, nil)
assert(attack_ok == false, "retarget should not queue while native cast cadence is not ready")
assert(#casts == 1, "retarget while not ready queued a second cast")
assert(#face_targets == 3, "retarget should still update target-facing while not ready")
assert(face_targets[3].actor_address == enemy_b.actor_address, "not-ready retarget should face the newly closest enemy")

bot.cast_ready = true
attack_ok = hooks.issue_auto_attack(1300, attack_scene, bot, nil)
assert(attack_ok == true, "cast should queue after native readiness re-arms")
assert(#casts == 2, "second ready attack should queue another cast")
assert(casts[2].target_actor_address == enemy_b.actor_address, "cast should switch to newly closest enemy")

print("lua_bots_targeting_ok=true")
