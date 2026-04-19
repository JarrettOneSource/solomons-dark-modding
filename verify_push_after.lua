-- Sample bot position after ticks have elapsed.
local ps = sd.player.get_state()
local bots = sd.bots.get_state()
local bot = bots[1]
local ba = bot.actor_address
local bx = sd.debug.read_float(ba + 0x18)
local by = sd.debug.read_float(ba + 0x1C)
local dx = bx - ps.x
local dy = by - ps.y
local dist = math.sqrt(dx * dx + dy * dy)
return string.format("AFTER player=(%.2f,%.2f) bot=(%.2f,%.2f) delta=(%.2f,%.2f) dist=%.2f",
  ps.x, ps.y, bx, by, dx, dy, dist)
