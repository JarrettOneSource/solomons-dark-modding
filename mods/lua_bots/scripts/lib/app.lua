local app = {}

local function require_mod(path)
  if type(sd) ~= "table" or type(sd.runtime) ~= "table" or type(sd.runtime.require_mod) ~= "function" then
    error("sd.runtime.require_mod is unavailable")
  end
  return sd.runtime.require_mod(path)
end

local function seed_random()
  pcall(function()
    local seed = 1
    if type(os) == "table" and type(os.time) == "function" then
      seed = os.time()
    end
    math.randomseed(seed)
    math.random()
    math.random()
    math.random()
  end)
end

local function publish_test_hooks(ctx)
  if rawget(_G, "lua_bots_enable_test_hooks") ~= true then
    return
  end

  rawset(_G, "lua_bots_test_hooks", {
    is_enemy_actor = ctx.is_enemy_actor,
    find_nearest_enemy = ctx.find_nearest_enemy,
    issue_auto_attack = ctx.issue_auto_attack,
    heading_towards = ctx.heading_towards,
    snap_target_to_nav = ctx.snap_target_to_nav,
    compute_follow_target = ctx.compute_follow_target,
    choose_follow_target = ctx.choose_follow_target,
    should_refresh_follow_target = ctx.should_refresh_follow_target,
    update_same_scene_follow = ctx.update_same_scene_follow,
    handle_pending_skill_choice = ctx.handle_pending_skill_choice,
    follow_stop_distance = ctx.config.FOLLOW_STOP_DISTANCE,
    follow_resume_distance = ctx.config.FOLLOW_RESUME_DISTANCE,
    follow_target_arrival_distance = ctx.config.FOLLOW_TARGET_ARRIVAL_DISTANCE,
    follow_move_timeout_ms = ctx.config.FOLLOW_MOVE_TIMEOUT_MS,
    state = ctx.state,
  })
end

local function register_events(ctx)
  local state = ctx.state

  sd.events.on("run.started", function()
    ctx.log("run.started")
    for _, bot_state in ipairs(state.bots) do
      bot_state.pending_run_promotion = true
    end
    ctx.sync_legacy_state_alias()
    ctx.reset_travel_candidate()
    state.travel_state = "run"
    state.active_private_area_name = nil
    state.target_area_name = nil
  end)

  sd.events.on("run.ended", function()
    ctx.log("run.ended")
    ctx.destroy_managed_bots()
  end)

  sd.events.on("runtime.tick", function(event)
    if rawget(_G, "lua_bots_disable_tick") == true then
      return
    end

    local now_ms = tonumber(event.monotonic_milliseconds) or 0
    if now_ms - state.last_tick_ms < ctx.config.TICK_INTERVAL_MS then
      return
    end
    state.last_tick_ms = now_ms

    local scene = ctx.get_scene_state()
    local player = ctx.get_player_state()
    local desired_scene = ctx.build_scene_intent(scene)
    if type(scene) ~= "table" or type(player) ~= "table" or type(desired_scene) ~= "table" then
      if ctx.has_any_managed_bot_context() or state.last_scene_name ~= nil then
        ctx.destroy_managed_bots()
      end
      return
    end
    ctx.track_scene_entry(now_ms, scene)

    local anchor = nil
    if desired_scene.kind == "private_region" then
      local area = ctx.config.SUPPORTED_PRIVATE_AREAS[tostring(scene.name or "")]
      anchor = area ~= nil and area.interior_anchor or nil
    end

    local scene_name = tostring(scene.name or "")
    for _, bot_state in ipairs(state.bots) do
      ctx.load_bot_context(bot_state)
      local bot = ctx.ensure_bot_spawned(now_ms, player, desired_scene, anchor)
      if type(bot) == "table" and bot.available then
        ctx.handle_pending_skill_choice()
        if state.bot_dead or ctx.is_bot_dead(bot) then
          ctx.mark_bot_dead(now_ms, bot)
        elseif scene_name == "hub" then
          ctx.handle_hub_state(now_ms, scene, player, bot)
        elseif scene_name == "testrun" then
          ctx.handle_run_state(now_ms, scene, player, bot)
        else
          ctx.handle_private_state(now_ms, scene, player, bot)
        end
      end
      ctx.save_bot_context(bot_state)
    end
    ctx.sync_legacy_state_alias()
  end)
end

local function create_context()
  local config = require_mod("scripts/lib/lua_bots/config.lua").create()
  local state, state_api = require_mod("scripts/lib/lua_bots/state.lua").create(config)
  local ctx = {
    config = config,
    state = state,
  }

  for key, value in pairs(state_api) do
    ctx[key] = value
  end

  require_mod("scripts/lib/lua_bots/runtime.lua").install(ctx)
  require_mod("scripts/lib/lua_bots/lifecycle.lua").install(ctx)
  require_mod("scripts/lib/lua_bots/skill_choices.lua").install(ctx)
  require_mod("scripts/lib/lua_bots/scene.lua").install(ctx)
  require_mod("scripts/lib/lua_bots/combat.lua").install(ctx)
  require_mod("scripts/lib/lua_bots/follow.lua").install(ctx)
  require_mod("scripts/lib/lua_bots/travel.lua").install(ctx)

  return ctx
end

function app.start()
  seed_random()
  local ctx = create_context()
  publish_test_hooks(ctx)
  register_events(ctx)
end

return app
