local lifecycle = {}

function lifecycle.install(ctx)
  local state = ctx.state
  local config = ctx.config

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

    ctx.log(string.format(
      "managed bot dead id=%s hp=%.2f; leaving corpse inert for rest of run",
      tostring(state.bot_id),
      tonumber(type(bot) == "table" and bot.hp or 0.0) or 0.0))
  end

  local function is_managed_bot_name(bot_name)
    return type(bot_name) == "string" and config.MANAGED_BOT_NAMES[bot_name] == true
  end

  local function destroy_managed_bots()
    for _, bot_state in ipairs(state.bots) do
      if bot_state.bot_id ~= nil then
        destroy_bot_by_id(bot_state.bot_id)
      end
    end

    local bots = ctx.get_all_bot_states()
    if type(bots) == "table" then
      for _, bot in ipairs(bots) do
        if type(bot) == "table" and is_managed_bot_name(bot.name) then
          destroy_bot_by_id(bot.id)
        end
      end
    end

    ctx.clear_follow_state()
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
    local bots = ctx.get_all_bot_states()
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
        elseif exact_name_match or not config.CURRENT_MANAGED_BOT_NAMES[bot.name] then
          destroy_bot_by_id(bot.id)
        end
      end
    end
  end

  ctx.is_bot_dead = is_bot_dead
  ctx.destroy_bot_by_id = destroy_bot_by_id
  ctx.mark_bot_dead = mark_bot_dead
  ctx.is_managed_bot_name = is_managed_bot_name
  ctx.destroy_managed_bots = destroy_managed_bots
  ctx.has_any_managed_bot_context = has_any_managed_bot_context
  ctx.adopt_existing_managed_bot = adopt_existing_managed_bot
end

return lifecycle
