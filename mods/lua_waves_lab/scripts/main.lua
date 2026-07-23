if type(sd) ~= "table" or type(sd.waves) ~= "table" then
  error("sd.waves is unavailable")
end
if not sd.runtime.has_capability("waves.read") or
    not sd.runtime.has_capability("waves.schedule.read") then
  error("Lua wave capabilities are unavailable")
end

sd.events.on("wave.started", function(event)
  print(
    "Lua waves lab observed wave " .. tostring(event.wave) ..
    " with planned enemies=" .. tostring(event.planned)
  )
end)

print("Lua waves lab ready")
