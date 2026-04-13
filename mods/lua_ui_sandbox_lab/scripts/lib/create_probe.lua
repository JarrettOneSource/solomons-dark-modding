local function new(ctx)
  local cfg = ctx.config
  local offsets = cfg.offsets
  local sizes = cfg.sizes
  local addresses = cfg.addresses

  local default_capture_phases = {
    { delay_ms = 120, label = "early" },
    { delay_ms = cfg.timing.create_probe_wait_ms, label = "settled" },
  }
  local discipline_capture_phases = {
    { delay_ms = 80, label = "early" },
    { delay_ms = 260, label = "mid" },
    { delay_ms = cfg.timing.create_probe_wait_ms, label = "settled" },
  }
  local action_sequence = {
    { action_id = ctx.actions.create_select_earth, tag = "element_earth", capture_phases = default_capture_phases },
    { action_id = ctx.actions.create_select_ether, tag = "element_ether", capture_phases = default_capture_phases },
    { action_id = ctx.actions.create_select_fire, tag = "element_fire", capture_phases = default_capture_phases },
    { action_id = ctx.actions.create_select_water, tag = "element_water", capture_phases = default_capture_phases },
    { action_id = ctx.actions.create_select_air, tag = "element_air", capture_phases = default_capture_phases },
    { action_id = ctx.actions.create_select_mind, tag = "discipline_mind", capture_phases = discipline_capture_phases },
    { action_id = ctx.actions.create_select_body, tag = "discipline_body", capture_phases = discipline_capture_phases },
    { action_id = ctx.actions.create_select_arcane, tag = "discipline_arcane", capture_phases = discipline_capture_phases },
  }

  local state = {
    started = false,
    completed = false,
    action_index = 1,
    active_action = nil,
    active_request_id = 0,
    activated_at_ms = 0,
    active_capture_index = 0,
    last_snapshot_prefix = nil,
    last_captured_suffixes = nil,
    last_wait_log_ms = 0,
    baseline_wait_started_ms = 0,
    debug_armed = false,
    last_dispatch_owner = 0,
    last_dispatch_control = 0,
    last_dispatch_status = nil,
  }

  local self = {}

  local function sanitize_snapshot_tag(value)
    return tostring(value):gsub("[^%w]+", "_")
  end

  local function get_capture_phase(action, capture_index)
    if type(action) ~= "table" or type(action.capture_phases) ~= "table" then
      return nil
    end
    return action.capture_phases[capture_index]
  end

  local function capture_snapshot(tag, dispatch_snapshot)
    if type(sd.debug) ~= "table" then
      ctx.fail("sd.debug unavailable")
      return false
    end

    local prefix = "create_probe_" .. sanitize_snapshot_tag(tag)
    local captured_suffixes = {}

    local function capture(suffix, address, size)
      local ok = ctx.snapshot_block(prefix .. suffix, address, size)
      if ok then
        captured_suffixes[#captured_suffixes + 1] = suffix
      end
      return ok
    end

    local player_state = ctx.get_player_state()
    local scene_name = ctx.get_scene_name()
    local create_surface_object = ctx.find_surface_object_ptr("create")
    local create_active_record_value = ctx.read_debug_ptr(addresses.create_active_record_global) or 0
    local create_owner_context_value = ctx.read_debug_ptr(addresses.create_owner_context_global) or 0
    local create_remote_state_value = ctx.read_debug_ptr(addresses.create_remote_state_global) or 0
    local create_selected_descriptor_value = ctx.read_debug_ptr(addresses.create_selected_descriptor_global) or 0
    local create_selected_subindex_value = ctx.read_debug_u32(addresses.create_selected_subindex_global)
    if create_selected_subindex_value == nil then
      create_selected_subindex_value = 0
    end
    local create_owner_slot_value = ctx.read_debug_ptr(addresses.create_owner_slot_global) or 0
    local dispatch_owner = 0
    local dispatch_control = 0
    local dispatch_kind = nil
    local actor_address = 0
    local progression_address = 0
    local render_selection = nil
    local animation_state = nil
    local render_frame_table = nil
    local attachment_ptr = nil
    local descriptor_signature = 0
    local source_profile = nil
    local render_variant_primary = nil
    local render_variant_secondary = nil
    local render_weapon_type = nil
    local render_variant_tertiary = nil

    if type(player_state) == "table" then
      actor_address = tonumber(player_state.render_subject_address or player_state.actor_address) or 0
      progression_address = tonumber(player_state.progression_address) or 0
      render_selection = player_state.render_subject_selection_byte or player_state.render_selection_byte
      animation_state = player_state.resolved_animation_state_id
      render_frame_table = player_state.render_subject_frame_table or player_state.render_frame_table
      attachment_ptr = player_state.render_subject_hub_visual_attachment_ptr or player_state.hub_visual_attachment_ptr
      source_profile =
        player_state.render_subject_hub_visual_source_profile_address or player_state.hub_visual_source_profile_address
      descriptor_signature =
        tonumber(player_state.render_subject_hub_visual_descriptor_signature or player_state.hub_visual_descriptor_signature) or 0
      render_variant_primary = player_state.render_subject_variant_primary or player_state.render_variant_primary
      render_variant_secondary = player_state.render_subject_variant_secondary or player_state.render_variant_secondary
      render_weapon_type = player_state.render_subject_weapon_type or player_state.render_weapon_type
      render_variant_tertiary = player_state.render_subject_variant_tertiary or player_state.render_variant_tertiary
    end

    if type(dispatch_snapshot) == "table" then
      dispatch_owner = tonumber(dispatch_snapshot.owner_address) or 0
      dispatch_control = tonumber(dispatch_snapshot.control_address) or 0
      dispatch_kind = dispatch_snapshot.dispatch_kind
    end

    local resolved_owner_source = ctx.read_object_u32(dispatch_owner, offsets.create_probe_owner_source_ptr) or 0
    local resolved_child_preview = ctx.read_object_u32(dispatch_owner, offsets.create_probe_child_preview) or 0
    local resolved_child_source = ctx.read_object_u32(resolved_child_preview, offsets.create_probe_child_source_ptr) or 0
    local create_selected_source = create_selected_descriptor_value
    local create_context_preview_object = resolved_child_preview
    local create_child_render_window =
      resolved_child_preview ~= 0 and (resolved_child_preview + offsets.actor_render_state_window) or 0
    local create_child_descriptor =
      resolved_child_preview ~= 0 and (resolved_child_preview + offsets.actor_descriptor_block) or 0
    local create_child_runtime_window =
      resolved_child_preview ~= 0 and (resolved_child_preview + offsets.actor_runtime_visual_window) or 0
    local create_child_source = resolved_child_source

    capture(
      "_global_active_record_ptr_window",
      addresses.create_active_record_global,
      sizes.create_slot_watch_window)
    capture(
      "_global_owner_context_ptr_window",
      addresses.create_owner_context_global,
      sizes.create_slot_watch_window)
    capture(
      "_global_remote_state_ptr_window",
      addresses.create_remote_state_global,
      sizes.create_slot_watch_window)
    capture(
      "_global_selected_descriptor_ptr_window",
      addresses.create_selected_descriptor_global,
      sizes.create_probe_selected_descriptor_ptr_window)
    capture(
      "_global_selected_subindex_window",
      addresses.create_selected_subindex_global,
      4)
    capture(
      "_global_owner_slot_ptr_window",
      addresses.create_owner_slot_global,
      sizes.create_slot_watch_window)

    if create_active_record_value ~= 0 then
      capture("_global_active_record_window", create_active_record_value, sizes.create_probe_active_record_window)
    end
    if create_owner_context_value ~= 0 then
      capture("_global_owner_context_window", create_owner_context_value, sizes.create_probe_owner_head)
      capture(
        "_global_owner_context_selection_window",
        create_owner_context_value + offsets.create_probe_selection_window,
        sizes.create_probe_selection_window)
      capture(
        "_global_owner_context_preview_window",
        create_owner_context_value + offsets.create_probe_preview_window,
        sizes.create_probe_preview_window)
      capture(
        "_global_owner_context_phase_window",
        create_owner_context_value + offsets.create_probe_phase_window,
        sizes.create_probe_phase_window)
      capture(
        "_global_owner_context_wizard_window",
        create_owner_context_value + offsets.create_probe_wizard_window,
        sizes.create_probe_wizard_window)
    end
    if create_selected_descriptor_value ~= 0 then
      capture(
        "_global_selected_descriptor_window",
        create_selected_descriptor_value,
        sizes.create_probe_selected_descriptor_window)
      capture(
        "_global_selected_descriptor_render_fields",
        create_selected_descriptor_value + offsets.source_render_fields,
        sizes.source_render_fields)
    end

    if dispatch_owner ~= 0 then
      capture("_resolved_owner_head", dispatch_owner, sizes.create_probe_owner_head)
      capture(
        "_resolved_owner_source_ptr_window",
        dispatch_owner + offsets.create_probe_owner_source_ptr,
        sizes.create_probe_child_source_ptr_window)
      if resolved_owner_source ~= 0 then
        capture("_resolved_owner_source_window", resolved_owner_source, sizes.create_probe_owner_source_window)
        capture(
          "_resolved_owner_source_render_fields",
          resolved_owner_source + offsets.source_render_fields,
          sizes.source_render_fields)
        capture("_resolved_owner_source_window_direct", resolved_owner_source, sizes.create_probe_owner_source_window)
        capture(
          "_resolved_owner_source_render_fields_direct",
          resolved_owner_source + offsets.source_render_fields,
          sizes.source_render_fields)
      end
      capture(
        "_resolved_selection_window",
        dispatch_owner + offsets.create_probe_selection_window,
        sizes.create_probe_selection_window)
      capture(
        "_resolved_preview_window",
        dispatch_owner + offsets.create_probe_preview_window,
        sizes.create_probe_preview_window)
      capture(
        "_resolved_phase_window",
        dispatch_owner + offsets.create_probe_phase_window,
        sizes.create_probe_phase_window)
      capture(
        "_resolved_wizard_window",
        dispatch_owner + offsets.create_probe_wizard_window,
        sizes.create_probe_wizard_window)
      if resolved_child_preview ~= 0 then
        capture("_resolved_child_preview", resolved_child_preview, sizes.create_probe_child_preview)
        capture("_resolved_child_actor_head", resolved_child_preview, sizes.create_probe_child_actor_head)
        capture(
          "_resolved_child_render_window",
          resolved_child_preview + offsets.actor_render_state_window,
          sizes.actor_render_state_window)
        capture(
          "_resolved_child_descriptor",
          resolved_child_preview + offsets.actor_descriptor_block,
          sizes.actor_descriptor_block)
        capture(
          "_resolved_child_runtime_window",
          resolved_child_preview + offsets.actor_runtime_visual_window,
          sizes.actor_runtime_visual_window)
        capture(
          "_resolved_child_source_ptr_window",
          resolved_child_preview + offsets.create_probe_child_source_ptr,
          sizes.create_probe_child_source_ptr_window)
        capture(
          "_resolved_child_render_window_direct",
          resolved_child_preview + offsets.actor_render_state_window,
          sizes.actor_render_state_window)
        capture(
          "_resolved_child_descriptor_direct",
          resolved_child_preview + offsets.actor_descriptor_block,
          sizes.actor_descriptor_block)
        capture(
          "_resolved_child_runtime_window_direct",
          resolved_child_preview + offsets.actor_runtime_visual_window,
          sizes.actor_runtime_visual_window)
      end
      if resolved_child_source ~= 0 then
        capture("_resolved_child_source_window", resolved_child_source, sizes.create_probe_child_source_window)
        capture(
          "_resolved_child_source_render_fields",
          resolved_child_source + offsets.source_render_fields,
          sizes.source_render_fields)
        capture("_resolved_child_source_window_direct", resolved_child_source, sizes.create_probe_child_source_window)
        capture(
          "_resolved_child_source_render_fields_direct",
          resolved_child_source + offsets.source_render_fields,
          sizes.source_render_fields)
      end
    end

    if dispatch_owner ~= 0 then
      capture("_create_context_head", dispatch_owner, sizes.create_probe_owner_head)
      capture(
        "_create_selected_source_ptr_window",
        dispatch_owner + offsets.create_probe_selected_source_ptr,
        sizes.create_probe_selected_descriptor_ptr_window)
    end
    if create_selected_source ~= 0 then
      capture("_create_selected_source_window", create_selected_source, sizes.create_probe_selected_descriptor_window)
      capture(
        "_create_selected_source_render_fields_direct",
        create_selected_source + offsets.source_render_fields,
        sizes.source_render_fields)
    end
    if create_context_preview_object ~= 0 then
      capture("_create_child_preview", create_context_preview_object, sizes.create_probe_child_preview)
      capture("_create_child_actor_head", create_context_preview_object, sizes.create_probe_child_actor_head)
      capture(
        "_create_child_source_ptr_window",
        create_context_preview_object + offsets.create_probe_child_source_ptr,
        sizes.create_probe_child_source_ptr_window)
    end
    if create_child_render_window ~= 0 then
      capture("_create_child_render_window", create_child_render_window, sizes.actor_render_state_window)
    end
    if create_child_descriptor ~= 0 then
      capture("_create_child_descriptor", create_child_descriptor, sizes.actor_descriptor_block)
    end
    if create_child_runtime_window ~= 0 then
      capture("_create_child_runtime_window", create_child_runtime_window, sizes.actor_runtime_visual_window)
    end
    if create_child_source ~= 0 then
      capture("_create_child_source_window", create_child_source, sizes.create_probe_child_source_window)
      capture(
        "_create_child_source_render_fields_direct",
        create_child_source + offsets.source_render_fields,
        sizes.source_render_fields)
    end

    if actor_address ~= 0 then
      capture("_actor_render_window", actor_address + offsets.actor_render_state_window, sizes.actor_render_state_window)
      capture("_actor_variant_window", actor_address + offsets.actor_render_variant_window, sizes.actor_render_variant_window)
      capture("_actor_descriptor", actor_address + offsets.actor_descriptor_block, sizes.actor_descriptor_block)
      capture("_actor_runtime_window", actor_address + offsets.actor_runtime_visual_window, sizes.actor_runtime_visual_window)
    end
    if source_profile ~= nil and source_profile ~= 0 then
      capture("_actor_source_render_fields", source_profile + offsets.source_render_fields, sizes.source_render_fields)
    end
    if progression_address ~= 0 then
      capture("_progression_head", progression_address, sizes.create_probe_progress_head)
    end

    local selection_state = ctx.resolve_wizard_selection_state(render_selection)
    if progression_address ~= 0 and selection_state ~= nil then
      if ctx.snapshot_ptr_block(
          prefix .. "_progression_selection_entry",
          progression_address + offsets.standalone_wizard_progress_table_ptr,
          selection_state * sizes.standalone_wizard_progress_entry,
          sizes.standalone_wizard_progress_entry) then
        captured_suffixes[#captured_suffixes + 1] = "_progression_selection_entry"
      end
    end

    local logged_any_state =
      actor_address ~= 0 or progression_address ~= 0 or dispatch_owner ~= 0 or
      resolved_owner_source ~= 0 or resolved_child_preview ~= 0 or
      create_active_record_value ~= 0 or create_owner_context_value ~= 0 or
      create_remote_state_value ~= 0 or create_selected_descriptor_value ~= 0 or
      create_owner_slot_value ~= 0
    if #captured_suffixes == 0 and not logged_any_state and scene_name == "transition" then
      return false
    end

    ctx.log_status(string.format(
      "create probe tag=%s scene=%s actor=%s render=%s anim=%s frame=%s attach=%s source=%s variants=%s/%s/%s/%s prog=%s create_surface=%s active_record=%s owner_context=%s remote_state=%s selected_descriptor=%s selected_subindex=%s owner_slot=%s dispatch_owner=%s dispatch_control=%s dispatch_kind=%s desc=0x%08X",
      tostring(tag),
      tostring(scene_name),
      tostring(actor_address),
      tostring(render_selection),
      tostring(animation_state),
      tostring(render_frame_table),
      tostring(attachment_ptr),
      tostring(source_profile),
      tostring(render_variant_primary),
      tostring(render_variant_secondary),
      tostring(render_weapon_type),
      tostring(render_variant_tertiary),
      tostring(progression_address),
      tostring(create_surface_object),
      ctx.format_hex32(create_active_record_value),
      ctx.format_hex32(create_owner_context_value),
      ctx.format_hex32(create_remote_state_value),
      ctx.format_hex32(create_selected_descriptor_value),
      tostring(create_selected_subindex_value),
      ctx.format_hex32(create_owner_slot_value),
      tostring(dispatch_owner),
      tostring(dispatch_control),
      tostring(dispatch_kind),
      descriptor_signature))
    ctx.log_status(string.format(
      "create probe sources tag=%s owner=%s state={%s} owner_source=%s owner_fields={%s} preview=%s preview_fields={%s} preview_source=%s preview_source_fields={%s} selected_descriptor=%s selected_descriptor_fields={%s} player_fields={%s} player_source_fields={%s}",
      tostring(tag),
      ctx.format_hex32(dispatch_owner),
      ctx.format_create_owner_selection_state(dispatch_owner),
      ctx.format_hex32(resolved_owner_source),
      ctx.format_source_render_fields(resolved_owner_source),
      ctx.format_hex32(resolved_child_preview),
      ctx.format_preview_actor_render_fields(resolved_child_preview),
      ctx.format_hex32(resolved_child_source),
      ctx.format_source_render_fields(resolved_child_source),
      ctx.format_hex32(create_selected_descriptor_value),
      ctx.format_source_render_fields(create_selected_descriptor_value),
      ctx.format_preview_actor_render_fields(actor_address),
      ctx.format_source_render_fields(source_profile)))

    if type(sd.debug.diff) == "function" and state.last_snapshot_prefix ~= nil and
        type(state.last_captured_suffixes) == "table" then
      local previous_suffixes = {}
      for _, suffix in ipairs(state.last_captured_suffixes) do
        previous_suffixes[suffix] = true
      end
      for _, suffix in ipairs(captured_suffixes) do
        if previous_suffixes[suffix] then
          sd.debug.diff(state.last_snapshot_prefix .. suffix, prefix .. suffix)
        end
      end
    end

    state.last_snapshot_prefix = prefix
    state.last_captured_suffixes = captured_suffixes
    state.last_dispatch_owner = dispatch_owner
    state.last_dispatch_control = dispatch_control
    return #captured_suffixes > 0 or logged_any_state
  end

  local function arm_debug_tools()
    if state.debug_armed or type(sd.debug) ~= "table" then
      return
    end

    local function try_watch(name, address, size)
      local ok, err = pcall(sd.debug.watch, name, address, size)
      if not ok then
        ctx.log_status("create probe failed to arm watch " .. tostring(name) .. ": " .. tostring(err))
      end
    end

    local function try_watch_write(name, address, size)
      local ok, armed = pcall(sd.debug.watch_write, name, address, size)
      if not ok then
        ctx.log_status("create probe failed to arm write watch " .. tostring(name) .. ": " .. tostring(armed))
        return
      end
      ctx.log_status("create probe write watch " .. tostring(name) .. " armed=" .. tostring(armed))
    end

    if type(sd.debug.trace_function) == "function" then
      pcall(sd.debug.trace_function, addresses.trace_create_event_handler, "create.event_handler")
      pcall(sd.debug.trace_function, addresses.trace_player_refresh_runtime, "player.refresh_runtime_handles")
      pcall(sd.debug.trace_function, addresses.trace_actor_progression_refresh, "actor.progression_refresh")
      pcall(sd.debug.trace_function, addresses.trace_actor_build_render_descriptor_from_source, "actor.build_render_descriptor_from_source")
      pcall(sd.debug.trace_function, addresses.trace_wizard_source_lookup, "create.wizard_source_lookup")
      pcall(sd.debug.trace_function, addresses.trace_wizard_preview_factory, "create.wizard_preview_factory")
    end

    if type(sd.debug.watch) == "function" then
      try_watch("create.active_record_global", addresses.create_active_record_global, sizes.create_slot_watch_window)
      try_watch("create.owner_context_global", addresses.create_owner_context_global, sizes.create_slot_watch_window)
      try_watch("create.remote_state_global", addresses.create_remote_state_global, sizes.create_slot_watch_window)
      try_watch("create.selected_descriptor_global", addresses.create_selected_descriptor_global, sizes.create_probe_selected_descriptor_ptr_window)
      try_watch("create.selected_subindex_global", addresses.create_selected_subindex_global, 4)
      try_watch("create.owner_slot_global", addresses.create_owner_slot_global, sizes.create_slot_watch_window)
    end

    if type(sd.debug.watch_write) == "function" then
      try_watch_write("create.active_record_write", addresses.create_active_record_global, 4)
      try_watch_write("create.owner_context_write", addresses.create_owner_context_global, 4)
      try_watch_write("create.remote_state_write", addresses.create_remote_state_global, 4)
      try_watch_write("create.selected_descriptor_write", addresses.create_selected_descriptor_global, 4)
      try_watch_write("create.selected_subindex_write", addresses.create_selected_subindex_global, 4)
      try_watch_write("create.owner_slot_write", addresses.create_owner_slot_global, 4)
    end

    if type(sd.debug.watch_ptr_field) == "function" then
      pcall(sd.debug.watch_ptr_field, addresses.local_player_actor_global, offsets.actor_source_profile_ptr, 4, "player.create_source_profile_ptr")
      pcall(sd.debug.watch_ptr_field, addresses.local_player_actor_global, offsets.actor_source_kind, 4, "player.create_source_kind")
      pcall(sd.debug.watch_ptr_field, addresses.local_player_actor_global, offsets.actor_source_aux, 4, "player.create_source_aux")
      pcall(sd.debug.watch_ptr_field, addresses.local_player_actor_global, offsets.actor_render_variant_window, sizes.actor_render_variant_window, "player.create_variant_window")
      pcall(sd.debug.watch_ptr_field, addresses.local_player_actor_global, offsets.actor_descriptor_block, sizes.actor_descriptor_block, "player.create_descriptor")
      pcall(sd.debug.watch_ptr_field, addresses.local_player_actor_global, offsets.actor_attachment_ptr, 4, "player.create_attachment_ptr")
    end

    state.debug_armed = true
    ctx.log_status("create probe armed direct create-wizard globals, write watches, traces, and watches")
  end

  function self.run(now_ms, setup_complete)
    if ctx.failed or not setup_complete or state.completed then
      return
    end

    arm_debug_tools()

    if not state.started then
      local create_surface_object = ctx.find_surface_object_ptr("create")
      local create_active_record = ctx.read_debug_ptr(addresses.create_active_record_global) or 0
      local create_owner_context = ctx.read_debug_ptr(addresses.create_owner_context_global) or 0
      local create_remote_state = ctx.read_debug_ptr(addresses.create_remote_state_global) or 0
      local create_selected_descriptor = ctx.read_debug_ptr(addresses.create_selected_descriptor_global) or 0
      local create_owner_slot = ctx.read_debug_ptr(addresses.create_owner_slot_global) or 0
      local snapshot = ctx.get_snapshot()
      local active_surface = type(snapshot) == "table" and snapshot.surface_id or nil
      if state.baseline_wait_started_ms == 0 then
        state.baseline_wait_started_ms = now_ms
      end
      if capture_snapshot("baseline") then
        state.started = true
        ctx.log_status("create probe baseline captured")
      elseif now_ms - state.baseline_wait_started_ms >= 2000 then
        state.started = true
        ctx.log_status("create probe starting without baseline snapshot")
      elseif state.last_wait_log_ms == 0 or now_ms - state.last_wait_log_ms >= 1000 then
        state.last_wait_log_ms = now_ms
        ctx.log_status(string.format(
          "create probe waiting for create surface state scene=%s active_surface=%s create_surface=%s active_record=%s owner_context=%s remote_state=%s selected_descriptor=%s owner_slot=%s",
          tostring(ctx.get_scene_name()),
          tostring(active_surface),
          tostring(create_surface_object),
          ctx.format_hex32(create_active_record),
          ctx.format_hex32(create_owner_context),
          ctx.format_hex32(create_remote_state),
          ctx.format_hex32(create_selected_descriptor),
          ctx.format_hex32(create_owner_slot)))
      end
      return
    end

    local action = action_sequence[state.action_index]
    if action == nil then
      state.completed = true
      ctx.log_status("create probe completed")
      return
    end

    if state.active_action == nil then
      if type(sd.ui) ~= "table" or type(sd.ui.activate_action) ~= "function" then
        ctx.fail("sd.ui.activate_action unavailable")
        return
      end

      local ok, request_id_or_error = sd.ui.activate_action(action.action_id, "create")
      if not ok then
        ctx.fail(tostring(request_id_or_error or ("create probe activation failed for " .. tostring(action.action_id))))
        return
      end

      state.active_action = action
      state.active_request_id = tonumber(request_id_or_error) or 0
      state.activated_at_ms = now_ms
      state.active_capture_index = 1
      ctx.log_status("create probe activated " .. tostring(action.action_id) .. " request_id=" .. tostring(request_id_or_error))
      return
    end

    local dispatch_snapshot = ctx.get_action_dispatch_snapshot(state.active_request_id)
    local dispatch_owner = type(dispatch_snapshot) == "table" and (tonumber(dispatch_snapshot.owner_address) or 0) or 0
    local dispatch_control = type(dispatch_snapshot) == "table" and (tonumber(dispatch_snapshot.control_address) or 0) or 0
    local dispatch_status = type(dispatch_snapshot) == "table" and tostring(dispatch_snapshot.status) or nil
    if type(dispatch_snapshot) == "table" and dispatch_owner ~= 0 and
        (dispatch_owner ~= state.last_dispatch_owner or
         dispatch_control ~= state.last_dispatch_control or
         dispatch_status ~= state.last_dispatch_status) then
      ctx.log_status(string.format(
        "create probe dispatch request=%s status=%s owner=%s control=%s kind=%s",
        tostring(state.active_request_id),
        tostring(dispatch_snapshot.status),
        tostring(dispatch_snapshot.owner_address),
        tostring(dispatch_snapshot.control_address),
        tostring(dispatch_snapshot.dispatch_kind)))
      state.last_dispatch_owner = dispatch_owner
      state.last_dispatch_control = dispatch_control
      state.last_dispatch_status = dispatch_status
    end

    local capture_phase = get_capture_phase(state.active_action, state.active_capture_index)
    if capture_phase == nil then
      state.action_index = state.action_index + 1
      state.active_action = nil
      state.active_request_id = 0
      state.active_capture_index = 0
      state.last_dispatch_status = nil
      return
    end

    local capture_delay_ms = tonumber(capture_phase.delay_ms) or cfg.timing.create_probe_wait_ms
    if now_ms - state.activated_at_ms < capture_delay_ms then
      return
    end

    local tag = string.format(
      "%02d_%s_%s",
      state.action_index,
      state.active_action.tag,
      tostring(capture_phase.label or state.active_capture_index))
    if not capture_snapshot(tag, dispatch_snapshot) then
      ctx.log_status("create probe snapshot empty for " .. tostring(state.active_action.action_id))
    end

    state.active_capture_index = state.active_capture_index + 1
    if get_capture_phase(state.active_action, state.active_capture_index) == nil then
      state.action_index = state.action_index + 1
      state.active_action = nil
      state.active_request_id = 0
      state.active_capture_index = 0
      state.last_dispatch_status = nil
    end
  end

  return self
end

return {
  new = new,
}
