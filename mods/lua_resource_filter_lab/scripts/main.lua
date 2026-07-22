if type(sd) ~= "table" or type(sd.events) ~= "table" then
  error("sd.events is unavailable")
end

sd.events.filter("xp.gaining", function(event)
  return {amount = event.amount * 2}
end)

sd.events.filter("gold.changing", function(event)
  if event.delta > 0 then
    return {delta = event.delta * 2}
  end
end)

print("doubling positive owner-simulated XP and gold gains")
