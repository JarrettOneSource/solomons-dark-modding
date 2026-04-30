local follow = {}

function follow.install(ctx)
  local state = ctx.state
  local config = ctx.config

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
      ctx.log_diag(string.format("follow_stop id=%s reason=%s", tostring(state.bot_id), tostring(reason)))
    else
      ctx.log_diag(string.format("follow_stop failed id=%s reason=%s", tostring(state.bot_id), tostring(reason)))
    end
  end

  local function reset_travel_candidate()
    state.hub_candidate_name = nil
    state.hub_candidate_since_ms = 0
    state.target_area_name = nil
    state.travel_state = "idle"
  end

  local function same_follow_point(a, b)
    if type(a) ~= "table" or type(b) ~= "table" then
      return false
    end

    return ctx.distance(
      tonumber(a.x) or 0.0,
      tonumber(a.y) or 0.0,
      tonumber(b.x) or 0.0,
      tonumber(b.y) or 0.0) <= 0.001
  end

  local function teleport_to_follow_target(now_ms, scene, bot, reason)
    if state.bot_id == nil or type(state.follow_target) ~= "table" then
      return false
    end
    if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.update) ~= "function" then
      return false
    end

    local target_x = tonumber(state.follow_target.x)
    local target_y = tonumber(state.follow_target.y)
    if target_x == nil or target_y == nil then
      return false
    end

    if type(sd.bots.stop) == "function" then
      pcall(sd.bots.stop, state.bot_id)
    end

    local scene_intent = ctx.build_scene_intent(scene)
    if scene_intent == nil and type(bot) == "table" then
      scene_intent = ctx.normalize_scene_intent(bot.scene)
    end

    local update = {
      id = state.bot_id,
      position = {
        x = target_x,
        y = target_y,
      },
    }
    if scene_intent ~= nil then
      update.scene = scene_intent
    end
    if type(bot) == "table" and tonumber(bot.heading) ~= nil then
      update.position.heading = tonumber(bot.heading)
    end

    local call_ok, update_result = pcall(sd.bots.update, update)
    local ok = call_ok and update_result
    if not call_ok then
      ctx.log_diag(string.format(
        "follow_teleport update rejected id=%s reason=%s error=%s",
        tostring(state.bot_id),
        tostring(reason),
        tostring(update_result)))
    end
    if ok then
      ctx.log_diag(string.format(
        "follow_teleport id=%s reason=%s point=(%.2f, %.2f)",
        tostring(state.bot_id),
        tostring(reason),
        target_x,
        target_y))
      state.follow_target = nil
      state.last_command_ms = tonumber(now_ms) or state.last_tick_ms or 0
    else
      ctx.log_diag(string.format(
        "follow_teleport failed id=%s reason=%s point=(%.2f, %.2f)",
        tostring(state.bot_id),
        tostring(reason),
        target_x,
        target_y))
    end
    return ok
  end

  local function expire_follow_move_if_needed(now_ms, scene, bot)
    if type(state.follow_target) ~= "table" then
      return false
    end
    local started_ms = tonumber(state.follow_target.move_started_ms)
    if started_ms == nil or tonumber(now_ms) == nil then
      return false
    end
    if now_ms - started_ms < config.FOLLOW_MOVE_TIMEOUT_MS then
      return false
    end

    local current_target = nil
    if type(bot) == "table" and bot.target_x ~= nil and bot.target_y ~= nil then
      current_target = { x = bot.target_x, y = bot.target_y }
    end
    if current_target ~= nil and not same_follow_point(current_target, state.follow_target) then
      state.follow_target = nil
      return true
    end

    local arrival_gap = ctx.distance(
      tonumber(type(bot) == "table" and bot.x or 0.0) or 0.0,
      tonumber(type(bot) == "table" and bot.y or 0.0) or 0.0,
      tonumber(state.follow_target.x) or 0.0,
      tonumber(state.follow_target.y) or 0.0)
    if arrival_gap <= config.FOLLOW_TARGET_ARRIVAL_DISTANCE then
      return false
    end

    return teleport_to_follow_target(now_ms, scene, bot, "follow_timeout")
  end

  local function issue_follow_move(target, now_ms, reason)
    if not config.ENABLE_FOLLOW_MOVEMENT then
      return false
    end
    if state.bot_id == nil or type(target) ~= "table" then
      return false
    end
    if now_ms - state.last_command_ms < config.COMMAND_COOLDOWN_MS then
      return false
    end
    if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
      return false
    end

    local ok = sd.bots.move_to(state.bot_id, target.x, target.y)
    if ok then
      local previous_target = state.follow_target
      local move_started_ms = now_ms
      if same_follow_point(previous_target, target) and tonumber(previous_target.move_started_ms) ~= nil then
        move_started_ms = previous_target.move_started_ms
      end
      state.follow_target = {
        x = target.x,
        y = target.y,
        reason = reason,
        player_x = target.player_x,
        player_y = target.player_y,
        player_gap = target.player_gap,
        move_started_ms = move_started_ms,
      }
      state.last_command_ms = now_ms
      ctx.log_diag(string.format(
        "follow_move id=%s reason=%s point=(%.2f, %.2f)",
        tostring(state.bot_id),
        tostring(reason),
        target.x,
        target.y))
    else
      ctx.log_diag(string.format(
        "follow_move failed id=%s reason=%s point=(%.2f, %.2f)",
        tostring(state.bot_id),
        tostring(reason),
        target.x,
        target.y))
    end
    return ok
  end

  local function get_nav_grid_snapshot(now_ms)
    if type(sd) ~= "table" or type(sd.debug) ~= "table" or type(sd.debug.get_nav_grid) ~= "function" then
      return nil
    end

    local scene = ctx.get_scene_state()
    local world_id = type(scene) == "table" and
      ctx.normalize_address_key(scene.world_id or scene.world_address or scene.id) or ""
    if world_id == "" then
      return nil
    end

    if state.nav_grid_cache ~= nil and
        state.nav_grid_cache_world_id == world_id and
        now_ms - state.nav_grid_cache_at_ms < config.NAV_GRID_REFRESH_MS then
      return state.nav_grid_cache
    end

    local grid = sd.debug.get_nav_grid(config.NAV_GRID_SUBDIVISIONS)
    if type(grid) ~= "table" or grid.valid == false or type(grid.cells) ~= "table" then
      return nil
    end
    local grid_world_id = ctx.normalize_address_key(grid.world_address or grid.world_id)
    if grid_world_id == "" or grid_world_id ~= world_id then
      return nil
    end

    state.nav_grid_cache = grid
    state.nav_grid_cache_world_id = world_id
    state.nav_grid_cache_at_ms = now_ms
    return grid
  end

  local function is_outer_grid_row(grid, cell)
    local grid_x = tonumber(type(cell) == "table" and cell.grid_x or nil)
    local height = tonumber(type(grid) == "table" and grid.height or nil)
    if grid_x == nil or height == nil or height <= 0 then
      return false
    end
    return grid_x <= 0 or grid_x >= height - 1
  end

  local function nav_sample_score(grid, cell, gap, options)
    local score = gap
    if options.prefer_traversable_cell and cell.traversable ~= true then
      score = score + 100000.0
    end
    if options.avoid_outer_rows and is_outer_grid_row(grid, cell) then
      score = score + 50000.0
    end
    return score
  end

  local function snap_target_to_nav(grid, target, options)
    if type(grid) ~= "table" or type(grid.cells) ~= "table" or type(target) ~= "table" then
      return nil
    end
    options = type(options) == "table" and options or {}

    local target_x = tonumber(target.x)
    local target_y = tonumber(target.y)
    if target_x == nil or target_y == nil then
      return nil
    end

    local best_sample = nil
    local best_sample_score = nil
    local best_sample_distance = nil
    for _, cell in ipairs(grid.cells) do
      if type(cell) == "table" and type(cell.samples) == "table" then
        for _, sample in ipairs(cell.samples) do
          if type(sample) == "table" and sample.traversable and
              tonumber(sample.world_x) ~= nil and tonumber(sample.world_y) ~= nil then
            local gap = ctx.distance(target_x, target_y, tonumber(sample.world_x), tonumber(sample.world_y))
            local score = nav_sample_score(grid, cell, gap, options)
            if best_sample_score == nil or score < best_sample_score or
                (score == best_sample_score and gap < best_sample_distance) then
              best_sample_score = score
              best_sample_distance = gap
              best_sample = { x = tonumber(sample.world_x), y = tonumber(sample.world_y) }
            end
          end
        end
      end
    end

    if best_sample == nil then
      return nil
    end

    best_sample.gap = target.gap
    return best_sample
  end

  local function snap_spawn_transform(now_ms, spawn)
    if type(spawn) ~= "table" then
      return nil
    end

    local snapped = snap_target_to_nav(get_nav_grid_snapshot(now_ms), spawn, {
      prefer_traversable_cell = true,
      avoid_outer_rows = true,
    })
    if type(snapped) ~= "table" then
      return nil
    end

    return {
      x = tonumber(snapped.x) or tonumber(spawn.x) or 0.0,
      y = tonumber(snapped.y) or tonumber(spawn.y) or 0.0,
      heading = tonumber(spawn.heading),
    }
  end

  local function compute_follow_target(player, bot)
    local player_x = tonumber(player.x) or 0.0
    local player_y = tonumber(player.y) or 0.0
    local bot_x = tonumber(bot.x) or 0.0
    local bot_y = tonumber(bot.y) or 0.0
    local gap = ctx.distance(bot_x, bot_y, player_x, player_y)
    local radius = config.FOLLOW_STOP_DISTANCE +
      (math.random() * (config.FOLLOW_RESUME_DISTANCE - config.FOLLOW_STOP_DISTANCE))
    local angle = math.random() * math.pi * 2.0
    return {
      x = player_x + (math.cos(angle) * radius),
      y = player_y + (math.sin(angle) * radius),
      gap = gap,
      player_x = player_x,
      player_y = player_y,
      radius = radius,
    }
  end

  local function follow_target_player_gap(player, target)
    if type(player) ~= "table" or type(target) ~= "table" then
      return nil
    end

    return ctx.distance(
      tonumber(player.x) or 0.0,
      tonumber(player.y) or 0.0,
      tonumber(target.x) or 0.0,
      tonumber(target.y) or 0.0)
  end

  local function follow_target_band_penalty(player, target)
    local gap = follow_target_player_gap(player, target)
    if gap == nil then
      return nil
    end
    if gap < config.FOLLOW_STOP_DISTANCE then
      return config.FOLLOW_STOP_DISTANCE - gap
    end
    if gap > config.FOLLOW_RESUME_DISTANCE then
      return gap - config.FOLLOW_RESUME_DISTANCE
    end
    return 0.0
  end

  local function should_refresh_follow_target(player, bot_gap, target)
    if type(player) ~= "table" or type(target) ~= "table" then
      return true
    end
    if (tonumber(bot_gap) or 0.0) <= config.FOLLOW_RESUME_DISTANCE then
      return false
    end

    return ctx.distance(
      tonumber(player.x) or 0.0,
      tonumber(player.y) or 0.0,
      tonumber(target.player_x) or 0.0,
      tonumber(target.player_y) or 0.0) > config.FOLLOW_TARGET_REFRESH_DISTANCE
  end

  local function annotate_follow_target(target, source, player)
    if type(target) ~= "table" then
      return nil
    end
    local player_x = tonumber(type(source) == "table" and source.player_x or nil) or tonumber(player.x) or 0.0
    local player_y = tonumber(type(source) == "table" and source.player_y or nil) or tonumber(player.y) or 0.0
    target.player_x = player_x
    target.player_y = player_y
    target.player_gap = ctx.distance(player_x, player_y, target.x, target.y)
    return target
  end

  local function choose_follow_target(now_ms, player, bot)
    local nav_grid = get_nav_grid_snapshot(now_ms)
    local best_target = nil
    local best_penalty = nil

    for _ = 1, config.FOLLOW_TARGET_SAMPLE_ATTEMPTS do
      local candidate = compute_follow_target(player, bot)
      local snapped = snap_target_to_nav(nav_grid, candidate, {
        avoid_outer_rows = true,
      })
      if type(snapped) == "table" then
        annotate_follow_target(snapped, candidate, player)
        local penalty = follow_target_band_penalty(player, snapped) or 1000000.0
        if best_penalty == nil or penalty < best_penalty then
          best_target = snapped
          best_penalty = penalty
        end
        if penalty <= 0.0 then
          return snapped
        end
      end
    end

    return best_target
  end

  local function update_same_scene_follow(now_ms, scene, player, bot)
    if type(player) ~= "table" or type(bot) ~= "table" then
      return
    end

    local actor_address = tonumber(bot.actor_address) or 0
    if actor_address == 0 or not bot.transform_valid then
      return
    end

    local probe = ctx.get_probe_state()
    ctx.issue_auto_attack(now_ms, scene, bot, probe)

    if type(probe) == "table" and probe.disable_follow ~= false then
      state.follow_target = nil
      return
    end

    local gap = ctx.distance(
      tonumber(bot.x) or 0.0,
      tonumber(bot.y) or 0.0,
      tonumber(player.x) or 0.0,
      tonumber(player.y) or 0.0)

    if state.follow_target ~= nil then
      if expire_follow_move_if_needed(now_ms, scene, bot) then
        return
      end

      local arrival_gap = ctx.distance(
        tonumber(bot.x) or 0.0,
        tonumber(bot.y) or 0.0,
        tonumber(state.follow_target.x) or 0.0,
        tonumber(state.follow_target.y) or 0.0)
      if arrival_gap <= config.FOLLOW_TARGET_ARRIVAL_DISTANCE then
        stop_follow_move("follow_arrival")
        return
      end

      if should_refresh_follow_target(player, gap, state.follow_target) then
        local target = choose_follow_target(now_ms, player, bot)
        if type(target) == "table" then
          issue_follow_move(target, now_ms, "follow_refresh")
        end
        return
      end

      if (not bot.moving) or (not bot.has_target) then
        if gap <= config.FOLLOW_RESUME_DISTANCE then
          state.follow_target = nil
          return
        end
        issue_follow_move(state.follow_target, now_ms, "follow_resume")
        return
      end

      if bot.target_x == nil or bot.target_y == nil then
        issue_follow_move(state.follow_target, now_ms, "follow_reissue")
        return
      end

      local target_gap = ctx.distance(bot.target_x, bot.target_y, state.follow_target.x, state.follow_target.y)
      if target_gap > config.FOLLOW_TARGET_REFRESH_DISTANCE then
        issue_follow_move(state.follow_target, now_ms, "follow_reissue")
      end
      return
    end

    if bot.moving or bot.has_target then
      if bot.target_x ~= nil and bot.target_y ~= nil then
        local native_arrival_gap = ctx.distance(
          tonumber(bot.x) or 0.0,
          tonumber(bot.y) or 0.0,
          tonumber(bot.target_x) or 0.0,
          tonumber(bot.target_y) or 0.0)
        if native_arrival_gap <= config.FOLLOW_TARGET_ARRIVAL_DISTANCE then
          stop_follow_move("follow_arrival")
        elseif gap > config.FOLLOW_RESUME_DISTANCE then
          local target = choose_follow_target(now_ms, player, bot)
          if type(target) == "table" then
            issue_follow_move(target, now_ms, "follow")
          end
        end
      elseif gap <= config.FOLLOW_RESUME_DISTANCE then
        stop_follow_move("follow_no_target")
      end
      return
    end

    if gap <= config.FOLLOW_RESUME_DISTANCE then
      return
    end

    local target = choose_follow_target(now_ms, player, bot)
    if type(target) == "table" then
      issue_follow_move(target, now_ms, "follow")
    end
  end

  local function track_bot_motion_sample(bot)
    if type(bot) ~= "table" then
      state.last_bot_sample = nil
      state.stuck_samples = 0
      return
    end

    local bot_x = tonumber(bot.x) or 0.0
    local bot_y = tonumber(bot.y) or 0.0
    if type(state.last_bot_sample) == "table" and bot.moving then
      local drift = ctx.distance(
        bot_x,
        bot_y,
        tonumber(state.last_bot_sample.x) or 0.0,
        tonumber(state.last_bot_sample.y) or 0.0)
      if drift <= config.STUCK_POSITION_EPSILON then
        state.stuck_samples = state.stuck_samples + 1
      else
        state.stuck_samples = 0
      end
    else
      state.stuck_samples = 0
    end
    state.last_bot_sample = {
      x = bot_x,
      y = bot_y,
    }
  end

  ctx.stop_follow_move = stop_follow_move
  ctx.reset_travel_candidate = reset_travel_candidate
  ctx.same_follow_point = same_follow_point
  ctx.teleport_to_follow_target = teleport_to_follow_target
  ctx.expire_follow_move_if_needed = expire_follow_move_if_needed
  ctx.issue_follow_move = issue_follow_move
  ctx.get_nav_grid_snapshot = get_nav_grid_snapshot
  ctx.snap_target_to_nav = snap_target_to_nav
  ctx.snap_spawn_transform = snap_spawn_transform
  ctx.compute_follow_target = compute_follow_target
  ctx.follow_target_player_gap = follow_target_player_gap
  ctx.follow_target_band_penalty = follow_target_band_penalty
  ctx.should_refresh_follow_target = should_refresh_follow_target
  ctx.annotate_follow_target = annotate_follow_target
  ctx.choose_follow_target = choose_follow_target
  ctx.update_same_scene_follow = update_same_scene_follow
  ctx.track_bot_motion_sample = track_bot_motion_sample
end

return follow
