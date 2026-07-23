if type(sd) ~= "table" or type(sd.scene) ~= "table" then
  error("sd.scene is unavailable")
end
if not sd.runtime.has_capability("scene.read") or
    not sd.runtime.has_capability("scene.switch.authority") then
  error("Lua scene capabilities are unavailable")
end

local scene = sd.scene.get_state()
print("Lua scene lab ready; scene=" .. tostring(scene and scene.name))
