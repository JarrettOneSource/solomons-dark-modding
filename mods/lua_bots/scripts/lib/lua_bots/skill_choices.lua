local skill_choices = {}

function skill_choices.install(ctx)
  local state = ctx.state

  local function handle_pending_skill_choice()
    if state.bot_id == nil or type(sd) ~= "table" or type(sd.bots) ~= "table" then
      return false
    end
    if type(sd.bots.get_skill_choices) ~= "function" or type(sd.bots.choose_skill) ~= "function" then
      return false
    end

    local ok, choices = pcall(sd.bots.get_skill_choices, state.bot_id)
    if not ok or type(choices) ~= "table" or choices.pending ~= true or type(choices.options) ~= "table" then
      return false
    end
    if #choices.options <= 0 then
      return false
    end

    local generation = tonumber(choices.generation) or 0
    if generation ~= 0 and generation == tonumber(state.last_skill_choice_generation) then
      return false
    end

    local option_index = math.random(1, #choices.options)
    local selected = choices.options[option_index]
    local apply_ok, apply_result = pcall(sd.bots.choose_skill, state.bot_id, option_index, generation)
    if apply_ok and apply_result then
      state.last_skill_choice_generation = generation
      if type(state.bot_profile) == "table" then
        if tonumber(choices.level) ~= nil then
          state.bot_profile.level = tonumber(choices.level)
        end
        if tonumber(choices.experience) ~= nil then
          state.bot_profile.experience = tonumber(choices.experience)
        end
      end
      ctx.log(string.format(
        "skill_choice id=%s generation=%s option_index=%d option_id=%s option_count=%d",
        tostring(state.bot_id),
        tostring(generation),
        option_index,
        tostring(type(selected) == "table" and selected.id or nil),
        #choices.options))
      return true
    end

    ctx.log(string.format(
      "skill_choice failed id=%s generation=%s error=%s",
      tostring(state.bot_id),
      tostring(generation),
      tostring(apply_result)))
    return false
  end

  ctx.handle_pending_skill_choice = handle_pending_skill_choice
end

return skill_choices
