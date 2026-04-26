local app = {}

function app.start()
  local LEGACY_MANAGED_BOT_NAMES = {
    ["Lua Patrol Bot"] = true,
    ["Lua Bot Fire"] = true,
    ["Lua Bot Water"] = true,
    ["Lua Bot Earth"] = true,
    ["Lua Bot Air"] = true,
    ["Lua Bot Ether"] = true,
  }

  local function default_primary_entry_index_for_element(element_id)
    -- Keep the sample bot's primary loadout aligned with the stock live
    -- selection-state mapping used by gameplay actors:
    --   ether -> 0x08
    --   fire  -> 0x10
    --   air   -> 0x18
    --   water -> 0x20
    --   earth -> 0x28
    local map = {
      [0] = 0x10, -- fire
      [1] = 0x20, -- water
      [2] = 0x28, -- earth
      [3] = 0x18, -- air
      [4] = 0x08, -- ether
    }
    return map[tonumber(element_id) or -1] or 0x08
  end

  local function make_bot_profile(element_id, discipline_id)
    local primary_entry_index = default_primary_entry_index_for_element(element_id)
    return {
      element_id = element_id,
      discipline_id = discipline_id,
      level = 1,
      experience = 0,
      loadout = {
        -- Keep each bot on the pure element primary by default. Mixed pairs
        -- resolve to combo/special abilities, which is not the intended
        -- baseline attack for this harness.
        primary_entry_index = primary_entry_index,
        primary_combo_entry_index = primary_entry_index,
        secondary_entry_indices = { -1, -1, -1 },
      },
    }
  end

  local BOT_CONFIGS = {
    {
      key = "water",
      name = "Lua Bot Water",
      element_id = 1,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = -60.0,
    },
    {
      key = "earth",
      name = "Lua Bot Earth",
      element_id = 2,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = -20.0,
    },
    {
      key = "air",
      name = "Lua Bot Air",
      element_id = 3,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = 20.0,
    },
    {
      key = "ether",
      name = "Lua Bot Ether",
      element_id = 4,
      discipline_id = 1,
      spawn_offset_x = 50.0,
      spawn_offset_y = 60.0,
    },
  }

  local CURRENT_MANAGED_BOT_NAMES = {}
  for _, config in ipairs(BOT_CONFIGS) do
    config.profile = make_bot_profile(config.element_id, config.discipline_id)
    CURRENT_MANAGED_BOT_NAMES[config.name] = true
  end

  local DEFAULT_SPAWN_OFFSET_X = 50.0
  local DEFAULT_SPAWN_OFFSET_Y = 0.0
  local FOLLOW_STOP_DISTANCE = 50.0
  local FOLLOW_RESUME_DISTANCE = 100.0
  local ARRIVAL_DISTANCE = 8.0
  local FOLLOW_SETTLE_DISTANCE = FOLLOW_STOP_DISTANCE + ARRIVAL_DISTANCE
  local FOLLOW_TARGET_REFRESH_DISTANCE = 24.0
  local COMMAND_COOLDOWN_MS = 250
  local TICK_INTERVAL_MS = 100
  local ATTACK_DIAG_INTERVAL_MS = 1000
  local DEFAULT_ATTACK_RANGE = 360.0
  local WAVE_ENEMY_OBJECT_TYPE_ID = 1001
  local SPAWN_RETRY_MS = 500
  local SCENE_UPDATE_COOLDOWN_MS = 250
  local NAV_GRID_REFRESH_MS = 3000
  local NAV_GRID_SUBDIVISIONS = 2
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
    bots = {},
    bot_count = 0,
    bot_id = nil,
    bot_dead = false,
    dead_bot_since_ms = 0,
    last_command_ms = 0,
    last_attack_diag_ms = 0,
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

  local BOT_CONTEXT_FIELDS = {
    "bot_id",
    "bot_dead",
    "dead_bot_since_ms",
    "last_command_ms",
    "last_attack_diag_ms",
    "last_spawn_attempt_ms",
    "last_scene_sync_ms",
    "follow_target",
    "scene_key",
    "pending_run_promotion",
    "last_bot_sample",
    "stuck_samples",
  }

  local function reset_bot_context(bot_state)
    bot_state.bot_id = nil
    bot_state.bot_dead = false
    bot_state.dead_bot_since_ms = 0
    bot_state.last_command_ms = 0
    bot_state.last_attack_diag_ms = 0
    bot_state.last_spawn_attempt_ms = 0
    bot_state.last_scene_sync_ms = 0
    bot_state.follow_target = nil
    bot_state.scene_key = nil
    bot_state.pending_run_promotion = false
    bot_state.last_bot_sample = nil
    bot_state.stuck_samples = 0
  end

  local function make_bot_context(config)
    local bot_state = {
      config = config,
      bot_name = config.name,
      bot_profile = config.profile,
      spawn_offset_x = tonumber(config.spawn_offset_x) or DEFAULT_SPAWN_OFFSET_X,
      spawn_offset_y = tonumber(config.spawn_offset_y) or DEFAULT_SPAWN_OFFSET_Y,
    }
    reset_bot_context(bot_state)
    return bot_state
  end

  for _, config in ipairs(BOT_CONFIGS) do
    table.insert(state.bots, make_bot_context(config))
  end
  state.bot_count = #state.bots

  local function load_bot_context(bot_state)
    if type(bot_state) ~= "table" then
      return
    end
    for _, field in ipairs(BOT_CONTEXT_FIELDS) do
      state[field] = bot_state[field]
    end
    state.bot_name = bot_state.bot_name
    state.bot_profile = bot_state.bot_profile
    state.spawn_offset_x = bot_state.spawn_offset_x
    state.spawn_offset_y = bot_state.spawn_offset_y
  end

  local function save_bot_context(bot_state)
    if type(bot_state) ~= "table" then
      return
    end
    for _, field in ipairs(BOT_CONTEXT_FIELDS) do
      bot_state[field] = state[field]
    end
  end

  local function sync_legacy_state_alias()
    local first = state.bots[1]
    if type(first) ~= "table" then
      return
    end
    for _, field in ipairs(BOT_CONTEXT_FIELDS) do
      state[field] = first[field]
    end
    state.bot_name = first.bot_name
    state.bot_profile = first.bot_profile
    state.spawn_offset_x = first.spawn_offset_x
    state.spawn_offset_y = first.spawn_offset_y
  end

  sync_legacy_state_alias()

  lua_bots_debug = state

  local function log(message)
    print("[lua.bots] " .. tostring(message))
  end

  local function get_probe_state()
    local probe = rawget(_G, "lua_bots_probe")
    if type(probe) ~= "table" then
      return nil
    end
    if probe.enabled ~= true then
      return nil
    end
    local probe_bot_id = tonumber(probe.bot_id)
    if probe_bot_id ~= nil and probe_bot_id > 0 and tonumber(state.bot_id) ~= probe_bot_id then
      return nil
    end
    return probe
  end

  local function distance(ax, ay, bx, by)
    local dx = (ax or 0.0) - (bx or 0.0)
    local dy = (ay or 0.0) - (by or 0.0)
    return math.sqrt((dx * dx) + (dy * dy))
  end

  local function bot_formation_offset(radius)
    local offset_x = tonumber(state.spawn_offset_x) or DEFAULT_SPAWN_OFFSET_X
    local offset_y = tonumber(state.spawn_offset_y) or DEFAULT_SPAWN_OFFSET_Y
    local offset_len = distance(offset_x, offset_y, 0.0, 0.0)
    if offset_len < 0.001 then
      return tonumber(radius) or FOLLOW_STOP_DISTANCE, 0.0
    end

    local scale = (tonumber(radius) or FOLLOW_STOP_DISTANCE) / offset_len
    return offset_x * scale, offset_y * scale
  end

  local function add_bot_formation_offset(target, radius)
    if type(target) ~= "table" then
      return nil
    end

    local offset_x, offset_y = bot_formation_offset(radius)
    return {
      x = (tonumber(target.x) or 0.0) + offset_x,
      y = (tonumber(target.y) or 0.0) + offset_y,
    }
  end

  local function normalize_address_key(value)
    if value == nil then
      return ""
    end

    if type(value) == "number" then
      if value == 0 then
        return ""
      end
      return string.lower(string.format("0x%X", value))
    end

    local text = string.lower(tostring(value))
    if text == "" or text == "0" or text == "0x0" or text == "nil" then
      return ""
    end
    return text
  end

  local function get_scene_state()
    if type(sd) ~= "table" or type(sd.world) ~= "table" or type(sd.world.get_scene) ~= "function" then
      return nil
    end

    local scene = sd.world.get_scene()
    return type(scene) == "table" and scene or nil
  end

  local function get_world_state()
    if type(sd) ~= "table" or type(sd.world) ~= "table" or type(sd.world.get_state) ~= "function" then
      return nil
    end

    local world = sd.world.get_state()
    return type(world) == "table" and world or nil
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

  local function is_bot_dead(bot)
    if type(bot) ~= "table" then
      return false
    end

    local hp = tonumber(bot.hp)
    local max_hp = tonumber(bot.max_hp)
    if hp == nil then
      return false
    end
    if max_hp == nil or max_hp <= 0.0 then
      return false
    end

    return hp <= 0.0
  end

  local function destroy_bot_by_id(bot_id)
    if bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.destroy) ~= "function" then
      return
    end

    pcall(sd.bots.destroy, bot_id)
  end

  local function clear_current_bot_state()
    state.bot_id = nil
    state.bot_dead = false
    state.dead_bot_since_ms = 0
    state.last_command_ms = 0
    state.last_attack_diag_ms = 0
    state.last_spawn_attempt_ms = 0
    state.last_scene_sync_ms = 0
    state.follow_target = nil
    state.scene_key = nil
    state.pending_run_promotion = false
    state.last_bot_sample = nil
    state.stuck_samples = 0
  end

  local function clear_follow_state()
    for _, bot_state in ipairs(state.bots) do
      reset_bot_context(bot_state)
    end
    sync_legacy_state_alias()
    state.travel_state = "idle"
    state.target_area_name = nil
    state.active_private_area_name = nil
    state.last_scene_name = nil
    state.scene_entered_ms = 0
    state.last_player_sample = nil
    state.hub_candidate_name = nil
    state.hub_candidate_since_ms = 0
    state.entrance_armed = {}
    state.nav_grid_cache = nil
    state.nav_grid_cache_world_id = nil
    state.nav_grid_cache_at_ms = 0
  end

  local function mark_bot_dead(now_ms, bot)
    if state.bot_dead then
      return
    end

    state.bot_dead = true
    state.dead_bot_since_ms = tonumber(now_ms) or state.last_tick_ms or 0
    state.follow_target = nil
    state.last_command_ms = 0

    if state.bot_id ~= nil and type(sd) == "table" and type(sd.bots) == "table" and type(sd.bots.stop) == "function" then
      pcall(sd.bots.stop, state.bot_id)
    end

    log(string.format(
      "managed bot dead id=%s hp=%.2f; leaving corpse inert for rest of run",
      tostring(state.bot_id),
      tonumber(type(bot) == "table" and bot.hp or 0.0) or 0.0))
  end

  local function is_managed_bot_name(bot_name)
    return type(bot_name) == "string" and LEGACY_MANAGED_BOT_NAMES[bot_name] == true
  end

  local function destroy_managed_bots()
    for _, bot_state in ipairs(state.bots) do
      if bot_state.bot_id ~= nil then
        destroy_bot_by_id(bot_state.bot_id)
      end
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

  local function has_any_managed_bot_context()
    if state.bot_id ~= nil or state.scene_key ~= nil then
      return true
    end
    for _, bot_state in ipairs(state.bots) do
      if bot_state.bot_id ~= nil or bot_state.scene_key ~= nil then
        return true
      end
    end
    return false
  end

  local function adopt_existing_managed_bot()
    local bots = get_all_bot_states()
    if type(bots) ~= "table" then
      return
    end

    local adopted = false
    for _, bot in ipairs(bots) do
      if type(bot) == "table" and bot.available and is_managed_bot_name(bot.name) then
        local exact_name_match = bot.name == state.bot_name
        if exact_name_match and not adopted then
          state.bot_id = bot.id
          adopted = true
        elseif exact_name_match or not CURRENT_MANAGED_BOT_NAMES[bot.name] then
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
    local offset_x = tonumber(state.spawn_offset_x) or DEFAULT_SPAWN_OFFSET_X
    local offset_y = tonumber(state.spawn_offset_y) or DEFAULT_SPAWN_OFFSET_Y
    if type(anchor) == "table" then
      return {
        x = (tonumber(anchor.x) or 0.0) + offset_x,
        y = (tonumber(anchor.y) or 0.0) + offset_y,
        heading = heading,
      }
    end

    return {
      x = (tonumber(player.x) or 0.0) + offset_x,
      y = (tonumber(player.y) or 0.0) + offset_y,
      heading = heading,
    }
  end

  local get_nav_grid_snapshot
  local snap_target_to_nav
  local snap_spawn_transform

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
    spawn = snap_spawn_transform(now_ms, spawn)
    if type(spawn) ~= "table" then
      return false
    end

    local ok = sd.bots.update({
      id = state.bot_id,
      profile = state.bot_profile,
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

    if state.bot_dead then
      if state.bot_id ~= nil then
        return get_bot_state(state.bot_id)
      end
      return nil
    end

    adopt_existing_managed_bot()
    local spawn = build_spawn_transform(player, anchor)
    if type(spawn) ~= "table" then
      return nil
    end
    spawn = snap_spawn_transform(now_ms, spawn)
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
        name = state.bot_name,
        profile = state.bot_profile,
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
        tostring(state.bot_name),
        tostring(bot_id),
        tostring(state.scene_key),
        spawn.x,
        spawn.y))
      return get_bot_state(bot_id)
    end

    local bot = get_bot_state(state.bot_id)
    if bot == nil or not bot.available then
      clear_current_bot_state()
      return nil
    end
    if is_bot_dead(bot) then
      mark_bot_dead(now_ms, bot)
      return bot
    end

    return bot
  end

  local function is_enemy_actor(actor, bot)
    if type(actor) ~= "table" then
      return false
    end
    local address = tonumber(actor.actor_address) or 0
    if address == 0 then
      return false
    end
    if type(bot) == "table" and address == (tonumber(bot.actor_address) or 0) then
      return false
    end
    local tracked_enemy = actor.tracked_enemy == true
    if not tracked_enemy then
      return false
    end
    if (tonumber(actor.object_type_id) or 0) ~= WAVE_ENEMY_OBJECT_TYPE_ID then
      return false
    end
    if actor.dead == true then
      return false
    end
    local max_hp = tonumber(actor.max_hp) or 0.0
    local hp = tonumber(actor.hp) or 0.0
    if max_hp <= 0.0 or hp <= 0.0 then
      return false
    end
    return true
  end

  local function find_nearest_enemy(bot)
    if type(sd.world) ~= "table" or type(sd.world.list_actors) ~= "function" then
      return nil, nil
    end
    local actors = sd.world.list_actors()
    if type(actors) ~= "table" then
      return nil, nil
    end
    local bot_x = tonumber(bot.x) or 0.0
    local bot_y = tonumber(bot.y) or 0.0

    local best, best_gap = nil, math.huge
    for _, actor in ipairs(actors) do
      if is_enemy_actor(actor, bot) then
        local gap = distance(bot_x, bot_y, tonumber(actor.x) or 0.0, tonumber(actor.y) or 0.0)
        if gap < best_gap then
          best = actor
          best_gap = gap
        end
      end
    end
    if best == nil then
      return nil, nil
    end
    return best, best_gap
  end

  local function should_log_attack_diag(now_ms)
    now_ms = tonumber(now_ms) or 0
    local last_ms = tonumber(state.last_attack_diag_ms) or 0
    if now_ms - last_ms < ATTACK_DIAG_INTERVAL_MS then
      return false
    end
    state.last_attack_diag_ms = now_ms
    return true
  end

  local function get_combat_state()
    if type(sd) ~= "table" or type(sd.gameplay) ~= "table" or
        type(sd.gameplay.get_combat_state) ~= "function" then
      return nil
    end
    local ok, combat = pcall(sd.gameplay.get_combat_state)
    if ok and type(combat) == "table" then
      return combat
    end
    return nil
  end

  local function can_attack_in_scene(scene)
    if type(scene) ~= "table" or tostring(scene.name or "") ~= "testrun" then
      return false, "scene_inactive"
    end
    local world = get_world_state()
    local wave = type(world) == "table" and tonumber(world.wave) or 0
    if wave ~= nil and wave > 0 then
      return true, nil
    end

    local combat = get_combat_state()
    if type(combat) == "table" and combat.active then
      return true, nil
    end
    return false, "combat_inactive"
  end

  local function get_attack_enemy(bot, probe)
    if type(bot) ~= "table" then
      return nil, nil
    end
    return find_nearest_enemy(bot)
  end

  local function heading_towards(from_x, from_y, to_x, to_y)
    local dx = (tonumber(to_x) or 0.0) - (tonumber(from_x) or 0.0)
    local dy = (tonumber(to_y) or 0.0) - (tonumber(from_y) or 0.0)
    if dx * dx + dy * dy <= 0.0001 then
      return nil
    end

    local radians
    if type(math.atan2) == "function" then
      radians = math.atan2(dy, dx)
    elseif math.abs(dx) < 0.000001 then
      radians = dy >= 0.0 and (math.pi * 0.5) or (math.pi * -0.5)
    else
      radians = math.atan(dy / dx)
      if dx < 0.0 then
        radians = radians + math.pi
      elseif dy < 0.0 then
        radians = radians + (math.pi * 2.0)
      end
    end

    local heading = (radians * 180.0 / math.pi) + 90.0
    while heading < 0.0 do
      heading = heading + 360.0
    end
    while heading >= 360.0 do
      heading = heading - 360.0
    end
    return heading
  end

  local function face_enemy(bot, enemy, use_actor_target)
    if type(sd) ~= "table" or type(sd.bots) ~= "table" or type(sd.bots.face) ~= "function" then
      return nil
    end
    if state.bot_id == nil or type(bot) ~= "table" or type(enemy) ~= "table" then
      return nil
    end

    local heading = heading_towards(
      bot.x,
      bot.y,
      tonumber(enemy.x) or 0.0,
      tonumber(enemy.y) or 0.0)
    if heading == nil then
      return nil
    end

    local target_actor_address = tonumber(enemy.actor_address) or 0
    if use_actor_target and target_actor_address ~= 0 and type(sd.bots.face_target) == "function" then
      pcall(sd.bots.face_target, state.bot_id, target_actor_address, heading)
    else
      pcall(sd.bots.face, state.bot_id, heading)
    end
    return heading
  end

  local function clear_face_target()
    if state.bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" then
      return
    end
    if type(sd.bots.face_target) == "function" then
      pcall(sd.bots.face_target, state.bot_id, 0)
    end
  end

  local function issue_auto_attack(now_ms, scene, bot, probe)
    if state.bot_id == nil then
      return false
    end
    if type(sd.bots) ~= "table" or type(sd.bots.cast) ~= "function" then
      return false
    end
    if type(bot) ~= "table" or not bot.available or (tonumber(bot.actor_address) or 0) == 0 or not bot.transform_valid then
      return false
    end
    local attack_scene_ok, attack_scene_reason = can_attack_in_scene(scene)
    if not attack_scene_ok then
      clear_face_target()
      if should_log_attack_diag(now_ms) then
        local world = get_world_state()
        local combat = get_combat_state()
        log(string.format(
          "attack_skip id=%s reason=%s wave=%s combat_active=%s",
          tostring(state.bot_id),
          tostring(attack_scene_reason),
          tostring(type(world) == "table" and world.wave or nil),
          tostring(type(combat) == "table" and combat.active or nil)))
      end
      return false
    end
    local range = DEFAULT_ATTACK_RANGE
    local enemy, gap = get_attack_enemy(bot, probe)
    if enemy == nil then
      clear_face_target()
      if should_log_attack_diag(now_ms) then
        log(string.format(
          "attack_skip id=%s reason=%s",
          tostring(state.bot_id),
          "no_enemy_in_scene"))
      end
      return false
    end
    local target_actor_address = tonumber(enemy.actor_address) or 0
    local target_x = tonumber(enemy.x) or 0.0
    local target_y = tonumber(enemy.y) or 0.0
    local attack_heading = face_enemy(bot, enemy, true)
    if gap > range then
      if should_log_attack_diag(now_ms) then
        log(string.format(
          "attack_skip id=%s reason=out_of_range enemy=0x%X gap=%.2f range=%.1f",
          tostring(state.bot_id),
          tonumber(enemy.actor_address) or 0,
          gap,
          range))
      end
      return false
    end
    if attack_heading == nil then
      attack_heading = heading_towards(bot.x, bot.y, target_x, target_y)
    end
    if bot.cast_ready ~= true then
      return false
    end
    local ok = sd.bots.cast({
      id = state.bot_id,
      kind = "primary",
      target_actor_address = target_actor_address,
      target = { x = target_x, y = target_y },
      angle = attack_heading,
    })
    if ok then
      log(string.format(
        "attack id=%s primary enemy=0x%X bot=(%.2f, %.2f) target=(%.2f, %.2f) heading=%.2f gap=%.2f range=%.1f",
        tostring(state.bot_id),
        target_actor_address,
        tonumber(bot.x) or 0.0,
        tonumber(bot.y) or 0.0,
        target_x,
        target_y,
        tonumber(attack_heading) or -1.0,
        gap,
        range))
    else
      log(string.format(
        "attack failed id=%s primary",
        tostring(state.bot_id)))
    end
    return ok
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

  get_nav_grid_snapshot = function(now_ms)
    if type(sd) ~= "table" or type(sd.debug) ~= "table" or type(sd.debug.get_nav_grid) ~= "function" then
      return nil
    end

    local scene = get_scene_state()
    local world_id = type(scene) == "table" and normalize_address_key(scene.world_id or scene.world_address or scene.id) or ""
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
    local grid_world_id = normalize_address_key(grid.world_address or grid.world_id)
    if grid_world_id == "" or grid_world_id ~= world_id then
      return nil
    end

    state.nav_grid_cache = grid
    state.nav_grid_cache_world_id = world_id
    state.nav_grid_cache_at_ms = now_ms
    return grid
  end

  local function is_outer_grid_row(grid, cell)
    local grid_x = tonumber(type(cell) == "table" and cell.grid_x or nil)
    local height = tonumber(type(grid) == "table" and grid.height or nil)
    if grid_x == nil or height == nil or height <= 0 then
      return false
    end
    return grid_x <= 0 or grid_x >= height - 1
  end

  local function nav_sample_score(grid, cell, gap, options)
    local score = gap
    if options.prefer_traversable_cell and cell.traversable ~= true then
      score = score + 100000.0
    end
    if options.avoid_outer_rows and is_outer_grid_row(grid, cell) then
      score = score + 50000.0
    end
    return score
  end

  snap_target_to_nav = function(grid, target, options)
    if type(grid) ~= "table" or type(grid.cells) ~= "table" or type(target) ~= "table" then
      return nil
    end
    options = type(options) == "table" and options or {}

    local target_x = tonumber(target.x)
    local target_y = tonumber(target.y)
    if target_x == nil or target_y == nil then
      return nil
    end

    local best_sample = nil
    local best_sample_score = nil
    local best_sample_distance = nil
    for _, cell in ipairs(grid.cells) do
      if type(cell) == "table" then
        if type(cell.samples) == "table" then
          for _, sample in ipairs(cell.samples) do
            if type(sample) == "table" and sample.traversable and
                tonumber(sample.world_x) ~= nil and tonumber(sample.world_y) ~= nil then
              local gap = distance(target_x, target_y, tonumber(sample.world_x), tonumber(sample.world_y))
              local score = nav_sample_score(grid, cell, gap, options)
              if best_sample_score == nil or score < best_sample_score or
                  (score == best_sample_score and gap < best_sample_distance) then
                best_sample_score = score
                best_sample_distance = gap
                best_sample = { x = tonumber(sample.world_x), y = tonumber(sample.world_y) }
              end
            end
          end
        end
      end
    end

    if best_sample == nil then
      return nil
    end

    best_sample.gap = target.gap
    return best_sample
  end

  snap_spawn_transform = function(now_ms, spawn)
    if type(spawn) ~= "table" then
      return nil
    end

    local snapped = snap_target_to_nav(get_nav_grid_snapshot(now_ms), spawn, {
      prefer_traversable_cell = true,
      avoid_outer_rows = true,
    })
    if type(snapped) ~= "table" then
      return nil
    end

    return {
      x = tonumber(snapped.x) or tonumber(spawn.x) or 0.0,
      y = tonumber(snapped.y) or tonumber(spawn.y) or 0.0,
      heading = tonumber(spawn.heading),
    }
  end

  local function compute_follow_target(player, bot)
    local player_x = tonumber(player.x) or 0.0
    local player_y = tonumber(player.y) or 0.0
    local bot_x = tonumber(bot.x) or 0.0
    local bot_y = tonumber(bot.y) or 0.0
    local gap = distance(bot_x, bot_y, player_x, player_y)
    local offset_x, offset_y = bot_formation_offset(FOLLOW_STOP_DISTANCE)
    return {
      x = player_x + offset_x,
      y = player_y + offset_y,
      gap = gap,
    }
  end

  local function update_same_scene_follow(now_ms, scene, player, bot)
    if type(player) ~= "table" or type(bot) ~= "table" then
      return
    end

    local actor_address = tonumber(bot.actor_address) or 0
    if actor_address == 0 or not bot.transform_valid then
      return
    end

    local probe = get_probe_state()

    issue_auto_attack(now_ms, scene, bot, probe)

    if type(probe) == "table" and probe.disable_follow ~= false then
      state.follow_target = nil
      return
    end

    local target = snap_target_to_nav(get_nav_grid_snapshot(now_ms), compute_follow_target(player, bot), {
      avoid_outer_rows = true,
    })
    if type(target) ~= "table" then
      return
    end
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
      if gap <= FOLLOW_SETTLE_DISTANCE then
        stop_follow_move("follow_deadzone")
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
        wait_anchor = add_bot_formation_offset(wait_anchor, FOLLOW_STOP_DISTANCE)
        wait_anchor = snap_target_to_nav(get_nav_grid_snapshot(now_ms), wait_anchor, {
          prefer_traversable_cell = true,
        })
        if type(wait_anchor) ~= "table" then
          return
        end
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
    update_same_scene_follow(now_ms, scene, player, bot)
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
    update_same_scene_follow(now_ms, scene, player, bot)
  end

  local function handle_run_state(now_ms, scene, player, bot)
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
    update_same_scene_follow(now_ms, scene, player, bot)
  end

  if rawget(_G, "lua_bots_enable_test_hooks") == true then
    rawset(_G, "lua_bots_test_hooks", {
      is_enemy_actor = is_enemy_actor,
      find_nearest_enemy = find_nearest_enemy,
      issue_auto_attack = issue_auto_attack,
      heading_towards = heading_towards,
      snap_target_to_nav = snap_target_to_nav,
      follow_stop_distance = FOLLOW_STOP_DISTANCE,
      follow_resume_distance = FOLLOW_RESUME_DISTANCE,
      follow_settle_distance = FOLLOW_SETTLE_DISTANCE,
      state = state,
    })
  end

  sd.events.on("run.started", function()
    log("run.started")
    for _, bot_state in ipairs(state.bots) do
      bot_state.pending_run_promotion = true
    end
    sync_legacy_state_alias()
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
    if rawget(_G, "lua_bots_disable_tick") == true then
      return
    end

    local now_ms = tonumber(event.monotonic_milliseconds) or 0
    if now_ms - state.last_tick_ms < TICK_INTERVAL_MS then
      return
    end
    state.last_tick_ms = now_ms

    local scene = get_scene_state()
    local player = get_player_state()
    local desired_scene = build_scene_intent(scene)
    if type(scene) ~= "table" or type(player) ~= "table" or type(desired_scene) ~= "table" then
      if has_any_managed_bot_context() or state.last_scene_name ~= nil then
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

    local scene_name = tostring(scene.name or "")
    for _, bot_state in ipairs(state.bots) do
      load_bot_context(bot_state)
      local bot = ensure_bot_spawned(now_ms, player, desired_scene, anchor)
      if type(bot) == "table" and bot.available then
        if state.bot_dead or is_bot_dead(bot) then
          mark_bot_dead(now_ms, bot)
        elseif scene_name == "hub" then
          handle_hub_state(now_ms, scene, player, bot)
        elseif scene_name == "testrun" then
          handle_run_state(now_ms, scene, player, bot)
        else
          handle_private_state(now_ms, scene, player, bot)
        end
      end
      save_bot_context(bot_state)
    end
    sync_legacy_state_alias()
  end)
end

return app
