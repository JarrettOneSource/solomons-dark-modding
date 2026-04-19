local function new_context(config, actions)
  local ctx = {
    actions = actions,
    config = config,
    failed = false,
    failure_message = nil,
    lifecycle_events = {
      ["run.started"] = false,
    },
    mode = nil,
    active_preset = nil,
    mode_handlers = {},
  }

  function ctx.log_error(message)
    print("[ui.sandbox] " .. tostring(message))
  end

  function ctx.log_status(message)
    print("[ui.sandbox] " .. tostring(message))
  end

  function ctx.fail(message)
    if ctx.failed then
      return
    end

    ctx.failed = true
    ctx.failure_message = tostring(message)
    ctx.log_error(ctx.failure_message)
    if type(ctx.active_preset) == "string" and ctx.active_preset ~= "" then
      ctx.log_error("sequence aborted preset=" .. ctx.active_preset .. " reason=" .. ctx.failure_message)
    end
  end

  function ctx.mark_sequence_complete()
    if ctx.sequence_complete_logged then
      return
    end

    ctx.sequence_complete_logged = true
    if type(ctx.active_preset) == "string" and ctx.active_preset ~= "" then
      ctx.log_status("sequence complete preset=" .. ctx.active_preset)
    end
  end

  function ctx.get_snapshot()
    if type(sd.ui) ~= "table" or type(sd.ui.get_snapshot) ~= "function" then
      return nil
    end

    return sd.ui.get_snapshot()
  end

  function ctx.get_environment_variable(name)
    if type(name) ~= "string" or name == "" then
      return nil
    end
    if type(sd.runtime) ~= "table" or type(sd.runtime.get_environment_variable) ~= "function" then
      return nil
    end
    return sd.runtime.get_environment_variable(name)
  end

  function ctx.get_environment_integer(name, default_value)
    local value = ctx.get_environment_variable(name)
    local numeric = tonumber(value)
    if numeric == nil then
      return default_value
    end
    return numeric
  end

  function ctx.get_player_state()
    if type(sd.player) ~= "table" or type(sd.player.get_state) ~= "function" then
      return nil
    end

    return sd.player.get_state()
  end

  function ctx.get_scene_state()
    if type(sd.world) ~= "table" or type(sd.world.get_scene) ~= "function" then
      return nil
    end

    return sd.world.get_scene()
  end

  function ctx.get_scene_name()
    local scene_state = ctx.get_scene_state()
    if type(scene_state) ~= "table" then
      return nil
    end

    return tostring(scene_state.name or scene_state.kind or "")
  end

  function ctx.parse_runtime_address(value)
    if value == nil then
      return nil
    end

    local numeric = tonumber(value)
    if numeric ~= nil then
      return numeric
    end

    if type(value) == "string" then
      local trimmed = value:match("^%s*(.-)%s*$")
      if trimmed ~= nil then
        local hex = trimmed:match("^0[xX]([0-9A-Fa-f]+)$")
        if hex ~= nil then
          return tonumber(hex, 16)
        end
      end
    end

    return nil
  end

  function ctx.get_gameplay_address()
    local scene_state = ctx.get_scene_state()
    if type(scene_state) ~= "table" then
      return 0
    end

    local value = scene_state.id or scene_state.scene_id
    local numeric = tonumber(value)
    if numeric ~= nil then
      return numeric
    end

    if type(value) == "string" then
      local trimmed = value:match("^%s*(.-)%s*$")
      if trimmed ~= nil then
        local hex = trimmed:match("^0[xX]([0-9A-Fa-f]+)$")
        if hex ~= nil then
          return tonumber(hex, 16) or 0
        end
      end
    end

    return 0
  end

  function ctx.format_hex32(value)
    local numeric = tonumber(value)
    if numeric == nil then
      return tostring(value)
    end
    if numeric < 0 then
      numeric = numeric + 0x100000000
    end
    return string.format("0x%08X", numeric % 0x100000000)
  end

  function ctx.format_decimal_or_nil(value)
    local numeric = tonumber(value)
    if numeric == nil then
      return "nil"
    end
    return tostring(numeric)
  end

  function ctx.snapshot_block(name, address, size)
    if address == nil or address == 0 or size == nil or size <= 0 then
      return false
    end
    if type(sd.debug) ~= "table" or type(sd.debug.snapshot) ~= "function" then
      return false
    end
    sd.debug.snapshot(name, address, size)
    return true
  end

  function ctx.snapshot_ptr_block(name, ptr_address, offset, size)
    if ptr_address == nil or ptr_address == 0 or size == nil or size <= 0 then
      return false
    end
    if type(sd.debug) ~= "table" or type(sd.debug.snapshot_ptr_field) ~= "function" then
      return false
    end
    sd.debug.snapshot_ptr_field(name, ptr_address, offset, size)
    return true
  end

  function ctx.snapshot_nested_ptr_block(name, ptr_address, outer_offset, inner_offset, size)
    if ptr_address == nil or ptr_address == 0 or size == nil or size <= 0 then
      return false
    end
    if type(sd.debug.snapshot_nested_ptr_field) ~= "function" then
      return false
    end
    sd.debug.snapshot_nested_ptr_field(name, ptr_address, outer_offset, inner_offset, size)
    return true
  end

  function ctx.snapshot_double_nested_ptr_block(name, ptr_address, outer_offset, middle_offset, inner_offset, size)
    if ptr_address == nil or ptr_address == 0 or size == nil or size <= 0 then
      return false
    end
    if type(sd.debug.snapshot_double_nested_ptr_field) ~= "function" then
      return false
    end
    sd.debug.snapshot_double_nested_ptr_field(
      name,
      ptr_address,
      outer_offset,
      middle_offset,
      inner_offset,
      size)
    return true
  end

  function ctx.read_debug_ptr(address)
    if address == nil or address == 0 then
      return nil
    end
    if type(sd.debug) ~= "table" or type(sd.debug.read_ptr) ~= "function" then
      return nil
    end

    local ok, value = pcall(sd.debug.read_ptr, address)
    if not ok then
      return nil
    end
    return tonumber(value)
  end

  function ctx.read_object_u32(object_address, offset)
    if object_address == nil or object_address == 0 then
      return nil
    end
    return ctx.read_debug_ptr(object_address + offset)
  end

  function ctx.read_object_u8(object_address, offset)
    local value = ctx.read_object_u32(object_address, offset)
    if value == nil then
      return nil
    end
    return value % 0x100
  end

  function ctx.read_debug_ptr_field(ptr_address, offset)
    if ptr_address == nil or ptr_address == 0 then
      return nil
    end
    if type(sd.debug) ~= "table" or type(sd.debug.read_ptr_field) ~= "function" then
      return nil
    end

    local ok, value = pcall(sd.debug.read_ptr_field, ptr_address, offset)
    if not ok then
      return nil
    end
    return tonumber(value)
  end

  function ctx.read_debug_u32(address)
    if address == nil or address == 0 then
      return nil
    end
    if type(sd.debug) ~= "table" or type(sd.debug.read_u32) ~= "function" then
      return nil
    end

    local ok, value = pcall(sd.debug.read_u32, address)
    if not ok then
      return nil
    end
    return tonumber(value)
  end

  function ctx.resolve_wizard_selection_state(render_selection_byte)
    local selection = tonumber(render_selection_byte)
    if selection == nil then
      return nil
    end
    return ctx.config.wizard_selection_state_offsets[selection]
  end

  function ctx.resolve_player_actor_snapshot_target()
    local player_state = ctx.get_player_state()
    if type(player_state) == "table" then
      local player_actor = tonumber(player_state.actor_address) or 0
      if player_actor == 0 then
        player_actor = tonumber(player_state.render_subject_address) or 0
      end
      if player_actor ~= 0 then
        return player_actor, "sd.player.get_state()", player_state
      end
    end

    local gameplay_address = ctx.get_gameplay_address()
    if gameplay_address ~= 0 then
      local slot0_actor =
        ctx.read_debug_ptr_field(gameplay_address, ctx.config.offsets.gameplay_player_actor) or 0
      if slot0_actor ~= 0 then
        return slot0_actor,
          string.format("gameplay+0x%X", ctx.config.offsets.gameplay_player_actor),
          player_state
      end
    end

    local global_actor = ctx.read_debug_u32(ctx.config.addresses.local_player_actor_global) or 0
    if global_actor ~= 0 then
      return global_actor,
        string.format("u32[%s]", ctx.format_hex32(ctx.config.addresses.local_player_actor_global)),
        player_state
    end

    return 0, nil, player_state
  end

  function ctx.format_source_render_fields(source_address)
    if source_address == nil or source_address == 0 then
      return "nil"
    end

    local offsets = ctx.config.offsets
    local variant_primary = ctx.read_object_u8(source_address, offsets.source_render_variant_primary)
    local variant_secondary = ctx.read_object_u8(source_address, offsets.source_render_variant_secondary)
    local render_selection = ctx.read_object_u8(source_address, offsets.source_render_selection)
    local weapon_type = ctx.read_object_u8(source_address, offsets.source_render_weapon_type)
    local variant_tertiary = ctx.read_object_u8(source_address, offsets.source_render_variant_tertiary)
    local source_kind = ctx.read_object_u32(source_address, offsets.source_render_kind)
    local source_aux = ctx.read_object_u32(source_address, offsets.source_render_aux)

    return string.format(
      "kind=%s aux=%s variants=%s/%s sel=%s weapon=%s tertiary=%s",
      ctx.format_decimal_or_nil(source_kind),
      ctx.format_decimal_or_nil(source_aux),
      ctx.format_decimal_or_nil(variant_primary),
      ctx.format_decimal_or_nil(variant_secondary),
      ctx.format_decimal_or_nil(render_selection),
      ctx.format_decimal_or_nil(weapon_type),
      ctx.format_decimal_or_nil(variant_tertiary))
  end

  function ctx.format_preview_actor_render_fields(actor_address)
    if actor_address == nil or actor_address == 0 then
      return "nil"
    end

    local offsets = ctx.config.offsets
    local source_kind = ctx.read_object_u32(actor_address, offsets.actor_source_kind)
    local source_aux = ctx.read_object_u32(actor_address, offsets.actor_source_aux)
    local variant_primary = ctx.read_object_u8(actor_address, offsets.actor_render_variant_window)
    local variant_secondary = ctx.read_object_u8(actor_address, offsets.actor_render_variant_window + 1)
    local weapon_type = ctx.read_object_u8(actor_address, offsets.actor_render_variant_window + 2)
    local render_selection = ctx.read_object_u8(actor_address, offsets.actor_render_variant_window + 3)
    local variant_tertiary = ctx.read_object_u8(actor_address, offsets.actor_render_variant_window + 4)
    local attachment_ptr = ctx.read_object_u32(actor_address, offsets.actor_attachment_ptr)

    return string.format(
      "kind=%s aux=%s variants=%s/%s sel=%s weapon=%s tertiary=%s attach=%s",
      ctx.format_decimal_or_nil(source_kind),
      ctx.format_decimal_or_nil(source_aux),
      ctx.format_decimal_or_nil(variant_primary),
      ctx.format_decimal_or_nil(variant_secondary),
      ctx.format_decimal_or_nil(render_selection),
      ctx.format_decimal_or_nil(weapon_type),
      ctx.format_decimal_or_nil(variant_tertiary),
      ctx.format_hex32(attachment_ptr))
  end

  function ctx.format_create_owner_selection_state(owner_address)
    if owner_address == nil or owner_address == 0 then
      return "nil"
    end

    local offsets = ctx.config.offsets
    local selected_source = ctx.read_object_u32(owner_address, offsets.create_probe_owner_source_ptr)
    local mode = ctx.read_object_u32(owner_address, offsets.create_owner_mode)
    local preview_driver = ctx.read_object_u32(owner_address, offsets.create_owner_preview_driver)
    local element_selected = ctx.read_object_u32(owner_address, offsets.create_owner_element_selected)
    local element_hot = ctx.read_object_u32(owner_address, offsets.create_owner_element_hot)
    local discipline_selected = ctx.read_object_u32(owner_address, offsets.create_owner_discipline_selected)
    local discipline_hot = ctx.read_object_u32(owner_address, offsets.create_owner_discipline_hot)

    return string.format(
      "selected_source=%s mode=%s preview_driver=%s element=%s hover_element=%s discipline=%s hover_discipline=%s",
      ctx.format_hex32(selected_source),
      ctx.format_decimal_or_nil(mode),
      ctx.format_hex32(preview_driver),
      ctx.format_decimal_or_nil(element_selected),
      ctx.format_decimal_or_nil(element_hot),
      ctx.format_decimal_or_nil(discipline_selected),
      ctx.format_decimal_or_nil(discipline_hot))
  end

  function ctx.find_surface_object_ptr(surface_id)
    local snapshot = ctx.get_snapshot()
    if type(snapshot) ~= "table" or type(snapshot.elements) ~= "table" then
      return nil
    end

    for _, element in ipairs(snapshot.elements) do
      if type(element) == "table" and
          (element.surface_id == surface_id or element.surface_root_id == surface_id) then
        local surface_object_ptr = tonumber(element.surface_object_ptr)
        if surface_object_ptr ~= nil and surface_object_ptr ~= 0 then
          return surface_object_ptr
        end
      end
    end

    return nil
  end

  function ctx.get_action_dispatch_snapshot(request_id)
    if request_id == nil or request_id == 0 then
      return nil
    end
    if type(sd.ui) ~= "table" or type(sd.ui.get_action_dispatch) ~= "function" then
      return nil
    end

    local ok, result = pcall(sd.ui.get_action_dispatch, request_id)
    if not ok or type(result) ~= "table" then
      return nil
    end
    return result
  end

  return ctx
end

return {
  new_context = new_context,
}
