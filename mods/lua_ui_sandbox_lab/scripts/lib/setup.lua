local DEFAULT_MODE = "idle"
local require_mod = sd.runtime.require_mod
local trace_util = require_mod("scripts/lib/trace_util.lua")
local ACTIVE_PRESET_PATH = "config/active_preset.txt"
local ELEMENT_ACTIONS = {
  earth = "create_select_earth",
  ether = "create_select_ether",
  fire = "create_select_fire",
  water = "create_select_water",
  air = "create_select_air",
}
local DISCIPLINE_ACTIONS = {
  mind = "create_select_mind",
  body = "create_select_body",
  arcane = "create_select_arcane",
}

local function read_active_preset_file()
  if type(sd) ~= "table" or type(sd.runtime) ~= "table" or
      type(sd.runtime.get_mod_text_file) ~= "function" then
    return nil
  end

  local source = sd.runtime.get_mod_text_file(ACTIVE_PRESET_PATH)
  if type(source) ~= "string" then
    return nil
  end

  local preset = source:match("^%s*(.-)%s*$")
  if type(preset) ~= "string" or preset == "" then
    return nil
  end
  return preset
end

local function parse_create_selection(active_preset)
  if type(active_preset) ~= "string" then
    return nil, nil
  end

  local mode, suffix = active_preset:match("^(create_ready)_(.+)$")
  if mode ~= nil then
    suffix = suffix:gsub("_hub$", "")
    local element, discipline = suffix:match("^([a-z]+)_([a-z]+)$")
    if element ~= nil and ELEMENT_ACTIONS[element] ~= nil and DISCIPLINE_ACTIONS[discipline] ~= nil then
      return element, discipline
    end
    if ELEMENT_ACTIONS[suffix] ~= nil then
      return suffix, "arcane"
    end
  end

  mode, suffix = active_preset:match("^(map_create)_(.+)$")
  if mode ~= nil then
    suffix = suffix:gsub("_hub$", "")
    local element, discipline = suffix:match("^([a-z]+)_([a-z]+)$")
    if element ~= nil and ELEMENT_ACTIONS[element] ~= nil and DISCIPLINE_ACTIONS[discipline] ~= nil then
      return element, discipline
    end
    if ELEMENT_ACTIONS[suffix] ~= nil then
      return suffix, "arcane"
    end
  end

  return nil, nil
end

local function wants_hub_stop(active_preset)
  return type(active_preset) == "string" and active_preset:match("_hub$") ~= nil
end

local function resolve_create_element_action(actions, active_preset)
  local element = parse_create_selection(active_preset)
  if element ~= nil then
    local field = ELEMENT_ACTIONS[element]
    if field ~= nil then
      return actions[field]
    end
  end
  return actions.create_select_water
end

local function resolve_create_discipline_action(actions, active_preset)
  local _, discipline = parse_create_selection(active_preset)
  if discipline ~= nil then
    local field = DISCIPLINE_ACTIONS[discipline]
    if field ~= nil then
      return actions[field]
    end
  end
  return actions.create_select_arcane
end

local function resolve_mode()
  local active_preset = nil
  if type(sd) == "table" and type(sd.runtime) == "table" and
      type(sd.runtime.get_environment_variable) == "function" then
    active_preset = sd.runtime.get_environment_variable("SDMOD_UI_SANDBOX_PRESET")
  end
  if type(active_preset) ~= "string" or active_preset == "" then
    active_preset = read_active_preset_file()
  end

  local mode = DEFAULT_MODE
  if active_preset == "create_probe" then
    mode = "create_probe"
  elseif active_preset == "wizard_compare" then
    mode = "wizard_compare"
  end

  return mode, active_preset
end

local function build_steps(mode, actions, active_preset)
  local create_element_action = resolve_create_element_action(actions, active_preset)
  local create_discipline_action = resolve_create_discipline_action(actions, active_preset)

  local testrun_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "resolve_new_game_branch", create_surface_id = "create", confirm_action_id = actions.dialog_primary, confirm_surface_id = "dialog" },
    { kind = "wait_create_selection_ready", phase = "element" },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "wait_create_selection_ready", phase = "discipline" },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "wait_surface_not", surface_id = "create" },
    { kind = "delay", duration_ms = 1000 },
    { kind = "hub_start_testrun" },
    { kind = "delay", duration_ms = 250 },
  }

  local create_ready_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "resolve_new_game_branch", create_surface_id = "create", confirm_action_id = actions.dialog_primary, confirm_surface_id = "dialog" },
    { kind = "wait_create_selection_ready", phase = "element" },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "wait_create_selection_ready", phase = "discipline" },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "wait_surface_not", surface_id = "create" },
    { kind = "delay", duration_ms = 250 },
  }

  local hub_wait_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "resolve_new_game_branch", create_surface_id = "create", confirm_action_id = actions.dialog_primary, confirm_surface_id = "dialog" },
    { kind = "wait_create_selection_ready", phase = "element" },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "wait_create_selection_ready", phase = "discipline" },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "wait_surface_not", surface_id = "create" },
    { kind = "delay", duration_ms = 1000 },
  }

  local trace_rich_item_startup_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "resolve_new_game_branch", create_surface_id = "create", confirm_action_id = actions.dialog_primary, confirm_surface_id = "dialog" },
    { kind = "wait_create_selection_ready", phase = "element" },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "wait_create_selection_ready", phase = "discipline" },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "wait_surface_not", surface_id = "create" },
    { kind = "delay", duration_ms = 1000 },
    { kind = "hub_start_testrun" },
    { kind = "delay", duration_ms = 5000 },
  }

  local create_probe_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "resolve_new_game_branch", create_surface_id = "create", confirm_action_id = actions.dialog_primary, confirm_surface_id = "dialog" },
    { kind = "delay", duration_ms = 18000 },
  }

  if mode == "create_probe" then
    return create_probe_steps
  end
  if mode == "wizard_compare" then
    return {}
  end
  if active_preset == "trace_rich_item_startup" then
    return trace_rich_item_startup_steps
  end
  local selected_element, _ = parse_create_selection(active_preset)
  if active_preset == "enter_gameplay_wait" or
      (selected_element ~= nil and wants_hub_stop(active_preset)) then
    return hub_wait_steps
  end
  if selected_element ~= nil and active_preset:match("^create_ready_") then
    return create_ready_steps
  end
  if active_preset == "enter_gameplay_start_run_ready" or
      (selected_element ~= nil and active_preset:match("^map_create_")) then
    return testrun_steps
  end
  return {}
end

local function new(ctx)
  local self = {
    active_delay_started_ms = nil,
    setup_complete = false,
    step_index = 1,
    steps = build_steps(ctx.mode, ctx.actions, ctx.active_preset),
  }

  local function wait_for_surface(step)
    local snapshot = ctx.get_snapshot()
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

    local snapshot = ctx.get_snapshot()
    local active_surface = snapshot and snapshot.surface_id or "nil"
    return nil, "active_surface=" .. tostring(active_surface)
  end

  local function activate_action(step, now_ms)
    if type(sd.ui) ~= "table" or type(sd.ui.activate_action) ~= "function" then
      return false, "activate_action unavailable"
    end

    if step._request_id == nil then
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

      step._request_id = tonumber(request_id_or_error) or 0
      return nil, "waiting_for_dispatch"
    end

    local dispatch_snapshot = ctx.get_action_dispatch_snapshot(step._request_id)
    if type(dispatch_snapshot) ~= "table" then
      return nil, "waiting_for_dispatch"
    end

    local status = tostring(dispatch_snapshot.status or "")
    if status == "queued" or status == "dispatching" then
      return nil, "waiting_for_dispatch"
    end

    if status == "failed" then
      return false, tostring(dispatch_snapshot.error_message or "dispatch failed")
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

  local function arm_debug_traces(step, now_ms)
    if type(step.traces) ~= "table" then
      return false, "arm_debug_traces requires a traces table"
    end
    if not step._queued then
      trace_util.queue_traces(ctx, step.traces, now_ms, step.timeout_ms or 15000)
      step._queued = true
    end

    return trace_util.advance(ctx, now_ms)
  end

  local function resolve_new_game_branch(step, now_ms)
    local snapshot = ctx.get_snapshot()
    if type(snapshot) ~= "table" then
      return nil, "snapshot unavailable"
    end

    if step._confirm_request_id ~= nil then
      local dispatch_snapshot = ctx.get_action_dispatch_snapshot(step._confirm_request_id)
      if type(dispatch_snapshot) ~= "table" then
        return nil, "waiting_for_new_game_confirm_dispatch"
      end

      local status = tostring(dispatch_snapshot.status or "")
      if status == "queued" or status == "dispatching" then
        return nil, "waiting_for_new_game_confirm_dispatch"
      end

      if status == "failed" then
        return false, tostring(dispatch_snapshot.error_message or "new_game confirm dispatch failed")
      end

      step._confirm_request_id = nil
      step._confirm_dispatched = true
      step._confirm_dispatched_at_ms = now_ms
      ctx.log_status("new_game branch: confirm dispatched, waiting for create")
    end

    if snapshot.surface_id == step.confirm_surface_id then
      local action = sd.ui.find_action(step.confirm_action_id, step.confirm_surface_id)
      if action == nil then
        return nil, "confirm action unavailable"
      end

      local ok, request_id_or_error = sd.ui.activate_action(step.confirm_action_id, step.confirm_surface_id)
      if not ok then
        return false, tostring(request_id_or_error)
      end

      step._confirm_request_id = tonumber(request_id_or_error) or 0
      ctx.log_status("new_game branch: existing save confirm queued from NEW GAME path")
      return nil, "waiting_for_create_after_confirm"
    end

    if snapshot.surface_id == step.create_surface_id then
      return true
    end

    if snapshot.surface_id == "main_menu" and step._confirm_dispatched then
      return nil, "waiting_for_create_after_confirm"
    end

    return nil, "active_surface=" .. tostring(snapshot.surface_id)
  end

  local function is_create_selection_unset(value)
    local numeric = tonumber(value)
    return numeric == nil or numeric == -1 or numeric == 0xFFFFFFFF
  end

  local function wait_create_selection_ready(step)
    local owner_address = ctx.find_surface_object_ptr("create")
    if owner_address == nil or owner_address == 0 then
      return nil, "create owner unavailable"
    end

    local offsets = type(ctx.config) == "table" and ctx.config.offsets or nil
    if type(offsets) ~= "table" then
      return false, "create selection offsets unavailable"
    end

    local enabled_offset = nil
    local selected_offset = nil
    if step.phase == "element" then
      enabled_offset = offsets.create_owner_element_enabled_byte
      selected_offset = offsets.create_owner_element_selected
    elseif step.phase == "discipline" then
      enabled_offset = offsets.create_owner_discipline_enabled_byte
      selected_offset = offsets.create_owner_discipline_selected
    else
      return false, "unsupported create selection phase"
    end

    local enabled = ctx.read_object_u8(owner_address, enabled_offset)
    local selected = ctx.read_object_u32(owner_address, selected_offset)
    if enabled ~= nil and enabled ~= 0 and is_create_selection_unset(selected) then
      return true
    end

    return nil, string.format(
      "waiting_for_create_%s enabled=%s selected=%s owner=%s",
      tostring(step.phase),
      tostring(enabled),
      tostring(selected),
      ctx.format_hex32(owner_address))
  end

  local function wait_scene_prefix(step)
    local scene_name = ctx.get_scene_name()
    if type(scene_name) ~= "string" or scene_name == "" then
      return nil, "scene unavailable"
    end

    if type(step.scene_prefix) ~= "string" or step.scene_prefix == "" then
      return false, "wait_scene_prefix requires a scene_prefix"
    end

    if scene_name:sub(1, #step.scene_prefix) == step.scene_prefix then
      return true
    end

    return nil, "scene=" .. tostring(scene_name)
  end

  local function wait_surface_not(step)
    local snapshot = ctx.get_snapshot()
    if type(snapshot) ~= "table" then
      return true
    end

    if snapshot.surface_id ~= step.surface_id then
      return true
    end

    return nil, "active_surface=" .. tostring(snapshot.surface_id)
  end

  local function execute_step(step, now_ms)
    if step.kind == "wait_surface" then
      return wait_for_surface(step)
    end

    if step.kind == "wait_action" then
      return wait_for_action(step)
    end

    if step.kind == "activate_action" then
      return activate_action(step, now_ms)
    end

    if step.kind == "delay" then
      if self.active_delay_started_ms == nil then
        self.active_delay_started_ms = now_ms
      end

      if now_ms - self.active_delay_started_ms >= step.duration_ms then
        self.active_delay_started_ms = nil
        return true
      end

      return nil
    end

    if step.kind == "hub_start_testrun" then
      return start_testrun()
    end

    if step.kind == "arm_debug_traces" then
      return arm_debug_traces(step, now_ms)
    end

    if step.kind == "resolve_new_game_branch" then
      return resolve_new_game_branch(step, now_ms)
    end

    if step.kind == "wait_create_selection_ready" then
      return wait_create_selection_ready(step)
    end

    if step.kind == "wait_scene_prefix" then
      return wait_scene_prefix(step)
    end

    if step.kind == "wait_surface_not" then
      return wait_surface_not(step)
    end

    if step.kind == "wait_lifecycle" then
      if ctx.lifecycle_events[step.event_name] == true then
        return true
      end

      return nil
    end

    return false, "unsupported step kind"
  end

  function self.advance(now_ms)
    if ctx.failed or self.setup_complete then
      return
    end

    local step = self.steps[self.step_index]
    if step == nil then
      self.setup_complete = true
      ctx.mark_sequence_complete()
      return
    end

    local ok, detail = execute_step(step, now_ms)
    if ok == nil then
      return
    end

    if not ok then
      ctx.fail(detail or "step failed")
      return
    end

    self.step_index = self.step_index + 1
  end

  return self
end

return {
  new = new,
  resolve_mode = resolve_mode,
}
