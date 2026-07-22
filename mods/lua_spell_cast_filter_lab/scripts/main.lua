if type(sd) ~= "table" or type(sd.events) ~= "table" then
  error("sd.events is unavailable")
end

local cancel_next_primary = true

sd.events.filter("spell.casting", function(event)
  if cancel_next_primary and event.kind == "primary" then
    cancel_next_primary = false
    print("canceled first owner-simulated primary skill " .. tostring(event.skill_id))
    return false
  end
end)

print("waiting to cancel one owner-simulated primary cast")
