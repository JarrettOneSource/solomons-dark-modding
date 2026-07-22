if type(sd) ~= "table" or type(sd.events) ~= "table" then
  error("sd.events is unavailable")
end

sd.events.filter("enemy.spawning", function(event)
  return {
    hp = event.hp * 1.5,
    chase_speed = event.chase_speed * 1.1,
  }
end)

print("increasing owner-simulated enemy HP and chase speed")
