local scene_module = {}

function scene_module.install(ctx)
  local state = ctx.state
  local config = ctx.config

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

    local area = config.SUPPORTED_PRIVATE_AREAS[scene_name]
    if area == nil then
      return nil
    end

    return {
      kind = "private_region",
      region_index = area.region_index,
      region_type_id = area.region_type_id,
    }
  end

  local function normalize_scene_intent(scene)
    if type(scene) ~= "table" then
      return nil
    end

    local kind = normalize_scene_kind(scene.kind)
    if kind == "run" then
      return { kind = "run" }
    end
    if kind == "shared_hub" then
      return { kind = "shared_hub" }
    end
    if kind == "private_region" then
      return {
        kind = "private_region",
        region_index = tonumber(scene.region_index) or -1,
        region_type_id = tonumber(scene.region_type_id) or -1,
      }
    end
    return nil
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

  local function build_spawn_transform(player, anchor, scene_intent)
    if type(player) ~= "table" then
      return nil
    end

    local heading = tonumber(player.heading)
    local offset_x = tonumber(state.spawn_offset_x) or config.DEFAULT_SPAWN_OFFSET_X
    local offset_y = tonumber(state.spawn_offset_y) or config.DEFAULT_SPAWN_OFFSET_Y
    if type(anchor) == "table" then
      return {
        x = (tonumber(anchor.x) or 0.0) + offset_x,
        y = (tonumber(anchor.y) or 0.0) + offset_y,
        heading = heading,
      }
    end

    if type(scene_intent) == "table" and normalize_scene_kind(scene_intent.kind) == "shared_hub" then
      return {
        x = config.DEFAULT_HUB_SPAWN_X + offset_x,
        y = config.DEFAULT_HUB_SPAWN_Y + offset_y,
        heading = heading,
      }
    end

    return {
      x = (tonumber(player.x) or 0.0) + offset_x,
      y = (tonumber(player.y) or 0.0) + offset_y,
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
    if not force and now_ms - state.last_scene_sync_ms < config.SCENE_UPDATE_COOLDOWN_MS then
      return false
    end

    local spawn = build_spawn_transform(player, anchor, scene_intent)
    if type(spawn) ~= "table" then
      return false
    end
    spawn = ctx.snap_spawn_transform(now_ms, spawn)
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
      ctx.log(string.format(
        "scene_update id=%s reason=%s scene=%s spawn=(%.2f, %.2f)",
        tostring(state.bot_id),
        tostring(reason),
        tostring(state.scene_key),
        spawn.x,
        spawn.y))
    else
      ctx.log(string.format(
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
        return ctx.get_bot_state(state.bot_id)
      end
      return nil
    end

    ctx.adopt_existing_managed_bot()
    local spawn = build_spawn_transform(player, anchor, scene_intent)
    if type(spawn) ~= "table" then
      return nil
    end
    spawn = ctx.snap_spawn_transform(now_ms, spawn)
    if type(spawn) ~= "table" then
      return nil
    end

    if state.bot_id == nil then
      if now_ms - state.last_spawn_attempt_ms < config.SPAWN_RETRY_MS then
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
      ctx.log(string.format(
        "spawned %s id=%s scene=%s point=(%.2f, %.2f)",
        tostring(state.bot_name),
        tostring(bot_id),
        tostring(state.scene_key),
        spawn.x,
        spawn.y))
      return ctx.get_bot_state(bot_id)
    end

    local bot = ctx.get_bot_state(state.bot_id)
    if bot == nil or not bot.available then
      ctx.clear_current_bot_state()
      return nil
    end
    if ctx.is_bot_dead(bot) then
      ctx.mark_bot_dead(now_ms, bot)
      return bot
    end

    return bot
  end

  ctx.is_scene_stable = is_scene_stable
  ctx.normalize_scene_kind = normalize_scene_kind
  ctx.build_scene_intent = build_scene_intent
  ctx.normalize_scene_intent = normalize_scene_intent
  ctx.scene_key = scene_key
  ctx.scene_matches = scene_matches
  ctx.build_spawn_transform = build_spawn_transform
  ctx.issue_scene_update = issue_scene_update
  ctx.ensure_bot_spawned = ensure_bot_spawned
end

return scene_module
