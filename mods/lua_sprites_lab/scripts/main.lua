local active_atlas = nil
local frame_counter = 0

function lua_sprites_lab_register(image_path, bundle_path)
  active_atlas = sd.sprites.register(
    "lab",
    image_path or "sprites/lab.png",
    bundle_path or "sprites/lab.bundle")
  return active_atlas
end

function lua_sprites_lab_unregister()
  active_atlas = nil
  return sd.sprites.unregister("lab")
end

function lua_sprites_lab_state()
  return sd.sprites.get("lab"), sd.sprites.list(), sd.sprites.get_limits()
end

sd.events.on("runtime.tick", function()
  if active_atlas == nil then return end
  frame_counter = frame_counter + 1
  local frame = math.floor(frame_counter / 15) % active_atlas.frame_count
  sd.draw.sprite(active_atlas.id, frame, 96, 96, {
    centered = true,
    width = 128,
    height = 128,
  })
end)

print("Lua Runtime Sprites Lab loaded; call lua_sprites_lab_register after adding lab.png/lab.bundle")
