local LOG_PREFIX = "[ui.dark_cloud_sort_bootstrap]"
local ACTION_ID = "dialog.primary"
local SOURCE_SURFACE_ID = "dialog"
local TARGET_SURFACE_ID = "main_menu"

local armed_at_ms = nil
local last_attempt_ms = nil
local attempt_count = 0
local completed = false

local function log(message)
  print(LOG_PREFIX .. " " .. message)
end

if type(sd) ~= "table" or type(sd.ui) ~= "table" then
  error("sd.ui is unavailable")
end

if type(sd.ui.get_surface_id) ~= "function" or
   type(sd.ui.find_action) ~= "function" or
   type(sd.ui.activate_action) ~= "function" then
  error("sd.ui action helpers are unavailable")
end

sd.events.on("runtime.tick", function(event)
  if completed then
    return
  end

  if armed_at_ms == nil then
    armed_at_ms = event.monotonic_milliseconds + 2500
    log("armed")
    return
  end

  if event.monotonic_milliseconds < armed_at_ms then
    return
  end

  local active_surface_id = sd.ui.get_surface_id()
  if active_surface_id == TARGET_SURFACE_ID then
    completed = true
    log(string.format("sequence complete attempts=%d", attempt_count))
    return
  end

  if active_surface_id ~= SOURCE_SURFACE_ID then
    return
  end

  local action = sd.ui.find_action(ACTION_ID, SOURCE_SURFACE_ID)
  if action == nil then
    return
  end

  if last_attempt_ms ~= nil and event.monotonic_milliseconds - last_attempt_ms < 3000 then
    return
  end

  local ok, error_message = sd.ui.activate_action(ACTION_ID, SOURCE_SURFACE_ID)
  attempt_count = attempt_count + 1
  last_attempt_ms = event.monotonic_milliseconds

  if not ok then
    log(string.format(
      "step=%d action_id=%s resolved_label=%s ok=false reason=%s",
      attempt_count,
      ACTION_ID,
      tostring(action.label),
      tostring(error_message)))
    return
  end

  log(string.format(
    "step=%d action_id=%s resolved_label=%s ok=true",
    attempt_count,
    ACTION_ID,
    tostring(action.label)))
end)
