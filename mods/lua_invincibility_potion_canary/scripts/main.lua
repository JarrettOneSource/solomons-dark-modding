local DURATION_MS = 3 * 60 * 1000
local ITEM_KEY = "invincibility_potion"

sd.sprites.register(
  ITEM_KEY,
  "sprites/invincibility_potion.png",
  "sprites/invincibility_potion.bundle")

local potion
potion = sd.items.register({
  key = ITEM_KEY,
  name = "Invincibility Potion",
  type = "potion",
  description = "Grants invincibility and infinite mana for 3 minutes.",
  icon = {
    atlas = ITEM_KEY,
    frame = 0,
  },
  duration_ms = DURATION_MS,
  consume_vfx = {
    kind = "spell_glow",
    color = {0.15, 1.0, 0.25, 1.0},
  },
  on_consume = function(event)
    local restored, result = sd.player.restore_mana()
    if not restored then
      error("failed to restore mana: " .. tostring(result))
    end
    print(string.format(
      "invincibility potion consumed locally use_id=%d mana=%.2f",
      event.use_id,
      result))
  end,
})

sd.loot.register({
  item = potion.id,
  chance = 0.5,
  boss_chance = 1.0,
})

local active_effects = {}

local function clear_effects()
  for _, effect in pairs(active_effects) do
    sd.timer.cancel(effect.timer_id)
  end
  active_effects = {}
end

sd.events.on("item.consumed", function(event)
  if event.content_id ~= potion.id then
    return
  end

  local participant_id = event.participant_id
  local previous = active_effects[participant_id]
  if previous ~= nil then
    sd.timer.cancel(previous.timer_id)
  end

  local effect = {
    use_id = event.use_id,
  }
  active_effects[participant_id] = effect
  effect.timer_id = sd.timer.after(event.duration_ms, function()
    if active_effects[participant_id] == effect then
      active_effects[participant_id] = nil
      print(string.format(
        "invincibility potion expired participant_id=%d use_id=%d",
        participant_id,
        effect.use_id))
    end
  end)

  print(string.format(
    "invincibility potion activated participant_id=%d use_id=%d duration_ms=%d",
    participant_id,
    event.use_id,
    event.duration_ms))
end)

sd.events.on("run.started", clear_effects)
sd.events.on("run.ended", clear_effects)

sd.events.filter("damage.taken", function(event)
  if event.target_participant_id ~= nil and
      active_effects[event.target_participant_id] ~= nil then
    return false
  end
end)

sd.events.filter("mana.changing", function(event)
  if event.delta < 0 and event.participant_id ~= nil and
      active_effects[event.participant_id] ~= nil then
    return {delta = 0}
  end
end)

print(string.format(
  "Invincibility Potion Canary loaded content_id=%d normal_drop=50%% boss_drop=100%%",
  potion.id))
