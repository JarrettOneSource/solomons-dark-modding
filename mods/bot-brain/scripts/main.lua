local function create_mod_require()
  if type(load) ~= "function" or
      type(sd) ~= "table" or type(sd.runtime) ~= "table" or
      type(sd.runtime.get_mod_text_file) ~= "function" then
    error("mod-local Lua source loading is unavailable")
  end

  local loading_sentinel = {}
  local module_cache = {}
  return function(path)
    local normalized = tostring(path or ""):gsub("\\", "/")
    normalized = normalized:gsub("^%./", ""):gsub("/+", "/")
    if normalized == "" then
      error("module path must not be empty")
    end
    if module_cache[normalized] == loading_sentinel then
      error("circular module load for " .. normalized)
    end
    if module_cache[normalized] ~= nil then
      return module_cache[normalized]
    end

    local source = sd.runtime.get_mod_text_file(normalized)
    if type(source) ~= "string" then
      error("unable to read module " .. normalized)
    end
    local chunk, load_error = load(
      source,
      "@" .. normalized,
      "t",
      _ENV)
    if chunk == nil then
      error(
        "unable to compile module " .. normalized ..
        ": " .. tostring(load_error))
    end

    module_cache[normalized] = loading_sentinel
    local ok, result = pcall(chunk)
    if not ok then
      module_cache[normalized] = nil
      error(
        "error loading module " .. normalized ..
        ": " .. tostring(result))
    end
    module_cache[normalized] = result == nil and true or result
    return module_cache[normalized]
  end
end

local require_mod = create_mod_require()
local steering = assert(require_mod("scripts/steering.lua"))
local brain = assert(require_mod("scripts/brain.lua"))
local roster = assert(require_mod("scripts/roster.lua"))

local shared = {
  think_interval_ms = 250,
  spawn_retry_ms = 1000,
  nav_refresh_ms = 2000,
  attack_window_refresh_ms = 2000,
  cast_hold_ms = 80,
  approach_move_interval_ms = 1000,
  kite_move_interval_ms = 250,
  orbit_move_interval_ms = 500,
  flee_move_interval_ms = 250,
  threat_radius = 340.0,
  flee_threat_radius = 900.0,
  normal_lookahead = 140.0,
  flee_lookahead = 220.0,
  offense_enabled = true,
  think_profile = "standard",
  focus_bot_key = "NONE",
}

shared.threat_radius = sd.settings.get("kite_radius")
shared.offense_enabled = sd.settings.get("offense_enabled")
shared.think_profile = sd.settings.get("think_profile")
shared.think_interval_ms =
  shared.think_profile == "relaxed" and 400 or 250
shared.focus_bot_key = sd.settings.get("focus_bot_key")

local debug = {
  authority = false,
  active = false,
  participant_id = 0,
  participant_ids = {},
  roster_size = 0,
  startup_roster = nil,
  startup_apply_count = 0,
  bots = {},
  mode = "waiting",
  kite_radius = shared.threat_radius,
  offense_enabled = shared.offense_enabled,
  think_profile = shared.think_profile,
  focus_bot_key = shared.focus_bot_key,
  focus_active = false,
  settings_change_count = 0,
  last_settings_change_key = "",
  last_roster_new_size = -1,
  last_roster_old_size = -1,
  last_roster_new_value = nil,
  respawn_action_count = 0,
  reconciliation_error_count = 0,
  last_reconciliation_error = "",
}
rawset(_G, "bot_brain_debug", debug)

local function log(context, message)
  local prefix = ""
  if type(context) == "table" and type(context.row) == "table" then
    prefix =
      "roster=" .. tostring(context.roster_index) ..
      " name=" .. tostring(context.row.name) ..
      " element=" .. tostring(context.row.element) ..
      " discipline=" .. tostring(context.row.discipline) .. " "
  end
  print("[bot-brain] " .. prefix .. message)
end
shared.log = log

local function simulation_authority()
  local ok, authority = pcall(sd.state.is_authority)
  return ok and authority == true
end

local manager = roster.new(brain, steering, shared, debug)
local state = {
  last_tick_ms = -shared.think_interval_ms,
  last_now_ms = 0,
  focus_key_down = false,
  focus_active = false,
}

local startup_roster = sd.settings.get("roster")
local startup_errors = manager:apply(
  startup_roster,
  simulation_authority(),
  state.last_now_ms)
debug.startup_roster = startup_roster
debug.startup_apply_count = 1
if #startup_errors > 0 then
  log(nil, table.concat(startup_errors, "; "))
end

local function update_focus_key()
  local key_down =
    sd.settings.is_keybind_down("focus_bot_key")
  if key_down == true then
    local bot = manager:first_bot()
    if bot ~= nil then
      local ok, x, y = pcall(function()
        return bot:position()
      end)
      if ok and tonumber(x) ~= nil and tonumber(y) ~= nil then
        sd.camera.set_focus(x, y)
        state.focus_active = true
      end
    end
  elseif state.focus_key_down or state.focus_active then
    sd.camera.clear_focus()
    state.focus_active = false
  end
  state.focus_key_down = key_down == true
  debug.focus_active = state.focus_active
end

local function throw_reconciliation_errors(errors)
  if #errors > 0 then
    error(table.concat(errors, "; "))
  end
end

sd.settings.on_changed(function(key, new_value, old_value)
  if key == "kite_radius" then
    shared.threat_radius = new_value
    debug.kite_radius = new_value
  elseif key == "offense_enabled" then
    shared.offense_enabled = new_value
    debug.offense_enabled = new_value
  elseif key == "think_profile" then
    shared.think_profile = new_value
    shared.think_interval_ms =
      new_value == "relaxed" and 400 or 250
    debug.think_profile = new_value
  elseif key == "focus_bot_key" then
    shared.focus_bot_key = new_value
    debug.focus_bot_key = new_value
  elseif key == "roster" then
    debug.last_roster_new_size = #new_value
    debug.last_roster_new_value = new_value
    debug.last_roster_old_size =
      type(old_value) == "table" and #old_value or -1
    local errors = manager:apply(
      new_value,
      simulation_authority(),
      state.last_now_ms)
    debug.settings_change_count =
      debug.settings_change_count + 1
    debug.last_settings_change_key = key
    throw_reconciliation_errors(errors)
    return
  end
  debug.settings_change_count =
    debug.settings_change_count + 1
  debug.last_settings_change_key = key
end)

sd.settings.on_action("respawn_bot", function()
  if state.focus_active then
    sd.camera.clear_focus()
    state.focus_active = false
    state.focus_key_down = false
  end
  local errors = manager:respawn_all(
    state.last_now_ms,
    simulation_authority())
  debug.respawn_action_count =
    debug.respawn_action_count + 1
  debug.focus_active = false
  throw_reconciliation_errors(errors)
  log(nil, "roster respawn requested")
end)

sd.events.on("run.started", function()
  manager:reset_run(true)
  log(nil, "run started")
end)

sd.events.on("run.ended", function()
  manager:reset_run(false)
  log(nil, "run ended")
end)

sd.events.on("runtime.tick", function(event)
  if type(event) ~= "table" then
    return
  end
  local now_ms = tonumber(event.monotonic_milliseconds)
  if now_ms == nil then
    return
  end
  state.last_now_ms = now_ms
  update_focus_key()
  if now_ms - state.last_tick_ms <
      shared.think_interval_ms then
    return
  end
  state.last_tick_ms = now_ms
  local authority = simulation_authority()
  debug.authority = authority
  manager:tick(now_ms, authority)
end)
