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
  learned = {
    cast_interval_ms = 100,
    flee_threshold = 0.30,
    flee_recovery_threshold = 0.45,
  },
}

local CAST_MANA_HOLD_LOW_RATIO = 0.10
local CAST_MANA_RESUME_HIGH_RATIO = 0.80

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

local function current_run_scene()
  local ok, scene = pcall(sd.world.get_scene)
  if not ok or type(scene) ~= "table" then
    return false, ""
  end
  local name = tostring(scene.name or "")
  local kind = tostring(scene.kind or "")
  local is_run = name == "testrun" or kind == "run"
  return is_run, kind .. ":" .. name
end

local function update_arena(
    context,
    now_ms,
    bot_x,
    bot_y,
    scene_key)
  local shared = context.shared
  shared.policy_geometry:refresh(now_ms, scene_key)
  local geometry_revision =
    shared.policy_geometry.revision
  if context.arena ~= nil and
      context.arena_geometry_revision == geometry_revision then
    return context.arena
  end
  context.arena =
    context.steering.arena_from_grid(
      shared.policy_geometry.grid,
      bot_x,
      bot_y)
  context.arena_geometry_revision = geometry_revision
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

local function read_skill_choices(context)
  local reader = context.read_skill_choices
  local ok, choices
  if type(reader) == "function" then
    ok, choices = pcall(reader, context)
  else
    ok, choices = pcall(
      sd.bots.get_skill_choices,
      context.participant_id)
  end
  if not ok or type(choices) ~= "table" or
      choices.pending ~= true or
      type(choices.options) ~= "table" or
      #choices.options == 0 then
    return type(choices) == "table" and choices or {}
  end
  return choices
end

local function read_own_mana(context)
  if context.local_player ~= true then
    local snapshot_ok, snapshot = pcall(
      sd.bots.get_participant_state,
      context.participant_id)
    if not snapshot_ok or type(snapshot) ~= "table" or
        type(snapshot.mana_reserve_active) ~= "boolean" then
      return nil, nil, nil
    end
    local current = tonumber(snapshot.mp)
    local maximum = tonumber(snapshot.max_mp)
    if current == nil or maximum == nil or
        current ~= current or maximum <= 0.0 then
      return nil, nil, nil
    end
    local attainable_maximum =
      tonumber(snapshot.mana_attainable_max_mp) or maximum
    local resume_threshold =
      tonumber(snapshot.mana_resume_threshold_mp) or
        attainable_maximum * CAST_MANA_RESUME_HIGH_RATIO
    local attainable_cap_detected =
      snapshot.mana_attainable_cap_detected == true
    return current, maximum, snapshot.mana_reserve_active,
      attainable_maximum, resume_threshold,
      attainable_cap_detected
  end

  local handle_ok, current, maximum = pcall(function()
    return context.bot:mp(), context.bot:max_mp()
  end)
  current = tonumber(current)
  maximum = tonumber(maximum)
  if handle_ok and current ~= nil and maximum ~= nil and
      current == current and maximum > 0.0 then
    return current, maximum, nil, maximum,
      maximum * CAST_MANA_RESUME_HIGH_RATIO, false
  end
  return nil, nil, nil
end

local function update_mana_cast_hold(context)
  local current, maximum, native_reserve_active,
    attainable_maximum, resume_threshold,
    attainable_cap_detected =
    read_own_mana(context)
  if current == nil or maximum == nil then
    context.mana_sample_valid = false
    context.debug.mana_sample_valid = false
    return false
  end

  local ratio = math.max(0.0, math.min(current / maximum, 1.0))
  context.mana_sample_valid = true
  context.debug.mana_sample_valid = true
  context.debug.mp = current
  context.debug.max_mp = maximum
  context.debug.mp_ratio = ratio
  context.debug.mana_attainable_max_mp = attainable_maximum
  context.debug.mana_resume_threshold_mp = resume_threshold
  context.debug.mana_attainable_cap_detected =
    attainable_cap_detected
  local next_hold = context.mana_cast_hold
  if native_reserve_active ~= nil then
    next_hold = native_reserve_active
  elseif not next_hold and
      ratio <= CAST_MANA_HOLD_LOW_RATIO then
    next_hold = true
  elseif next_hold and
      ratio >= CAST_MANA_RESUME_HIGH_RATIO then
    next_hold = false
  end
  context.mana_fleeing = next_hold
  context.debug.mana_fleeing = next_hold

  if not context.mana_cast_hold and next_hold then
    context.mana_cast_hold = true
    context.debug.mana_cast_hold = true
    context.debug.mana_hold_start_count =
      context.debug.mana_hold_start_count + 1
    context.shared.log(
      context,
      "mana hold-start participant_id=" ..
      tostring(context.participant_id) ..
      " current=" .. tostring(current) ..
      " maximum=" .. tostring(maximum) ..
      " ratio=" .. tostring(ratio) ..
      " attainable_maximum=" ..
        tostring(attainable_maximum) ..
      " resume_threshold=" .. tostring(resume_threshold) ..
      " attainable_cap_detected=" ..
        tostring(attainable_cap_detected) ..
      " low=" .. tostring(CAST_MANA_HOLD_LOW_RATIO) ..
      " high=" .. tostring(CAST_MANA_RESUME_HIGH_RATIO))
  elseif context.mana_cast_hold and not next_hold then
    context.mana_cast_hold = false
    context.debug.mana_cast_hold = false
    context.debug.mana_hold_end_count =
      context.debug.mana_hold_end_count + 1
    context.shared.log(
      context,
      "mana hold-end participant_id=" ..
      tostring(context.participant_id) ..
      " current=" .. tostring(current) ..
      " maximum=" .. tostring(maximum) ..
      " ratio=" .. tostring(ratio) ..
      " attainable_maximum=" ..
        tostring(attainable_maximum) ..
      " resume_threshold=" .. tostring(resume_threshold) ..
      " attainable_cap_detected=" ..
        tostring(attainable_cap_detected) ..
      " low=" .. tostring(CAST_MANA_HOLD_LOW_RATIO) ..
      " high=" .. tostring(CAST_MANA_RESUME_HIGH_RATIO))
  end
  return true
end

local function update_flee_state(context, hp_ratio)
  if context.hp_fleeing then
    if hp_ratio >= context.profile.flee_recovery_threshold then
      context.hp_fleeing = false
      context.shared.log(
        context,
        "mode=normal hp_ratio=" .. tostring(hp_ratio))
    end
  elseif hp_ratio < context.profile.flee_threshold then
    context.hp_fleeing = true
    context.debug.flee_transition_count =
      context.debug.flee_transition_count + 1
    context.shared.log(
      context,
      "mode=flee hp_ratio=" .. tostring(hp_ratio))
  end
  context.mana_fleeing = context.mana_cast_hold
  context.fleeing = context.hp_fleeing or context.mana_fleeing
  context.debug.hp_fleeing = context.hp_fleeing
  context.debug.mana_fleeing = context.mana_fleeing
  local mode = context.mana_fleeing and "mana_flee" or
    (context.hp_fleeing and "flee" or "kite")
  context.debug.mode = mode
  return mode
end

local function should_use_scripted_movement(context)
  return context.row.behavior ~= "learned" or context.mana_fleeing
end

local function choose_pending_skill(context, choices)
  if type(choices) ~= "table" or
      choices.pending ~= true or
      type(choices.options) ~= "table" or
      #choices.options == 0 then
    return false
  end
  local generation = tonumber(choices.generation)
  if generation == nil or
      generation == context.last_skill_choice_generation then
    return false
  end

  local selected_index = math.random(1, #choices.options)
  local selected = choices.options[selected_index]
  local offered = {}
  for _, option in ipairs(choices.options) do
    offered[#offered + 1] =
      tostring(type(option) == "table" and option.id or -1)
  end
  local apply_ok, accepted
  if type(context.choose_skill) == "function" then
    apply_ok, accepted = pcall(
      context.choose_skill,
      context,
      selected_index,
      generation,
      selected)
  else
    apply_ok, accepted = pcall(
      sd.bots.choose_skill,
      context.participant_id,
      selected_index,
      generation)
  end
  if apply_ok and accepted == true then
    context.last_skill_choice_generation = generation
    context.debug.skill_choices_accepted =
      context.debug.skill_choices_accepted + 1
    context.shared.log(
      context,
      "skill pick participant_id=" ..
      tostring(context.participant_id) ..
      " wave=" .. tostring(context.debug.wave or 0) ..
      " generation=" .. tostring(generation) ..
      " offered=[" .. table.concat(offered, ",") .. "]" ..
      " chosen_index=" .. tostring(selected_index) ..
      " chosen_id=" .. tostring(selected and selected.id or -1))
    return true
  else
    context.debug.last_error =
      tostring(accepted or "skill choice rejected")
    context.shared.log(
      context,
      "skill pick failed participant_id=" ..
      tostring(context.participant_id) ..
      " wave=" .. tostring(context.debug.wave or 0) ..
      " generation=" .. tostring(generation) ..
      " offered=[" .. table.concat(offered, ",") .. "]" ..
      " chosen_index=" .. tostring(selected_index) ..
      " chosen_id=" .. tostring(selected and selected.id or -1) ..
      " error=" .. tostring(accepted))
  end
  return false
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

local function nearest_human(
    bot_x,
    bot_y,
    excluded_participant_id)
  local ok, multiplayer = pcall(sd.runtime.get_multiplayer_state)
  if not ok or type(multiplayer) ~= "table" then
    return nil
  end
  local nearest = nil
  local nearest_distance = math.huge
  for _, participant in ipairs(multiplayer.participants or {}) do
    local x = tonumber(participant.x)
    local y = tonumber(participant.y)
    if tonumber(participant.participant_id) ~=
          tonumber(excluded_participant_id) and
        tostring(participant.controller_kind or "") == "Native" and
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

local function constrain_to_guardian_leash(
    context,
    bot_x,
    bot_y,
    target,
    ward)
  if context.row.behavior ~= "guardian" or ward == nil then
    return target
  end
  return context.steering.constrain_to_guardian_leash(
    bot_x,
    bot_y,
    target,
    ward,
    context.profile.leash_radius)
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
      constrain_to_guardian_leash(
        context,
        bot_x,
        bot_y,
        raw_target,
        ward)
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
      context.fleeing or
      not context.mana_sample_valid or
      context.mana_cast_hold or target == nil or
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
      context.shared.cast_hold_ms,
      target)
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

local function issue_policy_movement(
    context,
    capture,
    decision,
    now_ms)
  local memory = context.policy_memory
  local action = decision.movement
  context.debug.policy_movement_action =
    decision.movement_action
  context.debug.policy_movement_name = action.name
  context.debug.policy_movement_probability =
    decision.movement_probability
  if decision.movement_action == 0 then
    if memory.previous_move_action ~= 0 then
      context.debug.policy_stop_issued =
        context.debug.policy_stop_issued + 1
      local ok, accepted = pcall(function()
        return context.bot:stop()
      end)
      if ok and accepted == true then
        context.debug.policy_stop_accepted =
          context.debug.policy_stop_accepted + 1
      end
    end
  else
    local target =
      capture.movement_targets[
        decision.movement_action + 1]
    context.debug.move_issued =
      context.debug.move_issued + 1
    local ok, accepted, error_message = pcall(function()
      return context.bot:move_to(target.x, target.y)
    end)
    if ok and accepted == true then
      context.debug.move_accepted =
        context.debug.move_accepted + 1
      context.debug.destination_x = target.x
      context.debug.destination_y = target.y
      context.debug.last_error = ""
      memory.last_move_ms = now_ms
    else
      context.debug.last_error =
        tostring(
          ok and error_message or accepted or
          "policy move rejected")
    end
  end
  memory.previous_move_action =
    decision.movement_action
  memory.previous_move_x = action.x
  memory.previous_move_y = action.y
end

local function issue_policy_cast(
    context,
    capture,
    decision,
    target,
    now_ms)
  local memory = context.policy_memory
  local action = decision.cast
  context.debug.policy_cast_action = decision.cast_action
  context.debug.policy_cast_name = action.name
  context.debug.policy_cast_probability =
    decision.cast_probability
  memory.previous_cast_action = decision.cast_action
  if decision.cast_action == 0 or target == nil or
      not context.mana_sample_valid or
      context.mana_cast_hold then
    return
  end

  context.last_cast_attempt_ms = now_ms
  context.debug.cast_issued = context.debug.cast_issued + 1
  local ok, accepted, error_message = pcall(function()
    return context.bot:cast(
      action.skill_slot,
      target.x,
      target.y,
      context.shared.cast_hold_ms,
      target)
  end)
  if ok and accepted == true then
    context.debug.cast_accepted =
      context.debug.cast_accepted + 1
    context.debug.last_error = ""
    memory.last_cast_ms = now_ms
    if action.skill_slot > 0 and
        target.in_primary_range ~= true then
      context.debug.secondary_beyond_primary_accepted =
        context.debug.secondary_beyond_primary_accepted + 1
      context.shared.log(
        context,
        "policy secondary accepted slot=" ..
        tostring(action.skill_slot) ..
        " target=" ..
        tostring(target.network_actor_id) ..
        " contact_distance=" ..
        tostring(target.contact_distance) ..
        " primary_max=" ..
        tostring(capture.loadout.primary.range_max))
    end
  else
    context.debug.last_error =
      tostring(
        ok and error_message or accepted or
        "policy cast rejected")
  end
end

local function request_nearby_pickup(
    context,
    capture,
    now_ms)
  if capture.loadout.pickup_range <= 0.0 then
    return
  end

  local memory = context.policy_memory
  local interval =
    context.shared.policy_spec.pickup_request_interval_ms
  if memory.last_pickup_request_ms ~= nil and
      now_ms - memory.last_pickup_request_ms < interval then
    return
  end

  for _, pickup in ipairs(capture.pickups) do
    local pickup_id = tonumber(pickup.network_drop_id) or 0
    local native_range =
      capture.loadout.pickup_range *
      pickup.pickup_range_multiplier
    local previous = memory.pickup_request_ms[pickup_id]
    if pickup_id > 0 and pickup.distance <= native_range and
        memory.pickup_request_accepted[pickup_id] ~= true and
        (previous == nil or now_ms - previous >= interval) then
      memory.last_pickup_request_ms = now_ms
      memory.pickup_request_ms[pickup_id] = now_ms
      context.debug.pickup_request_issued =
        context.debug.pickup_request_issued + 1
      context.debug.last_pickup_request_distance =
        pickup.distance
      context.debug.last_pickup_request_x = capture.bot_x
      context.debug.last_pickup_request_y = capture.bot_y
      local ok, accepted, sequence_or_error
      if type(context.request_loot_pickup) == "function" then
        ok, accepted, sequence_or_error = pcall(
          context.request_loot_pickup,
          context,
          pickup_id)
      else
        ok, accepted, sequence_or_error = pcall(
          sd.world.request_loot_pickup,
          pickup_id,
          context.participant_id)
      end
      if ok and accepted == true then
        memory.pickup_request_accepted[pickup_id] = true
        context.debug.pickup_request_accepted =
          context.debug.pickup_request_accepted + 1
        context.debug.last_pickup_request_sequence =
          tonumber(sequence_or_error) or 0
        context.debug.last_pickup_network_drop_id =
          pickup_id
        context.shared.log(
          context,
          "pickup request queued network_drop_id=" ..
          tostring(pickup_id) ..
          " sequence=" ..
          tostring(
            context.debug.last_pickup_request_sequence))
      else
        context.debug.last_pickup_error =
          tostring(
            ok and sequence_or_error or accepted or
            "pickup request rejected")
      end
      return
    end
  end
end

local function think_with_policy(
    context,
    frame)
  local shared = context.shared
  local capture = shared.policy_observation.capture(
    shared.policy_observation_builder,
    context,
    frame)
  local selected_target = nil
  local target_switched = false
  local decision = shared.policy_runtime:forward(
    capture.values,
    capture.movement_mask,
    capture.target_mask,
    function(target_action)
      selected_target, target_switched =
        shared.policy_observation.select_target(
          shared.policy_observation_builder,
          context,
          capture,
          target_action)
      return shared.policy_observation.build_cast_mask(
        shared.policy_observation_builder,
        capture,
        selected_target)
    end,
    shared.policy_training.enabled == true)
  context.debug.mode = "learned"
  context.debug.policy_generation = decision.generation
  context.debug.policy_decision_count =
    context.debug.policy_decision_count + 1
  context.debug.policy_value = decision.value
  context.debug.policy_log_probability =
    decision.log_probability
  context.debug.secondary_slot_count =
    #capture.loadout.secondaries
  context.debug.policy_target_action =
    decision.target_action
  context.debug.policy_target_name =
    decision.target.name
  context.debug.policy_target_probability =
    decision.target_probability
  context.debug.policy_target_switched =
    target_switched
  context.debug.target_network_actor_id =
    selected_target and
      selected_target.network_actor_id or 0
  context.debug.target_distance =
    selected_target and
      selected_target.distance or 0.0
  context.debug.policy_observation_version =
    shared.policy_spec.observation_version
  context.debug.policy_observation_count =
    #capture.values
  context.debug.policy_observation_finite = true
  context.debug.policy_observation = capture.values
  context.debug.policy_loadout = capture.loadout
  context.debug.policy_snapshot = capture.snapshot
  context.debug.policy_selected_target = selected_target
  context.debug.policy_capture_target_id =
    capture.current_target and
      capture.current_target.network_actor_id or 0
  context.debug.policy_bot_x = capture.bot_x
  context.debug.policy_bot_y = capture.bot_y
  context.debug.policy_movement_mask =
    capture.movement_mask
  context.debug.policy_movement_targets =
    capture.movement_targets
  context.debug.policy_target_mask =
    capture.target_mask
  context.debug.policy_cast_mask =
    decision.cast_mask
  context.debug.policy_selected_actions_legal =
    capture.movement_mask[
      decision.movement_action + 1] == true and
    capture.target_mask[
      decision.target_action + 1] == true and
    decision.cast_mask[
      decision.cast_action + 1] == true
  context.debug.primary_welded =
    capture.loadout.primary.welded == true
  context.debug.primary_build_id =
    capture.loadout.primary.build_id
  context.debug.primary_range_max =
    capture.loadout.primary.range_max
  context.debug.pickup_observation_count =
    #capture.pickups
  context.debug.pickup_observation_first_id =
    capture.pickups[1] and
      capture.pickups[1].network_drop_id or 0
  context.debug.pickup_range =
    capture.loadout.pickup_range
  context.debug.pickup_distance =
    capture.pickups[1] and
      capture.pickups[1].distance or 0.0
  context.debug.loot_authority_participant_id =
    tonumber(capture.loot.authority_participant_id) or 0
  context.debug.ally_observation_count =
    #capture.allies
  context.debug.current_target_slot = 0
  context.debug.enemy_slot_actor_ids = {}
  for slot, enemy in ipairs(capture.enemy_slots) do
    context.debug.enemy_slot_actor_ids[slot] =
      enemy and enemy.network_actor_id or 0
    if selected_target ~= nil and
        enemy.network_actor_id ==
          selected_target.network_actor_id then
      context.debug.current_target_slot = slot
    end
  end
  if target_switched and selected_target ~= nil then
    shared.log(
      context,
      "policy target selected network_actor_id=" ..
      tostring(selected_target.network_actor_id) ..
      " slot=" ..
      tostring(context.debug.current_target_slot))
  end

  issue_policy_movement(
    context,
    capture,
    decision,
    frame.now_ms)
  issue_policy_cast(
    context,
    capture,
    decision,
    selected_target,
    frame.now_ms)
  request_nearby_pickup(
    context,
    capture,
    frame.now_ms)
  shared.policy_training:record(
    context,
    capture,
    decision,
    frame.simulation_tick)
  context.last_policy_metrics = capture.metrics
  return selected_target
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
    last_attack_window_refresh_ms =
      -shared.attack_window_refresh_ms,
    last_cast_attempt_ms = -profile.cast_interval_ms,
    last_move_attempt_ms = -shared.approach_move_interval_ms,
    last_think_ms = -math.max(
      shared.think_interval_ms,
      shared.policy_interval_ms),
    last_skill_choice_generation = -1,
    mana_sample_valid = false,
    mana_cast_hold = false,
    hp_fleeing = false,
    mana_fleeing = false,
    last_position_x = nil,
    last_position_y = nil,
    arena = nil,
    arena_geometry_revision = -1,
    attack_window = nil,
    fleeing = false,
    death_latched = false,
    last_wave = -1,
    ward_enemy_distances = {},
    policy_pending = nil,
    last_policy_metrics = nil,
    policy_memory =
      shared.policy_observation.new_memory(),
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
      mp = 0.0,
      max_mp = 0.0,
      mp_ratio = 0.0,
      mana_sample_valid = false,
      mana_cast_hold = false,
      hp_fleeing = false,
      mana_fleeing = false,
      mana_attainable_max_mp = 0.0,
      mana_resume_threshold_mp = 0.0,
      mana_attainable_cap_detected = false,
      mana_hold_start_count = 0,
      mana_hold_end_count = 0,
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
      policy_generation = 0,
      policy_decision_count = 0,
      policy_movement_action = 0,
      policy_movement_name = "idle",
      policy_movement_probability = 0.0,
      policy_cast_action = 0,
      policy_cast_name = "none",
      policy_cast_probability = 0.0,
      policy_target_action = 0,
      policy_target_name = "keep_current",
      policy_target_probability = 0.0,
      policy_target_switched = false,
      policy_value = 0.0,
      policy_log_probability = 0.0,
      policy_stop_issued = 0,
      policy_stop_accepted = 0,
      inventory_distinct_count = 0,
      inventory_stack_count = 0,
      potion_stack_count = 0,
      secondary_slot_count = 0,
      pickup_request_issued = 0,
      pickup_request_accepted = 0,
      last_pickup_request_sequence = 0,
      last_pickup_network_drop_id = 0,
      last_pickup_request_distance = 0.0,
      last_pickup_request_x = 0.0,
      last_pickup_request_y = 0.0,
      last_pickup_error = "",
      policy_observation_version = 0,
      policy_observation_count = 0,
      policy_observation_finite = false,
      policy_observation = {},
      policy_loadout = {},
      policy_snapshot = {},
      policy_selected_target = nil,
      policy_capture_target_id = 0,
      policy_bot_x = 0.0,
      policy_bot_y = 0.0,
      policy_movement_mask = {},
      policy_movement_targets = {},
      policy_target_mask = {},
      policy_cast_mask = {},
      policy_selected_actions_legal = false,
      primary_welded = false,
      primary_build_id = 0,
      primary_range_max = 0.0,
      current_target_slot = 0,
      enemy_slot_actor_ids = {},
      pickup_observation_count = 0,
      pickup_observation_first_id = 0,
      pickup_range = 0.0,
      pickup_distance = 0.0,
      loot_authority_participant_id = 0,
      ally_observation_count = 0,
      secondary_beyond_primary_accepted = 0,
      last_error = "",
    },
  }
end

function brain.poll_skill_choice(context)
  if context.bot == nil or context.participant_id <= 0 then
    return false
  end
  update_wave_debug(context)
  return choose_pending_skill(
    context,
    read_skill_choices(context))
end

function brain.reset_run(context, started)
  if context.row.behavior == "learned" and not started then
    context.shared.policy_training:terminal(
      context,
      context.last_policy_metrics)
  else
    context.policy_pending = nil
  end
  context.fleeing = false
  context.hp_fleeing = false
  context.mana_fleeing = false
  context.death_latched = false
  context.mana_sample_valid = false
  context.mana_cast_hold = false
  context.debug.mana_sample_valid = false
  context.debug.mana_cast_hold = false
  context.debug.hp_fleeing = false
  context.debug.mana_fleeing = false
  context.last_position_x = nil
  context.last_position_y = nil
  context.last_move_attempt_ms =
    -context.shared.approach_move_interval_ms
  context.ward_enemy_distances = {}
  context.last_policy_metrics = nil
  context.policy_memory =
    context.shared.policy_observation.new_memory()
  context.arena = nil
  context.arena_geometry_revision = -1
  context.attack_window = nil
  if not started then
    context.debug.active = false
    context.debug.mode = "hub"
  end
end

function brain.think(
    context,
    now_ms,
    authority,
    simulation_tick)
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

  local think_interval =
    context.row.behavior == "learned" and
      context.shared.policy_interval_ms or
      context.shared.think_interval_ms
  if now_ms - context.last_think_ms < think_interval then
    return
  end
  context.last_think_ms = now_ms

  local wave = update_wave_debug(context)
  local is_run, scene_key = current_run_scene()
  if not is_run then
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
  update_mana_cast_hold(context)
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
    if context.row.behavior == "learned" then
      local metrics = context.last_policy_metrics or {}
      metrics.hp_ratio = 0.0
      metrics.alive = false
      context.shared.policy_training:terminal(
        context,
        metrics)
      context.last_policy_metrics = nil
    end
    return
  end

  context.debug.active = true
  local prewave =
    type(wave) ~= "table" or
    (tonumber(wave.wave) or 0) <= 0
  local manual_policy_run = false
  if prewave and context.row.behavior == "learned" then
    local manual_ok, manual_state =
      pcall(sd.gameplay.get_manual_enemy_spawner_state)
    manual_policy_run =
      manual_ok and type(manual_state) == "table" and
      manual_state.manual_mode == true
  end
  if prewave and not manual_policy_run then
    context.debug.mode = "prewave"
    context.fleeing = false
    context.last_position_x = nil
    context.last_position_y = nil
    return
  end

  context.debug.think_count = context.debug.think_count + 1
  track_path_distance(context, bot_x, bot_y)
  update_arena(
    context,
    now_ms,
    bot_x,
    bot_y,
    scene_key)

  local hp_ratio = hp / max_hp
  update_flee_state(context, hp_ratio)

  local snapshot_ok, world_snapshot =
    pcall(sd.world.get_replicated_actors)
  local snapshot_actors =
    snapshot_ok and type(world_snapshot) == "table" and
      world_snapshot.actors or nil
  if type(snapshot_actors) ~= "table" or
      #snapshot_actors == 0 then
    local actors_ok, local_actors =
      pcall(sd.world.list_actors)
    if actors_ok and type(local_actors) == "table" then
      world_snapshot = { actors = local_actors }
      snapshot_ok = true
    end
  end
  local all_enemies = context.steering.live_enemies(
    snapshot_ok and world_snapshot or nil)
  context.debug.live_enemy_count = #all_enemies

  local ward = nil
  local enemies = all_enemies
  if context.row.behavior == "guardian" then
    local ward_distance
    ward, ward_distance = nearest_human(
      bot_x,
      bot_y,
      context.participant_id)
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
      not context.fleeing and
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
  if not context.fleeing and target == nil and nearest_enemy ~= nil and
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
    movement_lookahead = math.max(
      math.min(
        nearest_enemy_distance -
          (effective_attack_range - 8.0),
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
  if not should_use_scripted_movement(context) then
    think_with_policy(
      context,
      {
        now_ms = now_ms,
        simulation_tick = simulation_tick,
        bot_x = bot_x,
        bot_y = bot_y,
        hp = hp,
        max_hp = max_hp,
        wave = wave,
        enemies = all_enemies,
        threat_count = threat_count,
        threat_radius = threat_radius,
        edge_pressure = edge_pressure,
        suggested_move_x = direction_x,
        suggested_move_y = direction_y,
        arena = context.arena,
        movement_lookahead =
          context.shared.policy_move_lookahead,
        offense_enabled =
          context.shared.offense_enabled,
        scene_key = scene_key,
        skill_choices = skill_choices,
      })
    return
  end
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
brain.choose_pending_skill = choose_pending_skill
brain.update_mana_cast_hold = update_mana_cast_hold
brain.update_flee_state = update_flee_state
brain.should_use_scripted_movement = should_use_scripted_movement
brain.cast_mana_hold_low_ratio = CAST_MANA_HOLD_LOW_RATIO
brain.cast_mana_resume_high_ratio = CAST_MANA_RESUME_HIGH_RATIO
brain.request_nearby_pickup = request_nearby_pickup

return brain
