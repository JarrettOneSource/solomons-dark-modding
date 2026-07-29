local steering = {}

local function finite_number(value)
  return type(value) == "number" and value == value and
    value > -math.huge and value < math.huge
end

local function normalize(x, y)
  if not finite_number(x) or not finite_number(y) then
    return 0.0, 0.0, 0.0
  end
  local length = math.sqrt((x * x) + (y * y))
  if length <= 0.0001 then
    return 0.0, 0.0, 0.0
  end
  return x / length, y / length, length
end

local function clamp(value, minimum, maximum)
  if value < minimum then
    return minimum
  end
  if value > maximum then
    return maximum
  end
  return value
end

function steering.arena_from_grid(grid, fallback_x, fallback_y)
  local minimum_x, maximum_x = math.huge, -math.huge
  local minimum_y, maximum_y = math.huge, -math.huge
  local accepted = 0
  if type(grid) == "table" and type(grid.cells) == "table" then
    for _, cell in ipairs(grid.cells) do
      local x = tonumber(cell.center_x)
      local y = tonumber(cell.center_y)
      if (cell.path_traversable == true or cell.traversable == true) and
          finite_number(x) and finite_number(y) then
        minimum_x = math.min(minimum_x, x)
        maximum_x = math.max(maximum_x, x)
        minimum_y = math.min(minimum_y, y)
        maximum_y = math.max(maximum_y, y)
        accepted = accepted + 1
      end
    end
  end

  local cell_width = tonumber(type(grid) == "table" and grid.cell_width) or 50.0
  local cell_height = tonumber(type(grid) == "table" and grid.cell_height) or 50.0
  if accepted == 0 then
    local x = finite_number(fallback_x) and fallback_x or 0.0
    local y = finite_number(fallback_y) and fallback_y or 0.0
    return {
      center_x = x,
      center_y = y,
      minimum_x = x - 300.0,
      maximum_x = x + 300.0,
      minimum_y = y - 300.0,
      maximum_y = y + 300.0,
      half_width = 300.0,
      half_height = 300.0,
      margin_x = 20.0,
      margin_y = 20.0,
      grid_backed = false,
    }
  end

  local center_x = (minimum_x + maximum_x) * 0.5
  local center_y = (minimum_y + maximum_y) * 0.5
  return {
    center_x = center_x,
    center_y = center_y,
    minimum_x = minimum_x,
    maximum_x = maximum_x,
    minimum_y = minimum_y,
    maximum_y = maximum_y,
    half_width = math.max((maximum_x - minimum_x) * 0.5, cell_width),
    half_height = math.max((maximum_y - minimum_y) * 0.5, cell_height),
    margin_x = math.max(cell_width * 0.35, 12.0),
    margin_y = math.max(cell_height * 0.35, 12.0),
    grid_backed = true,
  }
end

function steering.live_enemies(world_snapshot)
  local enemies = {}
  local actors = type(world_snapshot) == "table" and world_snapshot.actors or nil
  if type(actors) ~= "table" then
    return enemies
  end

  for _, actor in ipairs(actors) do
    local x = tonumber(actor.x)
    local y = tonumber(actor.y)
    local hp = tonumber(actor.hp)
    local max_hp = tonumber(actor.max_hp)
    if actor.tracked_enemy == true and actor.dead ~= true and
        finite_number(x) and finite_number(y) and
        finite_number(hp) and finite_number(max_hp) and
        hp > 0.0 and max_hp > 0.0 then
      table.insert(enemies, {
        network_actor_id = tonumber(actor.network_actor_id) or 0,
        x = x,
        y = y,
        radius = math.max(tonumber(actor.radius) or 0.0, 0.0),
        hp = hp,
        max_hp = max_hp,
      })
    end
  end
  return enemies
end

function steering.nearest_cast_target(
    bot_x,
    bot_y,
    enemies,
    minimum_range,
    maximum_range)
  local best = nil
  local best_distance = math.huge
  minimum_range = math.max(tonumber(minimum_range) or 0.0, 0.0)
  maximum_range = math.max(tonumber(maximum_range) or 0.0, minimum_range)

  for _, enemy in ipairs(enemies or {}) do
    local dx = enemy.x - bot_x
    local dy = enemy.y - bot_y
    local distance = math.sqrt((dx * dx) + (dy * dy))
    if distance >= minimum_range and
        distance <= maximum_range and
        distance < best_distance then
      best = enemy
      best_distance = distance
    end
  end
  return best, best_distance
end

function steering.nearest_enemy(bot_x, bot_y, enemies)
  local best = nil
  local best_distance = math.huge
  for _, enemy in ipairs(enemies or {}) do
    local dx = enemy.x - bot_x
    local dy = enemy.y - bot_y
    local distance = math.sqrt((dx * dx) + (dy * dy))
    if distance < best_distance then
      best = enemy
      best_distance = distance
    end
  end
  return best, best_distance
end

function steering.approach_direction(bot_x, bot_y, enemy, arena)
  if type(enemy) ~= "table" then
    return 0.0, 0.0
  end

  local toward_x, toward_y = normalize(
    enemy.x - bot_x,
    enemy.y - bot_y)
  local inward_x, inward_y = normalize(
    arena.center_x - bot_x,
    arena.center_y - bot_y)
  local edge_x =
    math.abs(bot_x - arena.center_x) / math.max(arena.half_width, 1.0)
  local edge_y =
    math.abs(bot_y - arena.center_y) / math.max(arena.half_height, 1.0)
  local edge_pressure = math.max(edge_x, edge_y)
  local center_weight =
    0.10 + math.max(edge_pressure - 0.55, 0.0) * 2.0
  local direction_x = toward_x + inward_x * center_weight
  local direction_y = toward_y + inward_y * center_weight
  local normalized_x, normalized_y = normalize(direction_x, direction_y)
  return normalized_x, normalized_y
end

function steering.kite_direction(
    bot_x,
    bot_y,
    enemies,
    arena,
    fleeing,
    now_ms,
    threat_radius)
  local repulsion_x, repulsion_y = 0.0, 0.0
  local threat_count = 0
  local nearest_threat_distance = math.huge
  local nearest_direction_x, nearest_direction_y = 0.0, 0.0
  threat_radius = math.max(tonumber(threat_radius) or 1.0, 1.0)

  for _, enemy in ipairs(enemies or {}) do
    local dx = bot_x - enemy.x
    local dy = bot_y - enemy.y
    local direction_x, direction_y, distance = normalize(dx, dy)
    if distance <= 0.0001 then
      local angle =
        ((tonumber(enemy.network_actor_id) or 0) % 16) * math.pi / 8.0
      direction_x, direction_y = math.cos(angle), math.sin(angle)
      distance = 0.0001
    end
    if distance <= threat_radius then
      local inverse_distance_weight =
        threat_radius / math.max(distance, 24.0)
      repulsion_x = repulsion_x + direction_x * inverse_distance_weight
      repulsion_y = repulsion_y + direction_y * inverse_distance_weight
      if distance < nearest_threat_distance then
        nearest_threat_distance = distance
        nearest_direction_x, nearest_direction_y = direction_x, direction_y
      end
      threat_count = threat_count + 1
    end
  end

  local repulsion_unit_x, repulsion_unit_y =
    normalize(repulsion_x, repulsion_y)
  if threat_count > 0 and
      repulsion_unit_x == 0.0 and repulsion_unit_y == 0.0 then
    repulsion_unit_x, repulsion_unit_y =
      nearest_direction_x, nearest_direction_y
  end
  local inward_x, inward_y = normalize(
    arena.center_x - bot_x,
    arena.center_y - bot_y)
  local edge_x =
    math.abs(bot_x - arena.center_x) / math.max(arena.half_width, 1.0)
  local edge_y =
    math.abs(bot_y - arena.center_y) / math.max(arena.half_height, 1.0)
  local edge_pressure = math.max(edge_x, edge_y)
  local perimeter_bias = math.max(edge_pressure - 0.55, 0.0)

  local direction_x, direction_y
  if threat_count > 0 then
    local center_alignment =
      (inward_x * repulsion_unit_x) + (inward_y * repulsion_unit_y)
    if center_alignment < 0.0 then
      inward_x = inward_x - repulsion_unit_x * center_alignment
      inward_y = inward_y - repulsion_unit_y * center_alignment
      inward_x, inward_y = normalize(inward_x, inward_y)
    end
    local repulsion_weight = fleeing and 1.65 or 1.0
    local center_weight = (fleeing and 0.12 or 0.16) +
      math.min(
        perimeter_bias * (fleeing and 0.8 or 1.1),
        fleeing and 0.32 or 0.48)
    direction_x = repulsion_unit_x * repulsion_weight +
      inward_x * center_weight
    direction_y = repulsion_unit_y * repulsion_weight +
      inward_y * center_weight
  else
    local radial_x, radial_y, radial_distance = normalize(
      bot_x - arena.center_x,
      bot_y - arena.center_y)
    if radial_distance <= 0.0001 then
      local angle = ((tonumber(now_ms) or 0) / 1000.0) * 0.75
      radial_x, radial_y = math.cos(angle), math.sin(angle)
    end
    local tangent_x, tangent_y = -radial_y, radial_x
    local center_weight = 0.12 + math.max(edge_pressure - 0.55, 0.0) * 1.8
    direction_x = tangent_x + inward_x * center_weight
    direction_y = tangent_y + inward_y * center_weight
  end

  local normalized_x, normalized_y, normalized_length =
    normalize(direction_x, direction_y)
  if normalized_length <= 0.0001 then
    normalized_x, normalized_y = inward_x, inward_y
  end
  if normalized_x == 0.0 and normalized_y == 0.0 then
    normalized_x = 1.0
  end
  return normalized_x, normalized_y, threat_count, nearest_threat_distance,
    edge_pressure
end

function steering.movement_candidates(
    bot_x,
    bot_y,
    direction_x,
    direction_y,
    arena,
    lookahead)
  local angles = {
    0.0,
    math.pi / 6.0,
    -math.pi / 6.0,
    math.pi / 3.0,
    -math.pi / 3.0,
    math.pi / 2.0,
    -math.pi / 2.0,
    math.pi,
  }
  local candidates = {}
  for index, angle in ipairs(angles) do
    local cosine = math.cos(angle)
    local sine = math.sin(angle)
    local rotated_x = direction_x * cosine - direction_y * sine
    local rotated_y = direction_x * sine + direction_y * cosine
    local distance = lookahead * (index <= 3 and 1.0 or 0.68)
    local target_x = clamp(
      bot_x + rotated_x * distance,
      arena.minimum_x + arena.margin_x,
      arena.maximum_x - arena.margin_x)
    local target_y = clamp(
      bot_y + rotated_y * distance,
      arena.minimum_y + arena.margin_y,
      arena.maximum_y - arena.margin_y)
    table.insert(candidates, {x = target_x, y = target_y})
  end
  return candidates
end

return steering
