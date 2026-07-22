if type(sd) ~= "table" or type(sd.draw) ~= "table" or sd.hud ~= sd.draw then
  error("sd.draw and its sd.hud alias are unavailable")
end

local white = {r = 255, g = 255, b = 255, a = 255}
local cyan = {r = 76, g = 214, b = 255, a = 255}
local gold = {r = 255, g = 205, b = 92, a = 255}
local panel = {r = 10, g = 18, b = 34, a = 224}

sd.events.on("runtime.tick", function(event)
  local viewport = sd.draw.get_viewport()
  if viewport == nil then
    return
  end

  local pulse = (math.sin(event.monotonic_milliseconds / 260.0) + 1.0) * 0.5
  local bar_width = 72 + pulse * 184

  sd.draw.rect(22, 22, 336, 152, {color = panel})
  sd.draw.rect(22, 22, 336, 152, {
    filled = false,
    thickness = 2,
    color = cyan,
  })
  sd.hud.text("LUA HUD SHOWCASE", 40, 38, {scale = 1.25, color = white})
  sd.draw.text(
    string.format("viewport %d x %d", viewport.width, viewport.height),
    40,
    68,
    {color = cyan})
  sd.draw.rect(40, 101, 256, 14, {
    filled = false,
    thickness = 2,
    color = white,
  })
  sd.draw.rect(42, 103, bar_width, 10, {color = gold})
  sd.draw.line(40, 137, 296, 137, {thickness = 2, color = cyan})

  sd.draw.sprite("Title", 9, viewport.width - 102, 74, {
    width = 180,
    height = 86,
    centered = true,
    color = white,
  })

  local player = sd.player.get_state()
  if type(player) == "table" then
    local marker = sd.draw.world_to_screen(player.x, player.y - 54)
    if type(marker) == "table" and marker.visible then
      sd.draw.line(marker.x - 10, marker.y, marker.x + 10, marker.y, {
        thickness = 2,
        color = gold,
      })
      sd.draw.line(marker.x, marker.y - 10, marker.x, marker.y + 10, {
        thickness = 2,
        color = gold,
      })
      sd.draw.text("YOU", marker.x - 14, marker.y - 30, {color = gold})
    end
  end
end)
