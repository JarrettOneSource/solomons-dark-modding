local observation = {}

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
  divisor = math.max(number(divisor, 1.0), 0.000001)
  return clamp(number(value) / divisor, -1.0, 1.0)
end

local function ratio(value, maximum)
  maximum = number(maximum)
  if maximum <= 0.0 then
    return 0.0
  end
  return clamp(number(value) / maximum, 0.0, 1.0)
end

local function log_count_scaled(value, saturation)
  saturation = math.max(number(saturation, 99.0), 1.0)
  local bounded = clamp(number(value), 0.0, saturation)
  return math.log(1.0 + bounded) /
    math.log(1.0 + saturation)
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

local function elapsed_scaled(now_ms, previous_ms, scale_ms)
  if previous_ms == nil then
    return 1.0
  end
  return clamp(
    (number(now_ms) - number(previous_ms)) / scale_ms,
    0.0,
    1.0)
end

local function default_snapshot(participant_id)
  local ok, snapshot = pcall(
    sd.bots.get_participant_state,
    participant_id)
  if ok and type(snapshot) == "table" then
    return snapshot
  end
  return {}
end

local function default_multiplayer_state()
  local ok, state = pcall(sd.runtime.get_multiplayer_state)
  if ok and type(state) == "table" then
    return state
  end
  return {}
end

local function default_loot()
  local ok, loot = pcall(sd.world.get_replicated_loot)
  if ok and type(loot) == "table" then
    return loot
  end
  return {}
end

local function default_test_segment(from_x, from_y, to_x, to_y)
  return sd.nav.test_segment(from_x, from_y, to_x, to_y)
end

local function find_participant(multiplayer, participant_id)
  for _, participant in ipairs(multiplayer.participants or {}) do
    if number(participant.participant_id) == participant_id then
      return participant
    end
  end
  return nil
end

local function new_memory()
  return {
    previous_move_action = 0,
    previous_move_x = 0.0,
    previous_move_y = 0.0,
    previous_cast_action = 0,
    previous_target_action = 0,
    previous_target_switched = false,
    target_actor_id = nil,
    enemy_position_history = {},
    pickup_request_ms = {},
    pickup_request_accepted = {},
  }
end

local function ensure_memory(context)
  if type(context.policy_memory) ~= "table" then
    context.policy_memory = new_memory()
  end
  local memory = context.policy_memory
  if type(memory.enemy_position_history) ~= "table" then
    memory.enemy_position_history = {}
  end
  if type(memory.pickup_request_ms) ~= "table" then
    memory.pickup_request_ms = {}
  end
  return memory
end

local function sort_enemies(
    enemies,
    bot_x,
    bot_y,
    now_ms,
    memory,
    spell_descriptors,
    primary,
    velocity_scale,
    enemy_descriptors)
  local rows = {}
  local next_history = {}
  for source_index, enemy in ipairs(enemies or {}) do
    local x = number(enemy.x)
    local y = number(enemy.y)
    local hp = number(enemy.hp)
    local max_hp = number(enemy.max_hp)
    local actor_id = number(enemy.network_actor_id)
    if actor_id > 0 and max_hp > 0.0 and hp > 0.0 then
      local dx = x - bot_x
      local dy = y - bot_y
      local unit_x, unit_y, distance =
        normalize(dx, dy)
      local velocity_x = 0.0
      local velocity_y = 0.0
      local previous =
        memory.enemy_position_history[actor_id]
      if type(previous) == "table" then
        local elapsed_ms = now_ms - number(previous.now_ms)
        if elapsed_ms > 0.0 then
          velocity_x =
            (x - number(previous.x)) * 1000.0 / elapsed_ms
          velocity_y =
            (y - number(previous.y)) * 1000.0 / elapsed_ms
        end
      end
      next_history[actor_id] = {
        x = x,
        y = y,
        now_ms = now_ms,
      }
      local in_primary_range, contact_distance =
        spell_descriptors:primary_in_range(
          primary,
          bot_x,
          bot_y,
          enemy)
      rows[#rows + 1] = {
        network_actor_id = actor_id,
        source_index = source_index,
        x = x,
        y = y,
        radius = math.max(number(enemy.radius), 0.0),
        hp = hp,
        max_hp = max_hp,
        alive = true,
        dx = unit_x,
        dy = unit_y,
        distance = distance,
        contact_distance = contact_distance,
        velocity_dx = scaled(velocity_x, velocity_scale),
        velocity_dy = scaled(velocity_y, velocity_scale),
        in_primary_range = in_primary_range,
        descriptor = enemy_descriptors:describe(enemy),
        heading = number(enemy.heading),
        object_type_id = number(
          enemy.object_type_id,
          number(enemy.native_type_id)),
        anim_drive_state = number(enemy.anim_drive_state),
        combat_status_resolved =
          enemy.combat_status_resolved == true,
      }
    end
  end
  table.sort(rows, function(left, right)
    if math.abs(left.distance - right.distance) > 0.000001 then
      return left.distance < right.distance
    end
    if left.network_actor_id ~= right.network_actor_id then
      return left.network_actor_id < right.network_actor_id
    end
    return left.source_index < right.source_index
  end)
  memory.enemy_position_history = next_history
  return rows
end

local function find_enemy_by_id(enemies, actor_id)
  if actor_id == nil or actor_id <= 0 then
    return nil
  end
  for _, enemy in ipairs(enemies) do
    if enemy.network_actor_id == actor_id then
      return enemy
    end
  end
  return nil
end

local function sort_allies(
    multiplayer,
    participant_id,
    bot_x,
    bot_y)
  local allies = {}
  for source_index, participant in
      ipairs(multiplayer.participants or {}) do
    local id = number(participant.participant_id)
    local x = tonumber(participant.x)
    local y = tonumber(participant.y)
    if id ~= participant_id and
        participant.in_run == true and
        finite_number(x) and finite_number(y) then
      local dx = x - bot_x
      local dy = y - bot_y
      local unit_x, unit_y, distance =
        normalize(dx, dy)
      local intent_x, intent_y = normalize(
        participant.movement_intent_x,
        participant.movement_intent_y)
      allies[#allies + 1] = {
        participant_id = id,
        source_index = source_index,
        dx = unit_x,
        dy = unit_y,
        distance = distance,
        hp_ratio = ratio(
          participant.life_current,
          participant.life_max),
        mana_ratio = ratio(
          participant.mana_current,
          participant.mana_max),
        alive = number(participant.life_current) > 0.0,
        is_human =
          tostring(participant.controller_kind or "") ==
            "Native",
        intent_dx = intent_x,
        intent_dy = intent_y,
      }
    end
  end
  table.sort(allies, function(left, right)
    if math.abs(left.distance - right.distance) > 0.000001 then
      return left.distance < right.distance
    end
    if left.participant_id ~= right.participant_id then
      return left.participant_id < right.participant_id
    end
    return left.source_index < right.source_index
  end)
  return allies
end

local PICKUP_RANGE_MULTIPLIERS = {
  Gold = 30.0,
  Item = 30.0,
  Potion = 30.0,
  Orb = 60.0,
}

local function sort_pickups(loot, bot_x, bot_y)
  local pickups = {}
  for source_index, drop in ipairs(loot.drops or {}) do
    local kind = tostring(drop.kind or "")
    local multiplier = PICKUP_RANGE_MULTIPLIERS[kind]
    local x = tonumber(drop.x)
    local y = tonumber(drop.y)
    if drop.active == true and multiplier ~= nil and
        finite_number(x) and finite_number(y) then
      local dx = x - bot_x
      local dy = y - bot_y
      local unit_x, unit_y, distance =
        normalize(dx, dy)
      local resource_kind = number(drop.resource_kind, -1)
      pickups[#pickups + 1] = {
        network_drop_id = number(drop.network_drop_id),
        source_index = source_index,
        x = x,
        y = y,
        dx = unit_x,
        dy = unit_y,
        distance = distance,
        kind = kind,
        type_gold = kind == "Gold",
        type_health_orb =
          kind == "Orb" and resource_kind == 0,
        type_mana_orb =
          kind == "Orb" and resource_kind == 1,
        type_item_carrier =
          kind == "Item" or kind == "Potion",
        pickup_range_multiplier = multiplier,
      }
    end
  end
  table.sort(pickups, function(left, right)
    if math.abs(left.distance - right.distance) > 0.000001 then
      return left.distance < right.distance
    end
    if left.network_drop_id ~= right.network_drop_id then
      return left.network_drop_id < right.network_drop_id
    end
    return left.source_index < right.source_index
  end)
  return pickups
end

local function nearest_within(enemies, maximum_distance)
  for _, enemy in ipairs(enemies) do
    if maximum_distance == nil or
        enemy.distance <= maximum_distance then
      return enemy
    end
  end
  return nil
end

local function count_within(enemies, maximum_distance)
  local result = 0
  for _, enemy in ipairs(enemies) do
    if enemy.distance <= maximum_distance then
      result = result + 1
    end
  end
  return result
end

local function build_movement_mask(
    builder,
    bot_x,
    bot_y,
    lookahead)
  local mask = {}
  local targets = {}
  for index, action in ipairs(builder.spec.movement_actions) do
    local target_x = bot_x + action.x * lookahead
    local target_y = bot_y + action.y * lookahead
    targets[index] = {x = target_x, y = target_y}
    if index == 1 then
      mask[index] = true
    else
      local ok, traversable = pcall(
        builder.test_segment,
        bot_x,
        bot_y,
        target_x,
        target_y)
      mask[index] = ok and traversable == true
    end
  end
  return mask, targets
end

local function build_target_mask(spec, enemy_slots, current_target)
  local mask = {}
  local has_enemy = #enemy_slots > 0
  mask[1] = current_target ~= nil or not has_enemy
  for slot = 1, spec.enemy_slot_count do
    local enemy = enemy_slots[slot]
    mask[slot + 1] =
      type(enemy) == "table" and enemy.alive == true
  end
  return mask
end

local function push(values, spec, name, value)
  local index = #values + 1
  local expected = spec.observation_names[index]
  if expected ~= name then
    error(
      "policy observation order mismatch at " ..
      tostring(index) .. ": expected " ..
      tostring(expected) .. ", got " .. tostring(name))
  end
  values[index] = number(value)
end

local function push_boolean(values, spec, name, value)
  push(values, spec, name, value == true and 1.0 or 0.0)
end

local function push_elements(values, spec, prefix, elements)
  for _, name in ipairs(
      {"fire", "water", "earth", "air", "ether"}) do
    push_boolean(
      values,
      spec,
      prefix .. name,
      elements[name])
  end
end

function observation.new(spec, dependencies)
  dependencies = type(dependencies) == "table" and
    dependencies or {}
  local indexes = {}
  for index, name in ipairs(spec.observation_names) do
    if indexes[name] ~= nil then
      error("duplicate policy observation name " .. name)
    end
    indexes[name] = index
  end
  return {
    spec = assert(spec),
    indexes = indexes,
    geometry = assert(dependencies.geometry),
    spell_descriptors =
      assert(dependencies.spell_descriptors),
    enemy_descriptors =
      assert(dependencies.enemy_descriptors),
    hazards = assert(dependencies.hazards),
    inventory = assert(dependencies.inventory),
    get_snapshot =
      dependencies.get_snapshot or default_snapshot,
    get_multiplayer_state =
      dependencies.get_multiplayer_state or
        default_multiplayer_state,
    get_loot = dependencies.get_loot or default_loot,
    test_segment =
      dependencies.test_segment or default_test_segment,
  }
end

function observation.capture(builder, context, frame)
  local spec = builder.spec
  local memory = ensure_memory(context)
  local bot_x = number(frame.bot_x)
  local bot_y = number(frame.bot_y)
  local now_ms = number(frame.now_ms)
  local geometry_cache =
    context.policy_geometry or builder.geometry
  local hazard_resolver =
    context.policy_hazards or builder.hazards
  geometry_cache:refresh(
    now_ms,
    frame.scene_key,
    context.participant_id)

  local snapshot = builder.get_snapshot(
    context.participant_id)
  snapshot = type(snapshot) == "table" and snapshot or {}
  local multiplayer = builder.get_multiplayer_state()
  multiplayer =
    type(multiplayer) == "table" and multiplayer or {}
  local participant = find_participant(
    multiplayer,
    context.participant_id)
  local loadout = builder.spell_descriptors:capture(
    context.participant_id,
    snapshot,
    participant,
    frame.skill_choices)
  local primary = loadout.primary
  local enemies = sort_enemies(
    frame.enemies,
    bot_x,
    bot_y,
    now_ms,
    memory,
    builder.spell_descriptors,
    primary,
    spec.velocity_scale,
    builder.enemy_descriptors)

  local persisted_id = number(memory.target_actor_id)
  local current_target =
    find_enemy_by_id(enemies, persisted_id)
  if current_target == nil then
    memory.target_actor_id = nil
  end
  local enemy_slots = {}
  for slot = 1, spec.enemy_slot_count do
    enemy_slots[slot] = enemies[slot]
  end

  local allies = sort_allies(
    multiplayer,
    context.participant_id,
    bot_x,
    bot_y)
  local loot = builder.get_loot()
  loot = type(loot) == "table" and loot or {}
  local pickups = sort_pickups(loot, bot_x, bot_y)
  local inventory_capture = builder.inventory:capture(
    context.participant_id,
    snapshot)
  local hazard_capture = hazard_resolver:capture(
    bot_x,
    bot_y,
    context.participant_id,
    geometry_cache.observer_radius,
    now_ms)

  local hp_current = number(frame.hp, number(snapshot.hp))
  local hp_max = number(frame.max_hp, number(snapshot.max_hp))
  local hp_ratio = ratio(hp_current, hp_max)
  local mana_current = number(
    snapshot.mp,
    type(participant) == "table" and
      participant.mana_current or 0.0)
  local mana_max = number(
    snapshot.max_mp,
    type(participant) == "table" and
      participant.mana_max or 0.0)
  local mana_ratio = ratio(mana_current, mana_max)
  local level = number(
    type(participant) == "table" and
      participant.level or snapshot.skill_choice_level)
  local wave_number = number(
    type(frame.wave) == "table" and frame.wave.wave)
  local values = {}

  -- Block A: self.
  push(values, spec, "self_hp_ratio", hp_ratio)
  push(values, spec, "self_mana_ratio", mana_ratio)
  push(
    values,
    spec,
    "self_level_scaled",
    scaled(level, spec.level_scale))
  push(
    values,
    spec,
    "wave_scaled",
    scaled(wave_number, spec.wave_scale))
  push(
    values,
    spec,
    "self_move_speed_scaled",
    scaled(
      type(participant) == "table" and
        participant.move_speed or 0.0,
      spec.velocity_scale))
  push_boolean(values, spec, "self_moving", snapshot.moving)
  push_boolean(
    values,
    spec,
    "self_cast_active",
    snapshot.cast_active)
  push_boolean(
    values,
    spec,
    "self_cast_ready",
    snapshot.cast_ready)
  push_boolean(
    values,
    spec,
    "self_poisoned",
    number(snapshot.native_poison_remaining_ticks) > 0 or
      number(snapshot.replicated_poison_remaining_ticks) > 0)
  push_boolean(
    values,
    spec,
    "self_webbed",
    number(snapshot.native_webbed_remaining_ticks) > 0)
  push_boolean(
    values,
    spec,
    "self_damage_x4",
    number(snapshot.native_damage_x4_remaining_ticks) > 0 or
      number(snapshot.replicated_damage_x4_remaining_ticks) > 0)
  push_boolean(
    values,
    spec,
    "self_status_active",
    number(snapshot.native_persistent_status_flags) ~= 0 or
      number(snapshot.native_transient_status_flags) ~= 0)
  push(
    values,
    spec,
    "self_mana_current_scaled",
    scaled(mana_current, spec.mana_scale))
  push(
    values,
    spec,
    "self_mana_max_scaled",
    scaled(mana_max, spec.mana_scale))
  push(
    values,
    spec,
    "self_hp_max_scaled",
    scaled(hp_max, spec.hp_scale))

  -- Block B: active primary.
  push_elements(
    values,
    spec,
    "primary_element_",
    primary.elements)
  push_boolean(values, spec, "primary_welded", primary.welded)
  push(
    values,
    spec,
    "primary_build_index_scaled",
    primary.build_index_scaled)
  push(
    values,
    spec,
    "primary_mana_cost_scaled",
    scaled(primary.mana_cost, spec.mana_scale))
  push(
    values,
    spec,
    "primary_range_min_scaled",
    scaled(primary.range_min, spec.range_scale))
  push(
    values,
    spec,
    "primary_range_max_scaled",
    scaled(primary.range_max, spec.range_scale))
  push_boolean(
    values,
    spec,
    "primary_affordable",
    primary.affordable)

  -- Block C: secondary slots.
  for slot = 1, spec.secondary_slot_count do
    local secondary = loadout.secondaries[slot]
    local prefix = "secondary_" .. tostring(slot) .. "_"
    local in_range =
      builder.spell_descriptors:secondary_in_range(
        secondary,
        bot_x,
        bot_y,
        current_target)
    secondary.in_range_of_target = in_range
    push_boolean(
      values,
      spec,
      prefix .. "occupied",
      secondary.occupied)
    push_elements(
      values,
      spec,
      prefix .. "element_",
      secondary.elements)
    push(
      values,
      spec,
      prefix .. "band_index_scaled",
      secondary.band_index_scaled)
    push(
      values,
      spec,
      prefix .. "mana_cost_scaled",
      scaled(secondary.mana_cost, spec.mana_scale))
    push(
      values,
      spec,
      prefix .. "range_scaled",
      scaled(secondary.range_max, spec.range_scale))
    push(
      values,
      spec,
      prefix .. "cooldown_scaled",
      scaled(
        secondary.cooldown_seconds,
        spec.cooldown_scale))
    push_boolean(
      values,
      spec,
      prefix .. "ready",
      secondary.ready)
    push_boolean(
      values,
      spec,
      prefix .. "affordable",
      secondary.affordable)
    push_boolean(
      values,
      spec,
      prefix .. "in_range_of_target",
      in_range)
  end

  -- Block D: nearest enemies.
  for slot = 1, spec.enemy_slot_count do
    local enemy = enemy_slots[slot]
    local prefix = "enemy_" .. tostring(slot) .. "_"
    push_boolean(values, spec, prefix .. "present", enemy ~= nil)
    push(values, spec, prefix .. "dx", enemy and enemy.dx or 0.0)
    push(values, spec, prefix .. "dy", enemy and enemy.dy or 0.0)
    push(
      values,
      spec,
      prefix .. "distance_scaled",
      enemy and scaled(enemy.distance, spec.range_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "hp_ratio",
      enemy and ratio(enemy.hp, enemy.max_hp) or 0.0)
    push(
      values,
      spec,
      prefix .. "radius_scaled",
      enemy and scaled(enemy.radius, spec.radius_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "velocity_dx",
      enemy and enemy.velocity_dx or 0.0)
    push(
      values,
      spec,
      prefix .. "velocity_dy",
      enemy and enemy.velocity_dy or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "in_primary_range",
      enemy ~= nil and enemy.in_primary_range)
    push_boolean(
      values,
      spec,
      prefix .. "is_current_target",
      enemy ~= nil and current_target ~= nil and
        enemy.network_actor_id ==
          current_target.network_actor_id)
  end

  -- Block E: persisted selected target.
  push_boolean(
    values,
    spec,
    "target_present",
    current_target ~= nil)
  push(
    values,
    spec,
    "target_dx",
    current_target and current_target.dx or 0.0)
  push(
    values,
    spec,
    "target_dy",
    current_target and current_target.dy or 0.0)
  push(
    values,
    spec,
    "target_distance_scaled",
    current_target and
      scaled(current_target.distance, spec.range_scale) or 0.0)
  push(
    values,
    spec,
    "target_contact_distance_scaled",
    current_target and
      scaled(
        current_target.contact_distance,
        spec.range_scale) or 0.0)
  push(
    values,
    spec,
    "target_hp_ratio",
    current_target and
      ratio(current_target.hp, current_target.max_hp) or 0.0)
  push(
    values,
    spec,
    "target_radius_scaled",
    current_target and
      scaled(current_target.radius, spec.radius_scale) or 0.0)
  push_boolean(
    values,
    spec,
    "target_in_primary_range",
    current_target ~= nil and
      current_target.in_primary_range)
  push(
    values,
    spec,
    "primary_min_range_scaled",
    scaled(primary.range_min, spec.range_scale))
  push(
    values,
    spec,
    "primary_max_range_scaled",
    scaled(primary.range_max, spec.range_scale))

  -- Block F: cached local geometry.
  local clearances, patch, obstacles =
    geometry_cache:features(
      bot_x,
      bot_y,
      multiplayer.participants,
      context.participant_id)
  if #clearances ~= 8 or #patch ~= 48 then
    error("policy geometry must produce 8 rays and 48 patch values")
  end
  local direction_names = {
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
    "north",
    "northeast",
  }
  for index, name in ipairs(direction_names) do
    push(
      values,
      spec,
      "clearance_" .. name .. "_scaled",
      clearances[index])
  end
  local patch_index = 1
  for row = 1, 7 do
    for column = 1, 7 do
      if row ~= 4 or column ~= 4 then
        push(
          values,
          spec,
          "walkability_patch_row_" .. tostring(row) ..
            "_col_" .. tostring(column),
          patch[patch_index])
        patch_index = patch_index + 1
      end
    end
  end

  -- Block G: replicated loot.
  for slot = 1, spec.pickup_slot_count do
    local pickup = pickups[slot]
    local prefix = "pickup_" .. tostring(slot) .. "_"
    push_boolean(values, spec, prefix .. "present", pickup ~= nil)
    push(values, spec, prefix .. "dx", pickup and pickup.dx or 0.0)
    push(values, spec, prefix .. "dy", pickup and pickup.dy or 0.0)
    push(
      values,
      spec,
      prefix .. "distance_scaled",
      pickup and scaled(pickup.distance, spec.range_scale) or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "type_gold",
      pickup ~= nil and pickup.type_gold)
    push_boolean(
      values,
      spec,
      prefix .. "type_health_orb",
      pickup ~= nil and pickup.type_health_orb)
    push_boolean(
      values,
      spec,
      prefix .. "type_mana_orb",
      pickup ~= nil and pickup.type_mana_orb)
    push_boolean(
      values,
      spec,
      prefix .. "type_item_carrier",
      pickup ~= nil and pickup.type_item_carrier)
  end
  push(
    values,
    spec,
    "pickup_count_scaled",
    scaled(#pickups, spec.pickup_count_scale))

  -- Block I: nearest in-run participants other than self.
  for slot = 1, spec.ally_slot_count do
    local ally = allies[slot]
    local prefix = "ally_" .. tostring(slot) .. "_"
    push_boolean(values, spec, prefix .. "present", ally ~= nil)
    push(values, spec, prefix .. "dx", ally and ally.dx or 0.0)
    push(values, spec, prefix .. "dy", ally and ally.dy or 0.0)
    push(
      values,
      spec,
      prefix .. "distance_scaled",
      ally and scaled(ally.distance, spec.range_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "hp_ratio",
      ally and ally.hp_ratio or 0.0)
    push(
      values,
      spec,
      prefix .. "mana_ratio",
      ally and ally.mana_ratio or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "alive",
      ally ~= nil and ally.alive)
    push_boolean(
      values,
      spec,
      prefix .. "is_human",
      ally ~= nil and ally.is_human)
    push(
      values,
      spec,
      prefix .. "intent_dx",
      ally and ally.intent_dx or 0.0)
    push(
      values,
      spec,
      prefix .. "intent_dy",
      ally and ally.intent_dy or 0.0)
  end
  push(
    values,
    spec,
    "ally_count_scaled",
    scaled(#allies, spec.ally_count_scale))

  -- Block H: aggregates, config, history, weld, and multipliers.
  local threat_radius = math.max(number(frame.threat_radius), 0.0)
  local nearest = nearest_within(enemies)
  local nearest_threat =
    nearest_within(enemies, threat_radius)
  push(
    values,
    spec,
    "enemy_count_scaled",
    scaled(#enemies, spec.enemy_count_scale))
  push(
    values,
    spec,
    "threat_count_scaled",
    scaled(
      count_within(enemies, threat_radius),
      spec.threat_count_scale))
  push(values, spec, "nearest_enemy_dx", nearest and nearest.dx or 0.0)
  push(values, spec, "nearest_enemy_dy", nearest and nearest.dy or 0.0)
  push(
    values,
    spec,
    "nearest_enemy_distance_scaled",
    nearest and scaled(nearest.distance, spec.range_scale) or 0.0)
  push(
    values,
    spec,
    "nearest_threat_dx",
    nearest_threat and nearest_threat.dx or 0.0)
  push(
    values,
    spec,
    "nearest_threat_dy",
    nearest_threat and nearest_threat.dy or 0.0)
  push(
    values,
    spec,
    "nearest_threat_distance_scaled",
    nearest_threat and
      scaled(nearest_threat.distance, spec.range_scale) or 0.0)
  push(
    values,
    spec,
    "escape_dx",
    nearest_threat and -nearest_threat.dx or 0.0)
  push(
    values,
    spec,
    "escape_dy",
    nearest_threat and -nearest_threat.dy or 0.0)
  push(
    values,
    spec,
    "suggested_move_dx",
    frame.suggested_move_x)
  push(
    values,
    spec,
    "suggested_move_dy",
    frame.suggested_move_y)

  local arena = type(frame.arena) == "table" and
    frame.arena or {}
  local center_dx, center_dy, center_distance = normalize(
    number(arena.center_x) - bot_x,
    number(arena.center_y) - bot_y)
  push(values, spec, "arena_center_dx", center_dx)
  push(values, spec, "arena_center_dy", center_dy)
  push(
    values,
    spec,
    "arena_center_distance_scaled",
    scaled(center_distance, spec.range_scale))
  push(
    values,
    spec,
    "arena_x_normalized",
    clamp(
      (bot_x - number(arena.center_x)) /
        math.max(number(arena.half_width, 1.0), 1.0),
      -1.0,
      1.0))
  push(
    values,
    spec,
    "arena_y_normalized",
    clamp(
      (bot_y - number(arena.center_y)) /
        math.max(number(arena.half_height, 1.0), 1.0),
      -1.0,
      1.0))
  push(
    values,
    spec,
    "edge_pressure",
    clamp(number(frame.edge_pressure), 0.0, 1.0))
  for _, name in ipairs(
      {"fire", "water", "earth", "air", "ether"}) do
    push_boolean(
      values,
      spec,
      "element_" .. name,
      context.row.element == name)
  end
  for _, name in ipairs({"mind", "body", "arcane"}) do
    push_boolean(
      values,
      spec,
      "discipline_" .. name,
      context.row.discipline == name)
  end

  local hp_delta = memory.last_hp_ratio ~= nil and
    hp_ratio - memory.last_hp_ratio or 0.0
  local mana_delta = memory.last_mana_ratio ~= nil and
    mana_ratio - memory.last_mana_ratio or 0.0
  local target_id = current_target ~= nil and
    current_target.network_actor_id or 0
  local target_hp_ratio = current_target ~= nil and
    ratio(current_target.hp, current_target.max_hp) or 0.0
  local target_hp_delta =
    target_id > 0 and target_id == memory.last_target_id and
    memory.last_target_hp_ratio ~= nil and
      target_hp_ratio - memory.last_target_hp_ratio or 0.0
  local enemy_count_delta =
    memory.last_enemy_count ~= nil and
      (#enemies - memory.last_enemy_count) /
        spec.enemy_count_scale or 0.0
  if hp_delta < -0.000001 then
    memory.last_damage_ms = now_ms
  end
  push(values, spec, "hp_delta", clamp(hp_delta, -1.0, 1.0))
  push(values, spec, "mana_delta", clamp(mana_delta, -1.0, 1.0))
  push(
    values,
    spec,
    "target_hp_delta",
    clamp(target_hp_delta, -1.0, 1.0))
  push(
    values,
    spec,
    "enemy_count_delta",
    clamp(enemy_count_delta, -1.0, 1.0))
  push(
    values,
    spec,
    "previous_move_dx",
    memory.previous_move_x)
  push(
    values,
    spec,
    "previous_move_dy",
    memory.previous_move_y)
  push_boolean(
    values,
    spec,
    "previous_cast_primary",
    memory.previous_cast_action == 1)
  push_boolean(
    values,
    spec,
    "previous_cast_secondary",
    number(memory.previous_cast_action) >= 2 and
      number(memory.previous_cast_action) <= 9)
  push(
    values,
    spec,
    "time_since_damage_scaled",
    elapsed_scaled(
      now_ms,
      memory.last_damage_ms,
      spec.history_time_scale_ms))
  push(
    values,
    spec,
    "time_since_cast_scaled",
    elapsed_scaled(
      now_ms,
      memory.last_cast_ms,
      spec.history_time_scale_ms))
  push(
    values,
    spec,
    "time_since_move_scaled",
    elapsed_scaled(
      now_ms,
      memory.last_move_ms,
      spec.history_time_scale_ms))
  push(
    values,
    spec,
    "previous_target_action_scaled",
    scaled(
      memory.previous_target_action,
      spec.target_action_scale))
  push_boolean(
    values,
    spec,
    "previous_target_switched",
    memory.previous_target_switched)
  push_boolean(
    values,
    spec,
    "has_spell_welding_skill",
    loadout.has_spell_welding_skill)
  push_boolean(
    values,
    spec,
    "weld_offer_pending",
    loadout.weld_offer_pending)
  push(
    values,
    spec,
    "offensive_damage_multiplier_scaled",
    scaled(
      loadout.offensive_damage_multiplier,
      spec.multiplier_scale))
  push(
    values,
    spec,
    "offensive_mana_multiplier_scaled",
    scaled(
      loadout.offensive_mana_multiplier,
      spec.multiplier_scale))
  push(
    values,
    spec,
    "cast_speed_multiplier_scaled",
    scaled(
      loadout.cast_speed_multiplier,
      spec.multiplier_scale))
  push(
    values,
    spec,
    "secondary_recharge_multiplier_scaled",
    scaled(
      loadout.secondary_recharge_multiplier,
      spec.multiplier_scale))

  -- Block J: participant-scoped potion timers.
  push(
    values,
    spec,
    "self_damage_x4_remaining_scaled",
    inventory_capture.damage_x4_remaining_scaled)
  push(
    values,
    spec,
    "self_poison_immunity_remaining_scaled",
    inventory_capture.poison_immunity_remaining_scaled)
  push(
    values,
    spec,
    "self_all_concentration_remaining_scaled",
    inventory_capture.all_concentration_remaining_scaled)

  -- Block K: enemy identity, combat state, and statuses.
  for slot = 1, spec.enemy_slot_count do
    local enemy = enemy_slots[slot]
    local descriptor =
      enemy ~= nil and enemy.descriptor or {}
    local prefix = "enemy_" .. tostring(slot) .. "_"
    push(
      values,
      spec,
      prefix .. "species_index_scaled",
      descriptor.species_index_scaled)
    for _, name in ipairs({
      "species_known",
      "role_melee",
      "role_ranged",
      "role_caster",
      "role_spawner",
      "role_exploder",
      "role_boss",
      "role_flying",
      "role_stationary",
    }) do
      push_boolean(
        values,
        spec,
        prefix .. name,
        descriptor[name])
    end
    push(
      values,
      spec,
      prefix .. "facing_dx",
      descriptor.facing_dx)
    push(
      values,
      spec,
      prefix .. "facing_dy",
      descriptor.facing_dy)
    push(
      values,
      spec,
      prefix .. "anim_state_scaled",
      descriptor.anim_state_scaled)
    for _, name in ipairs({
      "telegraph_known",
      "winding_up",
      "attack_active",
      "recovering",
    }) do
      push_boolean(
        values,
        spec,
        prefix .. name,
        descriptor[name])
    end
    push_boolean(
      values,
      spec,
      prefix .. "slowed",
      descriptor.slowed)
    push(
      values,
      spec,
      prefix .. "slow_remaining_scaled",
      scaled(
        descriptor.slow_remaining_seconds,
        spec.status_duration_scale_seconds))
    push_boolean(
      values,
      spec,
      prefix .. "frozen",
      descriptor.frozen)
    push(
      values,
      spec,
      prefix .. "frozen_remaining_scaled",
      scaled(
        descriptor.frozen_remaining_seconds,
        spec.status_duration_scale_seconds))
    push_boolean(
      values,
      spec,
      prefix .. "poisoned",
      descriptor.poisoned)
    push(
      values,
      spec,
      prefix .. "poison_remaining_scaled",
      scaled(
        descriptor.poison_remaining_seconds,
        spec.status_duration_scale_seconds))
    push_boolean(
      values,
      spec,
      prefix .. "webbed",
      descriptor.webbed)
    push(
      values,
      spec,
      prefix .. "webbed_remaining_scaled",
      scaled(
        descriptor.webbed_remaining_seconds,
        spec.status_duration_scale_seconds))
    push_boolean(
      values,
      spec,
      prefix .. "turn_undead",
      descriptor.turn_undead)
    push(
      values,
      spec,
      prefix .. "turn_undead_remaining_scaled",
      scaled(
        descriptor.turn_undead_remaining_seconds,
        spec.status_duration_scale_seconds))
  end

  -- Block L: persisted target motion and facing.
  push(
    values,
    spec,
    "target_velocity_dx",
    current_target and current_target.velocity_dx or 0.0)
  push(
    values,
    spec,
    "target_velocity_dy",
    current_target and current_target.velocity_dy or 0.0)
  push(
    values,
    spec,
    "target_facing_dx",
    current_target and
      current_target.descriptor.facing_dx or 0.0)
  push(
    values,
    spec,
    "target_facing_dy",
    current_target and
      current_target.descriptor.facing_dy or 0.0)

  -- Block M: nearest exact, radius-inflated collision obstacles.
  for slot = 1, spec.obstacle_slot_count do
    local obstacle = obstacles[slot]
    local prefix = "obstacle_" .. tostring(slot) .. "_"
    push_boolean(
      values,
      spec,
      prefix .. "present",
      obstacle ~= nil)
    push(
      values,
      spec,
      prefix .. "nearest_dx",
      obstacle and obstacle.nearest_dx or 0.0)
    push(
      values,
      spec,
      prefix .. "nearest_dy",
      obstacle and obstacle.nearest_dy or 0.0)
    push(
      values,
      spec,
      prefix .. "clearance_scaled",
      obstacle and
        scaled(obstacle.clearance, spec.range_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "normal_dx",
      obstacle and obstacle.normal_dx or 0.0)
    push(
      values,
      spec,
      prefix .. "normal_dy",
      obstacle and obstacle.normal_dy or 0.0)
    push(
      values,
      spec,
      prefix .. "radius_scaled",
      obstacle and
        scaled(obstacle.radius, spec.radius_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "extent_x_scaled",
      obstacle and
        scaled(obstacle.extent_x, spec.range_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "extent_y_scaled",
      obstacle and
        scaled(obstacle.extent_y, spec.range_scale) or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "kind_circle",
      obstacle ~= nil and obstacle.kind == "circle")
    push_boolean(
      values,
      spec,
      prefix .. "kind_segment",
      obstacle ~= nil and obstacle.kind == "segment")
    push_boolean(
      values,
      spec,
      prefix .. "kind_polygon",
      obstacle ~= nil and obstacle.kind == "polygon")
    push_boolean(
      values,
      spec,
      prefix .. "is_participant",
      obstacle ~= nil and obstacle.is_participant)
    push_boolean(
      values,
      spec,
      prefix .. "is_destructible",
      obstacle ~= nil and obstacle.is_destructible)
  end

  -- Block N: nearest hostile hazards. Unknown hostile classes are retained.
  for slot = 1, spec.hazard_slot_count do
    local hazard = hazard_capture.rows[slot]
    local prefix = "hazard_" .. tostring(slot) .. "_"
    push_boolean(
      values,
      spec,
      prefix .. "present",
      hazard ~= nil)
    push(
      values,
      spec,
      prefix .. "hazard_type_index_scaled",
      hazard and hazard.hazard_type_index_scaled or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "type_known",
      hazard ~= nil and hazard.type_known)
    push(values, spec, prefix .. "dx", hazard and hazard.dx or 0.0)
    push(values, spec, prefix .. "dy", hazard and hazard.dy or 0.0)
    push(
      values,
      spec,
      prefix .. "distance_scaled",
      hazard and scaled(hazard.distance, spec.range_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "velocity_dx",
      hazard and
        scaled(hazard.velocity_x, spec.velocity_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "velocity_dy",
      hazard and
        scaled(hazard.velocity_y, spec.velocity_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "radius_scaled",
      hazard and scaled(hazard.radius, spec.radius_scale) or 0.0)
    push(
      values,
      spec,
      prefix .. "time_to_contact_scaled",
      hazard and
        scaled(
          hazard.time_to_contact,
          spec.hazard_time_to_contact_scale_seconds) or 0.0)
    push(
      values,
      spec,
      prefix .. "remaining_time_scaled",
      hazard and
        scaled(
          hazard.remaining_time,
          spec.hazard_lifetime_scale_seconds) or 0.0)
    for _, name in ipairs({
      "kind_projectile",
      "kind_area",
      "kind_beam",
      "homing",
      "targeting_self",
      "source_enemy",
    }) do
      push_boolean(
        values,
        spec,
        prefix .. name,
        hazard ~= nil and hazard[name])
    end
  end
  push(
    values,
    spec,
    "hazard_count_scaled",
    log_count_scaled(
      hazard_capture.total_count,
      spec.inventory_count_saturation))

  -- Block O: count-ranked potion descriptors.
  for slot = 1, spec.potion_slot_count do
    local potion = inventory_capture.potion_rows[slot]
    local prefix = "potion_" .. tostring(slot) .. "_"
    for _, name in ipairs({
      "present",
      "stock_health",
      "stock_mana",
      "stock_wizard_chug",
      "stock_antidote",
      "stock_mind_chug",
      "stock_rejuvenation",
      "custom",
    }) do
      if name == "present" then
        push_boolean(
          values,
          spec,
          prefix .. name,
          potion ~= nil and potion.present)
        push(
          values,
          spec,
          prefix .. "count_scaled",
          potion and potion.count_scaled or 0.0)
      else
        push_boolean(
          values,
          spec,
          prefix .. name,
          potion ~= nil and potion[name])
      end
    end
    push(
      values,
      spec,
      prefix .. "restores_hp_fraction",
      potion and potion.restores_hp_fraction or 0.0)
    push(
      values,
      spec,
      prefix .. "restores_mana_fraction",
      potion and potion.restores_mana_fraction or 0.0)
    push(
      values,
      spec,
      prefix .. "damage_multiplier_scaled",
      potion and potion.damage_multiplier_scaled or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "cures_poison",
      potion ~= nil and potion.cures_poison)
    push(
      values,
      spec,
      prefix .. "poison_immunity_duration_scaled",
      potion and
        potion.poison_immunity_duration_scaled or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "concentrates_all",
      potion ~= nil and potion.concentrates_all)
    push(
      values,
      spec,
      prefix .. "effect_duration_scaled",
      potion and potion.effect_duration_scaled or 0.0)
    push_boolean(
      values,
      spec,
      prefix .. "custom_effect_known",
      potion ~= nil and potion.custom_effect_known)
    push(
      values,
      spec,
      prefix .. "identity_hash_a",
      potion and potion.identity_hash_a or 0.0)
    push(
      values,
      spec,
      prefix .. "identity_hash_b",
      potion and potion.identity_hash_b or 0.0)
  end
  push(
    values,
    spec,
    "potion_type_count_scaled",
    inventory_capture.potion_type_count_scaled)
  push(
    values,
    spec,
    "potion_total_count_scaled",
    inventory_capture.potion_total_count_scaled)

  -- Block P: equipped item identity and effect summaries.
  for _, slot in ipairs({
    "hat",
    "robe",
    "weapon",
    "ring_1",
    "ring_2",
    "ring_3",
    "amulet",
  }) do
    local equipment = inventory_capture.equipment_rows[slot]
    local prefix = "equipment_" .. slot .. "_"
    push_boolean(
      values,
      spec,
      prefix .. "present",
      equipment.present)
    push_boolean(
      values,
      spec,
      prefix .. "catalog_known",
      equipment.catalog_known)
    push(
      values,
      spec,
      prefix .. "identity_hash_a",
      equipment.identity_hash_a)
    push(
      values,
      spec,
      prefix .. "identity_hash_b",
      equipment.identity_hash_b)
    push(
      values,
      spec,
      prefix .. "rarity_scaled",
      equipment.rarity_scaled)
    push(
      values,
      spec,
      prefix .. "level_scaled",
      equipment.level_scaled)
    push_boolean(
      values,
      spec,
      prefix .. "set_complete",
      equipment.set_complete)
    push(
      values,
      spec,
      prefix .. "offense_effect_scaled",
      equipment.offense_effect_scaled)
    push(
      values,
      spec,
      prefix .. "resource_effect_scaled",
      equipment.resource_effect_scaled)
    push(
      values,
      spec,
      prefix .. "mobility_effect_scaled",
      equipment.mobility_effect_scaled)
    push(
      values,
      spec,
      prefix .. "defense_effect_scaled",
      equipment.defense_effect_scaled)
    push_boolean(
      values,
      spec,
      prefix .. "targeted_effect_present",
      equipment.targeted_effect_present)
    push(
      values,
      spec,
      prefix .. "target_kind_scaled",
      equipment.target_kind_scaled)
    push(
      values,
      spec,
      prefix .. "target_magnitude_scaled",
      equipment.target_magnitude_scaled)
    push_boolean(
      values,
      spec,
      prefix .. "special_feature_present",
      equipment.special_feature_present)
  end

  -- Block Q: bounded/log-scaled inventory taxonomy counts.
  for _, field in ipairs({
    "item_total_count",
    "potion_count",
    "equipment_count",
    "sack_count",
    "misc_count",
    "perk_count",
    "map_count",
    "registered_custom_count",
    "unknown_count",
  }) do
    push(
      values,
      spec,
      "inventory_" .. field .. "_scaled",
      inventory_capture.summary[field])
  end

  if #values ~= #spec.observation_names then
    error(
      "policy observation contains " .. tostring(#values) ..
      " values; expected " ..
      tostring(#spec.observation_names))
  end
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
      builder,
      bot_x,
      bot_y,
      number(
        frame.movement_lookahead,
        spec.movement_lookahead))
  local target_mask =
    build_target_mask(spec, enemy_slots, current_target)
  return {
    values = values,
    movement_mask = movement_mask,
    movement_targets = movement_targets,
    target_mask = target_mask,
    ability_mask = nil,
    aim_mask = nil,
    snapshot = snapshot,
    multiplayer = multiplayer,
    participant = participant,
    loadout = loadout,
    enemies = enemies,
    enemy_slots = enemy_slots,
    current_target = current_target,
    allies = allies,
    loot = loot,
    pickups = pickups,
    obstacles = obstacles,
    hazards = hazard_capture.rows,
    hazard_snapshot = hazard_capture.snapshot,
    inventory = inventory_capture,
    bot_x = bot_x,
    bot_y = bot_y,
    offense_enabled = frame.offense_enabled == true,
    metrics = {
      hp_ratio = hp_ratio,
      mana_ratio = mana_ratio,
      wave = wave_number,
      alive = hp_ratio > 0.0,
      attributed_experience = number(
        participant and
          participant.reward_attributed_experience),
      attributed_enemy_hp_ratio_damage = number(
        participant and
          participant.reward_attributed_enemy_hp_ratio_damage),
      enemy_count = #enemies,
    },
  }
end

function observation.select_target(
    builder,
    context,
    capture,
    target_action)
  target_action = math.floor(number(target_action, -1))
  local mask_index = target_action + 1
  if capture.target_mask[mask_index] ~= true then
    error(
      "policy selected illegal target action " ..
      tostring(target_action))
  end

  local action = builder.spec.target_actions[mask_index]
  local target = nil
  if action.enemy_slot == 0 then
    target = capture.current_target
  else
    target = capture.enemy_slots[action.enemy_slot]
  end

  local memory = ensure_memory(context)
  local old_id = number(memory.target_actor_id)
  local new_id =
    type(target) == "table" and
      number(target.network_actor_id) or 0
  local switched = old_id ~= new_id
  memory.target_actor_id =
    new_id > 0 and new_id or nil
  memory.previous_target_action = target_action
  memory.previous_target_switched = switched
  memory.last_target_id = new_id
  memory.last_target_hp_ratio =
    target ~= nil and ratio(target.hp, target.max_hp) or 0.0
  capture.selected_target = target
  capture.target_switched = switched
  return target, switched
end

function observation.build_ability_mask(
    builder,
    capture,
    target)
  local spec = builder.spec
  local mask = {}
  for index = 1, #spec.ability_actions do
    mask[index] = false
  end
  mask[1] = true

  local snapshot = capture.snapshot
  local cast_ready =
    capture.offense_enabled == true and
    type(target) == "table" and
    snapshot.cast_ready == true and
    snapshot.cast_active ~= true and
    snapshot.cast_pending ~= true
  if cast_ready then
    local primary = capture.loadout.primary
    local primary_in_range =
      builder.spell_descriptors:primary_in_range(
        primary,
        capture.bot_x,
        capture.bot_y,
        target)
    mask[2] =
      primary.occupied == true and
      primary.affordable == true and
      (primary.range_resolved ~= true or
        primary_in_range == true)

    for slot = 1, spec.secondary_slot_count do
      local secondary = capture.loadout.secondaries[slot]
      local in_range =
        builder.spell_descriptors:secondary_in_range(
          secondary,
          capture.bot_x,
          capture.bot_y,
          target)
      mask[slot + 2] =
        secondary.occupied == true and
        secondary.affordable == true and
        secondary.ready == true and
        (secondary.range_resolved ~= true or
          in_range == true)
    end
  end

  for slot = 1, spec.potion_slot_count do
    -- The inventory resolver permanently rejects stock subtypes 2/3/4,
    -- independent of vitals or timers.
    mask[slot + 10] =
      capture.inventory.potion_legal[slot] == true
  end
  capture.ability_mask = mask
  return mask
end

function observation.build_aim_mask(
    builder,
    capture,
    ability_action)
  ability_action = math.floor(number(ability_action, -1))
  local action = builder.spec.ability_actions[ability_action + 1]
  if type(action) ~= "table" then
    error(
      "policy selected invalid ability action " ..
      tostring(ability_action))
  end
  local free = false
  if action.kind == "cast" then
    local spell
    if action.skill_slot == 0 then
      spell = capture.loadout.primary
    else
      spell = capture.loadout.secondaries[action.skill_slot]
    end
    free = builder.spell_descriptors:aim_is_free(spell)
  end
  local mask = {}
  for index = 1, #builder.spec.aim_actions do
    mask[index] = index == 1 or free == true
  end
  capture.aim_mask = mask
  return mask
end

function observation.aim_point(
    builder,
    target,
    aim_action)
  if type(target) ~= "table" then
    return nil, nil
  end
  aim_action = math.floor(number(aim_action, -1))
  local action = builder.spec.aim_actions[aim_action + 1]
  if type(action) ~= "table" then
    error(
      "policy selected invalid aim action " ..
      tostring(aim_action))
  end
  return number(target.x) +
      action.x * builder.spec.aim_offset_world,
    number(target.y) +
      action.y * builder.spec.aim_offset_world
end

function observation.new_memory()
  return new_memory()
end

return observation
