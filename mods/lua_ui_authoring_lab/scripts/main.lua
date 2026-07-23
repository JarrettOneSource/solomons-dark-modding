local surface = sd.ui.create_surface({
  id = "authoring_lab",
  title = "Lua UI Authoring Lab",
  x = 0.25,
  y = 0.2,
  width = 0.5,
  height = 0.6,
  modal = true,
  close_on_escape = true,
})

local body = sd.ui.create_panel(surface, {
  id = "body",
  x = 0.05,
  y = 0.15,
  width = 0.9,
  height = 0.75,
})

local status = sd.ui.create_label(body, {
  id = "status",
  text = "Presentation count: 0",
  x = 0.05,
  y = 0.08,
  width = 0.9,
  height = 0.12,
})

local shared = sd.ui.create_label(body, {
  id = "shared",
  text = "Authority count: 0",
  x = 0.05,
  y = 0.24,
  width = 0.9,
  height = 0.12,
})

local presentation_count = 0
sd.ui.create_button(body, {
  id = "local_increment",
  label = "Increment local presentation",
  x = 0.1,
  y = 0.45,
  width = 0.8,
  height = 0.16,
  execution = "presentation",
  on_activate = function()
    presentation_count = presentation_count + 1
    sd.ui.set_text(status, "Presentation count: " .. presentation_count)
  end,
})

sd.ui.create_button(body, {
  id = "authority_increment",
  label = "Increment shared state",
  x = 0.1,
  y = 0.67,
  width = 0.8,
  height = 0.16,
  execution = "simulation",
  on_activate = function()
    local value = sd.state.get("ui_authoring_lab.count") or 0
    sd.state.set("ui_authoring_lab.count", value + 1)
  end,
})

local next_refresh = 0
sd.events.on("runtime.tick", function(tick)
  if tick.monotonic_milliseconds < next_refresh then return end
  next_refresh = tick.monotonic_milliseconds + 100
  local value = sd.state.get("ui_authoring_lab.count") or 0
  sd.ui.set_text(shared, "Authority count: " .. value)
end)

sd.ui.show(surface)
print("Lua UI Authoring Lab visible")
