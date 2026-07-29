local geometry = {}
local Cache = {}
Cache.__index = Cache

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

local function positive_integer(value)
  value = number(value, -1)
  return value >= 1 and value == math.floor(value)
end

local function lattice_index(row, column, column_count)
  return row * column_count + column + 1
end

function Cache:reset(scene_key)
  self.scene_key = scene_key
  self.grid = nil
  self.walkability = nil
  self.sample_rows = 0
  self.sample_columns = 0
  self.next_request_ms = 0
  self.revision = self.revision + 1
end

function Cache:adopt(grid)
  local subdivisions = number(grid.subdivisions)
  local rows = number(grid.width) * subdivisions
  local columns = number(grid.height) * subdivisions
  local walkability = {}

  for _, cell in ipairs(grid.cells) do
    local grid_x = number(cell.grid_x, -1)
    local grid_y = number(cell.grid_y, -1)
    if grid_x >= 0 and grid_y >= 0 then
      for _, sample in ipairs(cell.samples or {}) do
        local sample_x = number(sample.sample_x, -1)
        local sample_y = number(sample.sample_y, -1)
        if sample_x >= 0 and sample_x < subdivisions and
            sample_y >= 0 and sample_y < subdivisions then
          local row = grid_x * subdivisions + sample_x
          local column = grid_y * subdivisions + sample_y
          walkability[
            lattice_index(row, column, columns)] =
              sample.traversable == true
        end
      end
    end
  end

  self.grid = grid
  self.walkability = walkability
  self.sample_rows = rows
  self.sample_columns = columns
  self.sample_width = number(grid.cell_width) / subdivisions
  self.sample_height = number(grid.cell_height) / subdivisions
  self.revision = self.revision + 1
  self.adoption_count = self.adoption_count + 1
  self.grid_build_count = self.grid_build_count + 1
end

local function usable_grid(grid, subdivisions)
  return type(grid) == "table" and
    grid.refresh_pending == false and
    number(grid.subdivisions) == subdivisions and
    positive_integer(grid.width) and
    positive_integer(grid.height) and
    finite_number(tonumber(grid.cell_width)) and
    tonumber(grid.cell_width) > 0.0 and
    finite_number(tonumber(grid.cell_height)) and
    tonumber(grid.cell_height) > 0.0 and
    type(grid.cells) == "table"
end

function Cache:refresh(now_ms, scene_key)
  now_ms = number(now_ms)
  scene_key = tostring(scene_key or "")
  if self.scene_key == nil then
    self.scene_key = scene_key
  elseif self.scene_key ~= scene_key then
    self:reset(scene_key)
  end

  if now_ms < self.next_request_ms then
    return false
  end

  self.request_count = self.request_count + 1
  local ok, grid = pcall(
    self.get_grid,
    self.spec.nav_subdivisions)
  if ok and usable_grid(grid, self.spec.nav_subdivisions) then
    self:adopt(grid)
    self.next_request_ms =
      now_ms + self.spec.nav_refresh_ms
    return true
  end

  self.pending_count = self.pending_count + 1
  self.next_request_ms =
    now_ms + self.native_retry_ms
  return false
end

function Cache:walkable_at(world_x, world_y)
  if self.walkability == nil then
    return false
  end
  world_x = number(world_x, -1.0)
  world_y = number(world_y, -1.0)
  if world_x < 0.0 or world_y < 0.0 then
    return false
  end

  local column = math.floor(world_x / self.sample_width)
  local row = math.floor(world_y / self.sample_height)
  if row < 0 or row >= self.sample_rows or
      column < 0 or column >= self.sample_columns then
    return false
  end
  return self.walkability[
    lattice_index(
      row,
      column,
      self.sample_columns)] == true
end

function Cache:features(world_x, world_y)
  world_x = number(world_x)
  world_y = number(world_y)
  if self.walkability == nil then
    local clearances = {}
    local patch = {}
    for index = 1, 8 do
      clearances[index] = 0.0
    end
    for index = 1, 48 do
      patch[index] = 0.0
    end
    return clearances, patch
  end

  local clearances = {}
  for direction_index = 2, #self.spec.movement_actions do
    local action = self.spec.movement_actions[direction_index]
    local clearance = self.spec.ray_range
    local distance = self.spec.ray_step
    while distance <= self.spec.ray_range do
      local sample_x = world_x + action.x * distance
      local sample_y = world_y + action.y * distance
      if not self:walkable_at(sample_x, sample_y) then
        clearance = distance
        break
      end
      distance = distance + self.spec.ray_step
    end
    clearances[#clearances + 1] =
      math.max(
        0.0,
        math.min(clearance / self.spec.ray_range, 1.0))
  end

  local patch = {}
  local radius = self.spec.patch_radius
  for row_offset = -radius, radius do
    for column_offset = -radius, radius do
      if row_offset ~= 0 or column_offset ~= 0 then
        patch[#patch + 1] =
          self:walkable_at(
            world_x +
              column_offset * self.spec.patch_spacing,
            world_y +
              row_offset * self.spec.patch_spacing) and
          1.0 or 0.0
      end
    end
  end
  return clearances, patch
end

function Cache:status()
  return {
    scene_key = self.scene_key,
    ready = self.grid ~= nil,
    revision = self.revision,
    request_count = self.request_count,
    pending_count = self.pending_count,
    adoption_count = self.adoption_count,
    grid_build_count = self.grid_build_count,
    next_request_ms = self.next_request_ms,
  }
end

function geometry.new(spec, get_grid)
  if get_grid == nil then
    get_grid = function(subdivisions)
      return sd.nav.get_grid(subdivisions)
    end
  end
  return setmetatable({
    spec = assert(spec),
    get_grid = assert(get_grid),
    native_retry_ms = 500,
    scene_key = nil,
    grid = nil,
    walkability = nil,
    sample_rows = 0,
    sample_columns = 0,
    sample_width = 0.0,
    sample_height = 0.0,
    next_request_ms = 0,
    revision = 0,
    request_count = 0,
    pending_count = 0,
    adoption_count = 0,
    grid_build_count = 0,
  }, Cache)
end

return geometry
