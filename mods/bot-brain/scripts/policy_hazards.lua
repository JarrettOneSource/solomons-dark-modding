local hazards = {}
local Resolver = {}
Resolver.__index = Resolver

local KNOWN_TYPES = {
  0x07D3, 0x07D4, 0x07D5, 0x07D6, 0x07DA, 0x07DE, 0x07DF,
  0x07E0, 0x07E1, 0x07E2, 0x07E4, 0x07E5, 0x07EB, 0x07EC,
  0x07F3, 0x07FB, 0x0800, 0x0804, 0x0808, 0x080B, 0x080C,
  0x07E3, 0x07E6, 0x07E7, 0x07E8, 0x07E9, 0x07F0, 0x07F1,
  0x07F5, 0x07F7, 0x07FA, 0x07FE, 0x0801, 0x0802, 0x0805,
  0x0806, 0x0807, 0x07FF,
}

local TYPE_INDEX = {}
for index, type_id in ipairs(KNOWN_TYPES) do
  TYPE_INDEX[type_id] = index
end

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

local function normalize(x, y)
  local length = math.sqrt(x * x + y * y)
  if length <= 0.000001 then
    return 0.0, 0.0, 0.0
  end
  return x / length, y / length, length
end

local function default_read()
  local ok, snapshot = pcall(
    sd.world.get_replicated_hazards)
  if ok and type(snapshot) == "table" then
    return snapshot
  end
  return {}
end

local function impact_time(
    relative_x,
    relative_y,
    velocity_x,
    velocity_y,
    combined_radius)
  local a =
    velocity_x * velocity_x + velocity_y * velocity_y
  if a <= 0.000001 then
    return 0.0
  end
  local b = 2.0 *
    (relative_x * velocity_x + relative_y * velocity_y)
  local c =
    relative_x * relative_x +
    relative_y * relative_y -
    combined_radius * combined_radius
  if c <= 0.0 then
    return 0.0
  end
  local discriminant = b * b - 4.0 * a * c
  if discriminant < 0.0 then
    return 0.0
  end
  local root =
    (-b - math.sqrt(discriminant)) / (2.0 * a)
  return root >= 0.0 and root or 0.0
end

function Resolver:capture(
    bot_x,
    bot_y,
    participant_id,
    observer_radius,
    now_ms)
  local snapshot = self.read()
  snapshot = type(snapshot) == "table" and snapshot or {}
  local rows = {}
  local next_history = {}
  for source_index, hazard in
      ipairs(snapshot.hazards or {}) do
    local hazard_id = number(hazard.hazard_id)
    local x = tonumber(hazard.x)
    local y = tonumber(hazard.y)
    if hazard_id > 0 and
        hazard.active == true and
        hazard.hostile == true and
        finite_number(x) and finite_number(y) then
      local motion_x = number(hazard.motion_x)
      local motion_y = number(hazard.motion_y)
      local motion_resolved =
        hazard.motion_resolved == true
      local previous = self.history[hazard_id]
      if not motion_resolved and
          type(previous) == "table" then
        local elapsed_ms = now_ms - number(previous.now_ms)
        if elapsed_ms > 0.0 then
          motion_x =
            (x - number(previous.x)) * 1000.0 /
            elapsed_ms
          motion_y =
            (y - number(previous.y)) * 1000.0 /
            elapsed_ms
          motion_resolved = true
        end
      end
      next_history[hazard_id] = {
        x = x,
        y = y,
        now_ms = now_ms,
      }

      local relative_x = x - bot_x
      local relative_y = y - bot_y
      local dx, dy, distance =
        normalize(relative_x, relative_y)
      local radius = math.max(number(hazard.radius), 0.0)
      local type_id = math.floor(number(hazard.native_type_id))
      local type_index = TYPE_INDEX[type_id]
      local kind = tostring(hazard.kind or "unknown")
      rows[#rows + 1] = {
        hazard_id = hazard_id,
        source_index = source_index,
        type_known =
          hazard.type_known == true and
          type_index ~= nil,
        hazard_type_index_scaled =
          type_index ~= nil and
            type_index / self.spec.hazard_type_scale or 0.0,
        dx = dx,
        dy = dy,
        distance = math.max(distance - radius, 0.0),
        velocity_x = motion_resolved and motion_x or 0.0,
        velocity_y = motion_resolved and motion_y or 0.0,
        radius = radius,
        time_to_contact = motion_resolved and
          impact_time(
            relative_x,
            relative_y,
            motion_x,
            motion_y,
            radius + math.max(number(observer_radius), 0.0)) or
          0.0,
        remaining_time =
          hazard.lifetime_resolved == true and
            math.max(
              number(hazard.remaining_seconds),
              0.0) or 0.0,
        kind = kind,
        kind_projectile = kind == "projectile",
        kind_area = kind == "area",
        kind_beam = kind == "beam",
        homing = hazard.homing == true,
        targeting_self =
          number(hazard.target_participant_id) ==
            participant_id,
        source_enemy =
          number(hazard.source_network_actor_id) > 0 or
          number(hazard.source_participant_id) == 0,
      }
    end
  end
  self.history = next_history
  table.sort(rows, function(left, right)
    if math.abs(left.distance - right.distance) >
        0.000001 then
      return left.distance < right.distance
    end
    if left.hazard_id ~= right.hazard_id then
      return left.hazard_id < right.hazard_id
    end
    return left.source_index < right.source_index
  end)
  return {
    snapshot = snapshot,
    rows = rows,
    total_count = math.max(
      number(snapshot.hazard_total_count, #rows),
      #rows),
  }
end

function Resolver:reset()
  self.history = {}
end

function hazards.new(spec, api)
  api = type(api) == "table" and api or {}
  return setmetatable({
    spec = assert(spec),
    read = api.read or default_read,
    history = {},
  }, Resolver)
end

return hazards
