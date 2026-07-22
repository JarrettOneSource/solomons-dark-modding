if type(sd) ~= "table" or type(sd.events) ~= "table" then
  error("sd.events is unavailable")
end

sd.events.filter("wave.spawning", function(event)
  return {
    count = math.min(event.count * 2, 4096),
    spawn_delay = math.floor(event.spawn_delay / 2),
    wave_delay = math.floor(event.wave_delay / 2),
  }
end)

print("doubling and accelerating owner-simulated stock wave actions")
