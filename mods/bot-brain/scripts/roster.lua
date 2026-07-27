local roster = {}
local Manager = {}
Manager.__index = Manager

local ELEMENT_IDS = {
  fire = 0,
  water = 1,
  earth = 2,
  air = 3,
  ether = 4,
}

local function row_copy(row)
  return {
    name = tostring(row.name or ""),
    element = tostring(row.element or ""),
    discipline = tostring(row.discipline or ""),
  }
end

local function rows_match(left, right)
  return left ~= nil and right ~= nil and
    left.name == right.name and
    left.element == right.element and
    left.discipline == right.discipline
end

local function handle_participant_id(handle)
  local ok, participant_id =
    pcall(function() return handle:participant_id() end)
  if not ok then
    return 0
  end
  return tonumber(participant_id) or 0
end

local function snapshot_matches_row(participant_id, row)
  local ok, snapshot = pcall(
    sd.bots.get_participant_state,
    participant_id)
  if not ok or type(snapshot) ~= "table" then
    return false
  end
  local profile = snapshot.profile
  return tostring(snapshot.controller_kind or "") == "LuaBrain" and
    tostring(snapshot.name or "") == row.name and
    type(profile) == "table" and
    tonumber(profile.element_id) == ELEMENT_IDS[row.element]
end

local function clear_handle(context)
  context.bot = nil
  context.participant_id = 0
  context.debug.participant_id = 0
end

local function is_lobby_full(message)
  return tostring(message or "") == "lobby full"
end

function Manager:new(brain, steering, shared, debug)
  return setmetatable({
    brain = brain,
    steering = steering,
    shared = shared,
    debug = debug,
    contexts = {},
    retirements = {},
  }, self)
end

function Manager:retire_context(context)
  if context.bot == nil then
    clear_handle(context)
    return true
  end
  local ok, removed, error_message = pcall(function()
    return context.bot:despawn()
  end)
  if not ok or removed ~= true then
    local message =
      tostring(error_message or removed or "despawn rejected")
    context.debug.last_error = message
    return false, message
  end
  self.shared.log(context, "despawned")
  clear_handle(context)
  return true
end

function Manager:queue_retirement(context)
  table.insert(self.retirements, context)
end

function Manager:process_retirements()
  local remaining = {}
  for _, context in ipairs(self.retirements) do
    local retired = self:retire_context(context)
    if not retired then
      table.insert(remaining, context)
    end
  end
  self.retirements = remaining
end

function Manager:refresh_handles()
  local handles = {}
  for _, handle in ipairs(sd.bots.list() or {}) do
    local participant_id = handle_participant_id(handle)
    if participant_id > 0 then
      handles[participant_id] = handle
    end
  end

  local claimed = {}
  for _, context in ipairs(self.contexts) do
    if context.participant_id > 0 and
        handles[context.participant_id] ~= nil then
      context.bot = handles[context.participant_id]
      claimed[context.participant_id] = true
    else
      clear_handle(context)
    end
  end
  return handles, claimed
end

function Manager:adopt_context(context, handles, claimed)
  local ids = {}
  for participant_id in pairs(handles) do
    table.insert(ids, participant_id)
  end
  table.sort(ids)
  for _, participant_id in ipairs(ids) do
    if not claimed[participant_id] and
        snapshot_matches_row(participant_id, context.row) then
      context.bot = handles[participant_id]
      context.participant_id = participant_id
      context.debug.participant_id = participant_id
      context.debug.last_error = ""
      context.capacity_refused = false
      claimed[participant_id] = true
      self.shared.log(context, "adopted")
      return context.bot
    end
  end
  return nil
end

function Manager:ensure_context(
    context,
    now_ms,
    authority,
    force,
    handles,
    claimed)
  if context.bot ~= nil and context.participant_id > 0 then
    return context.bot
  end
  local adopted = self:adopt_context(context, handles, claimed)
  if adopted ~= nil or not authority then
    return adopted
  end
  if not force and
      now_ms - context.last_spawn_attempt_ms <
        self.shared.spawn_retry_ms then
    return nil
  end

  context.last_spawn_attempt_ms = now_ms
  local ok, bot, error_message = pcall(
    sd.bots.spawn,
    {
      name = context.row.name,
      class = context.row.element,
    })
  if not ok or bot == nil then
    local message =
      tostring(error_message or bot or "spawn rejected")
    context.debug.last_error = message
    context.capacity_refused = is_lobby_full(message)
    return nil, message
  end

  context.bot = bot
  context.participant_id = handle_participant_id(bot)
  context.debug.participant_id = context.participant_id
  context.debug.last_error = ""
  context.capacity_refused = false
  handles[context.participant_id] = bot
  claimed[context.participant_id] = true
  self.shared.log(context, "spawned")
  return bot
end

function Manager:sync_debug()
  local bots = {}
  local participant_ids = {}
  local active_bot_count = 0
  local capacity_refused_count = 0
  for index, context in ipairs(self.contexts) do
    context.roster_index = index
    context.debug.roster_index = index
    bots[index] = context.debug
    participant_ids[index] = context.participant_id
    if context.bot ~= nil and context.participant_id > 0 then
      active_bot_count = active_bot_count + 1
    end
    if context.capacity_refused == true then
      capacity_refused_count = capacity_refused_count + 1
    end
  end
  self.debug.bots = bots
  self.debug.participant_ids = participant_ids
  self.debug.roster_size = #self.contexts
  self.debug.active_bot_count = active_bot_count
  self.debug.desired_bot_count = #self.contexts
  self.debug.capacity_refused_count = capacity_refused_count
  local status =
    tostring(active_bot_count) .. " of " ..
    tostring(#self.contexts) .. " bots active"
  if active_bot_count < #self.contexts and
      capacity_refused_count > 0 then
    status = status .. " — lobby full"
  end
  if self.debug.status ~= status then
    self.debug.status = status
    self.shared.log(nil, status)
  end

  local first = self.contexts[1]
  if first ~= nil then
    for key, value in pairs(first.debug) do
      if type(value) ~= "table" then
        self.debug[key] = value
      end
    end
  else
    self.debug.active = false
    self.debug.participant_id = 0
    self.debug.mode = "waiting"
  end
end

function Manager:apply(rows, authority, now_ms)
  local next_contexts = {}
  local to_retire = {}
  for index, row in ipairs(rows or {}) do
    local normalized_row = row_copy(row)
    local existing = self.contexts[index]
    if existing ~= nil and
        rows_match(existing.row, normalized_row) then
      next_contexts[index] = existing
    else
      if existing ~= nil then
        table.insert(to_retire, existing)
      end
      next_contexts[index] = self.brain.new(
        normalized_row,
        index,
        self.shared,
        self.steering)
    end
  end
  for index = #next_contexts + 1, #self.contexts do
    table.insert(to_retire, self.contexts[index])
  end

  local errors = {}
  if authority then
    for _, context in ipairs(to_retire) do
      local retired, retire_error =
        self:retire_context(context)
      if not retired then
        self:queue_retirement(context)
        table.insert(
          errors,
          "roster entry " .. tostring(context.roster_index) ..
          " could not despawn: " .. retire_error)
      end
    end
  end
  self.contexts = next_contexts

  local handles, claimed = self:refresh_handles()
  for index, context in ipairs(self.contexts) do
    local _, spawn_error = self:ensure_context(
      context,
      now_ms,
      authority,
      true,
      handles,
      claimed)
    if spawn_error ~= nil and
        not is_lobby_full(spawn_error) then
      table.insert(
        errors,
        "roster entry " .. tostring(index) ..
        " (" .. context.row.name .. ") could not spawn: " ..
        spawn_error)
    end
  end
  self.debug.reconciliation_error_count = #errors
  self.debug.last_reconciliation_error =
    errors[#errors] or ""
  self:sync_debug()
  return errors
end

function Manager:tick(now_ms, authority)
  if authority then
    self:process_retirements()
  end
  local handles, claimed = self:refresh_handles()
  local errors = {}
  for index, context in ipairs(self.contexts) do
    local _, spawn_error = self:ensure_context(
      context,
      now_ms,
      authority,
      false,
      handles,
      claimed)
    if (spawn_error ~= nil and
        not is_lobby_full(spawn_error)) or
        (context.bot == nil and
         context.debug.last_error ~= "" and
         not is_lobby_full(context.debug.last_error)) then
      table.insert(
        errors,
        "roster entry " .. tostring(index) ..
        " (" .. context.row.name .. ") could not spawn: " ..
        tostring(spawn_error or context.debug.last_error))
    end
    self.brain.think(context, now_ms, authority)
  end
  self.debug.reconciliation_error_count = #errors
  self.debug.last_reconciliation_error =
    errors[#errors] or ""
  self:sync_debug()
end

function Manager:reset_run(started)
  for _, context in ipairs(self.contexts) do
    self.brain.reset_run(context, started)
  end
  self:sync_debug()
end

function Manager:respawn_all(now_ms, authority)
  if not authority then
    return {"respawn requires session authority"}
  end
  local errors = {}
  for index, context in ipairs(self.contexts) do
    local retired, retire_error = self:retire_context(context)
    if not retired then
      self:queue_retirement(context)
      table.insert(
        errors,
        "roster entry " .. tostring(index) ..
        " could not despawn: " .. retire_error)
    end
    context.last_spawn_attempt_ms = -self.shared.spawn_retry_ms
    context.last_position_x = nil
    context.last_position_y = nil
  end
  self:process_retirements()
  local handles, claimed = self:refresh_handles()
  for index, context in ipairs(self.contexts) do
    local _, spawn_error = self:ensure_context(
      context,
      now_ms,
      authority,
      true,
      handles,
      claimed)
    if spawn_error ~= nil and
        not is_lobby_full(spawn_error) then
      table.insert(
        errors,
        "roster entry " .. tostring(index) ..
        " could not spawn: " .. spawn_error)
    end
  end
  self:sync_debug()
  return errors
end

function Manager:first_bot()
  for _, context in ipairs(self.contexts) do
    if context.bot ~= nil then
      return context.bot
    end
  end
  return nil
end

function roster.new(brain, steering, shared, debug)
  return Manager:new(brain, steering, shared, debug)
end

return roster
