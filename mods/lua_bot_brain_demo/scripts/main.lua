local bot_id = nil
local patrol = nil
local last_log_tick = -1

local PATROL_OFFSET_X = 2.5
local PATROL_HALF_DISTANCE = 2.0
local ARRIVAL_DISTANCE = 0.35

local function get_player_state()
  if type(sd) ~= "table" or type(sd.player) ~= "table" or type(sd.player.get_state) ~= "function" then
    return nil
  end

  local state = sd.player.get_state()
  if type(state) ~= "table" then
    return nil
  end

  return state
end

local function get_bot_state()
  if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    return nil
  end

  local state = sd.bots.get_state(bot_id)
  if type(state) ~= "table" then
    return nil
  end

  return state
end

local function issue_move(target_key)
  if patrol == nil or bot_id == nil then
    return false
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
    return false
  end

  local target = patrol[target_key]
  if type(target) ~= "table" then
    return false
  end

  if not sd.bots.move_to(bot_id, target.x, target.y) then
    return false
  end

  patrol.active_target = target_key
  return true
end

local function ensure_bot()
  local state = get_bot_state()
  if state ~= nil then
    return state
  end

  local player = get_player_state()
  if player == nil then
    return nil
  end

  local spawn_x = player.x + PATROL_OFFSET_X
  local spawn_y = player.y
  bot_id = sd.bots.create({
    name = "Lua Patrol Bot",
    wizard_id = 2,
    ready = true,
    position = { x = spawn_x, y = spawn_y },
    heading = 0.0,
  })
  if bot_id == nil then
    return nil
  end

  patrol = {
    left = { x = spawn_x - PATROL_HALF_DISTANCE, y = spawn_y },
    right = { x = spawn_x + PATROL_HALF_DISTANCE, y = spawn_y },
    active_target = nil,
  }

  print(string.format(
    "created patrol bot %s left=(%.2f, %.2f) right=(%.2f, %.2f)",
    tostring(bot_id),
    patrol.left.x,
    patrol.left.y,
    patrol.right.x,
    patrol.right.y))

  issue_move("right")
  return get_bot_state()
end

sd.events.on("runtime.tick", function(event)
  local state = ensure_bot()
  if state == nil or patrol == nil or not state.available then
    return
  end

  if patrol.active_target == nil then
    issue_move("right")
    return
  end

  local target = patrol[patrol.active_target]
  if type(target) ~= "table" then
    return
  end

  local dx = target.x - state.x
  local dy = target.y - state.y
  local distance = math.sqrt(dx * dx + dy * dy)
  if distance <= ARRIVAL_DISTANCE then
    if patrol.active_target == "left" then
      issue_move("right")
    else
      issue_move("left")
    end
  end

  if last_log_tick < 0 or event.tick_count - last_log_tick >= 90 then
    last_log_tick = event.tick_count
    print(string.format(
      "patrol bot=%s pos=(%.2f, %.2f) target=%s dist=%.2f",
      tostring(bot_id),
      state.x,
      state.y,
      tostring(patrol.active_target),
      distance))
  end
end)
