local local_player = {}
local Controller = {}
Controller.__index = Controller

local Handle = {}
Handle.__index = Handle

-- This is the proven slot-zero automation pulse. Input hold frames are
-- consumed by the stock player tick, not by the Lua runtime scheduler.
local LOCAL_PRIMARY_HOLD_FRAMES = 3

local ELEMENT_BANDS = {
  { name = "ether", minimum = 8, maximum = 15 },
  { name = "fire", minimum = 16, maximum = 23 },
  { name = "air", minimum = 24, maximum = 31 },
  { name = "water", minimum = 32, maximum = 39 },
  { name = "earth", minimum = 40, maximum = 47 },
}

local function finite_number(value)
  return type(value) == "number" and value == value and
    value > -math.huge and value < math.huge
end

local function local_participant(runtime)
  if type(runtime) ~= "table" then
    return nil
  end
  for _, participant in ipairs(runtime.participants or {}) do
    if tostring(participant.kind or "") == "LocalHuman" and
        tostring(participant.controller_kind or "") == "Native" then
      return participant
    end
  end
  return nil
end

local function run_scene_active()
  local ok, scene = pcall(sd.world.get_scene)
  if not ok or type(scene) ~= "table" then
    return false
  end
  return tostring(scene.kind or "") == "run" or
    tostring(scene.name or "") == "testrun"
end

local function element_for_entry(entry_id)
  entry_id = tonumber(entry_id)
  if entry_id == nil then
    return nil
  end
  for _, band in ipairs(ELEMENT_BANDS) do
    if entry_id >= band.minimum and entry_id <= band.maximum then
      return band.name
    end
  end
  return nil
end

local function resolve_target_actor(target)
  if type(target) ~= "table" then
    return 0
  end
  local actor_address = tonumber(target.actor_address) or 0
  if actor_address > 0 then
    return actor_address
  end
  local network_actor_id =
    tonumber(target.network_actor_id) or 0
  if network_actor_id > 0 then
    local ok, actor = pcall(
      sd.world.get_run_enemy_by_network_id,
      network_actor_id)
    if ok and type(actor) == "table" then
      return tonumber(actor.actor_address) or 0
    end
  end

  local target_x = tonumber(target.x)
  local target_y = tonumber(target.y)
  if not finite_number(target_x) or
      not finite_number(target_y) then
    return 0
  end
  local ok, actors = pcall(sd.world.list_actors)
  if not ok or type(actors) ~= "table" then
    return 0
  end
  local nearest_address = 0
  local nearest_distance_squared = math.huge
  for _, actor in ipairs(actors) do
    local address = tonumber(actor.actor_address) or 0
    local x = tonumber(actor.x or actor.position_x)
    local y = tonumber(actor.y or actor.position_y)
    local hp = tonumber(actor.hp) or 0.0
    if actor.tracked_enemy == true and
        actor.dead ~= true and address > 0 and hp > 0.0 and
        finite_number(x) and finite_number(y) then
      local dx = x - target_x
      local dy = y - target_y
      local distance_squared = dx * dx + dy * dy
      if distance_squared < nearest_distance_squared then
        nearest_address = address
        nearest_distance_squared = distance_squared
      end
    end
  end
  return nearest_address
end

function Handle:new(controller)
  return setmetatable({ controller = controller }, self)
end

function Handle:participant_id()
  return self.controller.participant_id
end

function Handle:slot()
  local player = self.controller.player
  return type(player) == "table" and
    tonumber(player.actor_slot) or nil
end

function Handle:position()
  local player = self.controller.player
  if type(player) ~= "table" then
    return nil, "local player is unavailable"
  end
  local x = tonumber(player.x)
  local y = tonumber(player.y)
  if not finite_number(x) or not finite_number(y) then
    return nil, "local player position is unavailable"
  end
  return x, y
end

function Handle:hp()
  local player = self.controller.player
  local hp = type(player) == "table" and
    tonumber(player.hp) or nil
  if not finite_number(hp) then
    return nil, "local player health is unavailable"
  end
  return hp
end

function Handle:max_hp()
  local player = self.controller.player
  local max_hp = type(player) == "table" and
    tonumber(player.max_hp) or nil
  if not finite_number(max_hp) then
    return nil, "local player maximum health is unavailable"
  end
  return max_hp
end

function Handle:mp()
  local player = self.controller.player
  local mp = type(player) == "table" and
    tonumber(player.mp) or nil
  if not finite_number(mp) then
    return nil, "local player mana is unavailable"
  end
  return mp
end

function Handle:max_mp()
  local player = self.controller.player
  local max_mp = type(player) == "table" and
    tonumber(player.max_mp) or nil
  if not finite_number(max_mp) then
    return nil, "local player maximum mana is unavailable"
  end
  return max_mp
end

function Handle:alive()
  local hp = self:hp()
  local max_hp = self:max_hp()
  return hp ~= nil and max_hp ~= nil and
    max_hp > 0.0 and hp > 0.0
end

function Handle:move_to(x, y)
  x = tonumber(x)
  y = tonumber(y)
  if not finite_number(x) or not finite_number(y) then
    return false, "movement destination must be finite"
  end
  self.controller.destination_x = x
  self.controller.destination_y = y
  return true
end

function Handle:stop()
  self.controller.destination_x = nil
  self.controller.destination_y = nil
  return true
end

function Handle:cast(skill_slot, target_x, target_y, _hold_ms, target)
  skill_slot = tonumber(skill_slot)
  target_x = tonumber(target_x)
  target_y = tonumber(target_y)
  if skill_slot == nil or skill_slot < 0 or skill_slot > 8 or
      not finite_number(target_x) or
      not finite_number(target_y) then
    return false, "cast request is invalid"
  end

  local actor_address = resolve_target_actor(target)
  if actor_address <= 0 then
    return false, "cast target is not materialized locally"
  end
  local target_ok, accepted_or_error = pcall(
    sd.input.set_local_player_takeover_target,
    actor_address,
    target_x,
    target_y)
  if not target_ok or accepted_or_error ~= true then
    return false, tostring(accepted_or_error)
  end

  if skill_slot == 0 then
    local ok, result = pcall(
      sd.input.hold_mouse_left_frames,
      LOCAL_PRIMARY_HOLD_FRAMES)
    if not ok or result ~= true then
      return false, tostring(result)
    end
  else
    local ok, result = pcall(
      sd.input.press_binding,
      "belt_slot_" .. tostring(math.floor(skill_slot)))
    if not ok or result ~= true then
      return false, tostring(result)
    end
  end
  return true
end

function Controller:create_context(behavior)
  local context = self.brain.new(
    {
      name = "Local Player",
      element = self.element,
      behavior = behavior,
      discipline = "local",
    },
    0,
    self.shared,
    self.steering)
  context.local_player = true
  context.bot = self.handle
  context.participant_id = self.participant_id
  context.read_skill_choices = function()
    return self:read_skill_choices()
  end
  context.choose_skill = function(
      _,
      option_index,
      generation,
      option)
    return self:choose_skill(
      option_index,
      generation,
      option)
  end
  context.request_loot_pickup = function(_, network_drop_id)
    return sd.world.request_loot_pickup(network_drop_id)
  end
  self.context = context
  self.behavior = behavior
  self.debug.behavior = behavior
  self.debug.brain = context.debug
end

function Controller:new(
    brain,
    steering,
    shared,
    desired,
    behavior)
  local controller = setmetatable({
    brain = brain,
    steering = steering,
    shared = shared,
    desired = desired == true,
    behavior = tostring(behavior or "skirmisher"),
    active = false,
    key_down = false,
    participant_id = 0,
    element = "ether",
    player = nil,
    runtime = nil,
    destination_x = nil,
    destination_y = nil,
    last_state_sample_ms = -1000,
    handle = nil,
    context = nil,
    debug = {
      desired = desired == true,
      active = false,
      behavior = tostring(behavior or "skirmisher"),
      element = "ether",
      participant_id = 0,
      destination_x = 0.0,
      destination_y = 0.0,
      toggle_count = 0,
      activation_count = 0,
      release_count = 0,
      release_clean = true,
      last_release_reason = "",
      last_error = "",
      takeover_state = {},
      brain = {},
    },
  }, self)
  controller.handle = Handle:new(controller)
  controller:create_context(controller.behavior)
  return controller
end

function Controller:set_desired(desired, reason)
  desired = desired == true
  if desired == self.desired then
    return
  end
  self.desired = desired
  self.debug.desired = desired
  self.debug.toggle_count = self.debug.toggle_count + 1
  if not desired then
    self:release(reason or "disabled")
  end
end

function Controller:set_behavior(behavior)
  behavior = tostring(behavior or "")
  if self.brain.profiles[behavior] == nil or
      behavior == self.behavior then
    return
  end
  self:release("behavior changed")
  self:create_context(behavior)
end

function Controller:update_toggle_key()
  local ok, down = pcall(
    sd.settings.is_keybind_down,
    "play_for_me_toggle")
  down = ok and down == true
  if down and not self.key_down then
    self:set_desired(
      not self.desired,
      "keybind toggled off")
  end
  self.key_down = down
end

function Controller:read_skill_choices()
  local offer = type(self.runtime) == "table" and
    self.runtime.active_level_up_offer or nil
  if type(offer) ~= "table" or offer.valid ~= true or
      offer.selection_submitted == true then
    return {}
  end
  local target_participant_id =
    tonumber(offer.target_participant_id) or 0
  local local_offer_target_id =
    tonumber(self.runtime.local_steam_id) or 0
  if local_offer_target_id == 0 then
    local_offer_target_id = self.participant_id
  end
  if target_participant_id ~= 0 and
      target_participant_id ~= local_offer_target_id then
    return {}
  end
  return {
    pending = true,
    generation = tonumber(offer.offer_id) or 0,
    options = offer.options or {},
  }
end

function Controller:choose_skill(
    option_index,
    generation,
    option)
  local option_id = type(option) == "table" and
    tonumber(option.id or option.option_id) or nil
  return sd.runtime.choose_level_up_option({
    offer_id = generation,
    option_index = option_index,
    option_id = option_id,
  })
end

function Controller:update_runtime_state()
  local runtime_ok, runtime =
    pcall(sd.runtime.get_multiplayer_state)
  local player_ok, player = pcall(sd.player.get_state)
  self.runtime =
    runtime_ok and type(runtime) == "table" and runtime or nil
  self.player =
    player_ok and type(player) == "table" and player or nil

  local participant = local_participant(self.runtime)
  self.participant_id =
    type(participant) == "table" and
      (tonumber(participant.participant_id) or 0) or 0
  self.context.participant_id = self.participant_id
  self.debug.participant_id = self.participant_id

  if self.participant_id > 0 then
    local details_ok, details = pcall(
      sd.bots.get_loadout_details,
      self.participant_id)
    local primary = details_ok and type(details) == "table" and
      details.primary or nil
    local element = type(primary) == "table" and
      element_for_entry(primary.entry_id) or nil
    if element ~= nil then
      self.element = element
      self.context.row.element = element
      self.context.debug.element = element
      self.debug.element = element
    end
  end
  return participant
end

function Controller:can_drive(participant)
  if not run_scene_active() or
      type(self.player) ~= "table" or
      type(participant) ~= "table" then
    return false, "waiting for run"
  end
  local spectator = type(self.runtime) == "table" and
    self.runtime.death_spectator or nil
  if type(spectator) == "table" and spectator.active == true then
    return false, "spectating"
  end
  local actor_address = tonumber(self.player.actor_address) or 0
  local hp = tonumber(self.player.hp) or 0.0
  local max_hp = tonumber(self.player.max_hp) or 0.0
  local participant_hp =
    tonumber(participant.life_current) or hp
  if actor_address <= 0 or max_hp <= 0.0 or
      hp <= 0.0 or participant_hp <= 0.0 or
      participant.runtime_valid ~= true or
      participant.in_run ~= true then
    return false, "dead or materializing"
  end
  return true
end

function Controller:activate()
  if self.active then
    return true
  end
  local ok, accepted = pcall(
    sd.input.set_local_player_takeover,
    true)
  if not ok or accepted ~= true then
    self.debug.last_error = tostring(accepted)
    return false
  end
  self.active = true
  self.debug.active = true
  self.debug.activation_count =
    self.debug.activation_count + 1
  self.debug.last_error = ""
  return true
end

function Controller:release(reason)
  self.handle:stop()
  local should_release = self.active
  if not should_release then
    local state_ok, takeover =
      pcall(sd.input.get_local_player_takeover_state)
    should_release =
      state_ok and type(takeover) == "table" and
      takeover.active == true and
      tostring(takeover.owner_mod_id or "") == "bot.brain"
  end
  if should_release then
    local ok, accepted = pcall(
      sd.input.set_local_player_takeover,
      false)
    if not ok or accepted ~= true then
      self.debug.last_error = tostring(accepted)
    end
  end
  self.active = false
  self.debug.active = false
  self.context.debug.active = false
  self.context.debug.mode = tostring(reason or "released")
  if should_release then
    self.debug.release_count =
      self.debug.release_count + 1
    self.debug.last_release_reason = tostring(reason or "")
    local state_ok, takeover =
      pcall(sd.input.get_local_player_takeover_state)
    if state_ok and type(takeover) == "table" then
      self.debug.takeover_state = takeover
      self.debug.release_clean = takeover.clean == true
      if takeover.clean ~= true then
        self.debug.last_error =
          "local control release retained native state"
      end
    else
      self.debug.release_clean = false
      self.debug.last_error =
        tostring(takeover or "takeover state unavailable")
    end
  end
end

function Controller:drive_movement()
  local destination_x = self.destination_x
  local destination_y = self.destination_y
  if destination_x == nil or destination_y == nil or
      type(self.player) ~= "table" then
    self.debug.destination_x = 0.0
    self.debug.destination_y = 0.0
    return
  end
  local player_x = tonumber(self.player.x)
  local player_y = tonumber(self.player.y)
  if not finite_number(player_x) or not finite_number(player_y) then
    return
  end
  local dx = destination_x - player_x
  local dy = destination_y - player_y
  local distance = math.sqrt(dx * dx + dy * dy)
  if distance <= 12.0 then
    self.handle:stop()
    return
  end
  local ok, accepted = pcall(
    sd.input.hold_movement_frames,
    dx / distance,
    dy / distance,
    1)
  if not ok or accepted ~= true then
    self.debug.last_error = tostring(accepted)
  end
  self.debug.destination_x = destination_x
  self.debug.destination_y = destination_y
end

function Controller:draw_indicator()
  local x = 16.0
  local viewport_ok, viewport =
    pcall(sd.draw.get_viewport)
  if viewport_ok and type(viewport) == "table" and
      tonumber(viewport.width) ~= nil then
    x = math.max(tonumber(viewport.width) - 160.0, 16.0)
  end
  sd.draw.rect(x, 14.0, 144.0, 27.0, {
    color = { r = 8, g = 20, b = 16, a = 185 },
  })
  sd.draw.rect(x, 14.0, 144.0, 27.0, {
    filled = false,
    thickness = 1.0,
    color = { r = 92, g = 224, b = 156, a = 230 },
  })
  sd.draw.text("BOT PLAYING  [F9]", x + 8.0, 21.0, {
    scale = 0.8,
    color = { r = 215, g = 255, b = 232, a = 255 },
  })
end

function Controller:tick(now_ms, event)
  self:update_toggle_key()
  local participant = self:update_runtime_state()
  if self.desired then
    self.brain.poll_skill_choice(self.context)
  end
  local can_drive, reason = self:can_drive(participant)
  if not self.desired or not can_drive then
    if self.active then
      self:release(
        self.desired and reason or "disabled")
    end
    return
  end
  if not self:activate() then
    return
  end

  self.context.bot = self.handle
  self.context.participant_id = self.participant_id
  self.brain.think(
    self.context,
    now_ms,
    true,
    tonumber(event.tick_count) or 0)
  self:drive_movement()
  self:draw_indicator()
end

function Controller:reset_run(started)
  self.brain.reset_run(self.context, started)
  if not started then
    self:release("run ended")
  end
end

function local_player.new(
    brain,
    steering,
    shared,
    desired,
    behavior)
  return Controller:new(
    brain,
    steering,
    shared,
    desired,
    behavior)
end

return local_player
