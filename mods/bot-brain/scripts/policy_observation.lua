local observation = {}

local POTION_TYPE_ID = 0x1B59

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

local function ratio(value, maximum)
  maximum = number(maximum)
  if maximum <= 0.0 then
    return 0.0
  end
  return clamp(number(value) / maximum, 0.0, 1.0)
end

local function normalize(x, y)
  x = number(x)
  y = number(y)
  local length = math.sqrt(x * x + y * y)
  if length <= 0.000001 then
    return 0.0, 0.0, 0.0
  end
  return x / length, y / length, length
end

local function item_equipped(item)
  return type(item) == "table" and
    number(item.type_id) > 0
end

local function find_participant(participant_id)
  local ok, multiplayer = pcall(
    sd.runtime.get_multiplayer_state)
  if not ok or type(multiplayer) ~= "table" then
    return nil
  end
  for _, participant in ipairs(multiplayer.participants or {}) do
    if number(participant.participant_id) == participant_id then
      return participant
    end
  end
  return nil
end

local function nearest_enemy(
    bot_x,
    bot_y,
    enemies,
    maximum_distance)
  local nearest = nil
  local nearest_distance = math.huge
  for _, enemy in ipairs(enemies or {}) do
    local dx = number(enemy.x) - bot_x
    local dy = number(enemy.y) - bot_y
    local distance = math.sqrt(dx * dx + dy * dy)
    if distance < nearest_distance and
        (maximum_distance == nil or
         distance <= maximum_distance) then
      nearest = enemy
      nearest_distance = distance
    end
  end
  return nearest, nearest_distance
end

local function progression_summary(participant)
  local owned =
    type(participant) == "table" and
    participant.owned_progression or nil
  if type(owned) ~= "table" then
    owned = {}
  end
  local items = type(owned.inventory_items) == "table" and
    owned.inventory_items or {}
  local inventory_stack_count = 0
  local potion_stack_count = 0
  for _, item in ipairs(items) do
    local stack_count = math.max(number(item.stack_count, 1), 0)
    inventory_stack_count =
      inventory_stack_count + stack_count
    if number(item.type_id) == POTION_TYPE_ID then
      potion_stack_count =
        potion_stack_count + stack_count
    end
  end

  local equipment = owned.equipment
  if type(equipment) ~= "table" and
      type(participant) == "table" then
    equipment = participant.equipment
  end
  if type(equipment) ~= "table" then
    equipment = {}
  end
  local ring_count = 0
  for _, ring in ipairs(equipment.rings or {}) do
    if item_equipped(ring) then
      ring_count = ring_count + 1
    end
  end

  local progression_entries =
    type(owned.progression_book_entries) == "table" and
    owned.progression_book_entries or {}
  local active_count = 0
  local visible_count = 0
  for _, entry in ipairs(progression_entries) do
    if number(entry.active) > 0 then
      active_count = active_count + 1
    end
    if number(entry.visible) > 0 then
      visible_count = visible_count + 1
    end
  end

  local loadout = type(owned.ability_loadout) == "table" and
    owned.ability_loadout or {}
  local secondary_available = {}
  local secondary_count = 0
  for slot = 1, 8 do
    local entry_index = number(
      type(loadout.secondary_entry_indices) == "table" and
        loadout.secondary_entry_indices[slot],
      -1)
    secondary_available[slot] = entry_index >= 0
    if secondary_available[slot] then
      secondary_count = secondary_count + 1
    end
  end
  local derived = type(owned.derived_stats) == "table" and
    owned.derived_stats or {}
  return {
    owned = owned,
    inventory_distinct_count = #items,
    inventory_stack_count = inventory_stack_count,
    potion_stack_count = potion_stack_count,
    equipment_valid = equipment.valid == true,
    hat_equipped = item_equipped(equipment.hat),
    robe_equipped = item_equipped(equipment.robe),
    weapon_equipped = item_equipped(equipment.weapon),
    ring_count = ring_count,
    amulet_equipped = item_equipped(equipment.amulet),
    gold = number(owned.gold),
    progression_active_count = active_count,
    progression_visible_count = visible_count,
    secondary_available = secondary_available,
    secondary_count = secondary_count,
    inventory_truncated = owned.inventory_truncated == true,
    progression_truncated =
      owned.progression_book_truncated == true,
    offensive_damage_multiplier =
      number(derived.offensive_damage_multiplier, 1.0),
    offensive_mana_multiplier =
      number(derived.offensive_mana_multiplier, 1.0),
    cast_speed_multiplier =
      number(derived.cast_speed_multiplier, 1.0),
    secondary_recharge_multiplier =
      number(derived.secondary_recharge_multiplier, 1.0),
  }
end

local function build_movement_mask(
    spec,
    bot_x,
    bot_y,
    lookahead)
  local mask = {}
  local targets = {}
  for index, action in ipairs(spec.movement_actions) do
    if index == 1 then
      mask[index] = true
      targets[index] = { x = bot_x, y = bot_y }
    else
      local target_x = bot_x + action.x * lookahead
      local target_y = bot_y + action.y * lookahead
      local ok, traversable = pcall(
        sd.nav.test_segment,
        bot_x,
        bot_y,
        target_x,
        target_y)
      mask[index] = ok and traversable == true
      targets[index] = { x = target_x, y = target_y }
    end
  end
  return mask, targets
end

local function build_cast_mask(
    spec,
    frame,
    snapshot,
    progression)
  local mask = {}
  for index = 1, #spec.cast_actions do
    mask[index] = false
  end
  mask[1] = true
  local can_cast =
    frame.offense_enabled == true and
    type(frame.target) == "table" and
    frame.target_in_primary_range == true and
    type(snapshot) == "table" and
    snapshot.cast_ready == true and
    snapshot.cast_active ~= true and
    snapshot.cast_pending ~= true
  if not can_cast then
    return mask
  end
  mask[2] = frame.primary_available == true
  for slot = 1, 8 do
    mask[slot + 2] =
      progression.secondary_available[slot] == true
  end
  return mask
end

local function set(values, indexes, name, value)
  values[indexes[name]] = number(value)
end

local function set_boolean(values, indexes, name, value)
  values[indexes[name]] = value == true and 1.0 or 0.0
end

local function elapsed_scaled(now_ms, previous_ms)
  if previous_ms == nil then
    return 1.0
  end
  return clamp((now_ms - previous_ms) / 5000.0, 0.0, 1.0)
end

local function enemy_health(enemies)
  local result = {}
  for _, enemy in ipairs(enemies or {}) do
    local actor_id = number(enemy.network_actor_id)
    if actor_id > 0 then
      result[actor_id] = ratio(enemy.hp, enemy.max_hp)
    end
  end
  return result
end

function observation.new(spec)
  local indexes = {}
  for index, name in ipairs(spec.observation_names) do
    indexes[name] = index
  end
  return {
    spec = spec,
    indexes = indexes,
  }
end

function observation.capture(builder, context, frame)
  local spec = builder.spec
  local indexes = builder.indexes
  local values = {}
  for index = 1, #spec.observation_names do
    values[index] = 0.0
  end

  local snapshot_ok, snapshot = pcall(
    sd.bots.get_participant_state,
    context.participant_id)
  if not snapshot_ok or type(snapshot) ~= "table" then
    snapshot = {}
  end
  local participant = find_participant(context.participant_id)
  local progression = progression_summary(participant)
  local bot_x = number(frame.bot_x)
  local bot_y = number(frame.bot_y)
  local hp_ratio = ratio(frame.hp, frame.max_hp)
  local mana_ratio = ratio(snapshot.mp, snapshot.max_mp)
  local wave_number =
    number(type(frame.wave) == "table" and frame.wave.wave)
  local level =
    number(type(participant) == "table" and participant.level)
  if level <= 0 then
    level = number(snapshot.skill_choice_level)
  end

  set(values, indexes, "self_hp_ratio", hp_ratio)
  set(values, indexes, "self_mana_ratio", mana_ratio)
  set(values, indexes, "self_level_scaled", scaled(level, 20.0))
  set(values, indexes, "wave_scaled", scaled(wave_number, 20.0))
  set(
    values,
    indexes,
    "self_move_speed_scaled",
    scaled(
      type(participant) == "table" and
        participant.move_speed or 0.0,
      500.0))
  set_boolean(values, indexes, "self_moving", snapshot.moving)
  set_boolean(values, indexes, "self_cast_active", snapshot.cast_active)
  set_boolean(values, indexes, "self_cast_ready", snapshot.cast_ready)
  set_boolean(
    values,
    indexes,
    "self_poisoned",
    number(snapshot.native_poison_remaining_ticks) > 0 or
      number(snapshot.replicated_poison_remaining_ticks) > 0)
  set_boolean(
    values,
    indexes,
    "self_webbed",
    number(snapshot.native_webbed_remaining_ticks) > 0)
  set_boolean(
    values,
    indexes,
    "self_damage_x4",
    number(snapshot.native_damage_x4_remaining_ticks) > 0 or
      number(snapshot.replicated_damage_x4_remaining_ticks) > 0)
  set_boolean(
    values,
    indexes,
    "self_status_active",
    number(snapshot.native_persistent_status_flags) ~= 0 or
      number(snapshot.native_transient_status_flags) ~= 0)

  local target = frame.target
  local target_distance = number(frame.target_distance, math.huge)
  local target_radius =
    type(target) == "table" and
    math.max(number(target.radius), 0.0) or 0.0
  local target_dx, target_dy = 0.0, 0.0
  if type(target) == "table" then
    target_dx, target_dy = normalize(
      number(target.x) - bot_x,
      number(target.y) - bot_y)
  end
  set_boolean(
    values,
    indexes,
    "target_present",
    type(target) == "table")
  set(values, indexes, "target_dx", target_dx)
  set(values, indexes, "target_dy", target_dy)
  set(
    values,
    indexes,
    "target_distance_scaled",
    target_distance < math.huge and
      scaled(target_distance, 1000.0) or 0.0)
  set(
    values,
    indexes,
    "target_contact_distance_scaled",
    target_distance < math.huge and
      scaled(
        math.max(target_distance - target_radius, 0.0),
        1000.0) or 0.0)
  set(
    values,
    indexes,
    "target_hp_ratio",
    type(target) == "table" and
      ratio(target.hp, target.max_hp) or 0.0)
  set(
    values,
    indexes,
    "target_radius_scaled",
    scaled(target_radius, 100.0))
  set_boolean(
    values,
    indexes,
    "target_in_primary_range",
    frame.target_in_primary_range)
  set(
    values,
    indexes,
    "primary_min_range_scaled",
    scaled(frame.primary_min_range, 1000.0))
  set(
    values,
    indexes,
    "primary_max_range_scaled",
    scaled(frame.primary_max_range, 1000.0))

  local enemies = frame.enemies or {}
  local nearest, nearest_distance =
    nearest_enemy(bot_x, bot_y, enemies)
  local nearest_threat, nearest_threat_distance =
    nearest_enemy(
      bot_x,
      bot_y,
      enemies,
      number(frame.threat_radius))
  local nearest_dx, nearest_dy = 0.0, 0.0
  if nearest ~= nil then
    nearest_dx, nearest_dy = normalize(
      nearest.x - bot_x,
      nearest.y - bot_y)
  end
  local threat_dx, threat_dy = 0.0, 0.0
  if nearest_threat ~= nil then
    threat_dx, threat_dy = normalize(
      nearest_threat.x - bot_x,
      nearest_threat.y - bot_y)
  end
  set(
    values,
    indexes,
    "enemy_count_scaled",
    scaled(#enemies, 16.0))
  set(
    values,
    indexes,
    "threat_count_scaled",
    scaled(frame.threat_count, 8.0))
  set(values, indexes, "nearest_enemy_dx", nearest_dx)
  set(values, indexes, "nearest_enemy_dy", nearest_dy)
  set(
    values,
    indexes,
    "nearest_enemy_distance_scaled",
    nearest_distance < math.huge and
      scaled(nearest_distance, 1000.0) or 0.0)
  set(values, indexes, "nearest_threat_dx", threat_dx)
  set(values, indexes, "nearest_threat_dy", threat_dy)
  set(
    values,
    indexes,
    "nearest_threat_distance_scaled",
    nearest_threat_distance < math.huge and
      scaled(nearest_threat_distance, 1000.0) or 0.0)
  set(values, indexes, "escape_dx", -threat_dx)
  set(values, indexes, "escape_dy", -threat_dy)
  set(
    values,
    indexes,
    "suggested_move_dx",
    frame.suggested_move_x)
  set(
    values,
    indexes,
    "suggested_move_dy",
    frame.suggested_move_y)

  local arena = frame.arena or {}
  local center_dx, center_dy, center_distance = normalize(
    number(arena.center_x) - bot_x,
    number(arena.center_y) - bot_y)
  set(values, indexes, "arena_center_dx", center_dx)
  set(values, indexes, "arena_center_dy", center_dy)
  set(
    values,
    indexes,
    "arena_center_distance_scaled",
    scaled(center_distance, 1000.0))
  set(
    values,
    indexes,
    "arena_x_normalized",
    clamp(
      (bot_x - number(arena.center_x)) /
        math.max(number(arena.half_width, 1.0), 1.0),
      -1.0,
      1.0))
  set(
    values,
    indexes,
    "arena_y_normalized",
    clamp(
      (bot_y - number(arena.center_y)) /
        math.max(number(arena.half_height, 1.0), 1.0),
      -1.0,
      1.0))
  set(
    values,
    indexes,
    "edge_pressure",
    clamp(number(frame.edge_pressure), 0.0, 1.0))

  set(
    values,
    indexes,
    "inventory_distinct_scaled",
    scaled(progression.inventory_distinct_count, 32.0))
  set(
    values,
    indexes,
    "inventory_stack_scaled",
    scaled(progression.inventory_stack_count, 64.0))
  set(
    values,
    indexes,
    "potion_stack_scaled",
    scaled(progression.potion_stack_count, 16.0))
  set_boolean(
    values,
    indexes,
    "equipment_valid",
    progression.equipment_valid)
  set_boolean(
    values,
    indexes,
    "hat_equipped",
    progression.hat_equipped)
  set_boolean(
    values,
    indexes,
    "robe_equipped",
    progression.robe_equipped)
  set_boolean(
    values,
    indexes,
    "weapon_equipped",
    progression.weapon_equipped)
  set(
    values,
    indexes,
    "ring_count_scaled",
    scaled(progression.ring_count, 3.0))
  set_boolean(
    values,
    indexes,
    "amulet_equipped",
    progression.amulet_equipped)
  set(
    values,
    indexes,
    "gold_scaled",
    scaled(progression.gold, 1000.0))
  set(
    values,
    indexes,
    "progression_active_scaled",
    scaled(progression.progression_active_count, 64.0))
  set(
    values,
    indexes,
    "progression_visible_scaled",
    scaled(progression.progression_visible_count, 64.0))
  set(
    values,
    indexes,
    "secondary_slot_count_scaled",
    scaled(progression.secondary_count, 8.0))
  set_boolean(
    values,
    indexes,
    "inventory_truncated",
    progression.inventory_truncated)
  set_boolean(
    values,
    indexes,
    "progression_truncated",
    progression.progression_truncated)
  set(
    values,
    indexes,
    "offensive_damage_multiplier_scaled",
    scaled(progression.offensive_damage_multiplier, 4.0))
  set(
    values,
    indexes,
    "offensive_mana_multiplier_scaled",
    scaled(progression.offensive_mana_multiplier, 4.0))
  set(
    values,
    indexes,
    "cast_speed_multiplier_scaled",
    scaled(progression.cast_speed_multiplier, 4.0))
  set(
    values,
    indexes,
    "secondary_recharge_multiplier_scaled",
    scaled(progression.secondary_recharge_multiplier, 4.0))
  set_boolean(
    values,
    indexes,
    "primary_available",
    frame.primary_available)
  for slot = 1, 8 do
    set_boolean(
      values,
      indexes,
      "secondary_" .. tostring(slot) .. "_available",
      progression.secondary_available[slot])
  end
  for _, name in ipairs(
      { "fire", "water", "earth", "air", "ether" }) do
    set_boolean(
      values,
      indexes,
      "element_" .. name,
      context.row.element == name)
  end
  for _, name in ipairs({ "mind", "body", "arcane" }) do
    set_boolean(
      values,
      indexes,
      "discipline_" .. name,
      context.row.discipline == name)
  end

  local memory = context.policy_memory
  local hp_delta = memory.last_hp_ratio ~= nil and
    hp_ratio - memory.last_hp_ratio or 0.0
  local mana_delta = memory.last_mana_ratio ~= nil and
    mana_ratio - memory.last_mana_ratio or 0.0
  local target_id =
    type(target) == "table" and
    number(target.network_actor_id) or 0
  local target_hp_ratio =
    type(target) == "table" and
    ratio(target.hp, target.max_hp) or 0.0
  local target_hp_delta =
    target_id > 0 and target_id == memory.last_target_id and
    memory.last_target_hp_ratio ~= nil and
    target_hp_ratio - memory.last_target_hp_ratio or 0.0
  local enemy_count_delta =
    memory.last_enemy_count ~= nil and
    (#enemies - memory.last_enemy_count) / 16.0 or 0.0
  if hp_delta < -0.000001 then
    memory.last_damage_ms = frame.now_ms
  end
  set(values, indexes, "hp_delta", clamp(hp_delta, -1.0, 1.0))
  set(
    values,
    indexes,
    "mana_delta",
    clamp(mana_delta, -1.0, 1.0))
  set(
    values,
    indexes,
    "target_hp_delta",
    clamp(target_hp_delta, -1.0, 1.0))
  set(
    values,
    indexes,
    "enemy_count_delta",
    clamp(enemy_count_delta, -1.0, 1.0))
  set(
    values,
    indexes,
    "previous_move_dx",
    memory.previous_move_x or 0.0)
  set(
    values,
    indexes,
    "previous_move_dy",
    memory.previous_move_y or 0.0)
  set_boolean(
    values,
    indexes,
    "previous_cast_primary",
    memory.previous_cast_action == 1)
  set_boolean(
    values,
    indexes,
    "previous_cast_secondary",
    memory.previous_cast_action ~= nil and
      memory.previous_cast_action >= 2)
  set(
    values,
    indexes,
    "time_since_damage_scaled",
    elapsed_scaled(frame.now_ms, memory.last_damage_ms))
  set(
    values,
    indexes,
    "time_since_cast_scaled",
    elapsed_scaled(frame.now_ms, memory.last_cast_ms))
  set(
    values,
    indexes,
    "time_since_move_scaled",
    elapsed_scaled(frame.now_ms, memory.last_move_ms))

  for index, value in ipairs(values) do
    if not finite_number(value) then
      error(
        "policy observation " ..
        tostring(spec.observation_names[index]) ..
        " is not finite")
    end
  end

  memory.last_hp_ratio = hp_ratio
  memory.last_mana_ratio = mana_ratio
  memory.last_target_id = target_id
  memory.last_target_hp_ratio = target_hp_ratio
  memory.last_enemy_count = #enemies

  local movement_mask, movement_targets =
    build_movement_mask(
      spec,
      bot_x,
      bot_y,
      number(frame.movement_lookahead, 110.0))
  local cast_mask =
    build_cast_mask(spec, frame, snapshot, progression)
  return {
    values = values,
    movement_mask = movement_mask,
    movement_targets = movement_targets,
    cast_mask = cast_mask,
    snapshot = snapshot,
    participant = participant,
    progression = progression,
    metrics = {
      hp_ratio = hp_ratio,
      mana_ratio = mana_ratio,
      wave = wave_number,
      alive = hp_ratio > 0.0,
      enemy_count = #enemies,
      enemy_health = enemy_health(enemies),
    },
  }
end

return observation
