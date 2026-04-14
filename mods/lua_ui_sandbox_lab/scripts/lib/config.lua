local CONFIG_PATH = "config/probe-layout.ini"

local REQUIRED_SECTIONS = {
  addresses = {
    "local_player_actor_global",
    "gameplay_scene_global",
    "gameplay_index_state_table_global",
    "create_active_record_global",
    "create_owner_context_global",
    "create_remote_state_global",
    "create_selected_descriptor_global",
    "create_selected_subindex_global",
    "create_owner_slot_global",
    "trace_create_event_handler",
    "trace_player_refresh_runtime",
    "trace_actor_progression_refresh",
    "trace_player_appearance_apply_choice",
    "trace_gameplay_finalize_player_start",
    "trace_gameplay_create_player_slot",
    "trace_actor_world_register_gameplay_slot_actor",
    "trace_actor_world_unregister",
    "trace_puppet_manager_delete_puppet",
    "trace_actor_build_render_descriptor_from_source",
    "trace_equip_attachment_sink_attach",
    "trace_wizard_source_lookup",
    "trace_wizard_preview_factory",
  },
  offsets = {
    "gameplay_player_actor",
    "gameplay_item_list",
    "gameplay_visual_sink_primary",
    "gameplay_visual_sink_secondary",
    "gameplay_visual_sink_attachment",
    "gameplay_index_current_primary_selection",
    "actor_source_profile_ptr",
    "actor_render_state_window",
    "actor_render_variant_window",
    "actor_descriptor_block",
    "actor_runtime_visual_window",
    "source_render_fields",
    "standalone_wizard_progress_table_ptr",
    "actor_progression_runtime",
    "actor_equip_runtime",
    "create_probe_selection_window",
    "create_probe_preview_window",
    "create_probe_phase_window",
    "create_probe_wizard_window",
    "create_probe_child_preview",
    "create_probe_child_source_ptr",
    "create_probe_owner_source_ptr",
    "create_probe_selected_source_ptr",
    "source_render_variant_primary",
    "source_render_variant_secondary",
    "source_render_selection",
    "source_render_weapon_type",
    "source_render_variant_tertiary",
    "source_render_kind",
    "source_render_aux",
    "actor_source_kind",
    "actor_source_aux",
    "actor_attachment_ptr",
    "create_owner_mode",
    "create_owner_preview_driver",
    "create_owner_element_selected",
    "create_owner_element_hot",
    "create_owner_discipline_selected",
    "create_owner_discipline_hot",
  },
  sizes = {
    "player_actor_snapshot",
    "gameplay_item_list_window",
    "gameplay_visual_sink_window",
    "gameplay_index_selection_window",
    "actor_render_state_window",
    "actor_render_variant_window",
    "actor_descriptor_block",
    "actor_runtime_visual_window",
    "source_render_fields",
    "standalone_wizard_visual_runtime",
    "standalone_wizard_progress_entry",
    "standalone_wizard_equip",
    "create_probe_progress_head",
    "create_probe_selection_window",
    "create_probe_preview_window",
    "create_probe_phase_window",
    "create_probe_wizard_window",
    "create_probe_child_preview",
    "create_probe_child_actor_head",
    "create_probe_child_source_ptr_window",
    "create_probe_child_source_window",
    "create_probe_owner_head",
    "create_probe_owner_source_window",
    "create_probe_active_record_window",
    "create_probe_selected_descriptor_ptr_window",
    "create_probe_selected_descriptor_window",
    "create_slot_watch_window",
  },
  timing = {
    "create_probe_wait_ms",
  },
  wizard_selection_state_offsets = {
    "index_0",
    "index_1",
    "index_2",
    "index_3",
    "index_4",
  },
}

local function trim(value)
  local stripped = value:gsub("^%s+", "")
  stripped = stripped:gsub("%s+$", "")
  return stripped
end

local function parse_number(value)
  local trimmed = trim(value)
  local hex = trimmed:match("^0[xX]([0-9A-Fa-f]+)$")
  if hex ~= nil then
    return tonumber(hex, 16)
  end
  return tonumber(trimmed)
end

local function parse_ini(text)
  local sections = {}
  local current_section = nil

  for raw_line in (text .. "\n"):gmatch("([^\r\n]*)\r?\n") do
    local line = trim(raw_line)
    if line == "" or line:sub(1, 1) == ";" or line:sub(1, 1) == "#" then
      goto continue
    end

    local section_name = line:match("^%[([^%]]+)%]$")
    if section_name ~= nil then
      current_section = trim(section_name)
      if current_section == "" then
        error("empty section name in " .. CONFIG_PATH)
      end
      if sections[current_section] == nil then
        sections[current_section] = {}
      end
      goto continue
    end

    local key, value = line:match("^([^=]+)=(.+)$")
    if key == nil or value == nil or current_section == nil then
      error("invalid line in " .. CONFIG_PATH .. ": " .. raw_line)
    end

    sections[current_section][trim(key)] = trim(value)

    ::continue::
  end

  return sections
end

local function require_numeric_section(sections, section_name, keys)
  local section = sections[section_name]
  if type(section) ~= "table" then
    error("missing [" .. section_name .. "] in " .. CONFIG_PATH)
  end

  local values = {}
  for key, raw_value in pairs(section) do
    local parsed = parse_number(raw_value)
    if parsed == nil then
      error("invalid numeric value for [" .. section_name .. "] " .. key .. " in " .. CONFIG_PATH)
    end
    values[key] = parsed
  end

  for _, key in ipairs(keys) do
    local raw_value = section[key]
    if raw_value == nil then
      error("missing [" .. section_name .. "] " .. key .. " in " .. CONFIG_PATH)
    end
  end
  return values
end

local function load_config()
  if type(sd) ~= "table" or type(sd.runtime) ~= "table" or
      type(sd.runtime.get_mod_text_file) ~= "function" then
    error("sd.runtime.get_mod_text_file is unavailable")
  end

  local source = sd.runtime.get_mod_text_file(CONFIG_PATH)
  if type(source) ~= "string" then
    error("unable to read " .. CONFIG_PATH)
  end

  local sections = parse_ini(source)
  local config = {}
  for section_name, keys in pairs(REQUIRED_SECTIONS) do
    config[section_name] = require_numeric_section(sections, section_name, keys)
  end

  config.wizard_selection_state_offsets = {
    [0] = config.wizard_selection_state_offsets.index_0,
    [1] = config.wizard_selection_state_offsets.index_1,
    [2] = config.wizard_selection_state_offsets.index_2,
    [3] = config.wizard_selection_state_offsets.index_3,
    [4] = config.wizard_selection_state_offsets.index_4,
  }

  return config
end

return load_config()
