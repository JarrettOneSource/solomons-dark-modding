local bots = sd.bots.get_state()
local bot = bots[1]
local ba = bot.actor_address
local t = sd.runtime.now_ms and sd.runtime.now_ms() or 0
local bx = sd.debug.read_float(ba + 0x18)
local by = sd.debug.read_float(ba + 0x1C)
return string.format("t=%d bot=(%.3f,%.3f)", t, bx, by)
