-- Bug 1 verification: snap bot onto player, sample bot position before/after.
local ps = sd.player.get_state()
local bots = sd.bots.get_state()
local bot = bots[1]
local ba = bot.actor_address

-- Snap bot onto player and zero velocity
sd.debug.write_float(ba + 0x18, ps.x)
sd.debug.write_float(ba + 0x1C, ps.y)
sd.debug.write_float(ba + 0x20, 0)
sd.debug.write_float(ba + 0x24, 0)

local before_x = sd.debug.read_float(ba + 0x18)
local before_y = sd.debug.read_float(ba + 0x1C)

return string.format("BEFORE player=(%.2f,%.2f) bot=(%.2f,%.2f)",
  ps.x, ps.y, before_x, before_y)
