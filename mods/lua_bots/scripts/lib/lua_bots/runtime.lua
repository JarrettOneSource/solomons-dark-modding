local runtime = {}

function runtime.install(ctx)
  local state = ctx.state
  local config = ctx.config

  local function log(message)
    print("[lua.bots] " .. tostring(message))
  end

  local function log_diag(message)
    if rawget(_G, "lua_bots_enable_diagnostic_logs") == true then
      log(message)
    end
  end

  local function get_probe_state()
    local probe = rawget(_G, "lua_bots_probe")
    if type(probe) ~= "table" then
      return nil
    end
    if probe.enabled ~= true then
      return nil
    end
    local probe_bot_id = tonumber(probe.bot_id)
    if probe_bot_id ~= nil and probe_bot_id > 0 and tonumber(state.bot_id) ~= probe_bot_id then
      return nil
    end
    return probe
  end

  local function distance(ax, ay, bx, by)
    local dx = (ax or 0.0) - (bx or 0.0)
    local dy = (ay or 0.0) - (by or 0.0)
    return math.sqrt((dx * dx) + (dy * dy))
  end

  local function bot_formation_offset(radius)
    local offset_x = tonumber(state.spawn_offset_x) or config.DEFAULT_SPAWN_OFFSET_X
    local offset_y = tonumber(state.spawn_offset_y) or config.DEFAULT_SPAWN_OFFSET_Y
    local offset_len = distance(offset_x, offset_y, 0.0, 0.0)
    if offset_len < 0.001 then
      return tonumber(radius) or config.FOLLOW_STOP_DISTANCE, 0.0
    end

    local scale = (tonumber(radius) or config.FOLLOW_STOP_DISTANCE) / offset_len
    return offset_x * scale, offset_y * scale
  end

  local function add_bot_formation_offset(target, radius)
    if type(target) ~= "table" then
      return nil
    end

    local offset_x, offset_y = bot_formation_offset(radius)
    return {
      x = (tonumber(target.x) or 0.0) + offset_x,
      y = (tonumber(target.y) or 0.0) + offset_y,
    }
  end

  local function normalize_address_key(value)
    if value == nil then
      return ""
    end

    if type(value) == "number" then
      if value == 0 then
        return ""
      end
      return string.lower(string.format("0x%X", value))
    end

    local text = string.lower(tostring(value))
    if text == "" or text == "0" or text == "0x0" or text == "nil" then
      return ""
    end
    return text
  end

  local function get_scene_state()
    if type(sd) ~= "table" or type(sd.world) ~= "table" or type(sd.world.get_scene) ~= "function" then
      return nil
    end

    local scene = sd.world.get_scene()
    return type(scene) == "table" and scene or nil
  end

  local function get_world_state()
    if type(sd) ~= "table" or type(sd.world) ~= "table" or type(sd.world.get_state) ~= "function" then
      return nil
    end

    local world = sd.world.get_state()
    return type(world) == "table" and world or nil
  end

  local function get_player_state()
    if type(sd) ~= "table" or type(sd.player) ~= "table" or type(sd.player.get_state) ~= "function" then
      return nil
    end

    local player = sd.player.get_state()
    return type(player) == "table" and player or nil
  end

  local function get_all_bot_states()
    if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
      return nil
    end

    local bots = sd.bots.get_state()
    return type(bots) == "table" and bots or nil
  end

  local function get_bot_state(bot_id)
    if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
      return nil
    end

    local bot = sd.bots.get_state(bot_id)
    return type(bot) == "table" and bot or nil
  end

  ctx.log = log
  ctx.log_diag = log_diag
  ctx.get_probe_state = get_probe_state
  ctx.distance = distance
  ctx.bot_formation_offset = bot_formation_offset
  ctx.add_bot_formation_offset = add_bot_formation_offset
  ctx.normalize_address_key = normalize_address_key
  ctx.get_scene_state = get_scene_state
  ctx.get_world_state = get_world_state
  ctx.get_player_state = get_player_state
  ctx.get_all_bot_states = get_all_bot_states
  ctx.get_bot_state = get_bot_state
end

return runtime
