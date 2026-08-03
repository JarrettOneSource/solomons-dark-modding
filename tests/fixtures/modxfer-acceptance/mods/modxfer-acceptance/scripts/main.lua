local white = {r = 255, g = 255, b = 255, a = 255}
local yellow = {r = 255, g = 230, b = 64, a = 255}
local magenta = {r = 145, g = 16, b = 104, a = 238}

sd.events.on("runtime.tick", function()
  local viewport = sd.draw.get_viewport()
  if viewport == nil then
    return
  end

  local width = math.min(600, viewport.width - 32)
  local left = (viewport.width - width) / 2
  sd.draw.rect(left, 18, width, 78, {color = magenta})
  sd.draw.rect(left, 18, width, 78, {
    filled = false,
    thickness = 3,
    color = yellow,
  })
  sd.draw.text("MODXFER ACCEPTANCE ACTIVE", left + 24, 34, {
    scale = 1.35,
    color = white,
  })
  sd.draw.text("UNPUBLISHED HOST PACKAGE - 2026-08-03", left + 24, 67, {
    color = yellow,
  })
end)

print("MODXFER acceptance fixture active: acceptance.modxfer.host_only 1.0.0")
