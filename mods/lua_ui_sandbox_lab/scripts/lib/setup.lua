local DEFAULT_MODE = "patrol"
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

  local patrol_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "delay", duration_ms = 5000 },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 3000 },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 18000 },
    { kind = "hub_start_testrun" },
    { kind = "delay", duration_ms = 5000 },
    { kind = "spawn_patrol_bot" },
  }

  local testrun_ready_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "delay", duration_ms = 5000 },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 3000 },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 18000 },
    { kind = "hub_start_testrun" },
    { kind = "delay", duration_ms = 5000 },
  }

  local create_ready_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "delay", duration_ms = 5000 },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 3000 },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 5000 },
  }

  local trace_rich_item_startup_steps = {
    { kind = "wait_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "activate_action", action_id = actions.dialog_primary, surface_id = "dialog" },
    { kind = "wait_surface", surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_play, surface_id = "main_menu" },
    { kind = "wait_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "activate_action", action_id = actions.main_menu_new_game, surface_id = "main_menu" },
    { kind = "delay", duration_ms = 5000 },
    { kind = "activate_action", action_id = create_element_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 3000 },
    { kind = "activate_action", action_id = create_discipline_action, surface_id = "create", skip_find = true },
    { kind = "delay", duration_ms = 18000 },
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
  if selected_element ~= nil and active_preset:match("^create_ready_") then
    return create_ready_steps
  end
  if active_preset == "enter_gameplay_start_run_ready" or
      (selected_element ~= nil and active_preset:match("^map_create_")) then
    return testrun_ready_steps
  end
  return patrol_steps
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

    if step.kind == "wait_lifecycle" then
      if ctx.lifecycle_events[step.event_name] == true then
        return true
      end

      return nil
    end

    if step.kind == "spawn_patrol_bot" then
      return ctx.mode_handlers.patrol.spawn_patrol_bot()
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
