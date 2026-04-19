local BOT_NAME = "Lua Patrol Bot"
local LEGACY_MANAGED_BOT_NAMES = {
  ["Lua Patrol Bot"] = true,
  ["Lua Bot Fire"] = true,
  ["Lua Bot Earth"] = true,
}

local BOT_PROFILE = {
  element_id = 4,
  discipline_id = 1,
  level = 1,
  experience = 0,
  loadout = {
    primary_skill_id = 11,
    primary_combo_id = 22,
    secondary_skill_ids = { 33, 44, 55 },
  },
}

local SPAWN_OFFSET_X = 50.0
local SPAWN_OFFSET_Y = 0.0
local FOLLOW_STOP_DISTANCE = 50.0
local FOLLOW_RESUME_DISTANCE = 150.0
local ARRIVAL_DISTANCE = 8.0
local FOLLOW_TARGET_REFRESH_DISTANCE = 24.0
local COMMAND_COOLDOWN_MS = 250
local TICK_INTERVAL_MS = 100
local SPAWN_RETRY_MS = 500
local SCENE_UPDATE_COOLDOWN_MS = 250
local NAV_GRID_REFRESH_MS = 1000
local NAV_GRID_SUBDIVISIONS = 4
local ENABLE_FOLLOW_MOVEMENT = true
local ENTRANCE_TRIGGER_DISTANCE = 96.0
local ENTRANCE_ARRIVAL_DISTANCE = 20.0
local HUB_ENTRANCE_ARM_DELAY_MS = 1500
local HUB_ENTRANCE_DWELL_MS = 350
local PLAYER_MOVEMENT_ARM_DISTANCE = 12.0
local STUCK_SAMPLE_THRESHOLD = 8
local STUCK_POSITION_EPSILON = 1.0
local SUPPORTED_PRIVATE_AREAS = {
  memorator = {
    name = "memorator",
    region_index = 1,
    region_type_id = 4002,
    hub_anchor = { x = 87.480285644531, y = 443.60046386719 },
    hub_wait_anchor = { x = 75.0, y = 375.0 },
    interior_anchor = { x = 512.0, y = 798.25897216797 },
  },
  librarian = {
    name = "librarian",
    region_index = 2,
    region_type_id = 4004,
    hub_anchor = { x = 124.76531219482, y = 496.97552490234 },
    hub_wait_anchor = { x = 75.0, y = 525.0 },
    interior_anchor = { x = 512.0, y = 924.0 },
  },
  dowser = {
    name = "dowser",
    region_index = 3,
    region_type_id = 4003,
    hub_anchor = { x = 627.5, y = 137.6875 },
    hub_wait_anchor = { x = 675.0, y = 75.0 },
    interior_anchor = { x = 537.5, y = 647.73309326172 },
  },
  polisher_arch = {
    name = "polisher_arch",
    region_index = 4,
    region_type_id = 4005,
    hub_anchor = { x = 952.5, y = 106.6875 },
    hub_wait_anchor = { x = 825.0, y = 75.0 },
    interior_anchor = { x = 512.0, y = 867.88549804688 },
  },
}

local state = {
  bot_id = nil,
  last_command_ms = 0,
  last_spawn_attempt_ms = 0,
  last_scene_sync_ms = 0,
  last_tick_ms = 0,
  follow_target = nil,
  scene_key = nil,
  travel_state = "idle",
  target_area_name = nil,
  active_private_area_name = nil,
  pending_run_promotion = false,
  last_scene_name = nil,
  scene_entered_ms = 0,
  last_player_sample = nil,
  hub_candidate_name = nil,
  hub_candidate_since_ms = 0,
  entrance_armed = {},
  last_bot_sample = nil,
  stuck_samples = 0,
  nav_grid_cache = nil,
  nav_grid_cache_world_id = nil,
  nav_grid_cache_at_ms = 0,
}

lua_bots_debug = state

local function log(message)
  print("[lua.bots] " .. tostring(message))
end

local function distance(ax, ay, bx, by)
  local dx = (ax or 0.0) - (bx or 0.0)
  local dy = (ay or 0.0) - (by or 0.0)
  return math.sqrt((dx * dx) + (dy * dy))
end

local function get_scene_state()
  if type(sd) ~= "table" or type(sd.world) ~= "table" or type(sd.world.get_scene) ~= "function" then
    return nil
  end

  local scene = sd.world.get_scene()
  return type(scene) == "table" and scene or nil
end

local function get_player_state()
  if type(sd) ~= "table" or type(sd.player) ~= "table" or type(sd.player.get_state) ~= "function" then
    return nil
  end

  local player = sd.player.get_state()
  return type(player) == "table" and player or nil
end

local function get_all_bot_states()
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    return nil
  end

  local bots = sd.bots.get_state()
  return type(bots) == "table" and bots or nil
end

local function get_bot_state(bot_id)
  if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.get_state) ~= "function" then
    return nil
  end

  local bot = sd.bots.get_state(bot_id)
  return type(bot) == "table" and bot or nil
end

local function destroy_bot_by_id(bot_id)
  if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.destroy) ~= "function" then
    return
  end

  pcall(sd.bots.destroy, bot_id)
end

local function clear_follow_state()
  state.bot_id = nil
  state.last_command_ms = 0
  state.last_spawn_attempt_ms = 0
  state.last_scene_sync_ms = 0
  state.follow_target = nil
  state.scene_key = nil
  state.travel_state = "idle"
  state.target_area_name = nil
  state.active_private_area_name = nil
  state.pending_run_promotion = false
  state.last_scene_name = nil
  state.scene_entered_ms = 0
  state.last_player_sample = nil
  state.hub_candidate_name = nil
  state.hub_candidate_since_ms = 0
  state.entrance_armed = {}
  state.last_bot_sample = nil
  state.stuck_samples = 0
  state.nav_grid_cache = nil
  state.nav_grid_cache_world_id = nil
  state.nav_grid_cache_at_ms = 0
end

local function is_managed_bot_name(bot_name)
  return type(bot_name) == "string" and LEGACY_MANAGED_BOT_NAMES[bot_name] == true
end

local function destroy_managed_bots()
  if state.bot_id ~= nil then
    destroy_bot_by_id(state.bot_id)
  end

  local bots = get_all_bot_states()
  if type(bots) == "table" then
    for _, bot in ipairs(bots) do
      if type(bot) == "table" and is_managed_bot_name(bot.name) then
        destroy_bot_by_id(bot.id)
      end
    end
  end

  clear_follow_state()
end

local function adopt_existing_managed_bot()
  local bots = get_all_bot_states()
  if type(bots) ~= "table" then
    return
  end

  local adopted = false
  for _, bot in ipairs(bots) do
    if type(bot) == "table" and bot.available and is_managed_bot_name(bot.name) then
      if not adopted then
        state.bot_id = bot.id
        adopted = true
      else
        destroy_bot_by_id(bot.id)
      end
    end
  end
end

local function is_scene_stable(scene)
  if type(scene) ~= "table" then
    return false
  end

  local world_id = tostring(scene.world_id or "")
  return not scene.transitioning and world_id ~= "" and world_id ~= "0" and world_id ~= "0x0" and world_id ~= "nil"
end

local function normalize_scene_kind(kind)
  kind = tostring(kind or ""):lower()
  if kind == "sharedhub" then
    return "shared_hub"
  end
  if kind == "privateregion" then
    return "private_region"
  end
  return kind
end

local function build_scene_intent(scene)
  if not is_scene_stable(scene) then
    return nil
  end

  local scene_name = tostring(scene.name or scene.kind or "")
  if scene_name == "hub" then
    return { kind = "shared_hub" }
  end
  if scene_name == "testrun" then
    return { kind = "run" }
  end

  local area = SUPPORTED_PRIVATE_AREAS[scene_name]
  if area == nil then
    return nil
  end

  return {
    kind = "private_region",
    region_index = area.region_index,
    region_type_id = area.region_type_id,
  }
end

local function scene_key(scene_intent)
  if type(scene_intent) ~= "table" then
    return nil
  end

  local kind = normalize_scene_kind(scene_intent.kind)
  return table.concat({
    kind,
    tostring(scene_intent.region_index or -1),
    tostring(scene_intent.region_type_id or -1),
  }, ":")
end

local function scene_matches(bot_scene, desired_scene)
  if type(bot_scene) ~= "table" or type(desired_scene) ~= "table" then
    return false
  end

  return scene_key(bot_scene) == scene_key(desired_scene)
end

local function build_spawn_transform(player, anchor)
  if type(player) ~= "table" then
    return nil
  end

  local heading = tonumber(player.heading)
  if type(anchor) == "table" then
    return {
      x = tonumber(anchor.x) or 0.0,
      y = tonumber(anchor.y) or 0.0,
      heading = heading,
    }
  end

  return {
    x = (tonumber(player.x) or 0.0) + SPAWN_OFFSET_X,
    y = (tonumber(player.y) or 0.0) + SPAWN_OFFSET_Y,
    heading = heading,
  }
end

local function issue_scene_update(now_ms, scene_intent, player, reason, anchor, force)
  if state.bot_id == nil then
    return false
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.update) ~= "function" then
    return false
  end
  now_ms = tonumber(now_ms) or state.last_tick_ms or 0
  if not force and now_ms - state.last_scene_sync_ms < SCENE_UPDATE_COOLDOWN_MS then
    return false
  end

  local spawn = build_spawn_transform(player, anchor)
  if type(spawn) ~= "table" then
    return false
  end

  local ok = sd.bots.update({
    id = state.bot_id,
    profile = BOT_PROFILE,
    scene = scene_intent,
    position = {
      x = spawn.x,
      y = spawn.y,
      heading = spawn.heading,
    },
  })
  if ok then
    state.last_scene_sync_ms = now_ms
    state.scene_key = scene_key(scene_intent)
    state.follow_target = nil
    log(string.format(
      "scene_update id=%s reason=%s scene=%s spawn=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(reason),
      tostring(state.scene_key),
      spawn.x,
      spawn.y))
  else
    log(string.format(
      "scene_update failed id=%s reason=%s scene=%s",
      tostring(state.bot_id),
      tostring(reason),
      tostring(scene_key(scene_intent))))
  end
  return ok
end

local function ensure_bot_spawned(now_ms, player, scene_intent, anchor)
  if type(player) ~= "table" or type(scene_intent) ~= "table" then
    return nil
  end

  adopt_existing_managed_bot()
  local spawn = build_spawn_transform(player, anchor)
  if type(spawn) ~= "table" then
    return nil
  end

  if state.bot_id == nil then
    if now_ms - state.last_spawn_attempt_ms < SPAWN_RETRY_MS then
      return nil
    end

    state.last_spawn_attempt_ms = now_ms
    if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.create) ~= "function" then
      return nil
    end

    local bot_id = sd.bots.create({
      name = BOT_NAME,
      profile = BOT_PROFILE,
      scene = scene_intent,
      ready = true,
      position = {
        x = spawn.x,
        y = spawn.y,
        heading = spawn.heading,
      },
    })
    if bot_id == nil then
      return nil
    end

    state.bot_id = bot_id
    state.scene_key = scene_key(scene_intent)
    state.last_scene_sync_ms = now_ms
    log(string.format(
      "spawned %s id=%s scene=%s point=(%.2f, %.2f)",
      BOT_NAME,
      tostring(bot_id),
      tostring(state.scene_key),
      spawn.x,
      spawn.y))
    return get_bot_state(bot_id)
  end

  local bot = get_bot_state(state.bot_id)
  if bot == nil or not bot.available then
    clear_follow_state()
    return nil
  end

  return bot
end

local function stop_follow_move(reason)
  if state.bot_id == nil then
    return
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.stop) ~= "function" then
    return
  end

  local ok = sd.bots.stop(state.bot_id)
  if ok then
    state.follow_target = nil
    log(string.format("follow_stop id=%s reason=%s", tostring(state.bot_id), tostring(reason)))
  else
    log(string.format("follow_stop failed id=%s reason=%s", tostring(state.bot_id), tostring(reason)))
  end
end

local function reset_travel_candidate()
  state.hub_candidate_name = nil
  state.hub_candidate_since_ms = 0
  state.target_area_name = nil
  state.travel_state = "idle"
end

local function issue_follow_move(target, now_ms, reason)
  if not ENABLE_FOLLOW_MOVEMENT then
    return false
  end
  if state.bot_id == nil or type(target) ~= "table" then
    return false
  end
  if now_ms - state.last_command_ms < COMMAND_COOLDOWN_MS then
    return false
  end
  if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.move_to) ~= "function" then
    return false
  end

  local ok = sd.bots.move_to(state.bot_id, target.x, target.y)
  if ok then
    state.follow_target = {
      x = target.x,
      y = target.y,
      reason = reason,
    }
    state.last_command_ms = now_ms
    log(string.format(
      "follow_move id=%s reason=%s point=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(reason),
      target.x,
      target.y))
  else
    log(string.format(
      "follow_move failed id=%s reason=%s point=(%.2f, %.2f)",
      tostring(state.bot_id),
      tostring(reason),
      target.x,
      target.y))
  end
  return ok
end

local function get_nav_grid_snapshot(now_ms)
  if type(sd) ~= "table" or type(sd.debug) ~= "table" or type(sd.debug.get_nav_grid) ~= "function" then
    return nil
  end

  local scene = get_scene_state()
  local world_id = type(scene) == "table" and tostring(scene.world_id or scene.id or "") or ""
  if world_id == "" then
    return nil
  end

  if state.nav_grid_cache ~= nil and
      state.nav_grid_cache_world_id == world_id and
      now_ms - state.nav_grid_cache_at_ms < NAV_GRID_REFRESH_MS then
    return state.nav_grid_cache
  end

  local grid = sd.debug.get_nav_grid(NAV_GRID_SUBDIVISIONS)
  if type(grid) ~= "table" or grid.valid == false or type(grid.cells) ~= "table" then
    return nil
  end

  state.nav_grid_cache = grid
  state.nav_grid_cache_world_id = world_id
  state.nav_grid_cache_at_ms = now_ms
  return grid
end

local function snap_target_to_nav(grid, target)
  if type(grid) ~= "table" or type(grid.cells) ~= "table" or type(target) ~= "table" then
    return target
  end

  local target_x = tonumber(target.x)
  local target_y = tonumber(target.y)
  if target_x == nil or target_y == nil then
    return target
  end

  local best_sample = nil
  local best_sample_distance = nil
  local best_center = nil
  local best_center_distance = nil
  for _, cell in ipairs(grid.cells) do
    if type(cell) == "table" then
      if type(cell.samples) == "table" then
        for _, sample in ipairs(cell.samples) do
          if type(sample) == "table" and sample.traversable and
              tonumber(sample.world_x) ~= nil and tonumber(sample.world_y) ~= nil then
            local gap = distance(target_x, target_y, tonumber(sample.world_x), tonumber(sample.world_y))
            if best_sample_distance == nil or gap < best_sample_distance then
              best_sample_distance = gap
              best_sample = { x = tonumber(sample.world_x), y = tonumber(sample.world_y) }
            end
          end
        end
      end

      if cell.traversable and tonumber(cell.center_x) ~= nil and tonumber(cell.center_y) ~= nil then
        local gap = distance(target_x, target_y, tonumber(cell.center_x), tonumber(cell.center_y))
        if best_center_distance == nil or gap < best_center_distance then
          best_center_distance = gap
          best_center = { x = tonumber(cell.center_x), y = tonumber(cell.center_y) }
        end
      end
    end
  end

  local best = best_sample or best_center
  if best == nil then
    return target
  end

  best.gap = target.gap
  return best
end

local function compute_follow_target(player, bot)
  local player_x = tonumber(player.x) or 0.0
  local player_y = tonumber(player.y) or 0.0
  local bot_x = tonumber(bot.x) or 0.0
  local bot_y = tonumber(bot.y) or 0.0
  local gap = distance(bot_x, bot_y, player_x, player_y)
  local dir_x = bot_x - player_x
  local dir_y = bot_y - player_y
  if gap < 0.001 then
    dir_x = 1.0
    dir_y = 0.0
    gap = 1.0
  end

  local norm_x = dir_x / gap
  local norm_y = dir_y / gap
  return {
    x = player_x + (norm_x * FOLLOW_STOP_DISTANCE),
    y = player_y + (norm_y * FOLLOW_STOP_DISTANCE),
    gap = gap,
  }
end

local function update_same_scene_follow(now_ms, player, bot)
  if type(player) ~= "table" or type(bot) ~= "table" then
    return
  end

  local actor_address = tonumber(bot.actor_address) or 0
  if actor_address == 0 or not bot.transform_valid then
    return
  end

  local target = compute_follow_target(player, bot)
  target = snap_target_to_nav(get_nav_grid_snapshot(now_ms), target)
  local gap = target.gap
  if state.follow_target ~= nil and (not bot.moving) and (not bot.has_target) then
    local settled_gap = distance(
      tonumber(bot.x) or 0.0,
      tonumber(bot.y) or 0.0,
      tonumber(state.follow_target.x) or 0.0,
      tonumber(state.follow_target.y) or 0.0)
    if settled_gap <= ARRIVAL_DISTANCE then
      state.follow_target = nil
    end
  end

  local follow_active = bot.moving or bot.has_target or state.follow_target ~= nil
  if follow_active then
    if gap <= FOLLOW_STOP_DISTANCE then
      -- Stock GameNpc movement clears its own follow state once the current
      -- goal settles. Forcing an extra stop here tears down the controller
      -- state too early and leaves the world movement list in a bad shape.
      state.follow_target = nil
      return
    end
  else
    if gap <= FOLLOW_RESUME_DISTANCE then
      return
    end
  end

  if (not bot.moving) or (not bot.has_target) then
    issue_follow_move(target, now_ms, "follow")
    return
  end

  if bot.target_x == nil or bot.target_y == nil then
    issue_follow_move(target, now_ms, "follow")
    return
  end

  local target_gap = distance(bot.target_x, bot.target_y, target.x, target.y)
  if target_gap > FOLLOW_TARGET_REFRESH_DISTANCE then
    issue_follow_move(target, now_ms, "follow")
  end
end

local function track_bot_motion_sample(bot)
  if type(bot) ~= "table" then
    state.last_bot_sample = nil
    state.stuck_samples = 0
    return
  end

  local bot_x = tonumber(bot.x) or 0.0
  local bot_y = tonumber(bot.y) or 0.0
  if type(state.last_bot_sample) == "table" and bot.moving then
    local drift = distance(
      bot_x,
      bot_y,
      tonumber(state.last_bot_sample.x) or 0.0,
      tonumber(state.last_bot_sample.y) or 0.0)
    if drift <= STUCK_POSITION_EPSILON then
      state.stuck_samples = state.stuck_samples + 1
    else
      state.stuck_samples = 0
    end
  else
    state.stuck_samples = 0
  end
  state.last_bot_sample = {
    x = bot_x,
    y = bot_y,
  }
end

local function detect_hub_entrance(player, scene)
  if type(player) ~= "table" or type(scene) ~= "table" or tostring(scene.name or "") ~= "hub" then
    return nil
  end

  local player_x = tonumber(player.x) or 0.0
  local player_y = tonumber(player.y) or 0.0
  local best = nil
  local best_distance = nil
  for _, area in pairs(SUPPORTED_PRIVATE_AREAS) do
    local anchor = area.hub_anchor
    local gap = distance(player_x, player_y, anchor.x, anchor.y)
    if gap <= ENTRANCE_TRIGGER_DISTANCE and (best_distance == nil or gap < best_distance) then
      best = area
      best_distance = gap
    end
  end
  return best
end

local function track_scene_entry(now_ms, scene)
  local scene_name = type(scene) == "table" and tostring(scene.name or "") or nil
  if scene_name ~= state.last_scene_name then
    state.last_scene_name = scene_name
    state.scene_entered_ms = now_ms
    state.hub_candidate_name = nil
    state.hub_candidate_since_ms = 0
    state.entrance_armed = {}
    state.last_player_sample = nil
  end
end

local function player_moved_recently(player)
  if type(player) ~= "table" then
    return false
  end

  local player_x = tonumber(player.x) or 0.0
  local player_y = tonumber(player.y) or 0.0
  local moved = false
  if type(state.last_player_sample) == "table" then
    moved = distance(
      player_x,
      player_y,
      tonumber(state.last_player_sample.x) or 0.0,
      tonumber(state.last_player_sample.y) or 0.0) >= PLAYER_MOVEMENT_ARM_DISTANCE
  end
  state.last_player_sample = {
    x = player_x,
    y = player_y,
  }
  return moved
end

local function handle_hub_state(now_ms, scene, player, bot)
  track_bot_motion_sample(bot)
  local moved_recently = player_moved_recently(player)
  local entrance = detect_hub_entrance(player, scene)
  if now_ms - state.scene_entered_ms >= HUB_ENTRANCE_ARM_DELAY_MS then
    local player_x = tonumber(player.x) or 0.0
    local player_y = tonumber(player.y) or 0.0
    for _, area in pairs(SUPPORTED_PRIVATE_AREAS) do
      local gap = distance(player_x, player_y, area.hub_anchor.x, area.hub_anchor.y)
      if gap > ENTRANCE_TRIGGER_DISTANCE then
        state.entrance_armed[area.name] = true
      end
    end

    if entrance ~= nil and moved_recently and state.entrance_armed[entrance.name] == true then
      if state.hub_candidate_name ~= entrance.name then
        state.hub_candidate_name = entrance.name
        state.hub_candidate_since_ms = now_ms
      end
    elseif state.travel_state == "idle" then
      state.hub_candidate_name = nil
      state.hub_candidate_since_ms = 0
    end
  end

  local candidate = state.hub_candidate_name ~= nil and SUPPORTED_PRIVATE_AREAS[state.hub_candidate_name] or nil
  if candidate ~= nil and now_ms - state.hub_candidate_since_ms >= HUB_ENTRANCE_DWELL_MS then
    state.target_area_name = candidate.name
    state.travel_state = "travel_to_entrance"
    if type(bot) == "table" and bot.available and (tonumber(bot.actor_address) or 0) ~= 0 then
      local wait_anchor = candidate.hub_wait_anchor or candidate.hub_anchor
      wait_anchor = snap_target_to_nav(get_nav_grid_snapshot(now_ms), wait_anchor)
      local gap = distance(tonumber(bot.x) or 0.0, tonumber(bot.y) or 0.0, wait_anchor.x, wait_anchor.y)
      if gap > ENTRANCE_ARRIVAL_DISTANCE then
        issue_follow_move(wait_anchor, now_ms, "travel_to_" .. candidate.name)
      else
        stop_follow_move("entrance_arrival")
      end
      if state.stuck_samples >= STUCK_SAMPLE_THRESHOLD then
        stop_follow_move("travel_stuck")
        state.entrance_armed[candidate.name] = false
        reset_travel_candidate()
      end
    end
    return
  end

  if state.active_private_area_name ~= nil then
    local previous_area = SUPPORTED_PRIVATE_AREAS[state.active_private_area_name]
    if previous_area ~= nil and type(bot) == "table" and not scene_matches(bot.scene, { kind = "shared_hub" }) then
      issue_scene_update(
        now_ms,
        { kind = "shared_hub" },
        player,
        "return_from_" .. previous_area.name,
        previous_area.hub_anchor)
      return
    end
    state.active_private_area_name = nil
  end

  state.target_area_name = nil
  state.travel_state = "idle"
  update_same_scene_follow(now_ms, player, bot)
end

local function handle_private_state(now_ms, scene, player, bot)
  local area = SUPPORTED_PRIVATE_AREAS[tostring(scene.name or "")]
  if area == nil then
    state.travel_state = "idle"
    state.target_area_name = nil
    return
  end

  state.active_private_area_name = area.name
  local desired_scene = {
    kind = "private_region",
    region_index = area.region_index,
    region_type_id = area.region_type_id,
  }
  if type(bot) == "table" and bot.available and not scene_matches(bot.scene, desired_scene) and state.target_area_name == area.name then
    issue_scene_update(now_ms, desired_scene, player, "enter_" .. area.name, area.interior_anchor)
    return
  end

  state.travel_state = "in_private_area"
  state.target_area_name = area.name
  update_same_scene_follow(now_ms, player, bot)
end

local function handle_run_state(now_ms, player, bot)
  reset_travel_candidate()
  state.target_area_name = nil
  if state.pending_run_promotion and not scene_matches(bot.scene, { kind = "run" }) then
    if issue_scene_update(now_ms, { kind = "run" }, player, "run_started", nil, true) then
      state.pending_run_promotion = false
    end
    return
  end
  state.pending_run_promotion = false
  state.travel_state = "run"
  update_same_scene_follow(now_ms, player, bot)
end

sd.events.on("run.started", function()
  log("run.started")
  state.pending_run_promotion = true
  reset_travel_candidate()
  state.travel_state = "run"
  state.active_private_area_name = nil
  state.target_area_name = nil
end)

sd.events.on("run.ended", function()
  log("run.ended")
  destroy_managed_bots()
end)

sd.events.on("runtime.tick", function(event)
  local now_ms = tonumber(event.monotonic_milliseconds) or 0
  if now_ms - state.last_tick_ms < TICK_INTERVAL_MS then
    return
  end
  state.last_tick_ms = now_ms

  local scene = get_scene_state()
  local player = get_player_state()
  local desired_scene = build_scene_intent(scene)
  if type(scene) ~= "table" or type(player) ~= "table" or type(desired_scene) ~= "table" then
    if state.bot_id ~= nil or state.scene_key ~= nil or state.last_scene_name ~= nil then
      destroy_managed_bots()
    end
    return
  end
  track_scene_entry(now_ms, scene)

  local anchor = nil
  if desired_scene.kind == "private_region" then
    local area = SUPPORTED_PRIVATE_AREAS[tostring(scene.name or "")]
    anchor = area ~= nil and area.interior_anchor or nil
  end

  local bot = ensure_bot_spawned(now_ms, player, desired_scene, anchor)
  if type(bot) ~= "table" or not bot.available then
    return
  end

  local scene_name = tostring(scene.name or "")
  if scene_name == "hub" then
    handle_hub_state(now_ms, scene, player, bot)
  elseif scene_name == "testrun" then
    handle_run_state(now_ms, player, bot)
  else
    handle_private_state(now_ms, scene, player, bot)
  end
end)
