if type(sd) ~= "table" or type(sd.timer) ~= "table" then
  error("sd.timer is unavailable")
end

sd.timer.after(250, function()
  print("one-shot timer fired")
end)

local pulse_count = 0
local pulse_timer
pulse_timer = sd.timer.every(500, function()
  pulse_count = pulse_count + 1
  print("timer pulse=" .. tostring(pulse_count))
  if pulse_count == 3 then
    sd.timer.cancel(pulse_timer)
  end
end)

sd.timer.sequence({
  { delay_ms = 750, callback = function() print("sequence step one") end },
  { delay_ms = 250, callback = function() print("sequence step two") end },
})
