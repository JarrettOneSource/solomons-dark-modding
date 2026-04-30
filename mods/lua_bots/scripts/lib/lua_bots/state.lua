local state_module = {}

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
  "last_skill_choice_generation",
}

function state_module.create(config)
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
    last_skill_choice_generation = 0,
    nav_grid_cache = nil,
    nav_grid_cache_world_id = nil,
    nav_grid_cache_at_ms = 0,
  }

  local api = {
    BOT_CONTEXT_FIELDS = BOT_CONTEXT_FIELDS,
  }

  function api.reset_bot_context(bot_state)
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
    bot_state.last_skill_choice_generation = 0
  end

  function api.make_bot_context(bot_config)
    local bot_state = {
      config = bot_config,
      bot_name = bot_config.name,
      bot_profile = bot_config.profile,
      spawn_offset_x = tonumber(bot_config.spawn_offset_x) or config.DEFAULT_SPAWN_OFFSET_X,
      spawn_offset_y = tonumber(bot_config.spawn_offset_y) or config.DEFAULT_SPAWN_OFFSET_Y,
    }
    api.reset_bot_context(bot_state)
    return bot_state
  end

  for _, bot_config in ipairs(config.BOT_CONFIGS) do
    table.insert(state.bots, api.make_bot_context(bot_config))
  end
  state.bot_count = #state.bots

  function api.load_bot_context(bot_state)
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

  function api.save_bot_context(bot_state)
    if type(bot_state) ~= "table" then
      return
    end
    for _, field in ipairs(BOT_CONTEXT_FIELDS) do
      bot_state[field] = state[field]
    end
  end

  function api.sync_legacy_state_alias()
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

  function api.clear_current_bot_state()
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
    state.last_skill_choice_generation = 0
  end

  function api.clear_follow_state()
    for _, bot_state in ipairs(state.bots) do
      api.reset_bot_context(bot_state)
    end
    api.sync_legacy_state_alias()
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

  api.sync_legacy_state_alias()
  lua_bots_debug = state

  return state, api
end

return state_module
