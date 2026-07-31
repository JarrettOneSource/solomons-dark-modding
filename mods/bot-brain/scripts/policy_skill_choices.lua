local choices = {}
local Manager = {}
Manager.__index = Manager

local ELEMENT_BANDS = {
  {name = "ether", first = 8, last = 15},
  {name = "fire", first = 16, last = 23},
  {name = "air", first = 24, last = 31},
  {name = "water", first = 32, last = 39},
  {name = "earth", first = 40, last = 47},
}

local FAMILY_NAMES = {
  "element",
  "discipline",
  "ether",
  "fire",
  "air",
  "water",
  "earth",
  "arcane",
  "mind",
  "body",
  "advanced",
  "runtime_only",
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

local function scaled(value, divisor)
  return clamp(number(value) / divisor, -1.0, 1.0)
end

local function boolean(value)
  return value == true and 1.0 or 0.0
end

local function rank_value(values, rank)
  if type(values) ~= "table" or #values == 0 then
    return 0.0
  end
  local index =
    math.max(1, math.min(math.floor(number(rank)) + 1, #values))
  return number(values[index])
end

local function progression_rows(owned)
  local by_id = {}
  for _, row in ipairs(
      type(owned) == "table" and
        owned.progression_book_entries or {}) do
    local entry_id = math.floor(number(row.entry_index, -1))
    if entry_id >= 0 then
      by_id[entry_id] = row
    end
  end
  return by_id
end

local function element_band(entry_id)
  for _, band in ipairs(ELEMENT_BANDS) do
    if entry_id >= band.first and entry_id <= band.last then
      return band
    end
  end
  return nil
end

local function live_mechanics(loadout, entry_id)
  if type(loadout) ~= "table" then
    return nil
  end
  local primary = loadout.primary
  if type(primary) == "table" and
      number(primary.entry_id, -1) == entry_id then
    return primary
  end
  for _, secondary in ipairs(loadout.secondaries or {}) do
    if number(secondary.entry_id, -1) == entry_id then
      return secondary
    end
  end
  return nil
end

local function push(row, spec, name, value)
  local index = #row + 1
  if spec.option_descriptor_names[index] ~= name then
    error(
      "choice descriptor order mismatch at " ..
      tostring(index) .. ": expected " ..
      tostring(spec.option_descriptor_names[index]) ..
      ", got " .. tostring(name))
  end
  value = number(value)
  if not finite_number(value) then
    error("choice descriptor " .. name .. " is not finite")
  end
  row[index] = value
end

local function option_descriptor(
    manager,
    option,
    progression,
    loadout)
  local spec = manager.spec
  local entry_id = math.floor(number(option.id, -1))
  local catalog = manager.catalog[entry_id]
  local known = type(catalog) == "table"
  catalog = known and catalog or {
    family = "",
    cap_rank = 0,
    max_rank = 0,
  }
  local progression_row = progression[entry_id] or {}
  local learned_rank = math.max(number(progression_row.active), 0.0)
  local effective_rank = math.max(
    number(
      progression_row.statbook_max_level,
      learned_rank),
    0.0)
  local band = element_band(entry_id)
  local live = live_mechanics(loadout, entry_id)

  local mana_cost =
    rank_value(catalog.mana_cost, effective_rank)
  local mana_present = catalog.mana_cost_present == true
  local range =
    rank_value(catalog.range, effective_rank)
  local range_present = catalog.range_present == true
  local cooldown =
    rank_value(catalog.cooldown, effective_rank)
  local cooldown_present = catalog.cooldown_present == true
  if type(live) == "table" then
    if live.mana_cost_resolved == true then
      mana_cost = number(live.mana_cost)
      mana_present = true
    end
    if live.range_resolved == true then
      range = number(live.range_max)
      range_present = true
    end
    if live.cooldown_resolved == true or
        number(live.cooldown_seconds) > 0.0 then
      cooldown = number(live.cooldown_seconds)
      cooldown_present = true
    end
  end

  local weld_elements = {}
  local weld_build_index = 0.0
  if entry_id == 52 and
      loadout.pending_weld_build_id_resolved == true then
    local build_id =
      math.floor(number(loadout.pending_weld_build_id))
    local components =
      manager.spell_descriptors:weld_components(build_id)
    if type(components) == "table" then
      for _, component in ipairs(components) do
        local component_band = element_band(component)
        if component_band ~= nil then
          weld_elements[component_band.name] = true
        end
      end
      weld_build_index =
        clamp((build_id - 1000) / 10.0, 0.0, 1.0)
    end
  end

  local row = {}
  push(row, spec, "present", 1.0)
  push(
    row,
    spec,
    "option_id_index_scaled",
    scaled(entry_id, spec.skill_id_scale))
  push(row, spec, "catalog_known", boolean(known))
  push(
    row,
    spec,
    "apply_count_scaled",
    scaled(option.apply_count, spec.skill_rank_scale))
  push(
    row,
    spec,
    "learned_rank_scaled",
    scaled(learned_rank, spec.skill_rank_scale))
  push(
    row,
    spec,
    "effective_rank_scaled",
    scaled(effective_rank, spec.skill_rank_scale))
  push(
    row,
    spec,
    "cap_rank_scaled",
    scaled(catalog.cap_rank, spec.skill_rank_scale))
  push(
    row,
    spec,
    "max_rank_scaled",
    scaled(catalog.max_rank, spec.skill_rank_scale))
  push(
    row,
    spec,
    "band_index_scaled",
    band ~= nil and
      (entry_id - band.first) / spec.skill_band_scale or 0.0)

  for _, family in ipairs(FAMILY_NAMES) do
    push(
      row,
      spec,
      "family_" .. family,
      boolean(catalog.family == family))
  end
  push(row, spec, "is_primary", boolean(catalog.is_primary))
  push(row, spec, "is_secondary", boolean(catalog.is_secondary))
  push(row, spec, "is_passive", boolean(catalog.is_passive))
  push(row, spec, "is_utility", boolean(catalog.is_utility))
  push(row, spec, "is_weld", boolean(entry_id == 52))
  push(row, spec, "is_health_up", boolean(entry_id == 64))
  push(row, spec, "is_mana_up", boolean(entry_id == 56))

  for _, element in ipairs({
    "ether",
    "fire",
    "air",
    "water",
    "earth",
  }) do
    push(
      row,
      spec,
      "weld_element_" .. element,
      boolean(weld_elements[element]))
  end
  push(
    row,
    spec,
    "weld_build_index_scaled",
    weld_build_index)

  push(
    row,
    spec,
    "mana_cost_scaled",
    scaled(mana_cost, spec.mana_scale))
  push(
    row,
    spec,
    "damage_min_scaled",
    scaled(
      rank_value(catalog.damage_min, effective_rank),
      spec.skill_damage_scale))
  push(
    row,
    spec,
    "damage_max_scaled",
    scaled(
      rank_value(catalog.damage_max, effective_rank),
      spec.skill_damage_scale))
  push(
    row,
    spec,
    "range_scaled",
    scaled(range, spec.range_scale))
  push(
    row,
    spec,
    "cooldown_scaled",
    scaled(cooldown, spec.cooldown_scale))
  push(
    row,
    spec,
    "radius_scaled",
    scaled(
      rank_value(catalog.radius, effective_rank),
      spec.skill_radius_scale))
  push(
    row,
    spec,
    "duration_scaled",
    scaled(
      rank_value(catalog.duration, effective_rank),
      spec.skill_duration_scale))
  push(
    row,
    spec,
    "value_scaled",
    scaled(
      rank_value(catalog.value, effective_rank),
      spec.skill_value_scale))
  push(
    row,
    spec,
    "concentration_scaled",
    scaled(
      rank_value(catalog.concentration, effective_rank),
      spec.skill_concentration_scale))
  push(
    row,
    spec,
    "chance_scaled",
    scaled(
      rank_value(catalog.chance, effective_rank),
      spec.skill_chance_scale))
  push(
    row,
    spec,
    "quantity_or_strength_scaled",
    scaled(
      rank_value(
        catalog.quantity_or_strength,
        effective_rank),
      spec.skill_quantity_or_strength_scale))

  for _, item in ipairs({
    {"mana_cost_present", mana_present},
    {"damage_min_present", catalog.damage_min_present},
    {"damage_max_present", catalog.damage_max_present},
    {"range_present", range_present},
    {"cooldown_present", cooldown_present},
    {"radius_present", catalog.radius_present},
    {"duration_present", catalog.duration_present},
    {"value_present", catalog.value_present},
    {"concentration_present", catalog.concentration_present},
    {"chance_present", catalog.chance_present},
    {
      "quantity_or_strength_present",
      catalog.quantity_or_strength_present,
    },
  }) do
    push(row, spec, item[1], boolean(item[2]))
  end
  if #row ~= #spec.option_descriptor_names then
    error("choice option descriptor has the wrong size")
  end
  return row
end

function Manager:capture(
    participant,
    observation,
    loadout,
    skill_choices,
    simulation_tick,
    metrics)
  skill_choices =
    type(skill_choices) == "table" and skill_choices or {}
  if skill_choices.pending ~= true or
      type(skill_choices.options) ~= "table" or
      #skill_choices.options == 0 then
    return nil
  end
  if #skill_choices.options > self.spec.max_choice_options then
    error("native skill choice exceeded the v3 option bound")
  end
  local owned =
    type(participant) == "table" and
      participant.owned_progression or {}
  local progression = progression_rows(owned)
  local option_rows = {}
  local option_mask = {}
  for index, option in ipairs(skill_choices.options) do
    option_rows[index] = option_descriptor(
      self,
      option,
      progression,
      loadout)
    option_mask[index] = true
  end
  return {
    generation = math.floor(number(skill_choices.generation)),
    simulation_tick = math.floor(number(simulation_tick)),
    observation = observation,
    option_descriptors = option_rows,
    option_mask = option_mask,
    options = skill_choices.options,
    metrics = metrics,
  }
end

function Manager:handle(
    context,
    event,
    mode,
    runtime,
    training,
    scripted_selector,
    stochastic)
  if event == nil or
      event.generation ==
        context.last_skill_choice_generation then
    return false
  end
  if self.spec.skill_choice_modes[mode] ~= true then
    error("invalid policy skill_choice_mode " .. tostring(mode))
  end

  local decision
  if mode == "learned" then
    if type(runtime) ~= "table" or
        type(runtime.forward_choice) ~= "function" then
      error(
        "learned skill choices require the strict v3 choice runtime")
    end
    decision = runtime:forward_choice(
      event.observation,
      event.option_descriptors,
      event.option_mask,
      stochastic == true)
  else
    local selected_index = scripted_selector(event.options)
    if type(selected_index) ~= "number" then
      error("scripted skill choice returned no legal option")
    end
    decision = {
      choice_action = selected_index - 1,
      log_probability = 0.0,
      value = 0.0,
      choice_probability = 1.0,
    }
  end

  local selected_index =
    math.floor(number(decision.choice_action, -1)) + 1
  if event.option_mask[selected_index] ~= true then
    error("skill choice policy selected a masked option")
  end

  -- Latch before invoking native apply so a rejected request cannot resample
  -- the same generation on a later manager tick.
  context.last_skill_choice_generation = event.generation
  local apply_ok, accepted, error_message = pcall(
    self.choose_skill,
    {
      id = context.participant_id,
      generation = event.generation,
      option_index = selected_index,
    })
  local applied = apply_ok and accepted == true
  training:record_choice(
    context,
    event,
    decision,
    mode,
    applied)

  context.debug.skill_choice_mode = mode
  context.debug.skill_choice_generation = event.generation
  context.debug.skill_choice_option_index = selected_index
  context.debug.skill_choice_option_id =
    number(event.options[selected_index].id, -1)
  context.debug.skill_choice_probability =
    number(decision.choice_probability)
  if applied then
    context.debug.skill_choices_accepted =
      context.debug.skill_choices_accepted + 1
    context.debug.last_error = ""
    return true
  end
  context.debug.last_error = tostring(
    apply_ok and error_message or accepted or
      "skill choice rejected")
  return false
end

function choices.new(spec, catalog, spell_descriptors, api)
  api = type(api) == "table" and api or {}
  local choose_skill =
    api.choose_skill or function(request)
      return sd.bots.choose_skill(request)
    end
  return setmetatable({
    spec = assert(spec),
    catalog = assert(catalog),
    spell_descriptors = assert(spell_descriptors),
    choose_skill = choose_skill,
  }, Manager)
end

return choices
