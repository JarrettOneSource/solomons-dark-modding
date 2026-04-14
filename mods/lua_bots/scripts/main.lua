local BOT_NAME = "Lua Patrol Bot"
local LEGACY_MANAGED_BOT_NAMES = {
  ["Lua Patrol Bot"] = true,
  ["Lua Bot Fire"] = true,
  ["Lua Bot Earth"] = true,
}

local BOT_WIZARD_ID = 0
local SPAWN_OFFSET_X = 50.0
local SPAWN_OFFSET_Y = 0.0
local PATROL_SEGMENT_X = 150.0
local PATROL_SEGMENT_Y = 0.0
local ARRIVAL_DISTANCE = 8.0
local TARGET_REFRESH_DISTANCE = 12.0
local COMMAND_COOLDOWN_MS = 250
local TICK_INTERVAL_MS = 100
local SPAWN_RETRY_MS = 500
local DWELL_DURATION_MS = 2000
local ENABLE_PATROL_MOVEMENT = true

local state = {
  run_active = false,
  spawn_pending = false,
  last_spawn_attempt_ms = 0,
  last_tick_ms = 0,
  bot_id = nil,
  last_command_ms = 0,
  patrol = nil,
  dwell_until_ms = 0,
}

lua_bots_debug = state

local function log(message)
  print("[lua.bots] " .. tostring(message))
end

local function get_scene_state()
  if type(sd) ~= "table" or type(sd.world) ~= "table" or type(sd.world.get_scene) ~= "function" then
    return nil
  end

  local scene = sd.world.get_scene()
  if type(scene) ~= "table" then
    return nil
  end

  return scene
end

local function get_player_state()
  if type(sd) ~= "table" or type(sd.player) ~= "table" or type(sd.player.get_state) ~= "function" then
    return nil
  end

  local player = sd.player.get_state()
  if type(player) ~= "table" then
    return nil
  end

  return player
end

local function get_all_bot_states()
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    return nil
  end

  local bots = sd.bots.get_state()
  if type(bots) ~= "table" then
    return nil
  end

  return bots
end

local function get_bot_state(bot_id)
  if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    return nil
  end

  local bot = sd.bots.get_state(bot_id)
  if type(bot) ~= "table" then
    return nil
  end

  return bot
end

local function destroy_bot_by_id(bot_id)
  if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.destroy) ~= "function" then
    return
  end

  pcall(sd.bots.destroy, bot_id)
end

local function clear_patrol_state()
  state.bot_id = nil
  state.last_command_ms = 0
  state.patrol = nil
  state.dwell_until_ms = 0
end

local function is_managed_bot_name(bot_name)
  return type(bot_name) == "string" and LEGACY_MANAGED_BOT_NAMES[bot_name] == true
end

local function destroy_managed_bots()
  if state.bot_id ~= nil then
    destroy_bot_by_id(state.bot_id)
  end

  local bots = get_all_bot_states()
  if type(bots) == "table" then
    for _, bot in ipairs(bots) do
      if type(bot) == "table" and is_managed_bot_name(bot.name) then
        destroy_bot_by_id(bot.id)
      end
    end
  end

  clear_patrol_state()
end

local function adopt_existing_managed_bot()
  local bots = get_all_bot_states()
  if type(bots) ~= "table" then
    return
  end

  local adopted = false
  for _, bot in ipairs(bots) do
    if type(bot) == "table" and bot.available and is_managed_bot_name(bot.name) then
      if not adopted then
        state.bot_id = bot.id
        adopted = true
      else
        destroy_bot_by_id(bot.id)
      end
    end
  end
end

local build_patrol = nil

local function ensure_patrol_points(player)
  if type(state.patrol) ~= "table" and type(player) == "table" then
    state.patrol = build_patrol(player)
    log(string.format(
      "rebuilt patrol points A=(%.2f, %.2f) B=(%.2f, %.2f)",
      state.patrol.a.x,
      state.patrol.a.y,
      state.patrol.b.x,
      state.patrol.b.y))
  end
end

local function distance(ax, ay, bx, by)
  local dx = (ax or 0.0) - (bx or 0.0)
  local dy = (ay or 0.0) - (by or 0.0)
  return math.sqrt((dx * dx) + (dy * dy))
end

local function scene_is_live_run(scene, player)
  if type(scene) ~= "table" or type(player) ~= "table" then
    return false
  end

  local scene_name = tostring(scene.name or scene.kind or "")
  local actor_address = tonumber(player.actor_address or player.render_subject_address) or 0
  return scene_name == "testrun" and actor_address ~= 0 and not scene.transitioning
end

build_patrol = function(player)
  local spawn_x = (tonumber(player.x) or 0.0) + SPAWN_OFFSET_X
  local spawn_y = (tonumber(player.y) or 0.0) + SPAWN_OFFSET_Y
  return {
    a = { x = spawn_x, y = spawn_y },
    b = { x = spawn_x + PATROL_SEGMENT_X, y = spawn_y + PATROL_SEGMENT_Y },
    active_target = "b",
  }
end

local function get_active_target()
  if type(state.patrol) ~= "table" then
    return nil
  end
  return state.patrol[state.patrol.active_target]
end

local function issue_move(target_key, now_ms)
  if not ENABLE_PATROL_MOVEMENT then
    return
  end
  if state.bot_id == nil or type(state.patrol) ~= "table" then
    return
  end
  if now_ms - state.last_command_ms < COMMAND_COOLDOWN_MS then
    return
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
    return
  end

  local target = state.patrol[target_key]
  if type(target) ~= "table" then
    return
  end

  local ok = sd.bots.move_to(state.bot_id, target.x, target.y)
  if ok then
    state.patrol.active_target = target_key
    state.last_command_ms = now_ms
    state.dwell_until_ms = 0
    log(string.format(
      "move_to id=%s target=%s point=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(target_key),
      target.x,
      target.y))
  else
    log(string.format(
      "move_to failed id=%s target=%s point=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(target_key),
      target.x,
      target.y))
  end
end

local function ensure_bot_spawned(now_ms)
  if not state.run_active or not state.spawn_pending then
    return
  end

  if state.last_spawn_attempt_ms ~= 0 and now_ms - state.last_spawn_attempt_ms < SPAWN_RETRY_MS then
    return
  end

  local player = get_player_state()
  local scene = get_scene_state()
  if not scene_is_live_run(scene, player) then
    return
  end

  state.last_spawn_attempt_ms = now_ms
  adopt_existing_managed_bot()
  if state.bot_id ~= nil then
    ensure_patrol_points(player)
    local bot = get_bot_state(state.bot_id)
    if type(bot) ~= "table" or not bot.available or not bot.in_run or not bot.transform_valid then
      return
    end
    if ENABLE_PATROL_MOVEMENT and (not bot.moving or not bot.has_target) then
      log(string.format(
        "activating patrol id=%s moving=%s has_target=%s target=%s",
        tostring(state.bot_id),
        tostring(bot.moving),
        tostring(bot.has_target),
        tostring(state.patrol and state.patrol.active_target)))
      issue_move(state.patrol.active_target, now_ms)
      bot = get_bot_state(state.bot_id)
    end
    if type(bot) == "table" and (bot.moving or bot.has_target) then
      state.spawn_pending = false
    end
    return
  end

  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.create) ~= "function" then
    return
  end

  state.patrol = build_patrol(player)
  local spawn = state.patrol.a
  local bot_id = sd.bots.create({
    name = BOT_NAME,
    profile = {
      element_id = BOT_WIZARD_ID,
      discipline_id = 2,
    },
    ready = true,
    position = { x = spawn.x, y = spawn.y },
  })
  if bot_id == nil then
    return
  end

  state.bot_id = bot_id
  log(string.format(
    "spawned %s id=%s A=(%.2f, %.2f) B=(%.2f, %.2f)",
    BOT_NAME,
    tostring(bot_id),
    state.patrol.a.x,
    state.patrol.a.y,
    state.patrol.b.x,
    state.patrol.b.y))
end

local function update_patrol(now_ms)
  if state.bot_id == nil or type(state.patrol) ~= "table" then
    state.spawn_pending = true
    return
  end

  local bot = get_bot_state(state.bot_id)
  if bot == nil or not bot.available then
    clear_patrol_state()
    state.spawn_pending = true
    return
  end
  ensure_patrol_points(get_player_state())
  if not bot.in_run or not bot.transform_valid then
    return
  end

  local target = get_active_target()
  if type(target) ~= "table" then
    return
  end

  local gap = distance(bot.x, bot.y, target.x, target.y)
  if gap <= ARRIVAL_DISTANCE then
    if state.dwell_until_ms == 0 then
      state.dwell_until_ms = now_ms + DWELL_DURATION_MS
      log(string.format(
        "dwell id=%s target=%s until=%s",
        tostring(state.bot_id),
        tostring(state.patrol.active_target),
        tostring(state.dwell_until_ms)))
      return
    end
    if now_ms < state.dwell_until_ms then
      return
    end
    local next_target = state.patrol.active_target == "a" and "b" or "a"
    issue_move(next_target, now_ms)
    return
  end

  if (not bot.moving) or (not bot.has_target) then
    issue_move(state.patrol.active_target, now_ms)
    return
  end

  if bot.target_x == nil or bot.target_y == nil then
    issue_move(state.patrol.active_target, now_ms)
    return
  end

  local target_gap = distance(bot.target_x, bot.target_y, target.x, target.y)
  if target_gap > TARGET_REFRESH_DISTANCE then
    issue_move(state.patrol.active_target, now_ms)
  end
end

local function sync_run_state_from_scene()
  if state.run_active then
    return
  end

  local scene = get_scene_state()
  local player = get_player_state()
  if scene_is_live_run(scene, player) then
    state.run_active = true
    state.spawn_pending = true
  end
end

local function on_run_started()
  state.run_active = true
  state.spawn_pending = true
  state.last_spawn_attempt_ms = 0
  state.last_tick_ms = 0
  destroy_managed_bots()
  log("run.started")
end

local function on_run_ended()
  state.run_active = false
  state.spawn_pending = false
  state.last_spawn_attempt_ms = 0
  state.last_tick_ms = 0
  destroy_managed_bots()
  log("run.ended")
end

sd.events.on("run.started", on_run_started)
sd.events.on("run.ended", on_run_ended)

sd.events.on("runtime.tick", function(event)
  local now_ms = tonumber(event.monotonic_milliseconds) or 0

  sync_run_state_from_scene()
  ensure_bot_spawned(now_ms)

  if not state.run_active then
    return
  end
  if now_ms - state.last_tick_ms < TICK_INTERVAL_MS then
    return
  end
  state.last_tick_ms = now_ms

  local player = get_player_state()
  local scene = get_scene_state()
  if not scene_is_live_run(scene, player) then
    return
  end

  update_patrol(now_ms)
end)
