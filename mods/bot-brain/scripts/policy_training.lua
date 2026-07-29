local training = {}
local Controller = {}
Controller.__index = Controller

local function copy_array(value)
  local result = {}
  for index, item in ipairs(value or {}) do
    result[index] = item
  end
  return result
end

local function copy_mask(value)
  local result = {}
  for index, item in ipairs(value or {}) do
    result[index] = item == true
  end
  return result
end

local function copy_metrics(value)
  value = type(value) == "table" and value or {}
  local enemy_health = {}
  for actor_id, ratio in pairs(value.enemy_health or {}) do
    enemy_health[actor_id] = ratio
  end
  return {
    hp_ratio = value.hp_ratio,
    mana_ratio = value.mana_ratio,
    wave = value.wave,
    alive = value.alive,
    enemy_count = value.enemy_count,
    enemy_health = enemy_health,
  }
end

local function compact(controller)
  if controller.head <= 1024 or
      controller.head <= controller.tail / 2 then
    return
  end
  local next_buffer = {}
  for index = controller.head, controller.tail do
    next_buffer[#next_buffer + 1] =
      controller.buffer[index]
  end
  controller.buffer = next_buffer
  controller.head = 1
  controller.tail = #next_buffer
end

function Controller:buffer_size()
  return math.max(self.tail - self.head + 1, 0)
end

function Controller:discard_pending()
  for context in pairs(self.contexts) do
    context.policy_pending = nil
  end
end

function Controller:append(record)
  if self:buffer_size() >= self.capacity then
    self.buffer[self.head] = nil
    self.head = self.head + 1
    self.dropped = self.dropped + 1
  end
  self.tail = self.tail + 1
  self.buffer[self.tail] = record
  self.recorded = self.recorded + 1
  compact(self)
end

function Controller:reward(previous, current, terminal)
  local reward = 0.002
  local hp_delta =
    (current.hp_ratio or 0.0) -
    (previous.hp_ratio or 0.0)
  reward = reward + hp_delta * 1.25
  for actor_id, previous_ratio in
      pairs(previous.enemy_health or {}) do
    local current_ratio =
      (current.enemy_health or {})[actor_id] or 0.0
    if current_ratio < previous_ratio then
      reward =
        reward + (previous_ratio - current_ratio) * 0.65
    end
  end
  local wave_delta =
    (current.wave or 0) - (previous.wave or 0)
  if wave_delta > 0 then
    reward = reward + math.min(wave_delta, 1) * 1.5
  end
  if terminal == true and current.alive ~= true then
    reward = reward - 2.0
  end
  return math.max(-4.0, math.min(4.0, reward))
end

function Controller:finish_pending(context, metrics, terminal)
  local pending = context.policy_pending
  if pending == nil then
    return
  end
  pending.reward = self:reward(
    pending.metrics,
    metrics,
    terminal)
  pending.done = terminal == true
  pending.metrics = nil
  self:append(pending)
  context.policy_pending = nil
end

function Controller:record(
    context,
    capture,
    decision,
    simulation_tick)
  self.contexts[context] = true
  if self.enabled ~= true then
    context.policy_pending = nil
    return
  end
  self:finish_pending(context, capture.metrics, false)
  context.policy_pending = {
    trajectory_version = self.spec.trajectory_version,
    episode_id = self.episode_id,
    participant_id = context.participant_id,
    simulation_tick = simulation_tick or 0,
    observation = copy_array(capture.values),
    movement_mask = copy_mask(capture.movement_mask),
    target_mask = copy_mask(capture.target_mask),
    cast_mask = copy_mask(capture.cast_mask),
    movement_action = decision.movement_action,
    target_action = decision.target_action,
    cast_action = decision.cast_action,
    old_log_probability = decision.log_probability,
    old_value = decision.value,
    reward = 0.0,
    done = false,
    metrics = copy_metrics(capture.metrics),
  }
end

function Controller:terminal(context, metrics)
  self.contexts[context] = true
  if self.enabled ~= true then
    context.policy_pending = nil
    return
  end
  metrics = metrics or {
    hp_ratio = 0.0,
    mana_ratio = 0.0,
    wave = 0,
    alive = false,
    enemy_count = 0,
    enemy_health = {},
  }
  self:finish_pending(context, metrics, true)
end

function Controller:begin_episode()
  self.episode_id = self.episode_id + 1
  return self.episode_id
end

function Controller:enable(options)
  if self.runtime == nil then
    error(
      "ML policy v2 weights are unavailable until Phase 4")
  end
  options = type(options) == "table" and options or {}
  local capacity = math.floor(
    tonumber(options.capacity) or self.capacity)
  self.capacity = math.max(128, math.min(capacity, 50000))
  self.runtime:set_seed(options.seed or 20260729)
  self.enabled = true
  self:begin_episode()
  return self:status()
end

function Controller:disable()
  self.enabled = false
  self:discard_pending()
  return self:status()
end

function Controller:clear()
  self:discard_pending()
  self.buffer = {}
  self.head = 1
  self.tail = 0
  self.dropped = 0
  self.recorded = 0
  return self:status()
end

function Controller:drain(max_records)
  local available = self:buffer_size()
  local requested = math.floor(
    tonumber(max_records) or available)
  requested = math.max(0, math.min(requested, available))
  local records = {}
  for _ = 1, requested do
    records[#records + 1] = self.buffer[self.head]
    self.buffer[self.head] = nil
    self.head = self.head + 1
  end
  compact(self)
  return {
    records = records,
    status = self:status(),
  }
end

function Controller:load_parameters(candidate)
  if self.runtime == nil then
    error(
      "ML policy v2 weights are unavailable until Phase 4")
  end
  local generation = self.runtime:load(candidate)
  return {
    generation = generation,
    status = self:status(),
  }
end

function Controller:status()
  local policy_status
  if self.runtime ~= nil then
    policy_status = self.runtime:status()
  else
    policy_status = {
      available = false,
      version = self.spec.model_version,
      architecture = self.spec.architecture,
    }
  end
  return {
    enabled = self.enabled,
    episode_id = self.episode_id,
    capacity = self.capacity,
    buffered = self:buffer_size(),
    dropped = self.dropped,
    recorded = self.recorded,
    policy = policy_status,
  }
end

function training.new(spec, runtime)
  local controller = setmetatable({
    spec = assert(spec),
    runtime = runtime,
    enabled = false,
    episode_id = 0,
    capacity = 8192,
    buffer = {},
    contexts = setmetatable({}, {__mode = "k"}),
    head = 1,
    tail = 0,
    dropped = 0,
    recorded = 0,
  }, Controller)
  rawset(_G, "bot_policy_training", {
    enable = function(options)
      return controller:enable(options)
    end,
    disable = function()
      return controller:disable()
    end,
    clear = function()
      return controller:clear()
    end,
    drain = function(max_records)
      return controller:drain(max_records)
    end,
    status = function()
      return controller:status()
    end,
    load_parameters = function(candidate)
      return controller:load_parameters(candidate)
    end,
  })
  return controller
end

return training
