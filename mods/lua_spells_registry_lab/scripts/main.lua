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
  on_cast = function(context)
    return {
      key = "gravity_well_field",
      x = context.aim_x,
      y = context.aim_y,
      radius = context.cfg.radius,
      lifetime_ms = context.cfg.duration_ms,
      data = {hits = 0},
    }
  end,
  on_tick = function(effect)
    return {
      radius = math.max(0, effect.radius - effect.delta_ms * 0.02),
    }
  end,
  on_hit = function(effect, _target)
    return {data = {hits = effect.data.hits + 1}}
  end,
})

assert(spell.id == 8348995147374483494, "unexpected deterministic spell id")
print("registered Lua spell " .. spell.mod_id .. ":" .. spell.key)
