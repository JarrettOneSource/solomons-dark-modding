local spell = sd.spells.register({
  key = "gravity_well",
  slot = "secondary",
  cfg = {
    name = "Gravity Well",
    description = "Draw nearby enemies toward a collapsing field.",
    mana_cost = 30,
    cooldown_ms = 1200,
    duration_ms = 2400,
    tick_interval_ms = 50,
    radius = 180,
  },
  on_cast = function(_context)
  end,
  on_tick = function(_effect)
  end,
  on_hit = function(_effect, _target)
  end,
})

assert(spell.id == 8348995147374483494, "unexpected deterministic spell id")
print("registered Lua spell " .. spell.mod_id .. ":" .. spell.key)
