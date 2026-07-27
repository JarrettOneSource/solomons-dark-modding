local function create_mod_require()
  if type(load) ~= "function" or
      type(sd) ~= "table" or type(sd.runtime) ~= "table" or
      type(sd.runtime.get_mod_text_file) ~= "function" then
    error("mod-local Lua source loading is unavailable")
  end

  local loading_sentinel = {}
  local module_cache = {}
  return function(path)
    local normalized = tostring(path or ""):gsub("\\", "/")
    normalized = normalized:gsub("^%./", ""):gsub("/+", "/")
    if normalized == "" then
      error("module path must not be empty")
    end
    if module_cache[normalized] == loading_sentinel then
      error("circular module load for " .. normalized)
    end
    if module_cache[normalized] ~= nil then
      return module_cache[normalized]
    end

    local source = sd.runtime.get_mod_text_file(normalized)
    if type(source) ~= "string" then
      error("unable to read module " .. normalized)
    end
    local chunk, load_error = load(
      source,
      "@" .. normalized,
      "t",
      _ENV)
    if chunk == nil then
      error(
        "unable to compile module " .. normalized ..
        ": " .. tostring(load_error))
    end

    module_cache[normalized] = loading_sentinel
    local ok, result = pcall(chunk)
    if not ok then
      module_cache[normalized] = nil
      error(
        "error loading module " .. normalized ..
        ": " .. tostring(result))
    end
    module_cache[normalized] = result == nil and true or result
    return module_cache[normalized]
  end
end

local require_mod = create_mod_require()
local steering = assert(require_mod("scripts/steering.lua"))

local CONFIG = {
  bot_name = "Ember",
  bot_class = "fire",
  think_interval_ms = 250,
  spawn_retry_ms = 1000,
  nav_refresh_ms = 2000,
  attack_window_refresh_ms = 2000,
  cast_interval_ms = 500,
  cast_hold_ms = 80,
  approach_move_interval_ms = 1000,
  kite_move_interval_ms = 250,
  orbit_move_interval_ms = 500,
  flee_move_interval_ms = 250,
  threat_radius = 340.0,
  flee_threat_radius = 900.0,
  normal_lookahead = 140.0,
  flee_lookahead = 220.0,
  flee_threshold = 0.35,
  flee_recovery_threshold = 0.45,
  offense_enabled = true,
  think_profile = "standard",
  focus_bot_key = "NONE",
}

CONFIG.threat_radius = sd.settings.get("kite_radius")
CONFIG.offense_enabled = sd.settings.get("offense_enabled")
CONFIG.bot_name = sd.settings.get("persona_name")
CONFIG.think_profile = sd.settings.get("think_profile")
CONFIG.think_interval_ms =
  CONFIG.think_profile == "relaxed" and 400 or 250
CONFIG.focus_bot_key = sd.settings.get("focus_bot_key")

local state = {
  bot = nil,
  participant_id = 0,
  last_tick_ms = -CONFIG.think_interval_ms,
  last_spawn_attempt_ms = -CONFIG.spawn_retry_ms,
  last_nav_refresh_ms = -CONFIG.nav_refresh_ms,
  last_attack_window_refresh_ms = -CONFIG.attack_window_refresh_ms,
  last_cast_attempt_ms = -CONFIG.cast_interval_ms,
  last_move_attempt_ms = -CONFIG.approach_move_interval_ms,
  last_skill_choice_generation = -1,
  last_position_x = nil,
  last_position_y = nil,
  arena = nil,
  attack_window = nil,
  fleeing = false,
  focus_key_down = false,
  focus_active = false,
  death_latched = false,
  last_wave = -1,
  debug = {
    authority = false,
    active = false,
    participant_id = 0,
    wave = 0,
    mode = "waiting",
    hp = 0.0,
    max_hp = 0.0,
    live_enemy_count = 0,
    threat_count = 0,
    target_network_actor_id = 0,
    target_distance = 0.0,
    think_count = 0,
    move_issued = 0,
    move_accepted = 0,
    movement_candidates_blocked = 0,
    cast_issued = 0,
    cast_accepted = 0,
    skill_choices_accepted = 0,
    kite_path_distance = 0.0,
    nearest_enemy_distance = 0.0,
    arena_grid_backed = false,
    kite_radius = CONFIG.threat_radius,
    offense_enabled = CONFIG.offense_enabled,
    think_profile = CONFIG.think_profile,
    persona_name = CONFIG.bot_name,
    focus_bot_key = CONFIG.focus_bot_key,
    focus_active = false,
    settings_change_count = 0,
    last_settings_change_key = "",
    respawn_action_count = 0,
    last_error = "",
  },
}

rawset(_G, "bot_brain_debug", state.debug)

local function log(message)
  print("[bot-brain] " .. message)
end

local function simulation_authority()
  local ok, authority = pcall(sd.state.is_authority)
  return ok and authority == true
end

local function participant_name_matches(participant_id)
  local ok, multiplayer = pcall(sd.runtime.get_multiplayer_state)
  if not ok or type(multiplayer) ~= "table" then
    return false
  end
  for _, participant in ipairs(multiplayer.participants or {}) do
    if tonumber(participant.participant_id) == participant_id and
        tostring(participant.name or "") == CONFIG.bot_name and
        tostring(participant.controller_kind or "") == "LuaBrain" then
      return true
    end
  end
  return false
end

local function find_owned_bot()
  for _, bot in ipairs(sd.bots.list() or {}) do
    local participant_id = tonumber(bot:participant_id()) or 0
    if participant_id > 0 and participant_name_matches(participant_id) then
      return bot, participant_id
    end
  end
  return nil, 0
end

local function update_focus_key()
  local key_down = sd.settings.is_keybind_down("focus_bot_key")
  if key_down == true then
    local bot = state.bot
    if bot == nil then
      local participant_id
      bot, participant_id = find_owned_bot()
      if bot ~= nil then
        state.bot = bot
        state.participant_id = participant_id
        state.debug.participant_id = participant_id
      end
    end
    if bot ~= nil then
      local ok, x, y = pcall(function()
        return bot:position()
      end)
      if ok and tonumber(x) ~= nil and tonumber(y) ~= nil then
        sd.camera.set_focus(x, y)
        state.focus_active = true
      end
    end
  elseif state.focus_key_down or state.focus_active then
    sd.camera.clear_focus()
    state.focus_active = false
  end
  state.focus_key_down = key_down == true
  state.debug.focus_active = state.focus_active
end

local function ensure_bot(now_ms)
  if state.bot ~= nil and state.participant_id > 0 then
    return state.bot
  end

  local existing, existing_id = find_owned_bot()
  if existing ~= nil then
    state.bot = existing
    state.participant_id = existing_id
    state.debug.participant_id = existing_id
    log("adopted participant_id=" .. tostring(existing_id))
    return existing
  end

  if now_ms - state.last_spawn_attempt_ms < CONFIG.spawn_retry_ms then
    return nil
  end
  state.last_spawn_attempt_ms = now_ms
  local ok, bot, error_message = pcall(
    sd.bots.spawn,
    {name = CONFIG.bot_name, class = CONFIG.bot_class})
  if not ok or bot == nil then
    state.debug.last_error = tostring(error_message or bot or "spawn rejected")
    return nil
  end

  state.bot = bot
  state.participant_id = tonumber(bot:participant_id()) or 0
  state.debug.participant_id = state.participant_id
  state.debug.last_error = ""
  log(
    "spawned participant_id=" .. tostring(state.participant_id) ..
    " name=" .. CONFIG.bot_name ..
    " class=" .. CONFIG.bot_class)
  return bot
end

local function current_scene_is_run()
  local ok, scene = pcall(sd.world.get_scene)
  if not ok or type(scene) ~= "table" then
    return false
  end
  local name = tostring(scene.name or "")
  local kind = tostring(scene.kind or "")
  return name == "testrun" or kind == "run"
end

local function update_arena(now_ms, bot_x, bot_y)
  if state.arena ~= nil and
      now_ms - state.last_nav_refresh_ms < CONFIG.nav_refresh_ms then
    return state.arena
  end
  state.last_nav_refresh_ms = now_ms
  local ok, grid = pcall(sd.nav.get_grid, 1)
  if not ok then
    grid = nil
  end
  state.arena = steering.arena_from_grid(grid, bot_x, bot_y)
  state.debug.arena_grid_backed = state.arena.grid_backed
  return state.arena
end

local function update_attack_window(now_ms)
  if state.attack_window ~= nil and
      now_ms - state.last_attack_window_refresh_ms <
        CONFIG.attack_window_refresh_ms then
    return state.attack_window
  end
  state.last_attack_window_refresh_ms = now_ms
  local ok, window = pcall(
    sd.bots.get_primary_attack_window,
    state.participant_id)
  if ok and type(window) == "table" and
      tonumber(window.max_range) ~= nil then
    state.attack_window = window
    state.debug.last_error = ""
  end
  return state.attack_window
end

local function choose_pending_skill()
  local ok, choices = pcall(
    sd.bots.get_skill_choices,
    state.participant_id)
  if not ok or type(choices) ~= "table" or
      choices.pending ~= true or
      type(choices.options) ~= "table" or
      #choices.options == 0 then
    return
  end

  local generation = tonumber(choices.generation)
  if generation == nil or generation == state.last_skill_choice_generation then
    return
  end

  local priority = {
    [64] = 1, -- Health Up
    [16] = 2, -- Fireball
    [18] = 3, -- Explode
    [17] = 4, -- Embers
  }
  local selected_index = 1
  local selected_priority = math.huge
  for index, option in ipairs(choices.options) do
    local option_priority = priority[tonumber(option.id)] or 100 + index
    if option_priority < selected_priority then
      selected_priority = option_priority
      selected_index = index
    end
  end

  local apply_ok, accepted = pcall(
    sd.bots.choose_skill,
    state.participant_id,
    selected_index,
    generation)
  if apply_ok and accepted == true then
    state.last_skill_choice_generation = generation
    state.debug.skill_choices_accepted =
      state.debug.skill_choices_accepted + 1
    local selected = choices.options[selected_index]
    log(
      "skill choice accepted generation=" .. tostring(generation) ..
      " option_id=" .. tostring(selected and selected.id or -1))
  end
end

local function track_path_distance(bot_x, bot_y)
  if state.last_position_x ~= nil and state.last_position_y ~= nil then
    local dx = bot_x - state.last_position_x
    local dy = bot_y - state.last_position_y
    local distance = math.sqrt((dx * dx) + (dy * dy))
    if distance <= 350.0 then
      state.debug.kite_path_distance =
        state.debug.kite_path_distance + distance
    end
  end
  state.last_position_x = bot_x
  state.last_position_y = bot_y
end

local function issue_movement(
    bot,
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    lookahead_override,
    now_ms,
    move_interval)
  move_interval = tonumber(move_interval) or CONFIG.orbit_move_interval_ms
  if now_ms - state.last_move_attempt_ms < move_interval then
    return false
  end
  state.last_move_attempt_ms = now_ms
  local lookahead = tonumber(lookahead_override) or
    (state.fleeing and
      CONFIG.flee_lookahead or CONFIG.normal_lookahead)
  local candidates = steering.movement_candidates(
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    state.arena,
    lookahead)
  for _, target in ipairs(candidates) do
    local nav_ok, traversable = pcall(
      sd.nav.test_segment,
      bot_x,
      bot_y,
      target.x,
      target.y)
    if not nav_ok then
      state.debug.last_error = tostring(traversable)
    elseif traversable ~= true then
      state.debug.movement_candidates_blocked =
        state.debug.movement_candidates_blocked + 1
    else
      state.debug.move_issued = state.debug.move_issued + 1
      local ok, accepted, error_message = pcall(
        function()
          return bot:move_to(target.x, target.y)
        end)
      if ok and accepted == true then
        state.debug.move_accepted = state.debug.move_accepted + 1
        state.debug.destination_x = target.x
        state.debug.destination_y = target.y
        state.debug.last_error = ""
        return true
      end
      if ok then
        state.debug.last_error = tostring(error_message or "move rejected")
      else
        state.debug.last_error = tostring(accepted)
      end
    end
  end
  return false
end

local function issue_primary_cast(bot, now_ms, target)
  if not CONFIG.offense_enabled or state.fleeing or target == nil or
      now_ms - state.last_cast_attempt_ms < CONFIG.cast_interval_ms then
    return
  end
  state.last_cast_attempt_ms = now_ms
  state.debug.cast_issued = state.debug.cast_issued + 1
  local ok, accepted, error_message = pcall(
    function()
      return bot:cast(
        0,
        target.x,
        target.y,
        CONFIG.cast_hold_ms)
    end)
  if ok and accepted == true then
    state.debug.cast_accepted = state.debug.cast_accepted + 1
    state.debug.last_error = ""
    log(
      "cast accepted count=" ..
      tostring(state.debug.cast_accepted) ..
      " target=" .. tostring(target.network_actor_id))
  elseif ok then
    state.debug.last_error = tostring(error_message or "cast rejected")
  else
    state.debug.last_error = tostring(accepted)
  end
end

local function update_wave_debug()
  local ok, wave = pcall(sd.waves.get_state)
  if not ok or type(wave) ~= "table" then
    return nil
  end
  local wave_number = tonumber(wave.wave) or 0
  state.debug.wave = wave_number
  if wave_number ~= state.last_wave then
    state.last_wave = wave_number
    log(
      "wave=" .. tostring(wave_number) ..
      " phase=" .. tostring(wave.phase or ""))
  end
  return wave
end

local function think(now_ms)
  state.debug.authority = simulation_authority()
  if not state.debug.authority then
    state.debug.active = false
    state.debug.mode = "observer"
    return
  end

  local bot = ensure_bot(now_ms)
  if bot == nil then
    state.debug.active = false
    state.debug.mode = "spawning"
    return
  end

  local wave = update_wave_debug()
  choose_pending_skill()
  if not current_scene_is_run() then
    state.debug.active = false
    state.debug.mode = "hub"
    state.last_position_x = nil
    state.last_position_y = nil
    return
  end

  local position_ok, bot_x, bot_y = pcall(
    function()
      return bot:position()
    end)
  local hp_ok, hp = pcall(function() return bot:hp() end)
  local max_hp_ok, max_hp = pcall(function() return bot:max_hp() end)
  if not position_ok or tonumber(bot_x) == nil or tonumber(bot_y) == nil or
      not hp_ok or tonumber(hp) == nil or
      not max_hp_ok or tonumber(max_hp) == nil or max_hp <= 0.0 then
    state.debug.active = false
    state.debug.mode = "materializing"
    return
  end

  state.debug.hp = hp
  state.debug.max_hp = max_hp
  local alive_ok, alive = pcall(function() return bot:alive() end)
  if hp <= 0.0 or (alive_ok and alive ~= true) then
    state.debug.active = false
    state.debug.mode = "dead"
    if not state.death_latched and
        type(wave) == "table" and (tonumber(wave.wave) or 0) > 0 then
      state.death_latched = true
      log(
        "death wave=" .. tostring(state.debug.wave) ..
        " hp=" .. tostring(hp))
    end
    return
  end

  state.debug.active = true
  state.debug.think_count = state.debug.think_count + 1
  track_path_distance(bot_x, bot_y)
  update_arena(now_ms, bot_x, bot_y)

  local hp_ratio = hp / max_hp
  if state.fleeing then
    if hp_ratio >= CONFIG.flee_recovery_threshold then
      state.fleeing = false
      log("mode=normal hp_ratio=" .. tostring(hp_ratio))
    end
  elseif hp_ratio < CONFIG.flee_threshold then
    state.fleeing = true
    log("mode=flee hp_ratio=" .. tostring(hp_ratio))
  end
  state.debug.mode = state.fleeing and "flee" or "kite"

  local snapshot_ok, world_snapshot = pcall(
    sd.world.get_replicated_actors)
  local enemies = steering.live_enemies(
    snapshot_ok and world_snapshot or nil)
  state.debug.live_enemy_count = #enemies

  local direction_x, direction_y, threat_count,
    nearest_threat_distance, edge_pressure =
    steering.kite_direction(
      bot_x,
      bot_y,
      enemies,
      state.arena,
      state.fleeing,
      now_ms,
      state.fleeing and
        CONFIG.flee_threat_radius or CONFIG.threat_radius)
  local attack_window = update_attack_window(now_ms)
  local target = nil
  local target_distance = math.huge
  if type(attack_window) == "table" then
    target, target_distance = steering.nearest_cast_target(
      bot_x,
      bot_y,
      enemies,
      tonumber(attack_window.min_range) or 0.0,
      tonumber(attack_window.max_range) or 0.0)
  end
  local nearest_enemy, nearest_enemy_distance =
    steering.nearest_enemy(bot_x, bot_y, enemies)
  state.debug.nearest_enemy_distance =
    nearest_enemy_distance < math.huge and nearest_enemy_distance or 0.0
  local movement_lookahead = nil
  local move_interval = state.fleeing and
    CONFIG.flee_move_interval_ms or
    (threat_count > 0 and
      CONFIG.kite_move_interval_ms or CONFIG.orbit_move_interval_ms)
  if not state.fleeing and threat_count == 0 and target == nil and
      nearest_enemy ~= nil and
      nearest_enemy_distance >
        math.max(
          tonumber(attack_window and attack_window.max_range) or 0.0,
          1.0) then
    direction_x, direction_y = steering.approach_direction(
      bot_x,
      bot_y,
      nearest_enemy,
      state.arena)
    local desired_center_distance =
      (tonumber(attack_window and attack_window.max_range) or 0.0) +
      (tonumber(nearest_enemy.radius) or 0.0) - 8.0
    movement_lookahead = math.max(
      math.min(
        nearest_enemy_distance - desired_center_distance,
        CONFIG.normal_lookahead),
      28.0)
    move_interval = CONFIG.approach_move_interval_ms
    state.debug.mode = "approach"
  end
  state.debug.threat_count = threat_count
  state.debug.nearest_threat_distance =
    nearest_threat_distance < math.huge and nearest_threat_distance or 0.0
  state.debug.edge_pressure = edge_pressure
  issue_movement(
    bot,
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    movement_lookahead,
    now_ms,
    move_interval)

  state.debug.target_network_actor_id =
    target and target.network_actor_id or 0
  state.debug.target_distance =
    target_distance < math.huge and target_distance or 0.0
  issue_primary_cast(bot, now_ms, target)
end

sd.settings.on_changed(function(key, new_value)
  if key == "kite_radius" then
    CONFIG.threat_radius = new_value
    state.debug.kite_radius = new_value
  elseif key == "offense_enabled" then
    CONFIG.offense_enabled = new_value
    state.debug.offense_enabled = new_value
  elseif key == "think_profile" then
    CONFIG.think_profile = new_value
    CONFIG.think_interval_ms =
      new_value == "relaxed" and 400 or 250
    state.debug.think_profile = new_value
  elseif key == "focus_bot_key" then
    CONFIG.focus_bot_key = new_value
    state.debug.focus_bot_key = new_value
  end
  state.debug.settings_change_count =
    state.debug.settings_change_count + 1
  state.debug.last_settings_change_key = key
end)

sd.settings.on_action("respawn_bot", function()
  if state.focus_active then
    sd.camera.clear_focus()
    state.focus_active = false
    state.focus_key_down = false
  end
  if state.bot ~= nil then
    local ok, removed, error_message = pcall(function()
      return state.bot:despawn()
    end)
    if not ok or removed ~= true then
      error(tostring(error_message or removed or "despawn rejected"))
    end
  end
  state.bot = nil
  state.participant_id = 0
  state.last_spawn_attempt_ms = -CONFIG.spawn_retry_ms
  state.last_position_x = nil
  state.last_position_y = nil
  state.debug.participant_id = 0
  state.debug.respawn_action_count =
    state.debug.respawn_action_count + 1
  state.debug.focus_active = false
  log("respawn requested")
end)

sd.events.on("run.started", function()
  state.death_latched = false
  state.last_position_x = nil
  state.last_position_y = nil
  state.last_move_attempt_ms = -CONFIG.approach_move_interval_ms
  log("run started")
end)

sd.events.on("run.ended", function()
  state.fleeing = false
  state.death_latched = false
  state.last_position_x = nil
  state.last_position_y = nil
  state.debug.active = false
  state.debug.mode = "hub"
  log("run ended")
end)

sd.events.on("runtime.tick", function(event)
  if type(event) ~= "table" then
    return
  end
  update_focus_key()
  local now_ms = tonumber(event.monotonic_milliseconds)
  if now_ms == nil or
      now_ms - state.last_tick_ms < CONFIG.think_interval_ms then
    return
  end
  state.last_tick_ms = now_ms
  think(now_ms)
end)
