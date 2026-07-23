local source_version = "authoring-baseline-0001"

authoring_lab_version = source_version
authoring_lab_surface = sd.ui.create_surface({
  id = "authoring_reload_probe",
  title = "Lua Authoring Reload Probe",
  x = 0.3,
  y = 0.3,
  width = 0.4,
  height = 0.3,
})

local panel = sd.ui.create_panel(authoring_lab_surface, {
  id = "body",
  x = 0.08,
  y = 0.2,
  width = 0.84,
  height = 0.64,
})

sd.ui.create_label(panel, {
  id = "version",
  text = source_version,
  x = 0.08,
  y = 0.2,
  width = 0.84,
  height = 0.3,
})

print("Lua Authoring Lab loaded " .. source_version)
