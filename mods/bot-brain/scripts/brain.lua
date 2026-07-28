local brain = {}

local PROFILES = {
  skirmisher = {
    cast_interval_ms = 500,
    flee_threshold = 0.35,
    flee_recovery_threshold = 0.45,
  },
  guardian = {
    cast_interval_ms = 500,
    flee_threshold = 0.35,
    flee_recovery_threshold = 0.45,
    leash_radius = 260.0,
    engage_radius = 380.0,
  },
  striker = {
    cast_interval_ms = 300,
    flee_threshold = 0.20,
    flee_recovery_threshold = 0.30,
    engage_radius = 240.0,
    threat_radius = 220.0,
  },
}

local function distance(x1, y1, x2, y2)
  local dx = x2 - x1
  local dy = y2 - y1
  return math.sqrt((dx * dx) + (dy * dy))
end

local function normalize(x, y)
  local length = math.sqrt((x * x) + (y * y))
  if length <= 0.0001 then
    return 0.0, 0.0
  end
  return x / length, y / length
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

local function update_arena(context, now_ms, bot_x, bot_y)
  local shared = context.shared
  if context.arena ~= nil and
      now_ms - context.last_nav_refresh_ms < shared.nav_refresh_ms then
    return context.arena
  end
  context.last_nav_refresh_ms = now_ms
  local ok, grid = pcall(sd.nav.get_grid, 1)
  if not ok then
    grid = nil
  end
  context.arena =
    context.steering.arena_from_grid(grid, bot_x, bot_y)
  context.debug.arena_grid_backed = context.arena.grid_backed
  return context.arena
end

local function update_attack_window(context, now_ms)
  local shared = context.shared
  if context.attack_window ~= nil and
      now_ms - context.last_attack_window_refresh_ms <
        shared.attack_window_refresh_ms then
    return context.attack_window
  end
  context.last_attack_window_refresh_ms = now_ms
  local ok, window = pcall(
    sd.bots.get_primary_attack_window,
    context.participant_id)
  if ok and type(window) == "table" and
      tonumber(window.max_range) ~= nil then
    context.attack_window = window
    context.debug.attack_window_max =
      tonumber(window.max_range) or 0.0
    context.debug.last_error = ""
  end
  return context.attack_window
end

local function choose_pending_skill(context)
  local ok, choices = pcall(
    sd.bots.get_skill_choices,
    context.participant_id)
  if not ok or type(choices) ~= "table" or
      choices.pending ~= true or
      type(choices.options) ~= "table" or
      #choices.options == 0 then
    return
  end

  local generation = tonumber(choices.generation)
  if generation == nil or
      generation == context.last_skill_choice_generation then
    return
  end

  local priority = {
    [64] = 1, -- Health Up
  }
  if context.row.element == "fire" then
    priority[16] = 2 -- Fireball
    priority[18] = 3 -- Explode
    priority[17] = 4 -- Embers
  end
  local selected_index = 1
  local selected_priority = math.huge
  for index, option in ipairs(choices.options) do
    local option_priority =
      priority[tonumber(option.id)] or 100 + index
    if option_priority < selected_priority then
      selected_priority = option_priority
      selected_index = index
    end
  end
  local apply_ok, accepted = pcall(
    sd.bots.choose_skill,
    context.participant_id,
    selected_index,
    generation)
  if apply_ok and accepted == true then
    context.last_skill_choice_generation = generation
    context.debug.skill_choices_accepted =
      context.debug.skill_choices_accepted + 1
    local selected = choices.options[selected_index]
    context.shared.log(
      context,
      "skill choice accepted generation=" .. tostring(generation) ..
      " option_id=" .. tostring(selected and selected.id or -1))
  end
end

local function track_path_distance(context, bot_x, bot_y)
  if context.last_position_x ~= nil and
      context.last_position_y ~= nil then
    local traveled = distance(
      context.last_position_x,
      context.last_position_y,
      bot_x,
      bot_y)
    if traveled <= 350.0 then
      context.debug.kite_path_distance =
        context.debug.kite_path_distance + traveled
    end
  end
  context.last_position_x = bot_x
  context.last_position_y = bot_y
end

local function nearest_human(bot_x, bot_y)
  local ok, multiplayer = pcall(sd.runtime.get_multiplayer_state)
  if not ok or type(multiplayer) ~= "table" then
    return nil
  end
  local nearest = nil
  local nearest_distance = math.huge
  for _, participant in ipairs(multiplayer.participants or {}) do
    local x = tonumber(participant.x)
    local y = tonumber(participant.y)
    if tostring(participant.controller_kind or "") == "Native" and
        participant.runtime_valid == true and
        participant.in_run == true and
        (tonumber(participant.life_current) or 0.0) > 0.0 and
        x ~= nil and y ~= nil then
      local candidate_distance = distance(bot_x, bot_y, x, y)
      if candidate_distance < nearest_distance then
        nearest = {
          participant_id = tonumber(participant.participant_id) or 0,
          x = x,
          y = y,
        }
        nearest_distance = candidate_distance
      end
    end
  end
  return nearest, nearest_distance
end

local function approaching_ward_threats(context, ward, enemies)
  local profile = context.profile
  local approaching = {}
  local next_distances = {}
  for _, enemy in ipairs(enemies) do
    local actor_id = tonumber(enemy.network_actor_id) or 0
    local ward_distance =
      distance(ward.x, ward.y, enemy.x, enemy.y)
    local previous = context.ward_enemy_distances[actor_id]
    next_distances[actor_id] = ward_distance
    if ward_distance <= profile.engage_radius and
        previous ~= nil and ward_distance < previous - 0.5 then
      table.insert(approaching, enemy)
    end
  end
  context.ward_enemy_distances = next_distances
  return approaching
end

local function guardian_idle_direction(context, bot_x, bot_y, ward)
  local profile = context.profile
  local away_x, away_y = normalize(
    bot_x - ward.x,
    bot_y - ward.y)
  if away_x == 0.0 and away_y == 0.0 then
    away_x = 1.0
  end
  local tangent_x, tangent_y = -away_y, away_x
  local ward_distance = distance(bot_x, bot_y, ward.x, ward.y)
  local inward_weight =
    math.max(
      (ward_distance / profile.leash_radius) - 0.55,
      0.0) * 3.0
  return normalize(
    tangent_x + (ward.x - bot_x) /
      math.max(ward_distance, 1.0) * inward_weight,
    tangent_y + (ward.y - bot_y) /
      math.max(ward_distance, 1.0) * inward_weight)
end

local function constrain_to_guardian_leash(context, target, ward)
  if context.row.behavior ~= "guardian" or ward == nil then
    return target
  end
  local offset_x = target.x - ward.x
  local offset_y = target.y - ward.y
  local unit_x, unit_y = normalize(offset_x, offset_y)
  local target_distance =
    math.sqrt((offset_x * offset_x) + (offset_y * offset_y))
  local movement_radius =
    math.max(context.profile.leash_radius - 30.0, 1.0)
  if target_distance <= movement_radius then
    return target
  end
  return {
    x = ward.x + unit_x * movement_radius,
    y = ward.y + unit_y * movement_radius,
  }
end

local function issue_movement(
    context,
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    lookahead_override,
    now_ms,
    move_interval,
    ward)
  local shared = context.shared
  move_interval = tonumber(move_interval) or shared.orbit_move_interval_ms
  if now_ms - context.last_move_attempt_ms < move_interval then
    return false
  end
  context.last_move_attempt_ms = now_ms
  local lookahead = tonumber(lookahead_override) or
    (context.fleeing and shared.flee_lookahead or shared.normal_lookahead)
  local candidates = context.steering.movement_candidates(
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    context.arena,
    lookahead)
  for _, raw_target in ipairs(candidates) do
    local target =
      constrain_to_guardian_leash(context, raw_target, ward)
    local nav_ok, traversable = pcall(
      sd.nav.test_segment,
      bot_x,
      bot_y,
      target.x,
      target.y)
    if not nav_ok then
      context.debug.last_error = tostring(traversable)
    elseif traversable ~= true then
      context.debug.movement_candidates_blocked =
        context.debug.movement_candidates_blocked + 1
    else
      context.debug.move_issued = context.debug.move_issued + 1
      local ok, accepted, error_message = pcall(function()
        return context.bot:move_to(target.x, target.y)
      end)
      if ok and accepted == true then
        context.debug.move_accepted =
          context.debug.move_accepted + 1
        context.debug.destination_x = target.x
        context.debug.destination_y = target.y
        context.debug.last_error = ""
        return true
      end
      context.debug.last_error =
        tostring(ok and error_message or accepted or "move rejected")
    end
  end
  return false
end

local function issue_primary_cast(context, now_ms, target)
  if not context.shared.offense_enabled or
      context.fleeing or target == nil or
      now_ms - context.last_cast_attempt_ms <
        context.profile.cast_interval_ms then
    return
  end
  context.last_cast_attempt_ms = now_ms
  context.debug.cast_issued = context.debug.cast_issued + 1
  local ok, accepted, error_message = pcall(function()
    return context.bot:cast(
      0,
      target.x,
      target.y,
      context.shared.cast_hold_ms)
  end)
  if ok and accepted == true then
    context.debug.cast_accepted =
      context.debug.cast_accepted + 1
    context.debug.last_error = ""
    context.shared.log(
      context,
      "cast accepted count=" ..
      tostring(context.debug.cast_accepted) ..
      " target=" .. tostring(target.network_actor_id))
  else
    context.debug.last_error =
      tostring(ok and error_message or accepted or "cast rejected")
  end
end

local function update_wave_debug(context)
  local ok, wave = pcall(sd.waves.get_state)
  if not ok or type(wave) ~= "table" then
    return nil
  end
  local wave_number = tonumber(wave.wave) or 0
  context.debug.wave = wave_number
  if wave_number ~= context.last_wave then
    context.last_wave = wave_number
    context.shared.log(
      context,
      "wave=" .. tostring(wave_number) ..
      " phase=" .. tostring(wave.phase or ""))
  end
  return wave
end

function brain.new(row, roster_index, shared, steering)
  local profile = assert(PROFILES[row.behavior])
  return {
    row = {
      name = row.name,
      element = row.element,
      behavior = row.behavior,
      discipline = row.discipline,
    },
    roster_index = roster_index,
    shared = shared,
    steering = steering,
    profile = profile,
    bot = nil,
    participant_id = 0,
    last_spawn_attempt_ms = -shared.spawn_retry_ms,
    last_nav_refresh_ms = -shared.nav_refresh_ms,
    last_attack_window_refresh_ms =
      -shared.attack_window_refresh_ms,
    last_cast_attempt_ms = -profile.cast_interval_ms,
    last_move_attempt_ms = -shared.approach_move_interval_ms,
    last_skill_choice_generation = -1,
    last_position_x = nil,
    last_position_y = nil,
    arena = nil,
    attack_window = nil,
    fleeing = false,
    death_latched = false,
    last_wave = -1,
    ward_enemy_distances = {},
    debug = {
      roster_index = roster_index,
      name = row.name,
      element = row.element,
      behavior = row.behavior,
      discipline = row.discipline,
      authority = false,
      active = false,
      participant_id = 0,
      wave = 0,
      mode = "waiting",
      hp = 0.0,
      max_hp = 0.0,
      hp_ratio = 0.0,
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
      flee_threshold = profile.flee_threshold,
      flee_recovery_threshold = profile.flee_recovery_threshold,
      cast_interval_ms = profile.cast_interval_ms,
      engage_radius = profile.engage_radius or shared.threat_radius,
      guardian_leash_radius = profile.leash_radius or 0.0,
      guardian_ward_distance = 0.0,
      guardian_human_participant_id = 0,
      guardian_engaging = false,
      flee_transition_count = 0,
      last_error = "",
    },
  }
end

function brain.reset_run(context, started)
  context.fleeing = false
  context.death_latched = false
  context.last_position_x = nil
  context.last_position_y = nil
  context.last_move_attempt_ms =
    -context.shared.approach_move_interval_ms
  context.ward_enemy_distances = {}
  if not started then
    context.debug.active = false
    context.debug.mode = "hub"
  end
end

function brain.think(context, now_ms, authority)
  context.debug.authority = authority == true
  if not authority then
    context.debug.active = false
    context.debug.mode = "observer"
    return
  end
  if context.bot == nil or context.participant_id <= 0 then
    context.debug.active = false
    context.debug.mode = "spawning"
    return
  end

  local wave = update_wave_debug(context)
  choose_pending_skill(context)
  if not current_scene_is_run() then
    context.debug.active = false
    context.debug.mode = "hub"
    context.last_position_x = nil
    context.last_position_y = nil
    return
  end

  local position_ok, bot_x, bot_y = pcall(function()
    return context.bot:position()
  end)
  local hp_ok, hp = pcall(function() return context.bot:hp() end)
  local max_hp_ok, max_hp =
    pcall(function() return context.bot:max_hp() end)
  if not position_ok or tonumber(bot_x) == nil or
      tonumber(bot_y) == nil or
      not hp_ok or tonumber(hp) == nil or
      not max_hp_ok or tonumber(max_hp) == nil or
      max_hp <= 0.0 then
    context.debug.active = false
    context.debug.mode = "materializing"
    return
  end

  context.debug.hp = hp
  context.debug.max_hp = max_hp
  context.debug.hp_ratio = hp / max_hp
  local alive_ok, alive =
    pcall(function() return context.bot:alive() end)
  if hp <= 0.0 or (alive_ok and alive ~= true) then
    context.debug.active = false
    context.debug.mode = "dead"
    if not context.death_latched and
        type(wave) == "table" and
        (tonumber(wave.wave) or 0) > 0 then
      context.death_latched = true
      context.shared.log(
        context,
        "death wave=" .. tostring(context.debug.wave) ..
        " hp=" .. tostring(hp))
    end
    return
  end

  context.debug.active = true
  context.debug.think_count = context.debug.think_count + 1
  track_path_distance(context, bot_x, bot_y)
  update_arena(context, now_ms, bot_x, bot_y)

  local hp_ratio = hp / max_hp
  if context.fleeing then
    if hp_ratio >= context.profile.flee_recovery_threshold then
      context.fleeing = false
      context.shared.log(
        context,
        "mode=normal hp_ratio=" .. tostring(hp_ratio))
    end
  elseif hp_ratio < context.profile.flee_threshold then
    context.fleeing = true
    context.debug.flee_transition_count =
      context.debug.flee_transition_count + 1
    context.shared.log(
      context,
      "mode=flee hp_ratio=" .. tostring(hp_ratio))
  end
  context.debug.mode = context.fleeing and "flee" or "kite"

  local snapshot_ok, world_snapshot =
    pcall(sd.world.get_replicated_actors)
  local all_enemies = context.steering.live_enemies(
    snapshot_ok and world_snapshot or nil)
  context.debug.live_enemy_count = #all_enemies

  local ward = nil
  local enemies = all_enemies
  if context.row.behavior == "guardian" then
    local ward_distance
    ward, ward_distance = nearest_human(bot_x, bot_y)
    context.debug.guardian_human_participant_id =
      ward and ward.participant_id or 0
    context.debug.guardian_ward_distance =
      ward_distance and ward_distance < math.huge and
        ward_distance or 0.0
    if ward ~= nil then
      local ward_threats = approaching_ward_threats(
        context,
        ward,
        all_enemies)
      enemies = ward_threats
      context.debug.guardian_engaging =
        not context.fleeing and #ward_threats > 0
      if context.fleeing then
        enemies = all_enemies
      end
    else
      enemies = {}
      context.debug.guardian_engaging = false
    end
  end

  local threat_radius =
    context.profile.threat_radius or context.shared.threat_radius
  if context.fleeing then
    threat_radius = context.shared.flee_threat_radius
  end
  local direction_x, direction_y, threat_count,
    nearest_threat_distance, edge_pressure =
    context.steering.kite_direction(
      bot_x,
      bot_y,
      enemies,
      context.arena,
      context.fleeing,
      now_ms,
      threat_radius)

  if context.row.behavior == "guardian" and ward ~= nil and
      not context.fleeing and #enemies == 0 then
    direction_x, direction_y =
      guardian_idle_direction(context, bot_x, bot_y, ward)
    context.debug.mode = "guard"
  end
  if context.row.behavior == "guardian" and ward ~= nil and
      context.debug.guardian_ward_distance >
        context.profile.leash_radius * 0.82 then
    direction_x, direction_y =
      normalize(ward.x - bot_x, ward.y - bot_y)
    context.debug.mode = "return_to_ward"
  end

  local attack_window = update_attack_window(context, now_ms)
  local target = nil
  local target_distance = math.huge
  local effective_attack_range = 0.0
  if type(attack_window) == "table" then
    effective_attack_range =
      tonumber(attack_window.max_range) or 0.0
    if context.profile.engage_radius ~= nil then
      effective_attack_range =
        math.min(
          effective_attack_range,
          context.profile.engage_radius)
    end
    target, target_distance =
      context.steering.nearest_cast_target(
        bot_x,
        bot_y,
        enemies,
        tonumber(attack_window.min_range) or 0.0,
        effective_attack_range)
  end
  local nearest_enemy, nearest_enemy_distance =
    context.steering.nearest_enemy(bot_x, bot_y, enemies)
  context.debug.nearest_enemy_distance =
    nearest_enemy_distance < math.huge and
      nearest_enemy_distance or 0.0

  local movement_lookahead = nil
  local move_interval = context.fleeing and
    context.shared.flee_move_interval_ms or
    (threat_count > 0 and
      context.shared.kite_move_interval_ms or
      context.shared.orbit_move_interval_ms)
  if not context.fleeing and threat_count == 0 and
      target == nil and nearest_enemy ~= nil and
      nearest_enemy_distance >
        math.max(
          effective_attack_range,
          1.0) then
    direction_x, direction_y =
      context.steering.approach_direction(
        bot_x,
        bot_y,
        nearest_enemy,
        context.arena)
    local desired_center_distance =
      effective_attack_range +
      (tonumber(nearest_enemy.radius) or 0.0) - 8.0
    movement_lookahead = math.max(
      math.min(
        nearest_enemy_distance - desired_center_distance,
        context.shared.normal_lookahead),
      28.0)
    move_interval = context.shared.approach_move_interval_ms
    context.debug.mode = "approach"
  end

  context.debug.threat_count = threat_count
  context.debug.nearest_threat_distance =
    nearest_threat_distance < math.huge and
      nearest_threat_distance or 0.0
  context.debug.edge_pressure = edge_pressure
  issue_movement(
    context,
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    movement_lookahead,
    now_ms,
    move_interval,
    ward)

  context.debug.target_network_actor_id =
    target and target.network_actor_id or 0
  context.debug.target_distance =
    target_distance < math.huge and target_distance or 0.0
  issue_primary_cast(context, now_ms, target)
end

brain.profiles = PROFILES

return brain
