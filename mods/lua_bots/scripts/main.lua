local BOT_NAME = "Lua Patrol Bot"
local LEGACY_MANAGED_BOT_NAMES = {
  ["Lua Patrol Bot"] = true,
  ["Lua Bot Fire"] = true,
  ["Lua Bot Earth"] = true,
}

local BOT_WIZARD_ID = 0
local SPAWN_OFFSET_X = 50.0
local SPAWN_OFFSET_Y = 0.0
local FOLLOW_STOP_DISTANCE = 50.0
local FOLLOW_RESUME_DISTANCE = 250.0
local ARRIVAL_DISTANCE = 8.0
local FOLLOW_TARGET_REFRESH_DISTANCE = 24.0
local COMMAND_COOLDOWN_MS = 250
local TICK_INTERVAL_MS = 100
local SPAWN_RETRY_MS = 500
local ENABLE_FOLLOW_MOVEMENT = true

local state = {
  run_active = false,
  spawn_pending = false,
  last_spawn_attempt_ms = 0,
  last_tick_ms = 0,
  bot_id = nil,
  last_command_ms = 0,
  follow_target = nil,
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

local function clear_follow_state()
  state.bot_id = nil
  state.last_command_ms = 0
  state.follow_target = nil
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

  clear_follow_state()
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

local function compute_follow_target(player, bot)
  local player_x = tonumber(player.x) or 0.0
  local player_y = tonumber(player.y) or 0.0
  local bot_x = tonumber(bot.x) or 0.0
  local bot_y = tonumber(bot.y) or 0.0
  local gap = distance(bot_x, bot_y, player_x, player_y)
  local dir_x = bot_x - player_x
  local dir_y = bot_y - player_y
  if gap < 0.001 then
    dir_x = 1.0
    dir_y = 0.0
    gap = 1.0
  end

  local norm_x = dir_x / gap
  local norm_y = dir_y / gap
  return {
    x = player_x + (norm_x * FOLLOW_STOP_DISTANCE),
    y = player_y + (norm_y * FOLLOW_STOP_DISTANCE),
    gap = gap,
  }
end

local function stop_follow_move(reason)
  if state.bot_id == nil then
    return
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.stop) ~= "function" then
    return
  end

  local ok = sd.bots.stop(state.bot_id)
  if ok then
    state.follow_target = nil
    log(string.format(
      "follow_stop id=%s reason=%s",
      tostring(state.bot_id),
      tostring(reason)))
  else
    log(string.format(
      "follow_stop failed id=%s reason=%s",
      tostring(state.bot_id),
      tostring(reason)))
  end
end

local function issue_follow_move(target, now_ms, reason)
  if not ENABLE_FOLLOW_MOVEMENT then
    return
  end
  if state.bot_id == nil or type(target) ~= "table" then
    return
  end
  if now_ms - state.last_command_ms < COMMAND_COOLDOWN_MS then
    return
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
    return
  end

  local ok = sd.bots.move_to(state.bot_id, target.x, target.y)
  if ok then
    state.follow_target = {
      x = target.x,
      y = target.y,
      reason = reason,
    }
    state.last_command_ms = now_ms
    log(string.format(
      "follow_move id=%s reason=%s point=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(reason),
      target.x,
      target.y))
  else
    log(string.format(
      "follow_move failed id=%s reason=%s point=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(reason),
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
    local bot = get_bot_state(state.bot_id)
    if type(bot) ~= "table" or not bot.available or not bot.in_run or not bot.transform_valid then
      return
    end
    state.spawn_pending = false
    return
  end

  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.create) ~= "function" then
    return
  end

  local spawn = {
    x = (tonumber(player.x) or 0.0) + SPAWN_OFFSET_X,
    y = (tonumber(player.y) or 0.0) + SPAWN_OFFSET_Y,
  }
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
    "spawned %s id=%s point=(%.2f, %.2f) follow_stop=%.0f follow_resume=%.0f",
    BOT_NAME,
    tostring(bot_id),
    spawn.x,
    spawn.y,
    FOLLOW_STOP_DISTANCE,
    FOLLOW_RESUME_DISTANCE))
end

local function update_follow(now_ms, player)
  if state.bot_id == nil then
    state.spawn_pending = true
    return
  end

  local bot = get_bot_state(state.bot_id)
  if bot == nil or not bot.available then
    clear_follow_state()
    state.spawn_pending = true
    return
  end
  if not bot.in_run or not bot.transform_valid then
    return
  end
  if type(player) ~= "table" then
    return
  end

  local target = compute_follow_target(player, bot)
  local gap = target.gap
  if state.follow_target ~= nil and (not bot.moving) and (not bot.has_target) then
    local settled_gap = distance(
      tonumber(bot.x) or 0.0,
      tonumber(bot.y) or 0.0,
      tonumber(state.follow_target.x) or 0.0,
      tonumber(state.follow_target.y) or 0.0)
    if settled_gap <= ARRIVAL_DISTANCE then
      state.follow_target = nil
    end
  end
  local reason = "follow"
  local follow_active = bot.moving or bot.has_target or state.follow_target ~= nil

  if follow_active then
    if gap <= FOLLOW_STOP_DISTANCE then
      stop_follow_move("inside_stop_band")
      return
    end
  else
    if gap <= FOLLOW_RESUME_DISTANCE then
      return
    end
  end

  if (not bot.moving) or (not bot.has_target) then
    issue_follow_move(target, now_ms, reason)
    return
  end
  if bot.target_x == nil or bot.target_y == nil then
    issue_follow_move(target, now_ms, reason)
    return
  end

  local target_gap = distance(bot.target_x, bot.target_y, target.x, target.y)
  if target_gap > FOLLOW_TARGET_REFRESH_DISTANCE then
    issue_follow_move(target, now_ms, reason)
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

  update_follow(now_ms, player)
end)
