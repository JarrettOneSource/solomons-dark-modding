local training = {}
local Controller = {}
Controller.__index = Controller

-- V3-7 calibration, stock wave seed 29271575: 39 learned-attributed kills
-- observed through waves 1-10. Credited XP ranged 3.442497..3.825001 with
-- median 3.824997, so 25 maps the typical early kill to 0.153 reward.
local XP_SCALE = 25.0
training.XP_SCALE = XP_SCALE

local function copy_array(value)
  local result = {}
  for index, item in ipairs(value or {}) do
    result[index] = item
  end
  return result
end

local function copy_rows(value)
  local result = {}
  for index, row in ipairs(value or {}) do
    result[index] = copy_array(row)
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
    experience = value.experience,
    enemy_count = value.enemy_count,
    enemy_health = enemy_health,
  }
end

local function compact(buffer, head, tail)
  if head <= 1024 or head <= tail / 2 then
    return buffer, head, tail
  end
  local next_buffer = {}
  for index = head, tail do
    next_buffer[#next_buffer + 1] = buffer[index]
  end
  return next_buffer, 1, #next_buffer
end

local function append_bounded(
    controller,
    kind,
    record)
  local buffer_name = kind .. "_buffer"
  local head_name = kind .. "_head"
  local tail_name = kind .. "_tail"
  local dropped_name = kind .. "_dropped"
  local recorded_name = kind .. "_recorded"
  local buffer = controller[buffer_name]
  local head = controller[head_name]
  local tail = controller[tail_name]
  if math.max(tail - head + 1, 0) >= controller.capacity then
    buffer[head] = nil
    head = head + 1
    controller[dropped_name] =
      controller[dropped_name] + 1
  end
  tail = tail + 1
  buffer[tail] = record
  controller[recorded_name] =
    controller[recorded_name] + 1
  buffer, head, tail = compact(buffer, head, tail)
  controller[buffer_name] = buffer
  controller[head_name] = head
  controller[tail_name] = tail
end

function Controller:buffer_size(kind)
  return math.max(
    self[kind .. "_tail"] -
      self[kind .. "_head"] + 1,
    0)
end

function Controller:discard_pending()
  for context in pairs(self.contexts) do
    context.policy_pending = nil
    context.policy_choice_pending = nil
  end
end

function Controller:reward(previous, current, terminal)
  local reward = 0.0
  local hp_delta =
    (current.hp_ratio or 0.0) -
    (previous.hp_ratio or 0.0)
  reward = reward + hp_delta * 1.25
  local xp_delta = math.max(
    0.0,
    (current.experience or 0.0) -
      (previous.experience or 0.0))
  reward = reward + xp_delta / XP_SCALE
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

function Controller:accumulate_choice_reward(context, reward)
  local pending = context.policy_choice_pending
  if pending == nil then
    return
  end
  pending.duration_steps = pending.duration_steps + 1
  pending.rewards[#pending.rewards + 1] = reward
end

function Controller:finish_pending(context, metrics, terminal)
  local pending = context.policy_pending
  if pending == nil then
    return nil
  end
  pending.reward = self:reward(
    pending.metrics,
    metrics,
    terminal)
  pending.done = terminal == true
  pending.metrics = nil
  append_bounded(self, "main", pending)
  context.policy_pending = nil
  self:accumulate_choice_reward(context, pending.reward)
  return pending.reward
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
    ability_mask = copy_mask(capture.ability_mask),
    aim_mask = copy_mask(capture.aim_mask),
    movement_action = decision.movement_action,
    target_action = decision.target_action,
    ability_action = decision.ability_action,
    aim_action = decision.aim_action,
    old_log_probability = decision.log_probability,
    old_value = decision.value,
    reward = 0.0,
    done = false,
    metrics = copy_metrics(capture.metrics),
  }
end

function Controller:finish_choice(
    context,
    next_value,
    terminal)
  local pending = context.policy_choice_pending
  if pending == nil then
    return
  end
  pending.next_value = terminal == true and
    0.0 or tonumber(next_value) or 0.0
  pending.done = terminal == true
  local reward_sum = 0.0
  for _, reward in ipairs(pending.rewards or {}) do
    reward_sum = reward_sum + (tonumber(reward) or 0.0)
  end
  if type(context.shared) == "table" and
      type(context.shared.log) == "function" then
    context.shared.log(
      context,
      "choice interval closed mode=" ..
      tostring(pending.choice_mode) ..
      " trainable=" .. tostring(pending.trainable == true) ..
      " accepted=" .. tostring(pending.accepted == true) ..
      " duration_steps=" ..
      tostring(pending.duration_steps or 0) ..
      " reward_sum=" .. tostring(reward_sum))
  end
  append_bounded(self, "choice", pending)
  context.policy_choice_pending = nil
end

function Controller:record_choice(
    context,
    event,
    decision,
    mode,
    accepted)
  self.contexts[context] = true
  if self.enabled ~= true then
    context.policy_choice_pending = nil
    return
  end
  -- The reward edge ending at this choice state belongs to the previous
  -- semi-Markov interval. Finish it before closing that choice event.
  if type(event.metrics) == "table" then
    self:finish_pending(context, event.metrics, false)
  end
  self:finish_choice(context, decision.value, false)
  context.policy_choice_pending = {
    choice_trajectory_version =
      self.spec.choice_trajectory_version,
    episode_id = self.episode_id,
    participant_id = context.participant_id,
    generation = event.generation,
    simulation_tick = event.simulation_tick,
    observation = copy_array(event.observation),
    option_descriptors =
      copy_rows(event.option_descriptors),
    option_mask = copy_mask(event.option_mask),
    selected_option = decision.choice_action,
    old_log_probability =
      tonumber(decision.log_probability) or 0.0,
    old_value = tonumber(decision.value) or 0.0,
    next_value = 0.0,
    duration_steps = 0,
    rewards = {},
    done = false,
    choice_mode = mode,
    trainable = mode == "learned",
    accepted = accepted == true,
  }
end

function Controller:terminal(context, metrics)
  self.contexts[context] = true
  if self.enabled ~= true then
    context.policy_pending = nil
    context.policy_choice_pending = nil
    return
  end
  metrics = metrics or {
    hp_ratio = 0.0,
    mana_ratio = 0.0,
    wave = 0,
    alive = false,
    experience = 0.0,
    enemy_count = 0,
    enemy_health = {},
  }
  self:finish_pending(context, metrics, true)
  self:finish_choice(context, 0.0, true)
end

function Controller:begin_episode()
  self.episode_id = self.episode_id + 1
  return self.episode_id
end

function Controller:enable(options)
  options = type(options) == "table" and options or {}
  if type(self.runtime) ~= "table" or
      type(self.runtime.set_seed) ~= "function" then
    error(
      "strict v3 policy runtime is unavailable")
  end
  local capacity = math.floor(
    tonumber(options.capacity) or self.capacity)
  self.capacity = math.max(128, math.min(capacity, 50000))
  self.runtime:set_seed(options.seed or 20260730)
  self.enabled = true
  self:begin_episode()
  return self:status()
end

function Controller:disable()
  self.enabled = false
  self:discard_pending()
  return self:status()
end

function Controller:finish_episode()
  if self.enabled ~= true then
    return self:status()
  end
  for context in pairs(self.contexts) do
    local metrics = context.policy_pending and
      context.policy_pending.metrics or nil
    self:terminal(context, metrics)
  end
  self.enabled = false
  return self:status()
end

function Controller:clear()
  self:discard_pending()
  self.main_buffer = {}
  self.main_head = 1
  self.main_tail = 0
  self.main_dropped = 0
  self.main_recorded = 0
  self.choice_buffer = {}
  self.choice_head = 1
  self.choice_tail = 0
  self.choice_dropped = 0
  self.choice_recorded = 0
  self.scripted_choice_excluded = 0
  return self:status()
end

function Controller:clear_main()
  for context in pairs(self.contexts) do
    local pending = context.policy_pending
    if pending ~= nil then
      self:finish_pending(context, pending.metrics, false)
    end
  end
  self.main_buffer = {}
  self.main_head = 1
  self.main_tail = 0
  self.main_dropped = 0
  self.main_recorded = 0
  return self:status()
end

function Controller:drain(max_records)
  local available = self:buffer_size("main")
  local requested = math.floor(
    tonumber(max_records) or available)
  requested = math.max(0, math.min(requested, available))
  local records = {}
  for _ = 1, requested do
    records[#records + 1] =
      self.main_buffer[self.main_head]
    self.main_buffer[self.main_head] = nil
    self.main_head = self.main_head + 1
  end
  self.main_buffer, self.main_head, self.main_tail =
    compact(
      self.main_buffer,
      self.main_head,
      self.main_tail)
  return {
    records = records,
    status = self:status(),
  }
end

function Controller:drain_choices(
    max_records,
    include_scripted)
  local available = self:buffer_size("choice")
  local requested = math.max(
    0,
    math.floor(tonumber(max_records) or available))
  local records = {}
  while self.choice_head <= self.choice_tail and
      #records < requested do
    local record = self.choice_buffer[self.choice_head]
    self.choice_buffer[self.choice_head] = nil
    self.choice_head = self.choice_head + 1
    if include_scripted == true or record.trainable == true then
      records[#records + 1] = record
    else
      self.scripted_choice_excluded =
        self.scripted_choice_excluded + 1
    end
  end
  self.choice_buffer,
    self.choice_head,
    self.choice_tail = compact(
      self.choice_buffer,
      self.choice_head,
      self.choice_tail)
  return {
    records = records,
    status = self:status(),
  }
end

function Controller:load_parameters(candidate)
  if type(self.runtime) ~= "table" or
      type(self.runtime.load) ~= "function" then
    error(
      "strict v3 policy runtime is unavailable")
  end
  local generation = self.runtime:load(candidate)
  return {
    generation = generation,
    status = self:status(),
  }
end

function Controller:runtime_status()
  if type(self.runtime) == "table" and
      type(self.runtime.status) == "function" then
    return self.runtime:status()
  end
  return {
    available = false,
    version = self.spec.model_version,
    reason =
      "strict v3 policy runtime is unavailable",
  }
end

function Controller:status()
  return {
    enabled = self.enabled,
    episode_id = self.episode_id,
    capacity = self.capacity,
    buffered = self:buffer_size("main"),
    dropped = self.main_dropped,
    recorded = self.main_recorded,
    choice_buffered = self:buffer_size("choice"),
    choice_dropped = self.choice_dropped,
    choice_recorded = self.choice_recorded,
    scripted_choice_excluded =
      self.scripted_choice_excluded,
    policy = self:runtime_status(),
  }
end

function training.new(spec, runtime)
  local controller = setmetatable({
    spec = assert(spec),
    runtime = runtime,
    enabled = false,
    episode_id = 0,
    capacity = 8192,
    contexts = setmetatable({}, {__mode = "k"}),
    main_buffer = {},
    main_head = 1,
    main_tail = 0,
    main_dropped = 0,
    main_recorded = 0,
    choice_buffer = {},
    choice_head = 1,
    choice_tail = 0,
    choice_dropped = 0,
    choice_recorded = 0,
    scripted_choice_excluded = 0,
  }, Controller)
  rawset(_G, "bot_policy_training", {
    enable = function(options)
      return controller:enable(options)
    end,
    disable = function()
      return controller:disable()
    end,
    finish_episode = function()
      return controller:finish_episode()
    end,
    clear = function()
      return controller:clear()
    end,
    clear_main = function()
      return controller:clear_main()
    end,
    drain = function(max_records)
      return controller:drain(max_records)
    end,
    drain_choices = function(max_records, include_scripted)
      return controller:drain_choices(
        max_records,
        include_scripted)
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
