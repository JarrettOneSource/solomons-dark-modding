if type(sd) ~= "table" or type(sd.nav) ~= "table" then
  error("sd.nav is unavailable")
end
if not sd.runtime.has_capability("nav.read") then
  error("Lua navigation capability is unavailable")
end

local grid = sd.nav.get_grid(1)
print("Lua navigation lab ready; grid=" .. tostring(grid ~= nil))
