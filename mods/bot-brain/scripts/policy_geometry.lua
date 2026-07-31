local geometry = {}
local Cache = {}
Cache.__index = Cache

local EPSILON = 0.0000001

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
  if length <= EPSILON then
    return 0.0, 0.0, 0.0
  end
  return x / length, y / length, length
end

local function closest_point_on_segment(x, y, ax, ay, bx, by)
  local segment_x = bx - ax
  local segment_y = by - ay
  local length_squared =
    segment_x * segment_x + segment_y * segment_y
  if length_squared <= EPSILON then
    local dx = ax - x
    local dy = ay - y
    return ax, ay, dx * dx + dy * dy
  end
  local t =
    ((x - ax) * segment_x + (y - ay) * segment_y) /
    length_squared
  t = math.max(0.0, math.min(1.0, t))
  local closest_x = ax + segment_x * t
  local closest_y = ay + segment_y * t
  local dx = closest_x - x
  local dy = closest_y - y
  return closest_x, closest_y, dx * dx + dy * dy
end

local function point_in_polygon(x, y, points)
  if #points < 3 then
    return false
  end
  local inside = false
  local previous = points[#points]
  for _, current in ipairs(points) do
    local current_y = number(current.y)
    local previous_y = number(previous.y)
    local crosses =
      ((current_y > y) ~= (previous_y > y)) and
      (x <
        (number(previous.x) - number(current.x)) *
          (y - current_y) /
          (previous_y - current_y) +
        number(current.x))
    if crosses then
      inside = not inside
    end
    previous = current
  end
  return inside
end

local function closest_point_on_polygon(x, y, points)
  local best_x = x
  local best_y = y
  local best_distance_squared = math.huge
  if #points == 0 then
    return best_x, best_y, best_distance_squared
  end
  local previous = points[#points]
  for _, current in ipairs(points) do
    local closest_x, closest_y, distance_squared =
      closest_point_on_segment(
        x,
        y,
        number(previous.x),
        number(previous.y),
        number(current.x),
        number(current.y))
    if distance_squared < best_distance_squared then
      best_x = closest_x
      best_y = closest_y
      best_distance_squared = distance_squared
    end
    previous = current
  end
  return best_x, best_y, best_distance_squared
end

local function copy_points(source)
  local points = {}
  for _, point in ipairs(source or {}) do
    local x = tonumber(point.x)
    local y = tonumber(point.y)
    if finite_number(x) and finite_number(y) then
      points[#points + 1] = {x = x, y = y}
    end
  end
  return points
end

local function copy_circle(source)
  return {
    geometry_id = source.geometry_id,
    native_type_id = number(source.native_type_id),
    x = number(source.x),
    y = number(source.y),
    radius = math.max(number(source.radius), 0.0),
    path_blocks = source.path_blocks == true,
    destructible = source.destructible == true,
    destructible_resolved =
      source.destructible_resolved == true,
    dynamic = source.dynamic == true,
    kind = "circle",
  }
end

local function copy_segment(source)
  return {
    geometry_id = source.geometry_id,
    native_type_id = number(source.native_type_id),
    start_x = number(source.start_x),
    start_y = number(source.start_y),
    end_x = number(source.end_x),
    end_y = number(source.end_y),
    path_blocks = source.path_blocks == true,
    destructible = source.destructible == true,
    destructible_resolved =
      source.destructible_resolved == true,
    dynamic = source.dynamic == true,
    kind = "segment",
  }
end

local function copy_polygon(source)
  return {
    geometry_id = source.geometry_id,
    native_type_id = number(source.native_type_id),
    bounds_x = number(source.bounds_x),
    bounds_y = number(source.bounds_y),
    bounds_w = math.max(number(source.bounds_w), 0.0),
    bounds_h = math.max(number(source.bounds_h), 0.0),
    path_blocks = source.path_blocks == true,
    destructible = source.destructible == true,
    destructible_resolved =
      source.destructible_resolved == true,
    dynamic = source.dynamic == true,
    points = copy_points(source.points),
    kind = "polygon",
  }
end

local function usable_snapshot(snapshot)
  return type(snapshot) == "table" and
    snapshot.valid == true and
    snapshot.refresh_pending == false and
    snapshot.observer_radius_resolved == true and
    number(snapshot.observer_radius) > 0.0 and
    type(snapshot.circles) == "table" and
    type(snapshot.segments) == "table" and
    type(snapshot.polygons) == "table" and
    type(snapshot.participant_radii) == "table"
end

local function revision_key(snapshot)
  return table.concat({
    tostring(snapshot.scene_epoch or 0),
    tostring(snapshot.run_nonce or 0),
    tostring(snapshot.static_revision or 0),
    tostring(snapshot.dynamic_revision or 0),
  }, ":")
end

function Cache:reset(scene_key)
  self.scene_key = scene_key
  self.snapshot = nil
  self.primitives = {}
  self.participant_radii = {}
  self.observer_radius = 0.0
  self.accepted_revision_key = nil
  self.next_request_ms = 0.0
  self.revision = self.revision + 1
end

function Cache:adopt(snapshot)
  local key = revision_key(snapshot)
  self.snapshot = snapshot
  self.observer_radius =
    math.max(number(snapshot.observer_radius), 0.0)
  self.participant_collision_padding =
    math.max(
      number(snapshot.participant_collision_padding),
      0.0)

  local participant_radii = {}
  for _, row in ipairs(snapshot.participant_radii) do
    local participant_id = number(row.participant_id)
    if participant_id > 0 and
        row.radius_resolved == true and
        number(row.radius) > 0.0 then
      participant_radii[participant_id] =
        number(row.radius)
    end
  end
  self.participant_radii = participant_radii

  if key ~= self.accepted_revision_key then
    local primitives = {}
    for _, row in ipairs(snapshot.circles) do
      primitives[#primitives + 1] = copy_circle(row)
    end
    for _, row in ipairs(snapshot.segments) do
      primitives[#primitives + 1] = copy_segment(row)
    end
    for _, row in ipairs(snapshot.polygons) do
      local polygon = copy_polygon(row)
      if #polygon.points >= 3 then
        primitives[#primitives + 1] = polygon
      end
    end
    self.primitives = primitives
    self.accepted_revision_key = key
    self.geometry_build_count =
      self.geometry_build_count + 1
    self.revision = self.revision + 1
  end
  self.adoption_count = self.adoption_count + 1
end

function Cache:refresh(now_ms, scene_key, participant_id)
  now_ms = number(now_ms)
  scene_key = tostring(scene_key or "")
  participant_id = math.floor(number(participant_id))
  if self.scene_key == nil then
    self.scene_key = scene_key
  elseif self.scene_key ~= scene_key then
    self:reset(scene_key)
  end
  if participant_id <= 0 or now_ms < self.next_request_ms then
    return false
  end

  self.request_count = self.request_count + 1
  local ok, snapshot = pcall(
    self.get_collision_geometry,
    participant_id)
  if ok and usable_snapshot(snapshot) then
    self:adopt(snapshot)
    self.next_request_ms =
      now_ms + self.spec.nav_refresh_ms
    return true
  end

  self.pending_count = self.pending_count + 1
  self.next_request_ms = now_ms + self.native_retry_ms
  return false
end

local function participant_position(row)
  local x = tonumber(row.x)
  local y = tonumber(row.y)
  if not finite_number(x) or not finite_number(y) then
    local position = type(row.position) == "table" and
      row.position or {}
    x = tonumber(position.x)
    y = tonumber(position.y)
  end
  if not finite_number(x) or not finite_number(y) then
    return nil, nil
  end
  return x, y
end

function Cache:participant_primitives(participants, observer_id)
  local result = {}
  for _, participant in ipairs(participants or {}) do
    local participant_id =
      math.floor(number(participant.participant_id))
    local x, y = participant_position(participant)
    if participant_id > 0 and
        participant_id ~= observer_id and
        participant.in_run == true and
        x ~= nil and y ~= nil and
        number(participant.life_current, 1.0) > 0.0 then
      local radius =
        self.participant_radii[participant_id] or
        self.observer_radius
      if radius > 0.0 then
        result[#result + 1] = {
          geometry_id =
            "participant:" .. tostring(participant_id),
          native_type_id = 0,
          x = x,
          y = y,
          radius = radius +
            self.participant_collision_padding,
          path_blocks = true,
          destructible = false,
          destructible_resolved = true,
          dynamic = true,
          participant_id = participant_id,
          kind = "circle",
        }
      end
    end
  end
  return result
end

local function circle_overlap(
    primitive,
    x,
    y,
    observer_radius)
  local dx = x - primitive.x
  local dy = y - primitive.y
  local combined = observer_radius + primitive.radius
  return dx * dx + dy * dy <= combined * combined
end

local function segment_overlap(
    primitive,
    x,
    y,
    observer_radius)
  local _, _, distance_squared = closest_point_on_segment(
    x,
    y,
    primitive.start_x,
    primitive.start_y,
    primitive.end_x,
    primitive.end_y)
  return distance_squared <=
    observer_radius * observer_radius
end

local function polygon_overlap(
    primitive,
    x,
    y,
    observer_radius)
  if point_in_polygon(x, y, primitive.points) then
    return true
  end
  local _, _, distance_squared =
    closest_point_on_polygon(x, y, primitive.points)
  return distance_squared <=
    observer_radius * observer_radius
end

function Cache:walkable_at(
    world_x,
    world_y,
    participants,
    observer_id)
  if self.snapshot == nil or self.observer_radius <= 0.0 then
    return false
  end
  local x = number(world_x)
  local y = number(world_y)
  for _, primitive in ipairs(self.primitives) do
    if primitive.path_blocks == true then
      if (primitive.kind == "circle" and
          circle_overlap(
            primitive,
            x,
            y,
            self.observer_radius)) or
          (primitive.kind == "segment" and
           segment_overlap(
             primitive,
             x,
             y,
             self.observer_radius)) or
          (primitive.kind == "polygon" and
           polygon_overlap(
             primitive,
             x,
             y,
             self.observer_radius)) then
        return false
      end
    end
  end
  for _, primitive in ipairs(
      self:participant_primitives(
        participants,
        observer_id)) do
    if circle_overlap(
        primitive,
        x,
        y,
        self.observer_radius) then
      return false
    end
  end
  return true
end

local function circle_feature(
    primitive,
    x,
    y,
    observer_radius)
  local outward_x, outward_y, center_distance =
    normalize(x - primitive.x, y - primitive.y)
  if center_distance <= EPSILON then
    outward_x = 1.0
    outward_y = 0.0
  end
  local closest_x =
    primitive.x + outward_x * primitive.radius
  local closest_y =
    primitive.y + outward_y * primitive.radius
  local vector_x = closest_x - x
  local vector_y = closest_y - y
  local nearest_x, nearest_y =
    normalize(vector_x, vector_y)
  return {
    nearest_dx = nearest_x,
    nearest_dy = nearest_y,
    clearance =
      math.max(
        center_distance - primitive.radius -
          observer_radius,
        0.0),
    normal_dx = outward_x,
    normal_dy = outward_y,
    radius = primitive.radius,
    extent_x = 0.0,
    extent_y = 0.0,
  }
end

local function segment_feature(
    primitive,
    x,
    y,
    observer_radius)
  local closest_x, closest_y, distance_squared =
    closest_point_on_segment(
      x,
      y,
      primitive.start_x,
      primitive.start_y,
      primitive.end_x,
      primitive.end_y)
  local vector_x = closest_x - x
  local vector_y = closest_y - y
  local nearest_x, nearest_y, distance =
    normalize(vector_x, vector_y)
  local normal_x, normal_y = normalize(
    x - closest_x,
    y - closest_y)
  return {
    nearest_dx = nearest_x,
    nearest_dy = nearest_y,
    clearance = math.max(distance - observer_radius, 0.0),
    normal_dx = normal_x,
    normal_dy = normal_y,
    radius = 0.0,
    extent_x =
      math.abs(primitive.end_x - primitive.start_x) * 0.5,
    extent_y =
      math.abs(primitive.end_y - primitive.start_y) * 0.5,
  }
end

local function polygon_feature(
    primitive,
    x,
    y,
    observer_radius)
  local closest_x, closest_y, distance_squared =
    closest_point_on_polygon(x, y, primitive.points)
  local vector_x = closest_x - x
  local vector_y = closest_y - y
  local nearest_x, nearest_y, distance =
    normalize(vector_x, vector_y)
  local normal_x, normal_y = normalize(
    x - closest_x,
    y - closest_y)
  local inside = point_in_polygon(x, y, primitive.points)
  return {
    nearest_dx = nearest_x,
    nearest_dy = nearest_y,
    clearance =
      inside and 0.0 or
        math.max(distance - observer_radius, 0.0),
    normal_dx = normal_x,
    normal_dy = normal_y,
    radius = 0.0,
    extent_x = primitive.bounds_w * 0.5,
    extent_y = primitive.bounds_h * 0.5,
  }
end

local function feature_for_primitive(
    primitive,
    x,
    y,
    observer_radius)
  local feature
  if primitive.kind == "circle" then
    feature = circle_feature(
      primitive,
      x,
      y,
      observer_radius)
  elseif primitive.kind == "segment" then
    feature = segment_feature(
      primitive,
      x,
      y,
      observer_radius)
  else
    feature = polygon_feature(
      primitive,
      x,
      y,
      observer_radius)
  end
  feature.geometry_id = primitive.geometry_id
  feature.kind = primitive.kind
  feature.is_participant =
    primitive.participant_id ~= nil
  feature.is_destructible =
    primitive.destructible_resolved == true and
    primitive.destructible == true
  return feature
end

function Cache:nearest_obstacles(
    world_x,
    world_y,
    participants,
    observer_id)
  if self.snapshot == nil then
    return {}
  end
  local x = number(world_x)
  local y = number(world_y)
  local rows = {}
  for _, primitive in ipairs(self.primitives) do
    if primitive.path_blocks == true then
      rows[#rows + 1] = feature_for_primitive(
        primitive,
        x,
        y,
        self.observer_radius)
    end
  end
  for _, primitive in ipairs(
      self:participant_primitives(
        participants,
        observer_id)) do
    rows[#rows + 1] = feature_for_primitive(
      primitive,
      x,
      y,
      self.observer_radius)
  end
  table.sort(rows, function(left, right)
    if math.abs(left.clearance - right.clearance) >
        EPSILON then
      return left.clearance < right.clearance
    end
    return tostring(left.geometry_id) <
      tostring(right.geometry_id)
  end)
  return rows
end

function Cache:features(
    world_x,
    world_y,
    participants,
    observer_id)
  local clearances = {}
  local patch = {}
  if self.snapshot == nil then
    for index = 1, 8 do
      clearances[index] = 0.0
    end
    for index = 1, 48 do
      patch[index] = 0.0
    end
    return clearances, patch, {}
  end

  for direction_index = 2, #self.spec.movement_actions do
    local action = self.spec.movement_actions[direction_index]
    local clearance = self.spec.ray_range
    for distance = self.spec.ray_step,
        self.spec.ray_range,
        self.spec.ray_step do
      if not self:walkable_at(
          world_x + action.x * distance,
          world_y + action.y * distance,
          participants,
          observer_id) then
        clearance = distance
        break
      end
    end
    clearances[#clearances + 1] =
      math.max(
        0.0,
        math.min(
          clearance / self.spec.ray_range,
          1.0))
  end

  local radius = self.spec.patch_radius
  for row_offset = -radius, radius do
    for column_offset = -radius, radius do
      if row_offset ~= 0 or column_offset ~= 0 then
        patch[#patch + 1] =
          self:walkable_at(
            world_x +
              column_offset * self.spec.patch_spacing,
            world_y +
              row_offset * self.spec.patch_spacing,
            participants,
            observer_id) and 1.0 or 0.0
      end
    end
  end
  return clearances,
    patch,
    self:nearest_obstacles(
      world_x,
      world_y,
      participants,
      observer_id)
end

function Cache:status()
  return {
    scene_key = self.scene_key,
    ready = self.snapshot ~= nil,
    revision = self.revision,
    accepted_revision_key = self.accepted_revision_key,
    request_count = self.request_count,
    pending_count = self.pending_count,
    adoption_count = self.adoption_count,
    geometry_build_count = self.geometry_build_count,
    next_request_ms = self.next_request_ms,
    primitive_count = #self.primitives,
    observer_radius = self.observer_radius,
  }
end

function geometry.new(spec, get_collision_geometry)
  if get_collision_geometry == nil then
    get_collision_geometry = function(participant_id)
      return sd.nav.get_collision_geometry(participant_id)
    end
  end
  return setmetatable({
    spec = assert(spec),
    get_collision_geometry = assert(get_collision_geometry),
    native_retry_ms = 500,
    scene_key = nil,
    snapshot = nil,
    primitives = {},
    participant_radii = {},
    observer_radius = 0.0,
    participant_collision_padding = 0.0,
    accepted_revision_key = nil,
    next_request_ms = 0.0,
    revision = 0,
    request_count = 0,
    pending_count = 0,
    adoption_count = 0,
    geometry_build_count = 0,
  }, Cache)
end

return geometry
