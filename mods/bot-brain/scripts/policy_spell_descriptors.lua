local descriptors = {}
local Resolver = {}
Resolver.__index = Resolver

local ELEMENT_BANDS = {
  {name = "ether", first = 8, last = 15, identity = 0.0},
  {name = "fire", first = 16, last = 23, identity = 0.2},
  {name = "air", first = 24, last = 31, identity = 0.4},
  {name = "water", first = 32, last = 39, identity = 0.6},
  {name = "earth", first = 40, last = 47, identity = 0.8},
}

local BASE_PRIMARY_IDS = {
  [8] = true,
  [16] = true,
  [24] = true,
  [32] = true,
  [40] = true,
}

local WELD_PAIRS = {
  [1000] = {8, 16},
  [1001] = {8, 32},
  [1002] = {8, 24},
  [1003] = {16, 24},
  [1004] = {32, 24},
  [1005] = {16, 32},
  [1006] = {8, 40},
  [1007] = {16, 40},
  [1008] = {32, 40},
  [1009] = {24, 40},
}

-- Only families whose native dispatch consumes a freely useful point/heading
-- receive offset actions. Homing missiles, beams, cones, toggles, self buffs,
-- and radial caster effects remain center-only.
local FREE_AIM_ENTRY_IDS = {
  [11] = true, -- Call Leviathan point
  [15] = true, -- Phasing heading
  [16] = true, -- Fireball
  [27] = true, -- Magic Storm
  [45] = true, -- Raise Golem placement
  [48] = true, -- Teleport destination
  [49] = true, -- Magic Circle
  [50] = true, -- Magic Trap
  [72] = true, -- Acid Rain
  [73] = true, -- Fire Wall
  [74] = true, -- Ether Drain
  [76] = true, -- Call Comet
  [77] = true, -- Turn Undead area
}

local FREE_AIM_BUILD_IDS = {
  [16] = true,
  [40] = true,
  [1006] = true,
  [1007] = true,
  [1008] = true,
  [1009] = true,
}

local function finite_number(value)
  return type(value) == "number" and value == value and
    value > -math.huge and value < math.huge
end

local function number(value, fallback)
  local result = tonumber(value)
  if not finite_number(result) then
    return fallback or 0.0
  end
  return result
end

local function element_band(entry_id)
  for _, band in ipairs(ELEMENT_BANDS) do
    if entry_id >= band.first and entry_id <= band.last then
      return band
    end
  end
  return nil
end

local function element_flags()
  return {
    fire = false,
    water = false,
    earth = false,
    air = false,
    ether = false,
  }
end

local function mark_element(flags, entry_id)
  local band = element_band(entry_id)
  if band ~= nil then
    flags[band.name] = true
  end
end

local function owned_progression(participant)
  local owned = type(participant) == "table" and
    participant.owned_progression or nil
  return type(owned) == "table" and owned or {}
end

local function find_skill_choices(participant_id)
  local ok, choices = pcall(
    sd.bots.get_skill_choices,
    participant_id)
  if ok and type(choices) == "table" then
    return choices
  end
  return {}
end

local function read_loadout_details(participant_id)
  local ok, details = pcall(
    sd.bots.get_loadout_details,
    participant_id)
  if ok and type(details) == "table" then
    return details
  end
  return {}
end

local function list_custom_spells()
  if type(sd.spells) ~= "table" or
      type(sd.spells.list) ~= "function" then
    return {}
  end
  local ok, spells = pcall(sd.spells.list)
  if ok and type(spells) == "table" then
    return spells
  end
  return {}
end

local function custom_config(row)
  if type(row) ~= "table" or type(row.cfg) ~= "table" then
    return nil
  end
  return row.cfg
end

local function range_relation(
    minimum,
    maximum,
    resolved,
    bot_x,
    bot_y,
    target)
  if type(target) ~= "table" then
    return false, 0.0
  end
  local dx = number(target.x) - number(bot_x)
  local dy = number(target.y) - number(bot_y)
  local center_distance = math.sqrt(dx * dx + dy * dy)
  local contact_distance =
    math.max(center_distance - math.max(number(target.radius), 0.0), 0.0)
  if resolved ~= true then
    return false, contact_distance
  end
  return contact_distance >= math.max(number(minimum), 0.0) and
    contact_distance <= math.max(number(maximum), 0.0),
    contact_distance
end

function Resolver:refresh_custom_spells()
  local by_id = {}
  for _, row in ipairs(self.list_spells()) do
    local id = number(row.id, -1)
    if id > 0 then
      by_id[id] = row
    end
  end
  self.custom_by_id = by_id
end

local function active_skill_summary(owned)
  local learned_primaries = {}
  local learned_primary_count = 0
  local has_welding = false
  for _, entry in ipairs(owned.progression_book_entries or {}) do
    local entry_id = number(entry.entry_index, -1)
    if number(entry.active) > 0 then
      if BASE_PRIMARY_IDS[entry_id] == true and
          learned_primaries[entry_id] ~= true then
        learned_primaries[entry_id] = true
        learned_primary_count = learned_primary_count + 1
      end
      if entry_id == 52 then
        has_welding = true
      end
    end
  end
  return learned_primaries, learned_primary_count, has_welding
end

local function loadout_entry(loadout, slot)
  local entries = type(loadout.secondary_entry_indices) == "table" and
    loadout.secondary_entry_indices or {}
  return number(entries[slot], -1)
end

local function resolve_primary(
    resolver,
    details,
    loadout,
    mana_current)
  local source = type(details.primary) == "table" and
    details.primary or {}
  local entry_id = number(
    source.entry_id,
    number(loadout.primary_entry_index, -1))
  local combo_entry_id = number(
    source.combo_entry_id,
    number(loadout.primary_combo_entry_index, -1))
  local build_id = number(source.build_id, entry_id)
  local build_resolved = source.build_id_resolved == true
  local custom = resolver.custom_by_id[entry_id]
  local cfg = custom_config(custom)
  local welded = build_resolved and WELD_PAIRS[build_id] ~= nil
  local elements = element_flags()
  if welded then
    local pair = WELD_PAIRS[build_id]
    mark_element(elements, pair[1])
    mark_element(elements, pair[2])
  else
    mark_element(elements, entry_id)
  end

  local build_index = 0.0
  if welded then
    build_index = (build_id - 1000) / 10.0
  else
    local band = element_band(entry_id)
    build_index = band ~= nil and band.identity or 0.0
  end

  local mana_cost = number(source.mana_cost)
  local mana_cost_resolved =
    source.mana_cost_resolved == true
  local range_min = number(source.range_min)
  local range_max = number(source.range_max)
  local range_resolved = source.range_resolved == true
  local range_source = tostring(source.range_source or "")
  if cfg ~= nil then
    if finite_number(tonumber(cfg.mana_cost)) then
      mana_cost = math.max(number(cfg.mana_cost), 0.0)
      mana_cost_resolved = true
    end
    if finite_number(tonumber(cfg.range)) then
      range_min = 0.0
      range_max = math.max(number(cfg.range), 0.0)
      range_resolved = true
      range_source = "registered_spell_config"
    end
  end

  return {
    occupied = entry_id >= 0,
    entry_id = entry_id,
    combo_entry_id = combo_entry_id,
    build_id = build_id,
    build_id_resolved = build_resolved,
    welded = welded,
    elements = elements,
    build_index_scaled = build_index,
    mana_cost = mana_cost,
    mana_cost_resolved = mana_cost_resolved,
    mana_charge_kind =
      tostring(source.mana_charge_kind or "none"),
    range_min = range_min,
    range_max = range_max,
    range_resolved = range_resolved,
    range_source = range_source,
    affordable =
      mana_cost_resolved and mana_current >= mana_cost,
    custom = custom ~= nil,
    aim_free =
      custom ~= nil or FREE_AIM_BUILD_IDS[build_id] == true,
  }
end

local function resolve_secondary(
    resolver,
    source,
    fallback_entry_id,
    snapshot,
    mana_current,
    slot)
  source = type(source) == "table" and source or {}
  local entry_id = number(source.entry_id, fallback_entry_id)
  local occupied = entry_id >= 0
  local band = element_band(entry_id)
  local elements = element_flags()
  mark_element(elements, entry_id)
  local custom = resolver.custom_by_id[entry_id]
  local cfg = custom_config(custom)

  local mana_cost = number(source.mana_cost)
  local mana_cost_resolved =
    source.mana_cost_resolved == true
  local range_min = 0.0
  local range_max = 0.0
  local range_resolved = false
  local cooldown_seconds =
    math.max(number(source.cooldown_seconds), 0.0)
  local cooldown_remaining_seconds =
    math.max(
      number(source.cooldown_remaining_seconds),
      0.0)
  local cooldown_resolved =
    source.cooldown_resolved == true
  if cfg ~= nil then
    if finite_number(tonumber(cfg.mana_cost)) then
      mana_cost = math.max(number(cfg.mana_cost), 0.0)
      mana_cost_resolved = true
    end
    if finite_number(tonumber(cfg.range)) then
      range_max = math.max(number(cfg.range), 0.0)
      range_resolved = true
    end
    if finite_number(tonumber(cfg.cooldown_ms)) then
      cooldown_seconds =
        math.max(number(cfg.cooldown_ms), 0.0) / 1000.0
      -- The custom-spell config supplies the static cooldown period, not
      -- per-slot live recharge state. Preserve the native resolved flag and
      -- fall back to the replicated global cast-ready bit when it is false.
    end
  end

  local ready
  if not occupied then
    ready = false
  elseif cooldown_resolved then
    ready = cooldown_remaining_seconds <= 0.000001
  else
    ready = snapshot.cast_ready == true
  end

  return {
    slot = slot,
    occupied = occupied,
    entry_id = entry_id,
    elements = elements,
    band_index_scaled =
      band ~= nil and (entry_id - band.first) / 8.0 or 0.0,
    mana_cost = mana_cost,
    mana_cost_resolved = mana_cost_resolved,
    range_min = range_min,
    range_max = range_max,
    range_resolved = range_resolved,
    cooldown_seconds = cooldown_seconds,
    cooldown_remaining_seconds =
      cooldown_remaining_seconds,
    cooldown_resolved = cooldown_resolved,
    ready = ready,
    affordable =
      occupied and mana_cost_resolved and
      mana_current >= mana_cost,
    custom = custom ~= nil,
    aim_free =
      custom ~= nil or FREE_AIM_ENTRY_IDS[entry_id] == true,
  }
end

function Resolver:capture(
    participant_id,
    snapshot,
    participant,
    skill_choices)
  snapshot = type(snapshot) == "table" and snapshot or {}
  participant = type(participant) == "table" and participant or {}
  local owned = owned_progression(participant)
  local loadout = type(owned.ability_loadout) == "table" and
    owned.ability_loadout or {}
  local details = self.read_details(participant_id)
  details = type(details) == "table" and details or {}
  skill_choices = type(skill_choices) == "table" and
    skill_choices or self.read_choices(participant_id)
  local mana_current = number(
    snapshot.mp,
    number(participant.mana_current))
  local learned_primaries, learned_primary_count,
    has_welding = active_skill_summary(owned)

  local primary =
    resolve_primary(self, details, loadout, mana_current)
  local secondaries = {}
  local source_secondaries =
    type(details.secondaries) == "table" and
      details.secondaries or {}
  for slot = 1, self.spec.secondary_slot_count do
    secondaries[slot] = resolve_secondary(
      self,
      source_secondaries[slot],
      loadout_entry(loadout, slot),
      snapshot,
      mana_current,
      slot)
  end

  local weld_offer_pending = false
  if skill_choices.pending == true then
    for _, option in ipairs(skill_choices.options or {}) do
      if number(option.id, -1) == 52 then
        weld_offer_pending = true
        break
      end
    end
  end

  local derived = type(owned.derived_stats) == "table" and
    owned.derived_stats or {}
  return {
    details = details,
    owned = owned,
    primary = primary,
    secondaries = secondaries,
    skill_choices = skill_choices,
    has_spell_welding_skill = has_welding,
    weld_offer_pending = weld_offer_pending,
    pending_weld_build_id =
      number(details.pending_weld_build_id),
    pending_weld_build_id_resolved =
      details.pending_weld_build_id_resolved == true,
    learned_primaries = learned_primaries,
    learned_primary_count = learned_primary_count,
    pickup_range = math.max(number(derived.pickup_range), 0.0),
    offensive_damage_multiplier =
      number(derived.offensive_damage_multiplier, 1.0),
    offensive_mana_multiplier =
      number(derived.offensive_mana_multiplier, 1.0),
    cast_speed_multiplier =
      number(derived.cast_speed_multiplier, 1.0),
    secondary_recharge_multiplier =
      number(derived.secondary_recharge_multiplier, 1.0),
    mana_current = mana_current,
  }
end

function Resolver:weld_components(build_id)
  return WELD_PAIRS[number(build_id)]
end

function Resolver:is_base_primary(entry_id)
  return BASE_PRIMARY_IDS[number(entry_id)] == true
end

function Resolver:aim_is_free(spell)
  return type(spell) == "table" and spell.aim_free == true
end

function Resolver:primary_in_range(
    primary,
    bot_x,
    bot_y,
    target)
  return range_relation(
    primary.range_min,
    primary.range_max,
    primary.range_resolved,
    bot_x,
    bot_y,
    target)
end

function Resolver:secondary_in_range(
    secondary,
    bot_x,
    bot_y,
    target)
  return range_relation(
    secondary.range_min,
    secondary.range_max,
    secondary.range_resolved,
    bot_x,
    bot_y,
    target)
end

function descriptors.primary_in_range(
    primary,
    bot_x,
    bot_y,
    target)
  return range_relation(
    primary.range_min,
    primary.range_max,
    primary.range_resolved,
    bot_x,
    bot_y,
    target)
end

function descriptors.secondary_in_range(
    secondary,
    bot_x,
    bot_y,
    target)
  return range_relation(
    secondary.range_min,
    secondary.range_max,
    secondary.range_resolved,
    bot_x,
    bot_y,
    target)
end

function descriptors.weld_components(build_id)
  return WELD_PAIRS[number(build_id)]
end

function descriptors.is_base_primary(entry_id)
  return BASE_PRIMARY_IDS[number(entry_id)] == true
end

function descriptors.new(spec, api)
  api = type(api) == "table" and api or {}
  local resolver = setmetatable({
    spec = assert(spec),
    read_details = api.read_details or read_loadout_details,
    read_choices = api.read_choices or find_skill_choices,
    list_spells = api.list_spells or list_custom_spells,
    custom_by_id = {},
  }, Resolver)
  resolver:refresh_custom_spells()
  return resolver
end

return descriptors
