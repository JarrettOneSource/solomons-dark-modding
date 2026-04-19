-- Reset bot, issue move, sample position every 50ms for 2 seconds.
local ps = sd.player.get_state()
local bots = sd.bots.get_state()
local bot = bots[1]
local ba = bot.actor_address

sd.bots.stop(bot.id)
sd.debug.write_float(ba + 0x18, ps.x + 200)
sd.debug.write_float(ba + 0x1C, ps.y + 100)
sd.debug.write_float(ba + 0x20, 0)
sd.debug.write_float(ba + 0x24, 0)

sd.bots.move_to(bot.id, ps.x + 200, ps.y - 200)

local samples = {}
local clock = os.clock
local t0 = clock()
for i = 1, 40 do
  local t_target = t0 + i * 0.05
  while clock() < t_target do end
  local bx = sd.debug.read_float(ba + 0x18)
  local by = sd.debug.read_float(ba + 0x1C)
  samples[#samples + 1] = string.format("%.3f,%.3f,%.3f", clock() - t0, bx, by)
end
return table.concat(samples, "|")
