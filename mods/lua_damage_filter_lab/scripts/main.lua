if type(sd) ~= "table" or type(sd.events) ~= "table" then
  error("sd.events is unavailable")
end

sd.events.filter("damage.taken", function(event)
  local rewritten_lanes = {}
  for index, value in ipairs(event.lanes) do
    rewritten_lanes[index] = value * 0.75
  end
  return {lanes = rewritten_lanes}
end)

print("reducing owner-resolved incoming damage lanes to 75 percent")
