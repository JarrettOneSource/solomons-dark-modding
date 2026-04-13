local function new(ctx)
  local cfg = ctx.config

  local state = {
    run_number = 0,
    captured_for_run = false,
    last_snapshot_name = nil,
    last_wait_log_ms = 0,
  }

  local self = {}

  function self.on_run_started()
    state.run_number = state.run_number + 1
    state.captured_for_run = false
    state.last_wait_log_ms = 0
  end

  function self.on_run_ended()
    state.captured_for_run = false
    state.last_wait_log_ms = 0
  end

  function self.update(now_ms, setup_complete)
    if ctx.failed or not setup_complete or state.captured_for_run then
      return
    end

    if not ctx.lifecycle_events["run.started"] then
      return
    end

    if type(sd.debug) ~= "table" or type(sd.debug.snapshot) ~= "function" or
        type(sd.debug.diff) ~= "function" then
      ctx.fail("wizard compare requires sd.debug.snapshot and sd.debug.diff")
      return
    end

    if state.run_number == 0 then
      state.run_number = 1
    end

    local scene_name = ctx.get_scene_name()
    if scene_name ~= "testrun" then
      if state.last_wait_log_ms == 0 or now_ms - state.last_wait_log_ms >= 1000 then
        state.last_wait_log_ms = now_ms
        ctx.log_status("wizard compare waiting for testrun scene; scene=" .. tostring(scene_name))
      end
      return
    end

    local actor_address, actor_source, player_state = ctx.resolve_player_actor_snapshot_target()
    if actor_address == 0 then
      if state.last_wait_log_ms == 0 or now_ms - state.last_wait_log_ms >= 1000 then
        state.last_wait_log_ms = now_ms
        ctx.log_status("wizard compare waiting for local player actor")
      end
      return
    end

    local snapshot_name = "player_actor_run_" .. tostring(state.run_number)
    sd.debug.snapshot(snapshot_name, actor_address, cfg.sizes.player_actor_snapshot)

    local source_profile = 0
    if type(player_state) == "table" then
      source_profile = tonumber(player_state.render_subject_hub_visual_source_profile_address) or 0
      if source_profile == 0 then
        source_profile = tonumber(player_state.hub_visual_source_profile_address) or 0
      end
    end
    if source_profile == 0 then
      source_profile = ctx.read_object_u32(actor_address, cfg.offsets.actor_source_profile_ptr) or 0
    end

    ctx.log_status(string.format(
      "wizard compare captured %s actor=%s via=%s render={%s} source={%s}",
      snapshot_name,
      ctx.format_hex32(actor_address),
      tostring(actor_source),
      ctx.format_preview_actor_render_fields(actor_address),
      ctx.format_source_render_fields(source_profile)))

    if state.last_snapshot_name ~= nil then
      sd.debug.diff(state.last_snapshot_name, snapshot_name)
      ctx.log_status(string.format(
        "wizard compare diffed %s -> %s",
        state.last_snapshot_name,
        snapshot_name))
    else
      ctx.log_status("wizard compare baseline captured; start another run with a different wizard type to diff")
    end

    state.last_snapshot_name = snapshot_name
    state.captured_for_run = true
  end

  return self
end

return {
  new = new,
}
