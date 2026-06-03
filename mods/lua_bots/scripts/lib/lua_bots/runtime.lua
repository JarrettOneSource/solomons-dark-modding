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

  local function strict_number(value)
    local number = tonumber(value)
    if number == nil or number ~= number then
      return nil
    end
    return number
  end

  local function distance(ax, ay, bx, by)
    ax = strict_number(ax)
    ay = strict_number(ay)
    bx = strict_number(bx)
    by = strict_number(by)
    if ax == nil or ay == nil or bx == nil or by == nil then
      return nil
    end

    local dx = ax - bx
    local dy = ay - by
    return math.sqrt((dx * dx) + (dy * dy))
  end

  local function bot_formation_offset(radius)
    local offset_x = tonumber(state.spawn_offset_x)
    local offset_y = tonumber(state.spawn_offset_y)
    if offset_x == nil or offset_y == nil then
      return nil, nil
    end
    local offset_len = distance(offset_x, offset_y, 0.0, 0.0)
    if offset_len < 0.001 then
      local requested_radius = tonumber(radius)
      if requested_radius == nil then
        return nil, nil
      end
      return requested_radius, 0.0
    end

    local requested_radius = tonumber(radius)
    if requested_radius == nil then
      return nil, nil
    end

    local scale = requested_radius / offset_len
    return offset_x * scale, offset_y * scale
  end

  local function add_bot_formation_offset(target, radius)
    if type(target) ~= "table" then
      return nil
    end

    local offset_x, offset_y = bot_formation_offset(radius)
    if offset_x == nil or offset_y == nil then
      return nil
    end

    local target_x = tonumber(target.x)
    local target_y = tonumber(target.y)
    if target_x == nil or target_y == nil then
      return nil
    end

    return {
      x = target_x + offset_x,
      y = target_y + offset_y,
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
  ctx.strict_number = strict_number
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
