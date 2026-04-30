local combat = {}

function combat.install(ctx)
  local state = ctx.state
  local config = ctx.config

  local function is_enemy_actor(actor, bot)
    if type(actor) ~= "table" then
      return false
    end
    local address = tonumber(actor.actor_address) or 0
    if address == 0 then
      return false
    end
    if type(bot) == "table" and address == (tonumber(bot.actor_address) or 0) then
      return false
    end
    local tracked_enemy = actor.tracked_enemy == true
    if not tracked_enemy then
      return false
    end
    if (tonumber(actor.object_type_id) or 0) ~= config.WAVE_ENEMY_OBJECT_TYPE_ID then
      return false
    end
    if actor.dead == true then
      return false
    end
    local max_hp = tonumber(actor.max_hp) or 0.0
    local hp = tonumber(actor.hp) or 0.0
    if max_hp <= 0.0 or hp <= 0.0 then
      return false
    end
    return true
  end

  local function find_nearest_enemy(bot)
    if type(sd.world) ~= "table" or type(sd.world.list_actors) ~= "function" then
      return nil, nil
    end
    local actors = sd.world.list_actors()
    if type(actors) ~= "table" then
      return nil, nil
    end
    local bot_x = tonumber(bot.x) or 0.0
    local bot_y = tonumber(bot.y) or 0.0

    local best, best_gap = nil, math.huge
    for _, actor in ipairs(actors) do
      if is_enemy_actor(actor, bot) then
        local gap = ctx.distance(bot_x, bot_y, tonumber(actor.x) or 0.0, tonumber(actor.y) or 0.0)
        if gap < best_gap then
          best = actor
          best_gap = gap
        end
      end
    end
    if best == nil then
      return nil, nil
    end
    return best, best_gap
  end

  local function should_log_attack_diag(now_ms)
    now_ms = tonumber(now_ms) or 0
    local last_ms = tonumber(state.last_attack_diag_ms) or 0
    if now_ms - last_ms < config.ATTACK_DIAG_INTERVAL_MS then
      return false
    end
    state.last_attack_diag_ms = now_ms
    return true
  end

  local function get_combat_state()
    if type(sd) ~= "table" or type(sd.gameplay) ~= "table" or
        type(sd.gameplay.get_combat_state) ~= "function" then
      return nil
    end
    local ok, combat_state = pcall(sd.gameplay.get_combat_state)
    if ok and type(combat_state) == "table" then
      return combat_state
    end
    return nil
  end

  local function can_attack_in_scene(scene)
    if type(scene) ~= "table" or tostring(scene.name or "") ~= "testrun" then
      return false, "scene_inactive"
    end
    local world = ctx.get_world_state()
    local wave = type(world) == "table" and tonumber(world.wave) or 0
    if wave ~= nil and wave > 0 then
      return true, nil
    end

    local combat_state = get_combat_state()
    if type(combat_state) == "table" and combat_state.active then
      return true, nil
    end
    return false, "combat_inactive"
  end

  local function get_attack_enemy(bot, probe)
    if type(bot) ~= "table" then
      return nil, nil
    end
    return find_nearest_enemy(bot)
  end

  local function heading_towards(from_x, from_y, to_x, to_y)
    local dx = (tonumber(to_x) or 0.0) - (tonumber(from_x) or 0.0)
    local dy = (tonumber(to_y) or 0.0) - (tonumber(from_y) or 0.0)
    if dx * dx + dy * dy <= 0.0001 then
      return nil
    end

    local radians
    if type(math.atan2) == "function" then
      radians = math.atan2(dy, dx)
    elseif math.abs(dx) < 0.000001 then
      radians = dy >= 0.0 and (math.pi * 0.5) or (math.pi * -0.5)
    else
      radians = math.atan(dy / dx)
      if dx < 0.0 then
        radians = radians + math.pi
      elseif dy < 0.0 then
        radians = radians + (math.pi * 2.0)
      end
    end

    local heading = (radians * 180.0 / math.pi) + 90.0
    while heading < 0.0 do
      heading = heading + 360.0
    end
    while heading >= 360.0 do
      heading = heading - 360.0
    end
    return heading
  end

  local function face_enemy(bot, enemy, use_actor_target)
    if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.face) ~= "function" then
      return nil
    end
    if state.bot_id == nil or type(bot) ~= "table" or type(enemy) ~= "table" then
      return nil
    end

    local heading = heading_towards(
      bot.x,
      bot.y,
      tonumber(enemy.x) or 0.0,
      tonumber(enemy.y) or 0.0)
    if heading == nil then
      return nil
    end

    local target_actor_address = tonumber(enemy.actor_address) or 0
    if use_actor_target and target_actor_address ~= 0 and type(sd.bots.face_target) == "function" then
      pcall(sd.bots.face_target, state.bot_id, target_actor_address, heading)
    else
      pcall(sd.bots.face, state.bot_id, heading)
    end
    return heading
  end

  local function clear_face_target()
    if state.bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" then
      return
    end
    if type(sd.bots.face_target) == "function" then
      pcall(sd.bots.face_target, state.bot_id, 0)
    end
  end

  local function read_actor_float(actor_address, offset)
    if type(sd) ~= "table" or type(sd.debug) ~= "table" or type(sd.debug.read_float) ~= "function" then
      return nil
    end

    actor_address = tonumber(actor_address)
    if actor_address == nil or actor_address == 0 then
      return nil
    end

    local ok, value = pcall(sd.debug.read_float, actor_address + offset)
    if not ok then
      return nil
    end

    value = tonumber(value)
    if value == nil or value ~= value then
      return nil
    end
    return value
  end

  local function water_attack_range(bot, fallback_range)
    local shape = read_actor_float(type(bot) == "table" and bot.actor_address or nil, 0x290)
    if shape == nil then
      return fallback_range
    end

    -- Native frost handler feeds FUN_00641B10 with range = 205 + 4 * actor[0x290].
    local native_range = config.WATER_BASE_CONE_RANGE + (shape * config.WATER_RANGE_PER_SHAPE_UNIT)
    return math.max(config.DEFAULT_ATTACK_RANGE, native_range - config.WATER_RANGE_SAFETY_MARGIN)
  end

  local function current_attack_window(bot)
    local profile = type(state.bot_profile) == "table" and state.bot_profile or nil
    local element_id = profile ~= nil and tonumber(profile.element_id) or nil
    local range = config.ATTACK_RANGE_BY_ELEMENT_ID[element_id] or config.DEFAULT_ATTACK_RANGE
    if element_id == 1 then
      range = water_attack_range(bot, range)
    end
    return config.MIN_ATTACK_RANGE_BY_ELEMENT_ID[element_id] or 0.0,
      range
  end

  local function issue_auto_attack(now_ms, scene, bot, probe)
    if state.bot_id == nil then
      return false
    end
    if type(sd.bots) ~= "table" or type(sd.bots.cast) ~= "function" then
      return false
    end
    if type(bot) ~= "table" or not bot.available or (tonumber(bot.actor_address) or 0) == 0 or not bot.transform_valid then
      return false
    end
    local attack_scene_ok, attack_scene_reason = can_attack_in_scene(scene)
    if not attack_scene_ok then
      clear_face_target()
      if should_log_attack_diag(now_ms) then
        local world = ctx.get_world_state()
        local combat_state = get_combat_state()
        ctx.log_diag(string.format(
          "attack_skip id=%s reason=%s wave=%s combat_active=%s",
          tostring(state.bot_id),
          tostring(attack_scene_reason),
          tostring(type(world) == "table" and world.wave or nil),
          tostring(type(combat_state) == "table" and combat_state.active or nil)))
      end
      return false
    end
    local min_range, range = current_attack_window(bot)
    local enemy, gap = get_attack_enemy(bot, probe)
    if enemy == nil then
      clear_face_target()
      if should_log_attack_diag(now_ms) then
        ctx.log_diag(string.format(
          "attack_skip id=%s reason=%s",
          tostring(state.bot_id),
          "no_enemy_in_scene"))
      end
      return false
    end
    local target_actor_address = tonumber(enemy.actor_address) or 0
    local target_x = tonumber(enemy.x) or 0.0
    local target_y = tonumber(enemy.y) or 0.0
    local attack_heading = face_enemy(bot, enemy, true)
    if gap < min_range then
      if should_log_attack_diag(now_ms) then
        ctx.log_diag(string.format(
          "attack_skip id=%s reason=too_close_for_native_release enemy=0x%X gap=%.2f min=%.1f range=%.1f",
          tostring(state.bot_id),
          tonumber(enemy.actor_address) or 0,
          gap,
          min_range,
          range))
      end
      return false
    end
    if gap > range then
      if should_log_attack_diag(now_ms) then
        ctx.log_diag(string.format(
          "attack_skip id=%s reason=out_of_range enemy=0x%X gap=%.2f range=%.1f",
          tostring(state.bot_id),
          tonumber(enemy.actor_address) or 0,
          gap,
          range))
      end
      return false
    end
    if attack_heading == nil then
      attack_heading = heading_towards(bot.x, bot.y, target_x, target_y)
    end
    if bot.cast_ready ~= true then
      return false
    end
    local ok = sd.bots.cast({
      id = state.bot_id,
      kind = "primary",
      target_actor_address = target_actor_address,
      target = { x = target_x, y = target_y },
      angle = attack_heading,
    })
    if ok then
      ctx.log_diag(string.format(
        "attack id=%s primary enemy=0x%X bot=(%.2f, %.2f) target=(%.2f, %.2f) heading=%.2f gap=%.2f range=%.1f",
        tostring(state.bot_id),
        target_actor_address,
        tonumber(bot.x) or 0.0,
        tonumber(bot.y) or 0.0,
        target_x,
        target_y,
        tonumber(attack_heading) or -1.0,
        gap,
        range))
    else
      ctx.log_diag(string.format(
        "attack failed id=%s primary",
        tostring(state.bot_id)))
    end
    return ok
  end

  ctx.is_enemy_actor = is_enemy_actor
  ctx.find_nearest_enemy = find_nearest_enemy
  ctx.should_log_attack_diag = should_log_attack_diag
  ctx.get_combat_state = get_combat_state
  ctx.can_attack_in_scene = can_attack_in_scene
  ctx.get_attack_enemy = get_attack_enemy
  ctx.heading_towards = heading_towards
  ctx.face_enemy = face_enemy
  ctx.clear_face_target = clear_face_target
  ctx.read_actor_float = read_actor_float
  ctx.water_attack_range = water_attack_range
  ctx.current_attack_window = current_attack_window
  ctx.issue_auto_attack = issue_auto_attack
end

return combat
