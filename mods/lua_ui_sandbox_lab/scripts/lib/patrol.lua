local INPUT_TEST_CLICK_POINTS = {
  { x = 0.82, y = 0.70 },
  { x = 0.18, y = 0.70 },
}

local function new(ctx)
  local cfg = ctx.config

  local player_input_test = nil
  local visual_diff_probe = {
    completed = false,
    last_wait_log_ms = 0,
  }
  local render_spawn_probe = {
    armed = false,
    bot_write_watches_armed = false,
  }

  local self = {}

  local function reset_player_input_test()
    player_input_test = {
      attempted_clicks = 0,
      issued = false,
      completed = false,
      issued_at_ms = 0,
      baseline_player_x = nil,
      baseline_player_y = nil,
      mode = "auto",
      external_notice_logged = false,
    }
  end

  local function reset_visual_diff_probe()
    visual_diff_probe = {
      completed = false,
      last_wait_log_ms = 0,
    }
  end

  local function reset_render_spawn_probe()
    render_spawn_probe = {
      armed = false,
      bot_write_watches_armed = false,
    }
  end

  local function should_arm_render_spawn_probe()
    local preset = tostring(ctx.active_preset or "")
    return preset == "static_bot_render_debug" or
      preset == "enter_gameplay_start_run_debug"
  end

  local function try_trace_function(address, name)
    if type(sd.debug) ~= "table" or type(sd.debug.trace_function) ~= "function" then
      return
    end
    if tonumber(address) == nil or tonumber(address) == 0 then
      return
    end
    pcall(sd.debug.trace_function, address, name)
  end

  local function try_watch_write(name, address, size)
    if type(sd.debug) ~= "table" or type(sd.debug.watch_write) ~= "function" then
      return
    end
    if tonumber(address) == nil or tonumber(address) == 0 or tonumber(size) == nil or tonumber(size) <= 0 then
      return
    end
    pcall(sd.debug.watch_write, name, address, size)
  end

  local function try_watch_write_ptr_field(ptr_address, offset, size, name)
    if type(sd.debug) ~= "table" then
      return
    end
    if tonumber(ptr_address) == nil or tonumber(ptr_address) == 0 or
        tonumber(offset) == nil or tonumber(size) == nil or tonumber(size) <= 0 then
      return
    end
    if type(sd.debug.watch_write_ptr_field) == "function" then
      pcall(sd.debug.watch_write_ptr_field, ptr_address, offset, size, name)
      return
    end
    if type(sd.debug.read_ptr) ~= "function" or type(sd.debug.watch_write) ~= "function" then
      return
    end
    local ok, base_address = pcall(sd.debug.read_ptr, ptr_address)
    if not ok then
      return
    end
    base_address = tonumber(base_address) or 0
    if base_address == 0 then
      return
    end
    pcall(sd.debug.watch_write, name, base_address + offset, size)
  end

  local function arm_render_spawn_probe()
    if render_spawn_probe.armed then
      return
    end

    local addresses = cfg.addresses
    local offsets = cfg.offsets
    local sizes = cfg.sizes
    local player_state = ctx.get_player_state()
    local scene_state = ctx.get_scene_state()
    local gameplay_address = 0
    local player_actor = 0

    if type(scene_state) == "table" then
      gameplay_address = ctx.parse_runtime_address(scene_state.id or scene_state.scene_id) or 0
    end
    if type(player_state) == "table" then
      player_actor = tonumber(player_state.render_subject_address or player_state.actor_address) or 0
    end

    try_trace_function(addresses.trace_gameplay_create_player_slot, "gameplay.create_player_slot")
    try_trace_function(addresses.trace_player_appearance_apply_choice, "player.appearance_apply_choice")
    try_trace_function(addresses.trace_gameplay_finalize_player_start, "gameplay.finalize_player_start")
    try_trace_function(addresses.trace_actor_world_register_gameplay_slot_actor, "world.register_gameplay_slot_actor")
    try_trace_function(addresses.trace_actor_world_unregister, "world.unregister_actor")
    try_trace_function(addresses.trace_puppet_manager_delete_puppet, "puppet_manager.delete_puppet")
    try_trace_function(addresses.trace_actor_build_render_descriptor_from_source, "actor.build_render_descriptor_from_source")

    if gameplay_address ~= 0 then
      try_watch_write(
        "gameplay.item_list",
        gameplay_address + offsets.gameplay_item_list,
        sizes.gameplay_item_list_window)
      try_watch_write(
        "gameplay.sink.primary",
        gameplay_address + offsets.gameplay_visual_sink_primary,
        sizes.gameplay_visual_sink_window)
      try_watch_write(
        "gameplay.sink.secondary",
        gameplay_address + offsets.gameplay_visual_sink_secondary,
        sizes.gameplay_visual_sink_window)
      try_watch_write(
        "gameplay.sink.attachment",
        gameplay_address + offsets.gameplay_visual_sink_attachment,
        sizes.gameplay_visual_sink_window)
    end

    if player_actor ~= 0 then
      try_watch_write(
        "player.actor.variant_window",
        player_actor + offsets.actor_render_variant_window,
        sizes.actor_render_variant_window)
      try_watch_write(
        "player.actor.descriptor",
        player_actor + offsets.actor_descriptor_block,
        sizes.actor_descriptor_block)
      try_watch_write(
        "player.actor.attachment",
        player_actor + offsets.actor_attachment_ptr,
        4)
    end

    render_spawn_probe.armed = true
    ctx.log_status(string.format(
      "armed shared render-state spawn probe gameplay=%s player_actor=%s",
      tostring(gameplay_address),
      tostring(player_actor)))
  end

  local function arm_bot_actor_write_watches(bot_state)
    if render_spawn_probe.bot_write_watches_armed or type(bot_state) ~= "table" then
      return
    end

    local offsets = cfg.offsets
    local sizes = cfg.sizes
    local bot_actor = tonumber(bot_state.actor_address) or 0
    if bot_actor == 0 then
      return
    end

    try_watch_write("bot.actor.variant_window", bot_actor + offsets.actor_render_variant_window, sizes.actor_render_variant_window)
    try_watch_write("bot.actor.descriptor", bot_actor + offsets.actor_descriptor_block, sizes.actor_descriptor_block)
    try_watch_write("bot.actor.source_window", bot_actor + offsets.actor_source_kind, 0x10)
    try_watch_write("bot.actor.attachment", bot_actor + offsets.actor_attachment_ptr, 4)

    local bot_source_profile = tonumber(bot_state.hub_visual_source_profile_address) or 0
    if bot_source_profile ~= 0 then
      try_watch_write("bot.source.render_fields", bot_source_profile + offsets.source_render_fields, sizes.source_render_fields)
    end

    render_spawn_probe.bot_write_watches_armed = true
    ctx.log_status("armed bot actor render write watches actor=" .. tostring(bot_state.actor_address))
  end

  local function log_visual_state_summary(player_state, bot_state)
    local player_actor_address = "slot0"
    local player_render_selection = "slot0"
    local player_animation_state = "slot0"
    local player_render_frame_table = "slot0"
    local player_attachment_ptr = "slot0"
    local player_source_profile = "slot0"
    local player_progression = "slot0"
    local player_equip = "slot0"
    local player_descriptor_signature = 0
    local player_variant_primary = "slot0"
    local player_variant_secondary = "slot0"
    local player_weapon_type = "slot0"
    local player_variant_tertiary = "slot0"

    if type(player_state) == "table" then
      player_actor_address = player_state.actor_address
      player_render_selection = player_state.render_subject_selection_byte or player_state.render_selection_byte
      player_animation_state = player_state.resolved_animation_state_id
      player_render_frame_table = player_state.render_subject_frame_table or player_state.render_frame_table
      player_attachment_ptr = player_state.render_subject_hub_visual_attachment_ptr or player_state.hub_visual_attachment_ptr
      player_source_profile =
        player_state.render_subject_hub_visual_source_profile_address or player_state.hub_visual_source_profile_address
      player_progression = player_state.progression_address
      player_equip = player_state.equip_runtime_state_address
      player_descriptor_signature = tonumber(player_state.hub_visual_descriptor_signature) or 0
      player_variant_primary = player_state.render_subject_variant_primary or player_state.render_variant_primary
      player_variant_secondary = player_state.render_subject_variant_secondary or player_state.render_variant_secondary
      player_weapon_type = player_state.render_subject_weapon_type or player_state.render_weapon_type
      player_variant_tertiary = player_state.render_subject_variant_tertiary or player_state.render_variant_tertiary
    end

    ctx.log_status(string.format(
      "visual summary player={actor=%s render=%s anim=%s frame=%s attach=%s source=%s variants=%s/%s/%s/%s prog=%s equip=%s desc=0x%08X} bot={actor=%s render=%s anim=%s frame=%s attach=%s source=%s variants=%s/%s/%s/%s prog=%s equip=%s desc=0x%08X}",
      tostring(player_actor_address),
      tostring(player_render_selection),
      tostring(player_animation_state),
      tostring(player_render_frame_table),
      tostring(player_attachment_ptr),
      tostring(player_source_profile),
      tostring(player_variant_primary),
      tostring(player_variant_secondary),
      tostring(player_weapon_type),
      tostring(player_variant_tertiary),
      tostring(player_progression),
      tostring(player_equip),
      player_descriptor_signature,
      tostring(bot_state.actor_address),
      tostring(bot_state.render_selection_byte),
      tostring(bot_state.resolved_animation_state_id),
      tostring(bot_state.render_frame_table),
      tostring(bot_state.hub_visual_attachment_ptr),
      tostring(bot_state.hub_visual_source_profile_address),
      tostring(bot_state.render_variant_primary),
      tostring(bot_state.render_variant_secondary),
      tostring(bot_state.render_weapon_type),
      tostring(bot_state.render_variant_tertiary),
      tostring(bot_state.progression_runtime_state_address),
      tostring(bot_state.equip_runtime_state_address),
      tonumber(bot_state.hub_visual_descriptor_signature) or 0))
  end

  function self.get_patrol_bot_snapshot()
    if type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
      return nil
    end

    local snapshot = sd.bots.get_state(ctx.spawned_bot_id)
    if type(snapshot) == "table" then
      return snapshot
    end

    return nil
  end

  local function run_visual_diff_probe()
    if visual_diff_probe.completed then
      return true
    end

    if type(sd.debug) ~= "table" or type(sd.debug.snapshot) ~= "function" or
        type(sd.debug.snapshot_ptr_field) ~= "function" or type(sd.debug.diff) ~= "function" then
      ctx.fail("sd.debug snapshot tools unavailable")
      return false
    end

    local player_state = ctx.get_player_state()
    local scene_state = ctx.get_scene_state()
    local bot_state = self.get_patrol_bot_snapshot()
    if type(bot_state) ~= "table" or not bot_state.available then
      return "waiting_bot_snapshot"
    end
    if tonumber(bot_state.actor_address) == nil or tonumber(bot_state.actor_address) == 0 then
      return "waiting_bot_actor"
    end

    local gameplay_address = 0
    if type(scene_state) == "table" then
      gameplay_address = ctx.parse_runtime_address(scene_state.id or scene_state.scene_id) or 0
    end
    if gameplay_address == 0 then
      return "waiting_gameplay_scene"
    end

    log_visual_state_summary(player_state, bot_state)

    local bot_actor = tonumber(bot_state.actor_address) or 0
    local bot_progression = tonumber(bot_state.progression_runtime_state_address) or 0
    local bot_equip = tonumber(bot_state.equip_runtime_state_address) or 0
    local bot_selection_state = ctx.resolve_wizard_selection_state(bot_state.render_selection_byte)
    local player_actor = 0
    local player_progression = 0
    local player_equip = 0
    local player_selection_state = nil
    if type(player_state) == "table" then
      player_actor = tonumber(player_state.render_subject_address or player_state.actor_address) or 0
      player_progression = tonumber(player_state.progression_address) or 0
      player_equip = tonumber(player_state.equip_runtime_state_address) or 0
      player_selection_state = ctx.resolve_wizard_selection_state(
        player_state.render_subject_selection_byte or player_state.render_selection_byte)
    end
    if player_actor == 0 then
      return "waiting_player_actor"
    end

    local offsets = cfg.offsets
    local sizes = cfg.sizes

    ctx.snapshot_block(
      "player_actor_render_window",
      player_actor + offsets.actor_render_state_window,
      sizes.actor_render_state_window)
    ctx.snapshot_block(
      "bot_actor_render_window",
      bot_actor + offsets.actor_render_state_window,
      sizes.actor_render_state_window)
    sd.debug.diff("player_actor_render_window", "bot_actor_render_window")

    ctx.snapshot_block(
      "player_actor_descriptor",
      player_actor + offsets.actor_descriptor_block,
      sizes.actor_descriptor_block)
    ctx.snapshot_block(
      "bot_actor_descriptor",
      bot_actor + offsets.actor_descriptor_block,
      sizes.actor_descriptor_block)
    sd.debug.diff("player_actor_descriptor", "bot_actor_descriptor")

    ctx.snapshot_block(
      "player_actor_variant_window",
      player_actor + offsets.actor_render_variant_window,
      sizes.actor_render_variant_window)
    ctx.snapshot_block(
      "bot_actor_variant_window",
      bot_actor + offsets.actor_render_variant_window,
      sizes.actor_render_variant_window)
    sd.debug.diff("player_actor_variant_window", "bot_actor_variant_window")

    ctx.snapshot_block(
      "player_actor_runtime_window",
      player_actor + offsets.actor_runtime_visual_window,
      sizes.actor_runtime_visual_window)
    ctx.snapshot_block(
      "bot_actor_runtime_window",
      bot_actor + offsets.actor_runtime_visual_window,
      sizes.actor_runtime_visual_window)
    sd.debug.diff("player_actor_runtime_window", "bot_actor_runtime_window")

    local player_source_profile =
      tonumber(player_state.render_subject_hub_visual_source_profile_address or player_state.hub_visual_source_profile_address) or 0
    local bot_source_profile = tonumber(bot_state.hub_visual_source_profile_address) or 0
    if player_source_profile ~= 0 then
      ctx.snapshot_block(
        "player_actor_source_render_fields",
        player_source_profile + offsets.source_render_fields,
        sizes.source_render_fields)
    end
    if bot_source_profile ~= 0 then
      ctx.snapshot_block(
        "bot_actor_source_render_fields",
        bot_source_profile + offsets.source_render_fields,
        sizes.source_render_fields)
      if player_source_profile ~= 0 then
        sd.debug.diff("player_actor_source_render_fields", "bot_actor_source_render_fields")
      end
    end

    if player_progression ~= 0 then
      ctx.snapshot_block("player_progression_head", player_progression, sizes.create_probe_progress_head)
    end
    if bot_progression ~= 0 then
      ctx.snapshot_block("bot_progression_head", bot_progression, sizes.create_probe_progress_head)
      if player_progression ~= 0 then
        sd.debug.diff("player_progression_head", "bot_progression_head")
      end
    end

    if player_selection_state ~= nil and player_progression ~= 0 then
      ctx.snapshot_ptr_block(
        "player_progression_selection_entry",
        player_progression + offsets.standalone_wizard_progress_table_ptr,
        player_selection_state * sizes.standalone_wizard_progress_entry,
        sizes.standalone_wizard_progress_entry)
    end

    if player_equip ~= 0 then
      ctx.snapshot_block("player_equip_runtime", player_equip, sizes.standalone_wizard_equip)
    end
    if bot_selection_state ~= nil and bot_progression ~= 0 then
      ctx.snapshot_ptr_block(
        "bot_progression_selection_entry",
        bot_progression + offsets.standalone_wizard_progress_table_ptr,
        bot_selection_state * sizes.standalone_wizard_progress_entry,
        sizes.standalone_wizard_progress_entry)
      if player_selection_state ~= nil and player_progression ~= 0 then
        sd.debug.diff("player_progression_selection_entry", "bot_progression_selection_entry")
      end
    end

    if bot_equip ~= 0 then
      ctx.snapshot_block("bot_equip_runtime", bot_equip, sizes.standalone_wizard_equip)
      if player_equip ~= 0 then
        sd.debug.diff("player_equip_runtime", "bot_equip_runtime")
      end
    end

    visual_diff_probe.completed = true
    ctx.log_status("captured player-vs-bot visual diff snapshots")
    return "complete"
  end

  local function update_visual_diff_probe_wait(now_ms, detail)
    if visual_diff_probe.completed then
      return nil
    end
    if visual_diff_probe.last_wait_log_ms ~= 0 and now_ms - visual_diff_probe.last_wait_log_ms < 1000 then
      return
    end
    visual_diff_probe.last_wait_log_ms = now_ms
    ctx.log_status("visual diff probe waiting: " .. tostring(detail))
  end

  local function get_player_position()
    local player_state = ctx.get_player_state()
    if type(player_state) ~= "table" then
      return nil, nil
    end

    local position = player_state.position or {}
    local x = tonumber(position.x or player_state.x)
    local y = tonumber(position.y or player_state.y)
    if x == nil or y == nil then
      return nil, nil
    end

    return x, y
  end

  local function is_bot_within_patrol_band(bot_x, bot_y)
    if ctx.patrol == nil then
      return false
    end

    local min_x = math.min(ctx.patrol.a.x, ctx.patrol.b.x) - cfg.input_probe.patrol_band_slop
    local max_x = math.max(ctx.patrol.a.x, ctx.patrol.b.x) + cfg.input_probe.patrol_band_slop
    local center_y = ctx.patrol.a.y
    return bot_x >= min_x and bot_x <= max_x and
      math.abs(bot_y - center_y) <= cfg.input_probe.patrol_band_slop
  end

  local function issue_player_input_probe(now_ms, bot_x, bot_y)
    if player_input_test == nil or player_input_test.completed then
      return
    end
    if player_input_test.mode == "external_wait" then
      return
    end
    if type(sd.input) ~= "table" or type(sd.input.click_normalized) ~= "function" then
      ctx.fail("sd.input.click_normalized unavailable")
      return
    end

    local point = INPUT_TEST_CLICK_POINTS[player_input_test.attempted_clicks + 1]
    if type(point) ~= "table" then
      player_input_test.mode = "external_wait"
      player_input_test.issued = false
      player_input_test.issued_at_ms = now_ms
      if not player_input_test.external_notice_logged then
        player_input_test.external_notice_logged = true
        ctx.log_status("internal click probe exhausted its points; waiting for external input verification")
      end
      return
    end

    local player_x, player_y = get_player_position()
    if player_x == nil or player_y == nil then
      return
    end

    local ok, result = pcall(sd.input.click_normalized, point.x, point.y)
    player_input_test.attempted_clicks = player_input_test.attempted_clicks + 1
    player_input_test.issued = ok and result == true
    player_input_test.issued_at_ms = now_ms
    player_input_test.baseline_player_x = player_x
    player_input_test.baseline_player_y = player_y

    ctx.log_status(string.format(
      "issued player movement click ok=%s result=%s bot=(%.2f,%.2f) player=(%.2f,%.2f) point=(%.2f,%.2f)",
      tostring(ok),
      tostring(result),
      tonumber(bot_x) or 0.0,
      tonumber(bot_y) or 0.0,
      player_x,
      player_y,
      point.x,
      point.y))

    if not player_input_test.issued then
      ctx.fail("player input probe failed to issue a gameplay click")
    end
  end

  local function update_player_input_probe(now_ms, bot_x, bot_y)
    if player_input_test == nil or player_input_test.completed or not ctx.patrol_loop_confirmed then
      return
    end

    local player_x, player_y = get_player_position()
    if player_x == nil or player_y == nil then
      return
    end

    if player_input_test.mode == "external_wait" then
      local baseline_x = tonumber(player_input_test.baseline_player_x) or player_x
      local baseline_y = tonumber(player_input_test.baseline_player_y) or player_y
      local delta_x = player_x - baseline_x
      local delta_y = player_y - baseline_y
      local player_delta = math.sqrt((delta_x * delta_x) + (delta_y * delta_y))
      if player_delta >= cfg.input_probe.player_move_threshold then
        local within_patrol = is_bot_within_patrol_band(bot_x, bot_y)
        ctx.log_status(string.format(
          "external input probe player_delta=%.2f bot=(%.2f,%.2f) within_patrol=%s",
          player_delta,
          bot_x,
          bot_y,
          tostring(within_patrol)))
        if within_patrol then
          ctx.log_status("input isolation confirmed")
          player_input_test.completed = true
          return
        end
        ctx.fail("bot left the patrol band after external player input")
      end
      return
    end

    if not player_input_test.issued then
      issue_player_input_probe(now_ms, bot_x, bot_y)
      return
    end

    local delta_x = player_x - player_input_test.baseline_player_x
    local delta_y = player_y - player_input_test.baseline_player_y
    local player_delta = math.sqrt((delta_x * delta_x) + (delta_y * delta_y))
    if player_delta >= cfg.input_probe.player_move_threshold then
      local within_patrol = is_bot_within_patrol_band(bot_x, bot_y)
      ctx.log_status(string.format(
        "input probe player_delta=%.2f bot=(%.2f,%.2f) within_patrol=%s",
        player_delta,
        bot_x,
        bot_y,
        tostring(within_patrol)))
      if within_patrol then
        ctx.log_status("input isolation confirmed")
        player_input_test.completed = true
        return
      end
      ctx.fail("bot left the patrol band after player input")
      return
    end

    local elapsed_ms = now_ms - player_input_test.issued_at_ms
    if elapsed_ms >= cfg.input_probe.timeout_ms then
      player_input_test.mode = "external_wait"
      player_input_test.issued = false
      player_input_test.issued_at_ms = now_ms
      player_input_test.baseline_player_x = player_x
      player_input_test.baseline_player_y = player_y
      if not player_input_test.external_notice_logged then
        player_input_test.external_notice_logged = true
        ctx.log_status("internal click probe did not move the player; waiting for external input verification")
      end
      return
    end
    if elapsed_ms >= cfg.input_probe.retry_delay_ms and
        player_input_test.attempted_clicks < #INPUT_TEST_CLICK_POINTS then
      player_input_test.issued = false
    end
  end

  local function issue_patrol_move(target_key)
    if ctx.spawned_bot_id == nil or ctx.patrol == nil then
      return false, "patrol unavailable"
    end

    if type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
      return false, "sd.bots.move_to unavailable"
    end

    local target = ctx.patrol[target_key]
    if type(target) ~= "table" then
      return false, "invalid patrol point"
    end

    local ok = sd.bots.move_to(ctx.spawned_bot_id, target.x, target.y)
    if not ok then
      return false, "move_to returned false"
    end

    ctx.patrol.active_target = target_key
    return true
  end

  function self.spawn_patrol_bot()
    if ctx.spawned_bot_id ~= nil then
      return true
    end

    if type(sd.bots) ~= "table" or type(sd.bots.create) ~= "function" then
      return false, "sd.bots.create unavailable"
    end

    if ctx.get_scene_name() ~= "testrun" then
      return nil, "scene not ready"
    end

    local player_x, player_y = get_player_position()
    if player_x == nil or player_y == nil then
      return nil, "player position unavailable"
    end

    local spawn_x = player_x + cfg.patrol.spawn_offset_x
    local spawn_y = player_y + cfg.patrol.spawn_offset_y
    local point_a_x = spawn_x - cfg.patrol.half_distance
    local point_b_x = spawn_x + cfg.patrol.half_distance
    local requested_wizard_id = tonumber(ctx.get_environment_integer(
      "SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID",
      0)) or 0
    requested_wizard_id = math.floor(requested_wizard_id)
    if requested_wizard_id < 0 or requested_wizard_id > 4 then
      requested_wizard_id = 0
    end

    reset_render_spawn_probe()
    if should_arm_render_spawn_probe() then
      arm_render_spawn_probe()
    end

    local bot_id = sd.bots.create({
      name = "Patrol Debug Bot",
      wizard_id = requested_wizard_id,
      ready = true,
      position = {
        x = spawn_x,
        y = spawn_y,
      },
    })
    if bot_id == nil then
      return false, "create returned nil"
    end

    ctx.spawned_bot_id = bot_id
    ctx.patrol = {
      a = { x = point_a_x, y = spawn_y },
      b = { x = point_b_x, y = spawn_y },
      active_target = nil,
    }
    ctx.patrol_loop_confirmed = false
    ctx.last_patrol_trace_ms = 0
    reset_player_input_test()
    reset_visual_diff_probe()
    ctx.log_status(string.format(
      "spawned id=%s wizard_id=%d point_a=(%.2f,%.2f) point_b=(%.2f,%.2f)",
      tostring(bot_id),
      requested_wizard_id,
      point_a_x,
      spawn_y,
      point_b_x,
      spawn_y))
    return true
  end

  function self.on_run_ended()
    ctx.patrol = nil
    ctx.patrol_loop_confirmed = false
    ctx.spawned_bot_id = nil
    ctx.last_patrol_trace_ms = 0
    player_input_test = nil
    reset_visual_diff_probe()
    reset_render_spawn_probe()
  end

  function self.update(now_ms)
    if ctx.failed or ctx.spawned_bot_id == nil or ctx.patrol == nil then
      return
    end

    if ctx.get_scene_name() ~= "testrun" then
      return
    end

    if type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
      ctx.fail("sd.bots.get_state unavailable")
      return
    end

    local snapshot = self.get_patrol_bot_snapshot()
    if type(snapshot) ~= "table" or not snapshot.available then
      return
    end

    if should_arm_render_spawn_probe() then
      arm_bot_actor_write_watches(snapshot)
    end

    if not visual_diff_probe.completed then
      local probe_status = run_visual_diff_probe()
      if probe_status ~= "complete" then
        update_visual_diff_probe_wait(now_ms, probe_status)
        return
      end
    end

    if ctx.patrol.active_target == nil then
      local ok, detail = issue_patrol_move("b")
      if not ok then
        ctx.fail(detail or "initial patrol move failed")
      end
      return
    end

    local active_target = ctx.patrol[ctx.patrol.active_target]
    if type(active_target) ~= "table" then
      return
    end

    local position = snapshot.position or {}
    local bot_x = tonumber(position.x or snapshot.x or snapshot.position_x)
    local bot_y = tonumber(position.y or snapshot.y or snapshot.position_y)
    if bot_x == nil or bot_y == nil then
      return
    end

    local delta_x = active_target.x - bot_x
    local delta_y = active_target.y - bot_y
    local distance_to_target = math.sqrt((delta_x * delta_x) + (delta_y * delta_y))
    update_player_input_probe(now_ms, bot_x, bot_y)
    if ctx.last_patrol_trace_ms == 0 or now_ms - ctx.last_patrol_trace_ms >= 1500 then
      ctx.last_patrol_trace_ms = now_ms
      local player_x, player_y = get_player_position()
      ctx.log_status(string.format(
        "bot=(%.2f,%.2f) player=(%.2f,%.2f) target=%s dist=%.2f moving=%s actor=%s",
        bot_x,
        bot_y,
        tonumber(player_x) or 0.0,
        tonumber(player_y) or 0.0,
        tostring(ctx.patrol.active_target),
        distance_to_target,
        tostring(snapshot.moving),
        tostring(snapshot.actor_address)))
    end

    if distance_to_target > cfg.patrol.arrival_distance then
      return
    end

    local next_target = ctx.patrol.active_target == "a" and "b" or "a"
    if not ctx.patrol_loop_confirmed and ctx.patrol.active_target == "b" and next_target == "a" then
      ctx.patrol_loop_confirmed = true
      ctx.log_status("patrol loop confirmed")
    end
    local ok, detail = issue_patrol_move(next_target)
    if not ok then
      ctx.fail(detail or "patrol move failed")
    end
  end

  return self
end

return {
  new = new,
}
