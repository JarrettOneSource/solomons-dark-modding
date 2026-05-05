local travel = {}

function travel.install(ctx)
  local state = ctx.state

  local function track_scene_entry(now_ms, scene)
    local scene_name = type(scene) == "table" and tostring(scene.name or "") or nil
    if scene_name ~= state.last_scene_name then
      state.last_scene_name = scene_name
    end
  end

  local function handle_hub_state(now_ms, scene, player, bot)
    ctx.track_bot_motion_sample(bot)
    if type(bot) == "table" and not ctx.scene_matches(bot.scene, { kind = "shared_hub" }) then
      ctx.issue_scene_update(
        now_ms,
        { kind = "shared_hub" },
        player,
        "return_from_private",
        nil)
      return
    end

    state.active_private_area_name = nil
    state.target_area_name = nil
    state.travel_state = "idle"
    ctx.update_same_scene_follow(now_ms, scene, player, bot)
  end

  local function handle_private_state(now_ms, scene, player, bot)
    local desired_scene = ctx.build_scene_intent(scene)
    if type(desired_scene) ~= "table" or desired_scene.kind ~= "private_region" then
      state.travel_state = "idle"
      state.target_area_name = nil
      return
    end

    local area_name = tostring(scene.name or "private_region")
    state.active_private_area_name = area_name
    if type(bot) == "table" and bot.available and
        not ctx.scene_matches(bot.scene, desired_scene) then
      ctx.issue_scene_update(now_ms, desired_scene, player, "enter_" .. area_name, nil)
      return
    end

    state.travel_state = "in_private_area"
    state.target_area_name = area_name
    ctx.update_same_scene_follow(now_ms, scene, player, bot)
  end

  local function handle_run_state(now_ms, scene, player, bot)
    ctx.reset_travel_candidate()
    state.target_area_name = nil
    local run_scene = { kind = "run" }
    if state.pending_run_promotion then
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

  ctx.track_scene_entry = track_scene_entry
  ctx.handle_hub_state = handle_hub_state
  ctx.handle_private_state = handle_private_state
  ctx.handle_run_state = handle_run_state
end

return travel
