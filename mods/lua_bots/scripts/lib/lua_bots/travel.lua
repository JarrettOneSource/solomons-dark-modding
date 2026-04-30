local travel = {}

function travel.install(ctx)
  local state = ctx.state
  local config = ctx.config

  local function detect_hub_entrance(player, scene)
    if type(player) ~= "table" or type(scene) ~= "table" or tostring(scene.name or "") ~= "hub" then
      return nil
    end

    local player_x = tonumber(player.x) or 0.0
    local player_y = tonumber(player.y) or 0.0
    local best = nil
    local best_distance = nil
    for _, area in pairs(config.SUPPORTED_PRIVATE_AREAS) do
      local anchor = area.hub_anchor
      local gap = ctx.distance(player_x, player_y, anchor.x, anchor.y)
      if gap <= config.ENTRANCE_TRIGGER_DISTANCE and (best_distance == nil or gap < best_distance) then
        best = area
        best_distance = gap
      end
    end
    return best
  end

  local function track_scene_entry(now_ms, scene)
    local scene_name = type(scene) == "table" and tostring(scene.name or "") or nil
    if scene_name ~= state.last_scene_name then
      state.last_scene_name = scene_name
      state.scene_entered_ms = now_ms
      state.hub_candidate_name = nil
      state.hub_candidate_since_ms = 0
      state.entrance_armed = {}
      state.last_player_sample = nil
    end
  end

  local function player_moved_recently(player)
    if type(player) ~= "table" then
      return false
    end

    local player_x = tonumber(player.x) or 0.0
    local player_y = tonumber(player.y) or 0.0
    local moved = false
    if type(state.last_player_sample) == "table" then
      moved = ctx.distance(
        player_x,
        player_y,
        tonumber(state.last_player_sample.x) or 0.0,
        tonumber(state.last_player_sample.y) or 0.0) >= config.PLAYER_MOVEMENT_ARM_DISTANCE
    end
    state.last_player_sample = {
      x = player_x,
      y = player_y,
    }
    return moved
  end

  local function handle_hub_state(now_ms, scene, player, bot)
    ctx.track_bot_motion_sample(bot)
    local moved_recently = player_moved_recently(player)
    local entrance = detect_hub_entrance(player, scene)
    if now_ms - state.scene_entered_ms >= config.HUB_ENTRANCE_ARM_DELAY_MS then
      local player_x = tonumber(player.x) or 0.0
      local player_y = tonumber(player.y) or 0.0
      for _, area in pairs(config.SUPPORTED_PRIVATE_AREAS) do
        local gap = ctx.distance(player_x, player_y, area.hub_anchor.x, area.hub_anchor.y)
        if gap > config.ENTRANCE_TRIGGER_DISTANCE then
          state.entrance_armed[area.name] = true
        end
      end

      if entrance ~= nil and moved_recently and state.entrance_armed[entrance.name] == true then
        if state.hub_candidate_name ~= entrance.name then
          state.hub_candidate_name = entrance.name
          state.hub_candidate_since_ms = now_ms
        end
      elseif state.travel_state == "idle" then
        state.hub_candidate_name = nil
        state.hub_candidate_since_ms = 0
      end
    end

    local candidate = state.hub_candidate_name ~= nil and
      config.SUPPORTED_PRIVATE_AREAS[state.hub_candidate_name] or nil
    if candidate ~= nil and now_ms - state.hub_candidate_since_ms >= config.HUB_ENTRANCE_DWELL_MS then
      state.target_area_name = candidate.name
      state.travel_state = "travel_to_entrance"
      if type(bot) == "table" and bot.available and (tonumber(bot.actor_address) or 0) ~= 0 then
        local wait_anchor = candidate.hub_wait_anchor or candidate.hub_anchor
        wait_anchor = ctx.add_bot_formation_offset(wait_anchor, config.FOLLOW_STOP_DISTANCE)
        wait_anchor = ctx.snap_target_to_nav(ctx.get_nav_grid_snapshot(now_ms), wait_anchor, {
          prefer_traversable_cell = true,
        })
        if type(wait_anchor) ~= "table" then
          return
        end
        local gap = ctx.distance(tonumber(bot.x) or 0.0, tonumber(bot.y) or 0.0, wait_anchor.x, wait_anchor.y)
        if gap > config.ENTRANCE_ARRIVAL_DISTANCE then
          ctx.issue_follow_move(wait_anchor, now_ms, "travel_to_" .. candidate.name)
        else
          ctx.stop_follow_move("entrance_arrival")
        end
        if state.stuck_samples >= config.STUCK_SAMPLE_THRESHOLD then
          ctx.stop_follow_move("travel_stuck")
          state.entrance_armed[candidate.name] = false
          ctx.reset_travel_candidate()
        end
      end
      return
    end

    if state.active_private_area_name ~= nil then
      local previous_area = config.SUPPORTED_PRIVATE_AREAS[state.active_private_area_name]
      if previous_area ~= nil and type(bot) == "table" and
          not ctx.scene_matches(bot.scene, { kind = "shared_hub" }) then
        ctx.issue_scene_update(
          now_ms,
          { kind = "shared_hub" },
          player,
          "return_from_" .. previous_area.name,
          previous_area.hub_anchor)
        return
      end
      state.active_private_area_name = nil
    end

    state.target_area_name = nil
    state.travel_state = "idle"
    ctx.update_same_scene_follow(now_ms, scene, player, bot)
  end

  local function handle_private_state(now_ms, scene, player, bot)
    local area = config.SUPPORTED_PRIVATE_AREAS[tostring(scene.name or "")]
    if area == nil then
      state.travel_state = "idle"
      state.target_area_name = nil
      return
    end

    state.active_private_area_name = area.name
    local desired_scene = {
      kind = "private_region",
      region_index = area.region_index,
      region_type_id = area.region_type_id,
    }
    if type(bot) == "table" and bot.available and
        not ctx.scene_matches(bot.scene, desired_scene) and state.target_area_name == area.name then
      ctx.issue_scene_update(now_ms, desired_scene, player, "enter_" .. area.name, area.interior_anchor)
      return
    end

    state.travel_state = "in_private_area"
    state.target_area_name = area.name
    ctx.update_same_scene_follow(now_ms, scene, player, bot)
  end

  local function handle_run_state(now_ms, scene, player, bot)
    ctx.reset_travel_candidate()
    state.target_area_name = nil
    local run_scene = { kind = "run" }
    if state.pending_run_promotion and not ctx.scene_matches(bot.scene, run_scene) then
      if ctx.issue_scene_update(now_ms, run_scene, player, "run_started", nil, true) then
        state.pending_run_promotion = false
      end
      return
    end
    if ctx.scene_matches(bot.scene, run_scene) then
      state.scene_key = ctx.scene_key(run_scene)
    end
    state.pending_run_promotion = false
    state.travel_state = "run"
    ctx.update_same_scene_follow(now_ms, scene, player, bot)
  end

  ctx.detect_hub_entrance = detect_hub_entrance
  ctx.track_scene_entry = track_scene_entry
  ctx.player_moved_recently = player_moved_recently
  ctx.handle_hub_state = handle_hub_state
  ctx.handle_private_state = handle_private_state
  ctx.handle_run_state = handle_run_state
end

return travel
