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

local picker = sd.ui.create_surface({
  id = "spell_picker",
  title = "Lua Spell Picker",
  x = 0.28,
  y = 0.24,
  width = 0.44,
  height = 0.52,
  modal = true,
  close_on_escape = true,
})

local body = sd.ui.create_panel(picker, {
  id = "body",
  x = 0.06,
  y = 0.18,
  width = 0.88,
  height = 0.72,
})

local status = sd.ui.create_label(body, {
  id = "status",
  text = "Gravity Well is not equipped",
  x = 0.06,
  y = 0.08,
  width = 0.88,
  height = 0.14,
})

sd.ui.create_button(body, {
  id = "equip_gravity_well",
  label = "Equip Gravity Well in belt slot 1",
  x = 0.08,
  y = 0.34,
  width = 0.84,
  height = 0.18,
  execution = "presentation",
  on_activate = function()
    sd.spells.select(spell.id, 1)
    sd.ui.set_text(status, "Gravity Well equipped in belt slot 1")
  end,
})

sd.ui.create_button(body, {
  id = "clear_gravity_well",
  label = "Clear belt slot 1",
  x = 0.08,
  y = 0.62,
  width = 0.84,
  height = 0.18,
  execution = "presentation",
  on_activate = function()
    sd.spells.clear_selection("secondary", 1)
    sd.ui.set_text(status, "Gravity Well is not equipped")
  end,
})

sd.ui.show(picker)
print("registered Lua spell " .. spell.mod_id .. ":" .. spell.key)
