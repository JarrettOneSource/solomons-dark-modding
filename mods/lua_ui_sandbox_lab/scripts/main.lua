local DEFAULT_MODE = "patrol"
local ACTIVE_PRESET = nil
if type(sd) == "table" and type(sd.runtime) == "table" and
    type(sd.runtime.get_environment_variable) == "function" then
  ACTIVE_PRESET = sd.runtime.get_environment_variable("SDMOD_UI_SANDBOX_PRESET")
end
local MODE = ACTIVE_PRESET == "create_probe" and "create_probe" or DEFAULT_MODE

local ACTIONS = {
  dialog_primary = "dialog.primary",
  main_menu_play = "main_menu.play",
  main_menu_new_game = "main_menu.new_game",
  create_select_earth = "create.select_element_earth",
  create_select_ether = "create.select_element_ether",
  create_select_fire = "create.select_element_fire",
  create_select_water = "create.select_element_water",
  create_select_air = "create.select_element_air",
  create_select_mind = "create.select_discipline_mind",
  create_select_body = "create.select_discipline_body",
  create_select_arcane = "create.select_discipline_arcane",
}

local lifecycle_events = {
  ["run.started"] = false,
}

local PATROL_SPAWN_OFFSET_X = 32.0
local PATROL_SPAWN_OFFSET_Y = 0.0
local PATROL_HALF_DISTANCE = 12.0
local PATROL_ARRIVAL_DISTANCE = 0.75
local LOCAL_PLAYER_ACTOR_GLOBAL = 0x0081D5BC
local CREATE_OBJECT_GLOBAL = 0x008203F0
local CREATE_CONTROLLER_GLOBAL = 0x0081F618
local GAMEPLAY_PLAYER_ACTOR_OFFSET = 0x1358
local ACTOR_SOURCE_PROFILE_PTR_OFFSET = 0x178
local ACTOR_RENDER_STATE_WINDOW_OFFSET = 0x138
local ACTOR_RENDER_STATE_WINDOW_SIZE = 0x130
local ACTOR_RENDER_VARIANT_WINDOW_OFFSET = 0x23C
local ACTOR_RENDER_VARIANT_WINDOW_SIZE = 0x08
local ACTOR_DESCRIPTOR_BLOCK_OFFSET = 0x244
local ACTOR_DESCRIPTOR_BLOCK_SIZE = 0x20
local ACTOR_RUNTIME_VISUAL_WINDOW_OFFSET = 0x1FC
local ACTOR_RUNTIME_VISUAL_WINDOW_SIZE = 0x10C
local SOURCE_RENDER_FIELDS_OFFSET = 0x98
local SOURCE_RENDER_FIELDS_SIZE = 0x14
local STANDALONE_WIZARD_VISUAL_RUNTIME_SIZE = 0x8E4
local STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE = 0x70
local STANDALONE_WIZARD_PROGRESS_TABLE_PTR_OFFSET = 0x20
local STANDALONE_WIZARD_EQUIP_SIZE = 100
local ACTOR_PROGRESSION_RUNTIME_OFFSET = 0x200
local ACTOR_EQUIP_RUNTIME_OFFSET = 0x1FC
local INPUT_TEST_CLICK_POINTS = {
  { x = 0.82, y = 0.70 },
  { x = 0.18, y = 0.70 },
}
local INPUT_TEST_PLAYER_MOVE_THRESHOLD = 8.0
local INPUT_TEST_RETRY_DELAY_MS = 1500
local INPUT_TEST_TIMEOUT_MS = 6000
local INPUT_TEST_PATROL_BAND_SLOP = 2.5
local CREATE_PROBE_WAIT_MS = 1200
local CREATE_PROBE_PROGRESS_HEAD_SIZE = 0x120
local CREATE_PROBE_SELECTION_WINDOW_OFFSET = 0x180
local CREATE_PROBE_SELECTION_WINDOW_SIZE = 0x100
local CREATE_PROBE_PREVIEW_WINDOW_OFFSET = 0x240
local CREATE_PROBE_PREVIEW_WINDOW_SIZE = 0x80
local CREATE_PROBE_PHASE_WINDOW_OFFSET = 0x3F0
local CREATE_PROBE_PHASE_WINDOW_SIZE = 0x90
local CREATE_PROBE_WIZARD_WINDOW_OFFSET = 0x5C0
local CREATE_PROBE_WIZARD_WINDOW_SIZE = 0x30
local CREATE_PROBE_CHILD_PREVIEW_OFFSET = 0x27C
local CREATE_PROBE_CHILD_PREVIEW_SIZE = 0x120
local CREATE_PROBE_CHILD_ACTOR_HEAD_SIZE = 0x310
local CREATE_PROBE_CHILD_SOURCE_PTR_OFFSET = 0x178
local CREATE_PROBE_CHILD_SOURCE_PTR_WINDOW_SIZE = 0x20
local CREATE_PROBE_CHILD_SOURCE_WINDOW_SIZE = 0xD8
local CREATE_PROBE_OWNER_HEAD_SIZE = 0x90
local CREATE_PROBE_OWNER_SOURCE_PTR_OFFSET = 0x48
local CREATE_PROBE_OWNER_SOURCE_WINDOW_SIZE = 0xD8
local CREATE_PROBE_SELECTED_SOURCE_PTR_OFFSET = 0x48
local CREATE_PROBE_SELECTED_SOURCE_PTR_WINDOW_SIZE = 0x20
local CREATE_PROBE_SELECTED_SOURCE_WINDOW_SIZE = 0xD8
local TRACE_CREATE_EVENT_HANDLER = 0x0058E600
local TRACE_PLAYER_REFRESH_RUNTIME = 0x0052A370
local TRACE_ACTOR_PROGRESSION_REFRESH = 0x0065F9A0
local TRACE_WIZARD_SOURCE_LOOKUP = 0x00683B90
local TRACE_WIZARD_PREVIEW_FACTORY = 0x00466FA0
local CREATE_PROBE_DEFAULT_CAPTURE_PHASES = {
  { delay_ms = 120, label = "early" },
  { delay_ms = CREATE_PROBE_WAIT_MS, label = "settled" },
}
local CREATE_PROBE_DISCIPLINE_CAPTURE_PHASES = {
  { delay_ms = 80, label = "early" },
  { delay_ms = 260, label = "mid" },
  { delay_ms = CREATE_PROBE_WAIT_MS, label = "settled" },
}

local CREATE_PROBE_ACTION_SEQUENCE = {
  { action_id = ACTIONS.create_select_earth, tag = "element_earth", capture_phases = CREATE_PROBE_DEFAULT_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_ether, tag = "element_ether", capture_phases = CREATE_PROBE_DEFAULT_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_fire, tag = "element_fire", capture_phases = CREATE_PROBE_DEFAULT_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_water, tag = "element_water", capture_phases = CREATE_PROBE_DEFAULT_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_air, tag = "element_air", capture_phases = CREATE_PROBE_DEFAULT_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_mind, tag = "discipline_mind", capture_phases = CREATE_PROBE_DISCIPLINE_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_body, tag = "discipline_body", capture_phases = CREATE_PROBE_DISCIPLINE_CAPTURE_PHASES },
  { action_id = ACTIONS.create_select_arcane, tag = "discipline_arcane", capture_phases = CREATE_PROBE_DISCIPLINE_CAPTURE_PHASES },
}

local PATROL_SETUP_STEPS = {
  {
    kind = "wait_action",
    action_id = ACTIONS.dialog_primary,
    surface_id = "dialog",
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.dialog_primary,
    surface_id = "dialog",
  },
  {
    kind = "wait_surface",
    surface_id = "main_menu",
  },
  {
    kind = "wait_action",
    action_id = ACTIONS.main_menu_play,
    surface_id = "main_menu",
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.main_menu_play,
    surface_id = "main_menu",
  },
  {
    kind = "wait_action",
    action_id = ACTIONS.main_menu_new_game,
    surface_id = "main_menu",
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.main_menu_new_game,
    surface_id = "main_menu",
  },
  {
    kind = "delay",
    duration_ms = 5000,
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.create_select_water,
    surface_id = "create",
    skip_find = true,
  },
  {
    kind = "delay",
    duration_ms = 3000,
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.create_select_arcane,
    surface_id = "create",
    skip_find = true,
  },
  {
    kind = "delay",
    duration_ms = 18000,
  },
  {
    kind = "hub_start_testrun",
  },
  {
    kind = "delay",
    duration_ms = 5000,
  },
  {
    kind = "spawn_patrol_bot",
  },
}

local CREATE_PROBE_SETUP_STEPS = {
  {
    kind = "wait_action",
    action_id = ACTIONS.dialog_primary,
    surface_id = "dialog",
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.dialog_primary,
    surface_id = "dialog",
  },
  {
    kind = "wait_surface",
    surface_id = "main_menu",
  },
  {
    kind = "wait_action",
    action_id = ACTIONS.main_menu_play,
    surface_id = "main_menu",
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.main_menu_play,
    surface_id = "main_menu",
  },
  {
    kind = "wait_action",
    action_id = ACTIONS.main_menu_new_game,
    surface_id = "main_menu",
  },
  {
    kind = "activate_action",
    action_id = ACTIONS.main_menu_new_game,
    surface_id = "main_menu",
  },
  {
    kind = "delay",
    duration_ms = 18000,
  },
}

local steps = MODE == "create_probe" and CREATE_PROBE_SETUP_STEPS or PATROL_SETUP_STEPS

local step_index = 1
local active_delay_started_ms = nil
local setup_complete = false
local failed = false
local failure_message = nil
local spawned_bot_id = nil
local patrol = nil
local patrol_loop_confirmed = false
local last_patrol_trace_ms = 0
local player_input_test = nil
local get_patrol_bot_snapshot = nil
local visual_diff_probe = {
  requested = false,
  completed = false,
  last_wait_log_ms = 0,
}
local create_probe = {
  started = false,
  completed = false,
  action_index = 1,
  active_action = nil,
  active_request_id = 0,
  activated_at_ms = 0,
  active_capture_index = 0,
  last_snapshot_prefix = nil,
  last_wait_log_ms = 0,
  baseline_wait_started_ms = 0,
  debug_armed = false,
  last_dispatch_owner = 0,
  last_dispatch_control = 0,
  last_dispatch_status = nil,
}

local function log_error(message)
  print("[patrol.bot] " .. tostring(message))
end

local function log_status(message)
  print("[patrol.bot] " .. tostring(message))
end

local function fail(message)
  if failed then
    return
  end

  failed = true
  failure_message = tostring(message)
  log_error(failure_message)
end

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
    requested = false,
    completed = false,
    last_wait_log_ms = 0,
  }
end

local function get_snapshot()
  if type(sd.ui) ~= "table" or type(sd.ui.get_snapshot) ~= "function" then
    return nil
  end

  return sd.ui.get_snapshot()
end

local function get_player_state()
  if type(sd.player) ~= "table" or type(sd.player.get_state) ~= "function" then
    return nil
  end

  return sd.player.get_state()
end

local function get_scene_state()
  if type(sd.world) ~= "table" or type(sd.world.get_scene) ~= "function" then
    return nil
  end

  return sd.world.get_scene()
end

local function get_scene_name()
  local scene_state = get_scene_state()
  if type(scene_state) ~= "table" then
    return nil
  end

  return tostring(scene_state.name or scene_state.kind or "")
end

local function resolve_wizard_selection_state(render_selection_byte)
  local selection = tonumber(render_selection_byte)
  if selection == nil then
    return nil
  end

  if selection == 0 then
    return 0x08
  end
  if selection == 1 then
    return 0x10
  end
  if selection == 2 then
    return 0x18
  end
  if selection == 3 then
    return 0x20
  end
  if selection == 4 then
    return 0x28
  end

  return nil
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
    player_variant_primary =
      player_state.render_subject_variant_primary or player_state.render_variant_primary
    player_variant_secondary =
      player_state.render_subject_variant_secondary or player_state.render_variant_secondary
    player_weapon_type =
      player_state.render_subject_weapon_type or player_state.render_weapon_type
    player_variant_tertiary =
      player_state.render_subject_variant_tertiary or player_state.render_variant_tertiary
  end

  log_status(string.format(
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

local function snapshot_block(name, address, size)
  if address == nil or address == 0 or size == nil or size <= 0 then
    return false
  end
  if type(sd.debug) ~= "table" or type(sd.debug.snapshot) ~= "function" then
    return false
  end
  sd.debug.snapshot(name, address, size)
  return true
end

local function snapshot_ptr_block(name, ptr_address, offset, size)
  if ptr_address == nil or ptr_address == 0 or size == nil or size <= 0 then
    return false
  end
  if type(sd.debug) ~= "table" or type(sd.debug.snapshot_ptr_field) ~= "function" then
    return false
  end
  sd.debug.snapshot_ptr_field(name, ptr_address, offset, size)
  return true
end

local function snapshot_nested_ptr_block(name, ptr_address, outer_offset, inner_offset, size)
  if ptr_address == nil or ptr_address == 0 or size == nil or size <= 0 then
    return false
  end
  if type(sd.debug.snapshot_nested_ptr_field) ~= "function" then
    return false
  end
  sd.debug.snapshot_nested_ptr_field(name, ptr_address, outer_offset, inner_offset, size)
  return true
end

local function snapshot_double_nested_ptr_block(name, ptr_address, outer_offset, middle_offset, inner_offset, size)
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

local function parse_runtime_address(value)
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

local function format_hex32(value)
  local numeric = tonumber(value)
  if numeric == nil then
    return tostring(value)
  end
  if numeric < 0 then
    numeric = numeric + 0x100000000
  end
  return string.format("0x%08X", numeric % 0x100000000)
end

local function read_debug_ptr(address)
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

local function read_object_u32(object_address, offset)
  if object_address == nil or object_address == 0 then
    return nil
  end
  return read_debug_ptr(object_address + offset)
end

local function read_object_u8(object_address, offset)
  local value = read_object_u32(object_address, offset)
  if value == nil then
    return nil
  end
  return value % 0x100
end

local function read_debug_ptr_field(ptr_address, offset)
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

local function format_decimal_or_nil(value)
  local numeric = tonumber(value)
  if numeric == nil then
    return "nil"
  end
  return tostring(numeric)
end

local function format_source_render_fields(source_address)
  if source_address == nil or source_address == 0 then
    return "nil"
  end

  local variant_primary = read_object_u8(source_address, 0x9C)
  local variant_secondary = read_object_u8(source_address, 0x9D)
  local render_selection = read_object_u8(source_address, 0xA0)
  local weapon_type = read_object_u8(source_address, 0xA4)
  local variant_tertiary = read_object_u8(source_address, 0xA8)
  local source_kind = read_object_u32(source_address, 0x4C)
  local source_aux = read_object_u32(source_address, 0x50)

  return string.format(
    "kind=%s aux=%s variants=%s/%s sel=%s weapon=%s tertiary=%s",
    format_decimal_or_nil(source_kind),
    format_decimal_or_nil(source_aux),
    format_decimal_or_nil(variant_primary),
    format_decimal_or_nil(variant_secondary),
    format_decimal_or_nil(render_selection),
    format_decimal_or_nil(weapon_type),
    format_decimal_or_nil(variant_tertiary))
end

local function format_preview_actor_render_fields(actor_address)
  if actor_address == nil or actor_address == 0 then
    return "nil"
  end

  local source_kind = read_object_u32(actor_address, 0x174)
  local source_aux = read_object_u32(actor_address, 0x17C)
  local variant_primary = read_object_u8(actor_address, 0x23C)
  local variant_secondary = read_object_u8(actor_address, 0x23D)
  local weapon_type = read_object_u8(actor_address, 0x23E)
  local render_selection = read_object_u8(actor_address, 0x23F)
  local variant_tertiary = read_object_u8(actor_address, 0x240)
  local attachment_ptr = read_object_u32(actor_address, 0x264)

  return string.format(
    "kind=%s aux=%s variants=%s/%s sel=%s weapon=%s tertiary=%s attach=%s",
    format_decimal_or_nil(source_kind),
    format_decimal_or_nil(source_aux),
    format_decimal_or_nil(variant_primary),
    format_decimal_or_nil(variant_secondary),
    format_decimal_or_nil(render_selection),
    format_decimal_or_nil(weapon_type),
    format_decimal_or_nil(variant_tertiary),
    format_hex32(attachment_ptr))
end

local function format_create_owner_selection_state(owner_address)
  if owner_address == nil or owner_address == 0 then
    return "nil"
  end

  local selected_source = read_object_u32(owner_address, 0x48)
  local mode = read_object_u32(owner_address, 0x6C)
  local preview_driver = read_object_u32(owner_address, 0x70)
  local element_selected = read_object_u32(owner_address, 0x1A4)
  local element_hot = read_object_u32(owner_address, 0x1B4)
  local discipline_selected = read_object_u32(owner_address, 0x22C)
  local discipline_hot = read_object_u32(owner_address, 0x278)

  return string.format(
    "selected_source=%s mode=%s preview_driver=%s element=%s hover_element=%s discipline=%s hover_discipline=%s",
    format_hex32(selected_source),
    format_decimal_or_nil(mode),
    format_hex32(preview_driver),
    format_decimal_or_nil(element_selected),
    format_decimal_or_nil(element_hot),
    format_decimal_or_nil(discipline_selected),
    format_decimal_or_nil(discipline_hot))
end

local function run_visual_diff_probe()
  if visual_diff_probe.completed then
    return true
  end

  if type(sd.debug) ~= "table" or type(sd.debug.snapshot) ~= "function" or
      type(sd.debug.snapshot_ptr_field) ~= "function" or type(sd.debug.diff) ~= "function" then
    fail("sd.debug snapshot tools unavailable")
    return false
  end

  local player_state = get_player_state()
  local scene_state = get_scene_state()
  local bot_state = get_patrol_bot_snapshot()
  if type(bot_state) ~= "table" or not bot_state.available then
    return "waiting_bot_snapshot"
  end
  if tonumber(bot_state.actor_address) == nil or tonumber(bot_state.actor_address) == 0 then
    return "waiting_bot_actor"
  end
  local gameplay_address = 0
  if type(scene_state) == "table" then
    gameplay_address = parse_runtime_address(scene_state.id or scene_state.scene_id) or 0
  end
  if gameplay_address == 0 then
    return "waiting_gameplay_scene"
  end

  log_visual_state_summary(player_state, bot_state)

  local bot_actor = tonumber(bot_state.actor_address) or 0
  local bot_progression = tonumber(bot_state.progression_runtime_state_address) or 0
  local bot_equip = tonumber(bot_state.equip_runtime_state_address) or 0
  local bot_selection_state = resolve_wizard_selection_state(bot_state.render_selection_byte)
  local player_actor = 0
  local player_progression = 0
  local player_equip = 0
  local player_selection_state = nil
  if type(player_state) == "table" then
    player_actor = tonumber(player_state.render_subject_address or player_state.actor_address) or 0
    player_progression = tonumber(player_state.progression_address) or 0
    player_equip = tonumber(player_state.equip_runtime_state_address) or 0
    player_selection_state = resolve_wizard_selection_state(
      player_state.render_subject_selection_byte or player_state.render_selection_byte)
  end
  if player_actor == 0 then
    return "waiting_player_actor"
  end

  snapshot_block(
    "player_actor_render_window",
    player_actor + ACTOR_RENDER_STATE_WINDOW_OFFSET,
    ACTOR_RENDER_STATE_WINDOW_SIZE)
  snapshot_block("bot_actor_render_window", bot_actor + ACTOR_RENDER_STATE_WINDOW_OFFSET, ACTOR_RENDER_STATE_WINDOW_SIZE)
  sd.debug.diff("player_actor_render_window", "bot_actor_render_window")

  snapshot_block(
    "player_actor_descriptor",
    player_actor + ACTOR_DESCRIPTOR_BLOCK_OFFSET,
    ACTOR_DESCRIPTOR_BLOCK_SIZE)
  snapshot_block("bot_actor_descriptor", bot_actor + ACTOR_DESCRIPTOR_BLOCK_OFFSET, ACTOR_DESCRIPTOR_BLOCK_SIZE)
  sd.debug.diff("player_actor_descriptor", "bot_actor_descriptor")

  snapshot_block(
    "player_actor_variant_window",
    player_actor + ACTOR_RENDER_VARIANT_WINDOW_OFFSET,
    ACTOR_RENDER_VARIANT_WINDOW_SIZE)
  snapshot_block(
    "bot_actor_variant_window",
    bot_actor + ACTOR_RENDER_VARIANT_WINDOW_OFFSET,
    ACTOR_RENDER_VARIANT_WINDOW_SIZE)
  sd.debug.diff("player_actor_variant_window", "bot_actor_variant_window")

  snapshot_block(
    "player_actor_runtime_window",
    player_actor + ACTOR_RUNTIME_VISUAL_WINDOW_OFFSET,
    ACTOR_RUNTIME_VISUAL_WINDOW_SIZE)
  snapshot_block(
    "bot_actor_runtime_window",
    bot_actor + ACTOR_RUNTIME_VISUAL_WINDOW_OFFSET,
    ACTOR_RUNTIME_VISUAL_WINDOW_SIZE)
  sd.debug.diff("player_actor_runtime_window", "bot_actor_runtime_window")

  local player_source_profile =
    tonumber(player_state.render_subject_hub_visual_source_profile_address or player_state.hub_visual_source_profile_address) or 0
  local bot_source_profile = tonumber(bot_state.hub_visual_source_profile_address) or 0
  if player_source_profile ~= 0 then
    snapshot_block(
      "player_actor_source_render_fields",
      player_source_profile + SOURCE_RENDER_FIELDS_OFFSET,
      SOURCE_RENDER_FIELDS_SIZE)
  end
  if bot_source_profile ~= 0 then
    snapshot_block(
      "bot_actor_source_render_fields",
      bot_source_profile + SOURCE_RENDER_FIELDS_OFFSET,
      SOURCE_RENDER_FIELDS_SIZE)
    if player_source_profile ~= 0 then
      sd.debug.diff("player_actor_source_render_fields", "bot_actor_source_render_fields")
    end
  end

  if player_progression ~= 0 then
    snapshot_block("player_progression_head", player_progression, 0x120)
  end
  if bot_progression ~= 0 then
    snapshot_block("bot_progression_head", bot_progression, 0x120)
    if player_progression ~= 0 then
      sd.debug.diff("player_progression_head", "bot_progression_head")
    end
  end

  if player_selection_state ~= nil and player_progression ~= 0 then
    snapshot_ptr_block(
      "player_progression_selection_entry",
      player_progression + STANDALONE_WIZARD_PROGRESS_TABLE_PTR_OFFSET,
      player_selection_state * STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE,
      STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE)
  end

  if player_equip ~= 0 then
    snapshot_block("player_equip_runtime", player_equip, STANDALONE_WIZARD_EQUIP_SIZE)
  end
  if bot_selection_state ~= nil and bot_progression ~= 0 then
    snapshot_ptr_block(
      "bot_progression_selection_entry",
      bot_progression + STANDALONE_WIZARD_PROGRESS_TABLE_PTR_OFFSET,
      bot_selection_state * STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE,
      STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE)
    if player_selection_state ~= nil and player_progression ~= 0 then
      sd.debug.diff("player_progression_selection_entry", "bot_progression_selection_entry")
    end
  end

  if bot_equip ~= 0 then
    snapshot_block("bot_equip_runtime", bot_equip, STANDALONE_WIZARD_EQUIP_SIZE)
    if player_equip ~= 0 then
      sd.debug.diff("player_equip_runtime", "bot_equip_runtime")
    end
  end

  visual_diff_probe.completed = true
  log_status("captured player-vs-bot visual diff snapshots")
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
  log_status("visual diff probe waiting: " .. tostring(detail))
end

local function sanitize_snapshot_tag(value)
  return tostring(value):gsub("[^%w]+", "_")
end

local function find_surface_object_ptr(surface_id)
  local snapshot = get_snapshot()
  if type(snapshot) ~= "table" or type(snapshot.elements) ~= "table" then
    return nil
  end

  for _, element in ipairs(snapshot.elements) do
    if type(element) == "table" and (element.surface_id == surface_id or element.surface_root_id == surface_id) then
      local surface_object_ptr = tonumber(element.surface_object_ptr)
      if surface_object_ptr ~= nil and surface_object_ptr ~= 0 then
        return surface_object_ptr
      end
    end
  end

  return nil
end

local function get_action_dispatch_snapshot(request_id)
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

local function get_create_probe_capture_phase(action, capture_index)
  if type(action) ~= "table" then
    return nil
  end
  local capture_phases = action.capture_phases
  if type(capture_phases) ~= "table" then
    return nil
  end
  return capture_phases[capture_index]
end

local function capture_create_probe_snapshot(tag, dispatch_snapshot)
  if type(sd.debug) ~= "table" then
    fail("sd.debug unavailable")
    return false
  end

  local prefix = "create_probe_" .. sanitize_snapshot_tag(tag)
  local player_state = get_player_state()
  local scene_name = get_scene_name()
  local create_surface_object = find_surface_object_ptr("create")
  local create_controller_slot_value = read_debug_ptr(CREATE_CONTROLLER_GLOBAL) or 0
  local create_global_slot_value = read_debug_ptr(CREATE_OBJECT_GLOBAL) or 0
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
  local create_selected_source = 0
  local create_selected_source_render_ptr = 0
  local create_context_preview_object = 0
  local create_child_render_window = 0
  local create_child_descriptor = 0
  local create_child_runtime_window = 0
  local create_child_source = 0
  local create_child_source_render_ptr = 0
  local diff_available = type(sd.debug.diff) == "function"

  if type(player_state) == "table" then
    actor_address = tonumber(player_state.render_subject_address or player_state.actor_address) or 0
    progression_address = tonumber(player_state.progression_address) or 0
    render_selection = player_state.render_subject_selection_byte or player_state.render_selection_byte
    animation_state = player_state.resolved_animation_state_id
    render_frame_table = player_state.render_subject_frame_table or player_state.render_frame_table
    attachment_ptr = player_state.render_subject_hub_visual_attachment_ptr or player_state.hub_visual_attachment_ptr
    source_profile =
      player_state.render_subject_hub_visual_source_profile_address or player_state.hub_visual_source_profile_address
    descriptor_signature = tonumber(player_state.render_subject_hub_visual_descriptor_signature or player_state.hub_visual_descriptor_signature) or 0
    render_variant_primary =
      player_state.render_subject_variant_primary or player_state.render_variant_primary
    render_variant_secondary =
      player_state.render_subject_variant_secondary or player_state.render_variant_secondary
    render_weapon_type =
      player_state.render_subject_weapon_type or player_state.render_weapon_type
    render_variant_tertiary =
      player_state.render_subject_variant_tertiary or player_state.render_variant_tertiary
  end

  if type(dispatch_snapshot) == "table" then
    dispatch_owner = tonumber(dispatch_snapshot.owner_address) or 0
    dispatch_control = tonumber(dispatch_snapshot.control_address) or 0
    dispatch_kind = dispatch_snapshot.dispatch_kind
  end

  local resolved_owner_source = read_object_u32(dispatch_owner, CREATE_PROBE_OWNER_SOURCE_PTR_OFFSET) or 0
  local resolved_owner_source_render_ptr = 0
  local resolved_child_preview = read_object_u32(dispatch_owner, CREATE_PROBE_CHILD_PREVIEW_OFFSET) or 0
  local resolved_child_render_window =
    resolved_child_preview ~= 0 and
    (resolved_child_preview + ACTOR_RENDER_STATE_WINDOW_OFFSET) or
    0
  local resolved_child_descriptor =
    resolved_child_preview ~= 0 and
    (resolved_child_preview + ACTOR_DESCRIPTOR_BLOCK_OFFSET) or
    0
  local resolved_child_runtime_window =
    resolved_child_preview ~= 0 and
    (resolved_child_preview + ACTOR_RUNTIME_VISUAL_WINDOW_OFFSET) or
    0
  local resolved_child_source = read_object_u32(resolved_child_preview, CREATE_PROBE_CHILD_SOURCE_PTR_OFFSET) or 0
  local resolved_child_source_render_ptr = 0
  create_selected_source = resolved_owner_source
  create_context_preview_object = resolved_child_preview
  create_child_render_window = resolved_child_render_window
  create_child_descriptor = resolved_child_descriptor
  create_child_runtime_window = resolved_child_runtime_window
  create_child_source = resolved_child_source

  local resolved_selection_captured = false
  local resolved_preview_captured = false
  local resolved_phase_captured = false
  local resolved_wizard_captured = false
  local resolved_owner_head_captured = false
  local resolved_owner_source_ptr_captured = false
  local resolved_owner_source_captured = false
  local resolved_owner_source_render_captured = false
  local resolved_child_actor_head_captured = false
  local resolved_child_preview_captured = false
  local resolved_child_render_captured = false
  local resolved_child_descriptor_captured = false
  local resolved_child_runtime_captured = false
  local resolved_child_source_ptr_captured = false
  local resolved_child_source_captured = false
  local resolved_child_source_render_captured = false
  local resolved_owner_source_direct_captured = false
  local resolved_owner_source_render_direct_captured = false
  local resolved_owner_source_render_ptr_captured = false
  local resolved_child_render_direct_captured = false
  local resolved_child_descriptor_direct_captured = false
  local resolved_child_runtime_direct_captured = false
  local resolved_child_source_direct_captured = false
  local resolved_child_source_render_direct_captured = false
  local resolved_child_source_render_ptr_captured = false
  if dispatch_owner ~= 0 then
    resolved_owner_head_captured =
      snapshot_block(
        prefix .. "_resolved_owner_head",
        dispatch_owner,
        CREATE_PROBE_OWNER_HEAD_SIZE)
    resolved_owner_source_ptr_captured =
      snapshot_block(
        prefix .. "_resolved_owner_source_ptr_window",
        dispatch_owner + CREATE_PROBE_OWNER_SOURCE_PTR_OFFSET,
        CREATE_PROBE_CHILD_SOURCE_PTR_WINDOW_SIZE)
    resolved_owner_source_captured =
      resolved_owner_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_owner_source_window",
        resolved_owner_source,
        CREATE_PROBE_OWNER_SOURCE_WINDOW_SIZE) or
      false
    resolved_owner_source_render_captured =
      resolved_owner_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_owner_source_render_fields",
        resolved_owner_source + SOURCE_RENDER_FIELDS_OFFSET,
        SOURCE_RENDER_FIELDS_SIZE) or
      false
    resolved_selection_captured =
      snapshot_block(
        prefix .. "_resolved_selection_window",
        dispatch_owner + CREATE_PROBE_SELECTION_WINDOW_OFFSET,
        CREATE_PROBE_SELECTION_WINDOW_SIZE)
    resolved_preview_captured =
      snapshot_block(
        prefix .. "_resolved_preview_window",
        dispatch_owner + CREATE_PROBE_PREVIEW_WINDOW_OFFSET,
        CREATE_PROBE_PREVIEW_WINDOW_SIZE)
    resolved_phase_captured =
      snapshot_block(
        prefix .. "_resolved_phase_window",
        dispatch_owner + CREATE_PROBE_PHASE_WINDOW_OFFSET,
        CREATE_PROBE_PHASE_WINDOW_SIZE)
    resolved_wizard_captured =
      snapshot_block(
        prefix .. "_resolved_wizard_window",
        dispatch_owner + CREATE_PROBE_WIZARD_WINDOW_OFFSET,
        CREATE_PROBE_WIZARD_WINDOW_SIZE)
    resolved_child_preview_captured =
      resolved_child_preview ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_preview",
        resolved_child_preview,
        CREATE_PROBE_CHILD_PREVIEW_SIZE) or
      false
    resolved_child_actor_head_captured =
      resolved_child_preview ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_actor_head",
        resolved_child_preview,
        CREATE_PROBE_CHILD_ACTOR_HEAD_SIZE) or
      false
    resolved_child_render_captured =
      resolved_child_preview ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_render_window",
        resolved_child_preview + ACTOR_RENDER_STATE_WINDOW_OFFSET,
        ACTOR_RENDER_STATE_WINDOW_SIZE) or
      false
    resolved_child_descriptor_captured =
      resolved_child_preview ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_descriptor",
        resolved_child_preview + ACTOR_DESCRIPTOR_BLOCK_OFFSET,
        ACTOR_DESCRIPTOR_BLOCK_SIZE) or
      false
    resolved_child_runtime_captured =
      resolved_child_preview ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_runtime_window",
        resolved_child_preview + ACTOR_RUNTIME_VISUAL_WINDOW_OFFSET,
        ACTOR_RUNTIME_VISUAL_WINDOW_SIZE) or
      false
    resolved_child_source_ptr_captured =
      resolved_child_preview ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_source_ptr_window",
        resolved_child_preview + CREATE_PROBE_CHILD_SOURCE_PTR_OFFSET,
        CREATE_PROBE_CHILD_SOURCE_PTR_WINDOW_SIZE) or
      false
    resolved_child_source_captured =
      resolved_child_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_source_window",
        resolved_child_source,
        CREATE_PROBE_CHILD_SOURCE_WINDOW_SIZE) or
      false
    resolved_child_source_render_captured =
      resolved_child_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_source_render_fields",
        resolved_child_source + SOURCE_RENDER_FIELDS_OFFSET,
        SOURCE_RENDER_FIELDS_SIZE) or
      false
    resolved_owner_source_direct_captured =
      resolved_owner_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_owner_source_window_direct",
        resolved_owner_source,
        CREATE_PROBE_OWNER_SOURCE_WINDOW_SIZE) or
      false
    resolved_owner_source_render_direct_captured =
      resolved_owner_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_owner_source_render_fields_direct",
        resolved_owner_source + SOURCE_RENDER_FIELDS_OFFSET,
        SOURCE_RENDER_FIELDS_SIZE) or
      false
    resolved_owner_source_render_ptr_captured =
      resolved_owner_source_render_ptr ~= 0 and
      snapshot_block(
        prefix .. "_resolved_owner_source_render_fields_ptr",
        resolved_owner_source_render_ptr,
        SOURCE_RENDER_FIELDS_SIZE) or
      false
    resolved_child_render_direct_captured =
      resolved_child_render_window ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_render_window_direct",
        resolved_child_render_window,
        ACTOR_RENDER_STATE_WINDOW_SIZE) or
      false
    resolved_child_descriptor_direct_captured =
      resolved_child_descriptor ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_descriptor_direct",
        resolved_child_descriptor,
        ACTOR_DESCRIPTOR_BLOCK_SIZE) or
      false
    resolved_child_runtime_direct_captured =
      resolved_child_runtime_window ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_runtime_window_direct",
        resolved_child_runtime_window,
        ACTOR_RUNTIME_VISUAL_WINDOW_SIZE) or
      false
    resolved_child_source_direct_captured =
      resolved_child_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_source_window_direct",
        resolved_child_source,
        CREATE_PROBE_CHILD_SOURCE_WINDOW_SIZE) or
      false
    resolved_child_source_render_direct_captured =
      resolved_child_source ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_source_render_fields_direct",
        resolved_child_source + SOURCE_RENDER_FIELDS_OFFSET,
        SOURCE_RENDER_FIELDS_SIZE) or
      false
    resolved_child_source_render_ptr_captured =
      resolved_child_source_render_ptr ~= 0 and
      snapshot_block(
        prefix .. "_resolved_child_source_render_fields_ptr",
        resolved_child_source_render_ptr,
        SOURCE_RENDER_FIELDS_SIZE) or
      false
  end

  local create_context_head_captured =
    dispatch_owner ~= 0 and
    snapshot_block(
      prefix .. "_create_context_head",
      dispatch_owner,
      CREATE_PROBE_OWNER_HEAD_SIZE) or
    false
  local create_child_actor_head_captured =
    create_context_preview_object ~= 0 and
    snapshot_block(
      prefix .. "_create_child_actor_head",
      create_context_preview_object,
      CREATE_PROBE_CHILD_ACTOR_HEAD_SIZE) or
    false
  local create_selected_source_ptr_captured =
    dispatch_owner ~= 0 and
    snapshot_block(
      prefix .. "_create_selected_source_ptr_window",
      dispatch_owner + CREATE_PROBE_SELECTED_SOURCE_PTR_OFFSET,
      CREATE_PROBE_SELECTED_SOURCE_PTR_WINDOW_SIZE) or
    false
  local create_selected_source_captured =
    create_selected_source ~= 0 and
    snapshot_block(
      prefix .. "_create_selected_source_window",
      create_selected_source,
      CREATE_PROBE_SELECTED_SOURCE_WINDOW_SIZE) or
    false
  local create_selected_source_render_direct_captured =
    create_selected_source ~= 0 and
    snapshot_block(
      prefix .. "_create_selected_source_render_fields_direct",
      create_selected_source + SOURCE_RENDER_FIELDS_OFFSET,
      SOURCE_RENDER_FIELDS_SIZE) or
    false
  local create_selected_source_render_captured =
    create_selected_source_render_ptr ~= 0 and
    snapshot_block(
      prefix .. "_create_selected_source_render_fields_ptr",
      create_selected_source_render_ptr,
      SOURCE_RENDER_FIELDS_SIZE) or
    false
  local create_child_preview_captured =
    create_context_preview_object ~= 0 and
    snapshot_block(
      prefix .. "_create_child_preview",
      create_context_preview_object,
      CREATE_PROBE_CHILD_PREVIEW_SIZE) or
    false
  local create_child_render_captured =
    create_child_render_window ~= 0 and
    snapshot_block(
      prefix .. "_create_child_render_window",
      create_child_render_window,
      ACTOR_RENDER_STATE_WINDOW_SIZE) or
    false
  local create_child_descriptor_captured =
    create_child_descriptor ~= 0 and
    snapshot_block(
      prefix .. "_create_child_descriptor",
      create_child_descriptor,
      ACTOR_DESCRIPTOR_BLOCK_SIZE) or
    false
  local create_child_runtime_captured =
    create_child_runtime_window ~= 0 and
    snapshot_block(
      prefix .. "_create_child_runtime_window",
      create_child_runtime_window,
      ACTOR_RUNTIME_VISUAL_WINDOW_SIZE) or
    false
  local create_child_source_ptr_captured =
    create_context_preview_object ~= 0 and
    snapshot_block(
      prefix .. "_create_child_source_ptr_window",
      create_context_preview_object + CREATE_PROBE_CHILD_SOURCE_PTR_OFFSET,
      CREATE_PROBE_CHILD_SOURCE_PTR_WINDOW_SIZE) or
    false
  local create_child_source_captured =
    create_child_source ~= 0 and
    snapshot_block(
      prefix .. "_create_child_source_window",
      create_child_source,
      CREATE_PROBE_CHILD_SOURCE_WINDOW_SIZE) or
    false
  local create_child_source_render_direct_captured =
    create_child_source ~= 0 and
    snapshot_block(
      prefix .. "_create_child_source_render_fields_direct",
      create_child_source + SOURCE_RENDER_FIELDS_OFFSET,
      SOURCE_RENDER_FIELDS_SIZE) or
    false
  local create_child_source_render_captured =
    create_child_source_render_ptr ~= 0 and
    snapshot_block(
      prefix .. "_create_child_source_render_fields_ptr",
      create_child_source_render_ptr,
      SOURCE_RENDER_FIELDS_SIZE) or
    false

  if not create_context_head_captured and not create_child_actor_head_captured and
      not create_selected_source_ptr_captured and
      not create_selected_source_captured and not create_selected_source_render_direct_captured and
      not create_selected_source_render_captured and
      not create_child_preview_captured and
      not create_child_render_captured and not create_child_descriptor_captured and
      not create_child_runtime_captured and not create_child_source_ptr_captured and
      not create_child_source_captured and not create_child_source_render_direct_captured and
      not create_child_source_render_captured and
      not resolved_selection_captured and not resolved_preview_captured and
      not resolved_phase_captured and not resolved_wizard_captured and
      not resolved_child_actor_head_captured and not resolved_child_preview_captured and
      not resolved_child_render_captured and
      not resolved_child_descriptor_captured and not resolved_child_runtime_captured and
      not resolved_child_source_ptr_captured and not resolved_child_source_captured and
      not resolved_child_source_render_captured and
      not resolved_owner_source_direct_captured and not resolved_owner_source_render_direct_captured and
      not resolved_owner_source_render_ptr_captured and
      not resolved_child_render_direct_captured and not resolved_child_descriptor_direct_captured and
      not resolved_child_runtime_direct_captured and not resolved_child_source_direct_captured and
      not resolved_child_source_render_direct_captured and
      not resolved_child_source_render_ptr_captured and
      actor_address == 0 and progression_address == 0 and
      scene_name == "transition" then
    return false
  end

  local actor_render_captured =
    actor_address ~= 0 and
    snapshot_block(prefix .. "_actor_render_window", actor_address + ACTOR_RENDER_STATE_WINDOW_OFFSET, ACTOR_RENDER_STATE_WINDOW_SIZE) or
    false
  local actor_variant_captured =
    actor_address ~= 0 and
    snapshot_block(prefix .. "_actor_variant_window", actor_address + ACTOR_RENDER_VARIANT_WINDOW_OFFSET, ACTOR_RENDER_VARIANT_WINDOW_SIZE) or
    false
  local actor_descriptor_captured =
    actor_address ~= 0 and
    snapshot_block(prefix .. "_actor_descriptor", actor_address + ACTOR_DESCRIPTOR_BLOCK_OFFSET, ACTOR_DESCRIPTOR_BLOCK_SIZE) or
    false
  local actor_runtime_captured =
    actor_address ~= 0 and
    snapshot_block(prefix .. "_actor_runtime_window", actor_address + ACTOR_RUNTIME_VISUAL_WINDOW_OFFSET, ACTOR_RUNTIME_VISUAL_WINDOW_SIZE) or
    false
  local actor_source_render_captured =
    source_profile ~= nil and source_profile ~= 0 and
    snapshot_block(prefix .. "_actor_source_render_fields", source_profile + SOURCE_RENDER_FIELDS_OFFSET, SOURCE_RENDER_FIELDS_SIZE) or
    false
  local progression_head_captured =
    progression_address ~= 0 and
    snapshot_block(prefix .. "_progression_head", progression_address, CREATE_PROBE_PROGRESS_HEAD_SIZE) or
    false

  local selection_state = resolve_wizard_selection_state(render_selection)
  local selection_entry_captured = false
  if progression_address ~= 0 and selection_state ~= nil then
    selection_entry_captured = snapshot_ptr_block(
      prefix .. "_progression_selection_entry",
      progression_address + STANDALONE_WIZARD_PROGRESS_TABLE_PTR_OFFSET,
      selection_state * STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE,
      STANDALONE_WIZARD_PROGRESS_ENTRY_STRIDE)
  end

  log_status(string.format(
    "create probe tag=%s scene=%s actor=%s render=%s anim=%s frame=%s attach=%s source=%s variants=%s/%s/%s/%s prog=%s create_surface=%s create_controller_slot=%s create_global_slot=%s dispatch_owner=%s dispatch_control=%s dispatch_kind=%s desc=0x%08X",
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
    format_hex32(create_controller_slot_value),
    format_hex32(create_global_slot_value),
    tostring(dispatch_owner),
    tostring(dispatch_control),
    tostring(dispatch_kind),
    descriptor_signature))
  log_status(string.format(
    "create probe owner tag=%s owner=%s state={%s} owner_source=%s owner_fields={%s} preview=%s preview_fields={%s} preview_source=%s preview_source_fields={%s} player_fields={%s} player_source_fields={%s}",
    tostring(tag),
    format_hex32(dispatch_owner),
    format_create_owner_selection_state(dispatch_owner),
    format_hex32(resolved_owner_source),
    format_source_render_fields(resolved_owner_source),
    format_hex32(resolved_child_preview),
    format_preview_actor_render_fields(resolved_child_preview),
    format_hex32(resolved_child_source),
    format_source_render_fields(resolved_child_source),
    format_preview_actor_render_fields(actor_address),
    format_source_render_fields(source_profile)))

  local previous_prefix = create_probe.last_snapshot_prefix
  if diff_available and previous_prefix ~= nil then
    if resolved_selection_captured then
      sd.debug.diff(previous_prefix .. "_resolved_selection_window", prefix .. "_resolved_selection_window")
    end
    if resolved_owner_head_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_head", prefix .. "_resolved_owner_head")
    end
    if resolved_owner_source_ptr_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_source_ptr_window", prefix .. "_resolved_owner_source_ptr_window")
    end
    if resolved_owner_source_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_source_window", prefix .. "_resolved_owner_source_window")
    end
    if resolved_owner_source_render_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_source_render_fields", prefix .. "_resolved_owner_source_render_fields")
    end
    if resolved_owner_source_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_source_window_direct", prefix .. "_resolved_owner_source_window_direct")
    end
    if resolved_owner_source_render_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_source_render_fields_direct", prefix .. "_resolved_owner_source_render_fields_direct")
    end
    if resolved_owner_source_render_ptr_captured then
      sd.debug.diff(previous_prefix .. "_resolved_owner_source_render_fields_ptr", prefix .. "_resolved_owner_source_render_fields_ptr")
    end
    if resolved_preview_captured then
      sd.debug.diff(previous_prefix .. "_resolved_preview_window", prefix .. "_resolved_preview_window")
    end
    if resolved_phase_captured then
      sd.debug.diff(previous_prefix .. "_resolved_phase_window", prefix .. "_resolved_phase_window")
    end
    if resolved_wizard_captured then
      sd.debug.diff(previous_prefix .. "_resolved_wizard_window", prefix .. "_resolved_wizard_window")
    end
    if resolved_child_actor_head_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_actor_head", prefix .. "_resolved_child_actor_head")
    end
    if resolved_child_preview_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_preview", prefix .. "_resolved_child_preview")
    end
    if resolved_child_render_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_render_window", prefix .. "_resolved_child_render_window")
    end
    if resolved_child_descriptor_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_descriptor", prefix .. "_resolved_child_descriptor")
    end
    if resolved_child_runtime_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_runtime_window", prefix .. "_resolved_child_runtime_window")
    end
    if resolved_child_source_ptr_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_source_ptr_window", prefix .. "_resolved_child_source_ptr_window")
    end
    if resolved_child_source_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_source_window", prefix .. "_resolved_child_source_window")
    end
    if resolved_child_source_render_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_source_render_fields", prefix .. "_resolved_child_source_render_fields")
    end
    if resolved_child_render_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_render_window_direct", prefix .. "_resolved_child_render_window_direct")
    end
    if resolved_child_descriptor_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_descriptor_direct", prefix .. "_resolved_child_descriptor_direct")
    end
    if resolved_child_runtime_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_runtime_window_direct", prefix .. "_resolved_child_runtime_window_direct")
    end
    if resolved_child_source_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_source_window_direct", prefix .. "_resolved_child_source_window_direct")
    end
    if resolved_child_source_render_direct_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_source_render_fields_direct", prefix .. "_resolved_child_source_render_fields_direct")
    end
    if resolved_child_source_render_ptr_captured then
      sd.debug.diff(previous_prefix .. "_resolved_child_source_render_fields_ptr", prefix .. "_resolved_child_source_render_fields_ptr")
    end
    if create_context_head_captured then
      sd.debug.diff(previous_prefix .. "_create_context_head", prefix .. "_create_context_head")
    end
    if create_child_actor_head_captured then
      sd.debug.diff(previous_prefix .. "_create_child_actor_head", prefix .. "_create_child_actor_head")
    end
    if create_selected_source_ptr_captured then
      sd.debug.diff(previous_prefix .. "_create_selected_source_ptr_window", prefix .. "_create_selected_source_ptr_window")
    end
    if create_selected_source_captured then
      sd.debug.diff(previous_prefix .. "_create_selected_source_window", prefix .. "_create_selected_source_window")
    end
    if create_selected_source_render_direct_captured then
      sd.debug.diff(previous_prefix .. "_create_selected_source_render_fields_direct", prefix .. "_create_selected_source_render_fields_direct")
    end
    if create_selected_source_render_captured then
      sd.debug.diff(previous_prefix .. "_create_selected_source_render_fields_ptr", prefix .. "_create_selected_source_render_fields_ptr")
    end
    if create_child_preview_captured then
      sd.debug.diff(previous_prefix .. "_create_child_preview", prefix .. "_create_child_preview")
    end
    if create_child_render_captured then
      sd.debug.diff(previous_prefix .. "_create_child_render_window", prefix .. "_create_child_render_window")
    end
    if create_child_descriptor_captured then
      sd.debug.diff(previous_prefix .. "_create_child_descriptor", prefix .. "_create_child_descriptor")
    end
    if create_child_runtime_captured then
      sd.debug.diff(previous_prefix .. "_create_child_runtime_window", prefix .. "_create_child_runtime_window")
    end
    if create_child_source_ptr_captured then
      sd.debug.diff(previous_prefix .. "_create_child_source_ptr_window", prefix .. "_create_child_source_ptr_window")
    end
    if create_child_source_captured then
      sd.debug.diff(previous_prefix .. "_create_child_source_window", prefix .. "_create_child_source_window")
    end
    if create_child_source_render_direct_captured then
      sd.debug.diff(previous_prefix .. "_create_child_source_render_fields_direct", prefix .. "_create_child_source_render_fields_direct")
    end
    if create_child_source_render_captured then
      sd.debug.diff(previous_prefix .. "_create_child_source_render_fields_ptr", prefix .. "_create_child_source_render_fields_ptr")
    end
    if actor_render_captured then
      sd.debug.diff(previous_prefix .. "_actor_render_window", prefix .. "_actor_render_window")
    end
    if actor_variant_captured then
      sd.debug.diff(previous_prefix .. "_actor_variant_window", prefix .. "_actor_variant_window")
    end
    if actor_descriptor_captured then
      sd.debug.diff(previous_prefix .. "_actor_descriptor", prefix .. "_actor_descriptor")
    end
    if actor_runtime_captured then
      sd.debug.diff(previous_prefix .. "_actor_runtime_window", prefix .. "_actor_runtime_window")
    end
    if actor_source_render_captured then
      sd.debug.diff(previous_prefix .. "_actor_source_render_fields", prefix .. "_actor_source_render_fields")
    end
    if progression_head_captured then
      sd.debug.diff(previous_prefix .. "_progression_head", prefix .. "_progression_head")
    end
    if selection_entry_captured then
      sd.debug.diff(previous_prefix .. "_progression_selection_entry", prefix .. "_progression_selection_entry")
    end
  end

  create_probe.last_snapshot_prefix = prefix
  create_probe.last_dispatch_owner = dispatch_owner
  create_probe.last_dispatch_control = dispatch_control
  local logged_any_state =
    actor_address ~= 0 or progression_address ~= 0 or dispatch_owner ~= 0 or
    resolved_owner_source ~= 0 or resolved_child_preview ~= 0 or
    create_controller_slot_value ~= 0 or create_global_slot_value ~= 0
  return resolved_selection_captured or resolved_owner_head_captured or
    resolved_owner_source_ptr_captured or resolved_owner_source_captured or
    resolved_owner_source_render_captured or resolved_owner_source_direct_captured or
    resolved_owner_source_render_direct_captured or resolved_owner_source_render_ptr_captured or
    resolved_preview_captured or resolved_phase_captured or
    resolved_wizard_captured or resolved_child_actor_head_captured or
    resolved_child_preview_captured or resolved_child_render_captured or
    resolved_child_descriptor_captured or resolved_child_runtime_captured or
    resolved_child_source_ptr_captured or resolved_child_source_captured or
    resolved_child_source_render_captured or resolved_child_render_direct_captured or
    resolved_child_descriptor_direct_captured or resolved_child_runtime_direct_captured or
    resolved_child_source_direct_captured or resolved_child_source_render_direct_captured or
    resolved_child_source_render_ptr_captured or create_context_head_captured or
    create_child_actor_head_captured or
    create_selected_source_ptr_captured or create_selected_source_captured or
    create_selected_source_render_direct_captured or create_selected_source_render_captured or
    create_child_preview_captured or create_child_render_captured or create_child_descriptor_captured or
    create_child_runtime_captured or create_child_source_ptr_captured or
    create_child_source_captured or create_child_source_render_direct_captured or
    create_child_source_render_captured or actor_render_captured or actor_variant_captured or actor_descriptor_captured or
    actor_runtime_captured or actor_source_render_captured or progression_head_captured or
    logged_any_state
end

local function arm_create_probe_debug_tools()
  if create_probe.debug_armed or type(sd.debug) ~= "table" then
    return
  end

  if type(sd.debug.trace_function) == "function" then
    pcall(sd.debug.trace_function, TRACE_CREATE_EVENT_HANDLER, "create.event_handler")
    pcall(sd.debug.trace_function, TRACE_PLAYER_REFRESH_RUNTIME, "player.refresh_runtime_handles")
    pcall(sd.debug.trace_function, TRACE_ACTOR_PROGRESSION_REFRESH, "actor.progression_refresh")
    pcall(sd.debug.trace_function, TRACE_WIZARD_SOURCE_LOOKUP, "create.wizard_source_lookup")
    pcall(sd.debug.trace_function, TRACE_WIZARD_PREVIEW_FACTORY, "create.wizard_preview_factory")
  end

  if type(sd.debug.watch) == "function" then
    pcall(sd.debug.watch, CREATE_CONTROLLER_GLOBAL, 0x20, "create.controller_slot_window")
    pcall(sd.debug.watch, CREATE_OBJECT_GLOBAL, 0x20, "create.object_slot_window")
  end

  if type(sd.debug.watch_ptr_field) == "function" then
    pcall(sd.debug.watch_ptr_field, LOCAL_PLAYER_ACTOR_GLOBAL, ACTOR_SOURCE_PROFILE_PTR_OFFSET, 4, "player.create_source_profile_ptr")
    pcall(sd.debug.watch_ptr_field, LOCAL_PLAYER_ACTOR_GLOBAL, 0x174, 4, "player.create_source_kind")
    pcall(sd.debug.watch_ptr_field, LOCAL_PLAYER_ACTOR_GLOBAL, 0x17C, 4, "player.create_source_aux")
    pcall(sd.debug.watch_ptr_field, LOCAL_PLAYER_ACTOR_GLOBAL, ACTOR_RENDER_VARIANT_WINDOW_OFFSET, ACTOR_RENDER_VARIANT_WINDOW_SIZE, "player.create_variant_window")
    pcall(sd.debug.watch_ptr_field, LOCAL_PLAYER_ACTOR_GLOBAL, ACTOR_DESCRIPTOR_BLOCK_OFFSET, ACTOR_DESCRIPTOR_BLOCK_SIZE, "player.create_descriptor")
    pcall(sd.debug.watch_ptr_field, LOCAL_PLAYER_ACTOR_GLOBAL, 0x264, 4, "player.create_attachment_ptr")
  end

  create_probe.debug_armed = true
  log_status("create probe armed create-surface traces and watches")
end

local function run_create_probe(now_ms)
  if MODE ~= "create_probe" or failed or not setup_complete or create_probe.completed then
    return
  end

  arm_create_probe_debug_tools()

  if not create_probe.started then
    local create_surface_object = find_surface_object_ptr("create")
    local create_controller_slot = read_debug_ptr(CREATE_CONTROLLER_GLOBAL) or 0
    local create_global_slot = read_debug_ptr(CREATE_OBJECT_GLOBAL) or 0
    local snapshot = get_snapshot()
    local active_surface = type(snapshot) == "table" and snapshot.surface_id or nil
    if create_probe.baseline_wait_started_ms == 0 then
      create_probe.baseline_wait_started_ms = now_ms
    end
    if capture_create_probe_snapshot("baseline") then
      create_probe.started = true
      log_status("create probe baseline captured")
    elseif now_ms - create_probe.baseline_wait_started_ms >= 2000 then
      create_probe.started = true
      log_status("create probe starting without baseline snapshot")
    elseif create_probe.last_wait_log_ms == 0 or now_ms - create_probe.last_wait_log_ms >= 1000 then
      create_probe.last_wait_log_ms = now_ms
      log_status(string.format(
        "create probe waiting for create surface state scene=%s active_surface=%s create_surface=%s create_controller=%s create_global=%s",
        tostring(get_scene_name()),
        tostring(active_surface),
        tostring(create_surface_object),
        format_hex32(create_controller_slot),
        format_hex32(create_global_slot)))
    end
    return
  end

  local action = CREATE_PROBE_ACTION_SEQUENCE[create_probe.action_index]
  if action == nil then
    create_probe.completed = true
    log_status("create probe completed")
    return
  end

  if create_probe.active_action == nil then
    if type(sd.ui) ~= "table" or type(sd.ui.activate_action) ~= "function" then
      fail("sd.ui.activate_action unavailable")
      return
    end

    local ok, request_id_or_error = sd.ui.activate_action(action.action_id, "create")
    if not ok then
      fail(tostring(request_id_or_error or ("create probe activation failed for " .. tostring(action.action_id))))
      return
    end

    create_probe.active_action = action
    create_probe.active_request_id = tonumber(request_id_or_error) or 0
    create_probe.activated_at_ms = now_ms
    create_probe.active_capture_index = 1
    log_status("create probe activated " .. tostring(action.action_id) .. " request_id=" .. tostring(request_id_or_error))
    return
  end

  local dispatch_snapshot = get_action_dispatch_snapshot(create_probe.active_request_id)
  local dispatch_owner = type(dispatch_snapshot) == "table" and (tonumber(dispatch_snapshot.owner_address) or 0) or 0
  local dispatch_control = type(dispatch_snapshot) == "table" and (tonumber(dispatch_snapshot.control_address) or 0) or 0
  local dispatch_status = type(dispatch_snapshot) == "table" and tostring(dispatch_snapshot.status) or nil
  if type(dispatch_snapshot) == "table" and dispatch_owner ~= 0 and
      (dispatch_owner ~= create_probe.last_dispatch_owner or
       dispatch_control ~= create_probe.last_dispatch_control or
       dispatch_status ~= create_probe.last_dispatch_status) then
    log_status(string.format(
      "create probe dispatch request=%s status=%s owner=%s control=%s kind=%s",
      tostring(create_probe.active_request_id),
      tostring(dispatch_snapshot.status),
      tostring(dispatch_snapshot.owner_address),
      tostring(dispatch_snapshot.control_address),
      tostring(dispatch_snapshot.dispatch_kind)))
    create_probe.last_dispatch_owner = dispatch_owner
    create_probe.last_dispatch_control = dispatch_control
    create_probe.last_dispatch_status = dispatch_status
  end

  local capture_phase = get_create_probe_capture_phase(create_probe.active_action, create_probe.active_capture_index)
  if capture_phase == nil then
    create_probe.action_index = create_probe.action_index + 1
    create_probe.active_action = nil
    create_probe.active_request_id = 0
    create_probe.active_capture_index = 0
    create_probe.last_dispatch_status = nil
    return
  end

  local capture_delay_ms = tonumber(capture_phase.delay_ms) or CREATE_PROBE_WAIT_MS
  if now_ms - create_probe.activated_at_ms < capture_delay_ms then
    return
  end

  local tag = string.format(
    "%02d_%s_%s",
    create_probe.action_index,
    create_probe.active_action.tag,
    tostring(capture_phase.label or create_probe.active_capture_index))
  if not capture_create_probe_snapshot(tag, dispatch_snapshot) then
    log_status("create probe snapshot empty for " .. tostring(create_probe.active_action.action_id))
  end

  create_probe.active_capture_index = create_probe.active_capture_index + 1
  if get_create_probe_capture_phase(create_probe.active_action, create_probe.active_capture_index) == nil then
    create_probe.action_index = create_probe.action_index + 1
    create_probe.active_action = nil
    create_probe.active_request_id = 0
    create_probe.active_capture_index = 0
    create_probe.last_dispatch_status = nil
  end
end

local function get_player_position()
  local player_state = get_player_state()
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
  if patrol == nil then
    return false
  end

  local min_x = math.min(patrol.a.x, patrol.b.x) - INPUT_TEST_PATROL_BAND_SLOP
  local max_x = math.max(patrol.a.x, patrol.b.x) + INPUT_TEST_PATROL_BAND_SLOP
  local center_y = patrol.a.y
  return bot_x >= min_x and bot_x <= max_x and math.abs(bot_y - center_y) <= INPUT_TEST_PATROL_BAND_SLOP
end

local function issue_player_input_probe(now_ms, bot_x, bot_y)
  if player_input_test == nil or player_input_test.completed then
    return
  end
  if player_input_test.mode == "external_wait" then
    return
  end
  if type(sd.input) ~= "table" or type(sd.input.click_normalized) ~= "function" then
    fail("sd.input.click_normalized unavailable")
    return
  end

  local point = INPUT_TEST_CLICK_POINTS[player_input_test.attempted_clicks + 1]
  if type(point) ~= "table" then
    player_input_test.mode = "external_wait"
    player_input_test.issued = false
    player_input_test.issued_at_ms = now_ms
    if not player_input_test.external_notice_logged then
      player_input_test.external_notice_logged = true
      log_status("internal click probe exhausted its points; waiting for external input verification")
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

  log_status(string.format(
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
    fail("player input probe failed to issue a gameplay click")
  end
end

local function update_player_input_probe(now_ms, bot_x, bot_y)
  if player_input_test == nil or player_input_test.completed or not patrol_loop_confirmed then
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
    if player_delta >= INPUT_TEST_PLAYER_MOVE_THRESHOLD then
      local within_patrol = is_bot_within_patrol_band(bot_x, bot_y)
      log_status(string.format(
        "external input probe player_delta=%.2f bot=(%.2f,%.2f) within_patrol=%s",
        player_delta,
        bot_x,
        bot_y,
        tostring(within_patrol)))
      if within_patrol then
        log_status("input isolation confirmed")
        player_input_test.completed = true
        return
      end
      fail("bot left the patrol band after external player input")
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
  if player_delta >= INPUT_TEST_PLAYER_MOVE_THRESHOLD then
    local within_patrol = is_bot_within_patrol_band(bot_x, bot_y)
    log_status(string.format(
      "input probe player_delta=%.2f bot=(%.2f,%.2f) within_patrol=%s",
      player_delta,
      bot_x,
      bot_y,
      tostring(within_patrol)))
    if within_patrol then
      log_status("input isolation confirmed")
      player_input_test.completed = true
      return
    end
    fail("bot left the patrol band after player input")
    return
  end

  local elapsed_ms = now_ms - player_input_test.issued_at_ms
  if elapsed_ms >= INPUT_TEST_TIMEOUT_MS then
    player_input_test.mode = "external_wait"
    player_input_test.issued = false
    player_input_test.issued_at_ms = now_ms
    player_input_test.baseline_player_x = player_x
    player_input_test.baseline_player_y = player_y
    if not player_input_test.external_notice_logged then
      player_input_test.external_notice_logged = true
      log_status("internal click probe did not move the player; waiting for external input verification")
    end
    return
  end
  if elapsed_ms >= INPUT_TEST_RETRY_DELAY_MS and player_input_test.attempted_clicks < #INPUT_TEST_CLICK_POINTS then
    player_input_test.issued = false
  end
end

local function wait_for_surface(step)
  local snapshot = get_snapshot()
  if type(snapshot) ~= "table" then
    return nil, "snapshot unavailable"
  end

  if snapshot.surface_id == step.surface_id then
    return true
  end

  return nil, tostring(snapshot.surface_id)
end

local function wait_for_action(step)
  if type(sd.ui) ~= "table" or type(sd.ui.find_action) ~= "function" then
    return nil, "find_action unavailable"
  end

  local action = sd.ui.find_action(step.action_id, step.surface_id)
  if action ~= nil then
    return true
  end

  local snapshot = get_snapshot()
  local active_surface = snapshot and snapshot.surface_id or "nil"
  return nil, "active_surface=" .. tostring(active_surface)
end

local function activate_action(step)
  if type(sd.ui) ~= "table" or type(sd.ui.activate_action) ~= "function" then
    return false, "activate_action unavailable"
  end

  if not step.skip_find then
    local action = sd.ui.find_action(step.action_id, step.surface_id)
    if action == nil then
      return nil, "action unavailable"
    end
  end

  local ok, request_id_or_error = sd.ui.activate_action(step.action_id, step.surface_id)
  if not ok then
    return false, tostring(request_id_or_error)
  end

  return true
end

local function start_testrun()
  if type(sd.hub) ~= "table" or type(sd.hub.start_testrun) ~= "function" then
    return false, "sd.hub.start_testrun unavailable"
  end

  local ok, result = pcall(sd.hub.start_testrun)
  if not ok then
    return false, tostring(result)
  end

  return true
end

local function issue_patrol_move(target_key)
  if spawned_bot_id == nil or patrol == nil then
    return false, "patrol unavailable"
  end

  if type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
    return false, "sd.bots.move_to unavailable"
  end

  local target = patrol[target_key]
  if type(target) ~= "table" then
    return false, "invalid patrol point"
  end

  local ok = sd.bots.move_to(spawned_bot_id, target.x, target.y)
  if not ok then
    return false, "move_to returned false"
  end

  patrol.active_target = target_key
  return true
end

get_patrol_bot_snapshot = function()
  if type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    return nil
  end

  local snapshot = sd.bots.get_state(spawned_bot_id)
  if type(snapshot) == "table" then
    return snapshot
  end

  return nil
end

local function spawn_patrol_bot()
  if spawned_bot_id ~= nil then
    return true
  end

  if type(sd.bots) ~= "table" or type(sd.bots.create) ~= "function" then
    return false, "sd.bots.create unavailable"
  end

  if get_scene_name() ~= "testrun" then
    return nil, "scene not ready"
  end

  local player_x, player_y = get_player_position()
  if player_x == nil or player_y == nil then
    return nil, "player position unavailable"
  end

  local spawn_x = player_x + PATROL_SPAWN_OFFSET_X
  local spawn_y = player_y + PATROL_SPAWN_OFFSET_Y
  local point_a_x = spawn_x - PATROL_HALF_DISTANCE
  local point_a_y = spawn_y
  local point_b_x = spawn_x + PATROL_HALF_DISTANCE
  local point_b_y = spawn_y
  local bot_id = sd.bots.create({
    name = "Patrol Debug Bot",
    wizard_id = 2,
    ready = true,
    position = {
      x = spawn_x,
      y = spawn_y,
    },
    heading = 0.0,
  })
  if bot_id == nil then
    return false, "create returned nil"
  end

  spawned_bot_id = bot_id
  patrol = {
    a = { x = point_a_x, y = point_a_y },
    b = { x = point_b_x, y = point_b_y },
    active_target = nil,
  }
  reset_player_input_test()
  reset_visual_diff_probe()
  log_status(string.format(
    "spawned id=%s point_a=(%.2f,%.2f) point_b=(%.2f,%.2f)",
    tostring(bot_id),
    point_a_x,
    point_a_y,
    point_b_x,
    point_b_y))
  return true
end

local function execute_step(step, now_ms)
  if step.kind == "wait_surface" then
    return wait_for_surface(step)
  end

  if step.kind == "wait_action" then
    return wait_for_action(step)
  end

  if step.kind == "activate_action" then
    return activate_action(step)
  end

  if step.kind == "delay" then
    if active_delay_started_ms == nil then
      active_delay_started_ms = now_ms
    end

    if now_ms - active_delay_started_ms >= step.duration_ms then
      active_delay_started_ms = nil
      return true
    end

    return nil
  end

  if step.kind == "hub_start_testrun" then
    return start_testrun()
  end

  if step.kind == "wait_lifecycle" then
    if lifecycle_events[step.event_name] == true then
      return true
    end

    return nil
  end

  if step.kind == "spawn_patrol_bot" then
    return spawn_patrol_bot()
  end

  return false, "unsupported step kind"
end

local function advance_setup(now_ms)
  if failed or setup_complete then
    return
  end

  local step = steps[step_index]
  if step == nil then
    setup_complete = true
    return
  end

  local ok, detail = execute_step(step, now_ms)
  if ok == nil then
    return
  end

  if not ok then
    fail(detail or "step failed")
    return
  end

  step_index = step_index + 1
end

local function update_patrol(now_ms)
  if failed or spawned_bot_id == nil or patrol == nil then
    return
  end

  if get_scene_name() ~= "testrun" then
    return
  end

  if type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    fail("sd.bots.get_state unavailable")
    return
  end

  local snapshot = get_patrol_bot_snapshot()
  if type(snapshot) ~= "table" or not snapshot.available then
    return
  end

  if not visual_diff_probe.completed then
    local probe_status = run_visual_diff_probe()
    if probe_status ~= "complete" then
      update_visual_diff_probe_wait(now_ms, probe_status)
      return
    end
  end

  if patrol.active_target == nil then
    local ok, detail = issue_patrol_move("b")
    if not ok then
      fail(detail or "initial patrol move failed")
    end
    return
  end

  local active_target = patrol[patrol.active_target]
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
  if last_patrol_trace_ms == 0 or now_ms - last_patrol_trace_ms >= 1500 then
    last_patrol_trace_ms = now_ms
    local player_x, player_y = get_player_position()
    log_status(string.format(
      "bot=(%.2f,%.2f) player=(%.2f,%.2f) target=%s dist=%.2f moving=%s actor=%s",
      bot_x,
      bot_y,
      tonumber(player_x) or 0.0,
      tonumber(player_y) or 0.0,
      tostring(patrol.active_target),
      distance_to_target,
      tostring(snapshot.moving),
      tostring(snapshot.actor_address)))
  end

  if distance_to_target > PATROL_ARRIVAL_DISTANCE then
    return
  end

  local next_target = patrol.active_target == "a" and "b" or "a"
  if not patrol_loop_confirmed and patrol.active_target == "b" and next_target == "a" then
    patrol_loop_confirmed = true
    log_status("patrol loop confirmed")
  end
  local ok, detail = issue_patrol_move(next_target)
  if not ok then
    fail(detail or "patrol move failed")
  end
end

sd.events.on("run.started", function()
  lifecycle_events["run.started"] = true
end)

sd.events.on("run.ended", function()
  lifecycle_events["run.started"] = false
  patrol = nil
  patrol_loop_confirmed = false
  spawned_bot_id = nil
  last_patrol_trace_ms = 0
  player_input_test = nil
  reset_visual_diff_probe()
end)

sd.events.on("runtime.tick", function(event)
  local now_ms = tonumber(event.monotonic_milliseconds) or 0
  advance_setup(now_ms)
  if MODE == "create_probe" then
    run_create_probe(now_ms)
  else
    update_patrol(now_ms)
  end
end)
