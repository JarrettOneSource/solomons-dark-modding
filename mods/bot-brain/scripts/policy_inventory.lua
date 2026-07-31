local inventory = {}
local Resolver = {}
Resolver.__index = Resolver

local EQUIPMENT_SLOTS = {
  "hat",
  "robe",
  "weapon",
  "ring_1",
  "ring_2",
  "ring_3",
  "amulet",
}

local SUMMARY_FIELDS = {
  "item_total_count",
  "potion_count",
  "equipment_count",
  "sack_count",
  "misc_count",
  "perk_count",
  "map_count",
  "registered_custom_count",
  "unknown_count",
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

local function clamp(value, minimum, maximum)
  return math.max(minimum, math.min(maximum, value))
end

local function default_read(participant_id)
  local ok, details = pcall(
    sd.bots.get_inventory_details,
    participant_id)
  if ok and type(details) == "table" then
    return details
  end
  return {}
end

local function count_scaled(value, saturation)
  local count = clamp(number(value), 0.0, saturation)
  return math.log(1.0 + count) /
    math.log(1.0 + saturation)
end

local function identity_hashes(value)
  value = tostring(value or "")
  if value == "" then
    return 0.0, 0.0
  end
  local first = 216613
  local second = 104729
  for index = 1, #value do
    local byte = string.byte(value, index)
    first = (first * 167 + byte + index) % 1000003
    second = (second * 257 + byte * 3 + index) % 1000033
  end
  return first / 1000003, second / 1000033
end

local function resource_ratio(current, maximum)
  maximum = number(maximum)
  if maximum <= 0.0 then
    return 0.0
  end
  return clamp(number(current) / maximum, 0.0, 1.0)
end

local function potion_can_change(
    potion,
    details,
    snapshot)
  if potion.synthetic_use_supported ~= true or
      potion.effect_resolved ~= true or
      number(potion.count) <= 0.0 then
    return false
  end

  local subtype = math.floor(number(potion.stock_subtype, -1))
  -- V3-2 proved no participant-scoped native route for these stock
  -- subtypes. They are permanently observed but never actionable.
  if subtype == 2 or subtype == 3 or subtype == 4 then
    return false
  end

  local hp_ratio = resource_ratio(
    snapshot.hp,
    snapshot.max_hp)
  local mana_ratio = resource_ratio(
    snapshot.mp,
    snapshot.max_mp)
  if subtype == 0 then
    return hp_ratio < 0.999999
  end
  if subtype == 1 then
    return mana_ratio < 0.999999
  end
  if subtype == 5 then
    return hp_ratio < 0.999999 or
      mana_ratio < 0.999999
  end

  -- Custom rows are actionable only through the native seam's declared
  -- synthetic-safe policy_effects contract.
  if potion.custom ~= true then
    return false
  end
  if number(potion.restores_hp_fraction) > 0.0 and
      hp_ratio < 0.999999 then
    return true
  end
  if number(potion.restores_mana_fraction) > 0.0 and
      mana_ratio < 0.999999 then
    return true
  end
  local duration =
    math.max(number(potion.effect_duration_seconds), 0.0)
  if number(potion.damage_multiplier, 1.0) > 1.0 and
      number(details.damage_x4_remaining_seconds) <
        duration then
    return true
  end
  local immunity = math.max(
    number(potion.poison_immunity_duration_seconds),
    0.0)
  if potion.cures_poison == true and
      (number(snapshot.native_poison_remaining_ticks) > 0.0 or
       number(snapshot.replicated_poison_remaining_ticks) > 0.0) then
    return true
  end
  if immunity > 0.0 and
      number(details.poison_immunity_remaining_seconds) <
        immunity then
    return true
  end
  if potion.concentrates_all == true and
      number(details.all_concentration_remaining_seconds) <
        duration then
    return true
  end
  return false
end

local function potion_row(potion, spec)
  local hash_a, hash_b =
    identity_hashes(potion.identity_key)
  local subtype = math.floor(number(potion.stock_subtype, -1))
  return {
    present = number(potion.count) > 0.0,
    count_scaled = count_scaled(
      potion.count,
      spec.inventory_count_saturation),
    stock_health = subtype == 0,
    stock_mana = subtype == 1,
    stock_wizard_chug = subtype == 2,
    stock_antidote = subtype == 3,
    stock_mind_chug = subtype == 4,
    stock_rejuvenation = subtype == 5,
    custom = potion.custom == true,
    restores_hp_fraction =
      clamp(number(potion.restores_hp_fraction), 0.0, 1.0),
    restores_mana_fraction =
      clamp(number(potion.restores_mana_fraction), 0.0, 1.0),
    damage_multiplier_scaled =
      clamp(
        number(potion.damage_multiplier, 1.0) /
          spec.multiplier_scale,
        0.0,
        1.0),
    cures_poison = potion.cures_poison == true,
    poison_immunity_duration_scaled =
      clamp(
        number(potion.poison_immunity_duration_seconds) /
          spec.status_duration_scale_seconds,
        0.0,
        1.0),
    concentrates_all = potion.concentrates_all == true,
    effect_duration_scaled =
      clamp(
        number(potion.effect_duration_seconds) /
          spec.status_duration_scale_seconds,
        0.0,
        1.0),
    custom_effect_known =
      potion.custom == true and
      potion.effect_resolved == true,
    identity_hash_a = hash_a,
    identity_hash_b = hash_b,
    source = potion,
  }
end

local function equipment_row(source, spec)
  source = type(source) == "table" and source or {}
  local hash_a, hash_b =
    identity_hashes(source.identity_key)
  return {
    present = source.present == true,
    catalog_known = source.catalog_resolved == true,
    identity_hash_a = hash_a,
    identity_hash_b = hash_b,
    rarity_scaled = clamp(
      number(source.rarity_id) /
        spec.equipment_rarity_scale,
      0.0,
      1.0),
    level_scaled = clamp(
      number(source.level) / spec.level_scale,
      0.0,
      1.0),
    set_complete = source.set_complete == true,
    offense_effect_scaled = clamp(
      number(source.offense_effect) /
        spec.equipment_effect_scale,
      -1.0,
      1.0),
    resource_effect_scaled = clamp(
      number(source.resource_effect) /
        spec.equipment_effect_scale,
      -1.0,
      1.0),
    mobility_effect_scaled = clamp(
      number(source.mobility_effect) /
        spec.equipment_effect_scale,
      -1.0,
      1.0),
    defense_effect_scaled = clamp(
      number(source.defense_effect) /
        spec.equipment_effect_scale,
      -1.0,
      1.0),
    targeted_effect_present =
      source.targeted_effect_present == true,
    target_kind_scaled = clamp(
      number(source.target_kind) /
        spec.equipment_target_kind_scale,
      0.0,
      1.0),
    target_magnitude_scaled = clamp(
      number(source.target_magnitude) /
        spec.equipment_effect_scale,
      -1.0,
      1.0),
    special_feature_present =
      source.special_feature_present == true,
    source = source,
  }
end

function Resolver:capture(participant_id, snapshot)
  snapshot = type(snapshot) == "table" and snapshot or {}
  local details = self.read(participant_id)
  details = type(details) == "table" and details or {}

  local source_potions = {}
  for index, potion in ipairs(details.potions or {}) do
    source_potions[index] = potion
  end
  table.sort(source_potions, function(left, right)
    local left_count = number(left.count)
    local right_count = number(right.count)
    if left_count ~= right_count then
      return left_count > right_count
    end
    return tostring(left.identity_key or "") <
      tostring(right.identity_key or "")
  end)

  local potion_rows = {}
  local potion_legal = {}
  local potion_total = 0.0
  for index, potion in ipairs(source_potions) do
    potion_total = potion_total +
      math.max(number(potion.count), 0.0)
    if index <= self.spec.potion_slot_count then
      potion_rows[index] =
        potion_row(potion, self.spec)
      potion_legal[index] =
        potion_can_change(potion, details, snapshot)
    end
  end

  local equipped_by_slot = {}
  for _, row in ipairs(details.equipped or {}) do
    equipped_by_slot[tostring(row.slot or "")] = row
  end
  local equipment_rows = {}
  for _, slot in ipairs(EQUIPMENT_SLOTS) do
    equipment_rows[slot] =
      equipment_row(equipped_by_slot[slot], self.spec)
  end

  local summary = {}
  local source_summary =
    type(details.summary) == "table" and
      details.summary or {}
  for _, field in ipairs(SUMMARY_FIELDS) do
    summary[field] = count_scaled(
      source_summary[field],
      self.spec.inventory_count_saturation)
  end

  return {
    details = details,
    potion_rows = potion_rows,
    potion_legal = potion_legal,
    potion_type_count_scaled = count_scaled(
      #source_potions,
      self.spec.inventory_count_saturation),
    potion_total_count_scaled = count_scaled(
      potion_total,
      self.spec.inventory_count_saturation),
    equipment_rows = equipment_rows,
    summary = summary,
    damage_x4_remaining_scaled = clamp(
      number(details.damage_x4_remaining_seconds) /
        self.spec.status_duration_scale_seconds,
      0.0,
      1.0),
    poison_immunity_remaining_scaled = clamp(
      number(details.poison_immunity_remaining_seconds) /
        self.spec.status_duration_scale_seconds,
      0.0,
      1.0),
    all_concentration_remaining_scaled = clamp(
      number(details.all_concentration_remaining_seconds) /
        self.spec.status_duration_scale_seconds,
      0.0,
      1.0),
  }
end

function Resolver:use(participant_id, capture, potion_slot)
  potion_slot = math.floor(number(potion_slot))
  if capture.potion_legal[potion_slot] ~= true then
    return false, "policy selected an illegal potion action"
  end
  return self.use_consumable(
    participant_id,
    {
      potion_slot = potion_slot,
      inventory_revision =
        capture.details.inventory_revision,
    })
end

function inventory.new(spec, api)
  api = type(api) == "table" and api or {}
  local use_consumable =
    api.use_consumable or function(participant_id, selector)
      return sd.bots.use_consumable(participant_id, selector)
    end
  return setmetatable({
    spec = assert(spec),
    read = api.read or default_read,
    use_consumable = use_consumable,
  }, Resolver)
end

inventory.count_scaled = count_scaled
inventory.identity_hashes = identity_hashes
inventory.equipment_slots = EQUIPMENT_SLOTS
inventory.summary_fields = SUMMARY_FIELDS

return inventory
