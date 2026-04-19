-- Bug 2 verification: move_to west (known walkable direction from bot spawn).
local ps = sd.player.get_state()
local bots = sd.bots.get_state()
local bot = bots[1]
local ba = bot.actor_address

sd.bots.stop(bot.id)
-- Put bot at known spawn-like position (1002.5, 175)
sd.debug.write_float(ba + 0x18, 1002.5)
sd.debug.write_float(ba + 0x1C, 175.0)
sd.debug.write_float(ba + 0x20, 0)
sd.debug.write_float(ba + 0x24, 0)

sd.bots.move_to(bot.id, 700.0, 175.0)
local bx = sd.debug.read_float(ba + 0x18)
local by = sd.debug.read_float(ba + 0x1C)
return string.format("START player=(%.2f,%.2f) bot=(%.3f,%.3f) target=(700,175)",
  ps.x, ps.y, bx, by)
