if type(sd) ~= "table" or type(sd.events) ~= "table" then
  error("sd.events is unavailable")
end

sd.events.filter("drop.rolling", function()
  return {kind = "gold"}
end)

print("forcing owner-simulated enemy rewards through the stock gold path")
