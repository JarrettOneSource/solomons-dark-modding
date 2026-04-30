#include "lua_engine_bindings_internal.h"

namespace sdmod::detail {
namespace {

int LuaBotsCreate(lua_State* state) {
    multiplayer::BotCreateRequest request;
    std::string error_message;
    if (!ParseBotCreateRequest(state, 1, &request, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    std::uint64_t bot_id = 0;
    if (!multiplayer::CreateBot(request, &bot_id)) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(bot_id));
    return 1;
}

int LuaBotsDestroy(lua_State* state) {
    std::uint64_t bot_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_pushboolean(state, multiplayer::DestroyBot(bot_id) ? 1 : 0);
    return 1;
}

int LuaBotsClear(lua_State* state) {
    (void)state;
    multiplayer::DestroyAllBots();
    return 0;
}

int LuaBotsUpdate(lua_State* state) {
    multiplayer::BotUpdateRequest request;
    std::string error_message;
    if (!ParseBotUpdateRequest(state, 1, &request, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_pushboolean(state, multiplayer::UpdateBot(request) ? 1 : 0);
    return 1;
}

int LuaBotsMoveTo(lua_State* state) {
    multiplayer::BotMoveToRequest request;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &request.bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (!lua_isnumber(state, 2) || !lua_isnumber(state, 3)) {
        return luaL_error(state, "sd.bots.move_to expects (id, x, y)");
    }

    request.target_x = static_cast<float>(lua_tonumber(state, 2));
    request.target_y = static_cast<float>(lua_tonumber(state, 3));
    lua_pushboolean(state, multiplayer::MoveBotTo(request) ? 1 : 0);
    return 1;
}

int LuaBotsStop(lua_State* state) {
    std::uint64_t bot_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_pushboolean(state, multiplayer::StopBot(bot_id) ? 1 : 0);
    return 1;
}

int LuaBotsFace(lua_State* state) {
    std::uint64_t bot_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (!lua_isnumber(state, 2)) {
        return luaL_error(state, "sd.bots.face expects (id, angle)");
    }

    const auto heading = static_cast<float>(lua_tonumber(state, 2));
    lua_pushboolean(state, multiplayer::FaceBot(bot_id, heading) ? 1 : 0);
    return 1;
}

int LuaBotsFaceTarget(lua_State* state) {
    std::uint64_t bot_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }
    if (!lua_isinteger(state, 2) && !lua_isnumber(state, 2)) {
        return luaL_error(state, "sd.bots.face_target expects (id, actor_address[, fallback_angle])");
    }

    const auto target_actor_value = static_cast<lua_Integer>(lua_tointeger(state, 2));
    if (target_actor_value < 0) {
        return luaL_error(state, "sd.bots.face_target actor_address must be non-negative");
    }
    const auto target_actor_address = static_cast<uintptr_t>(target_actor_value);
    const bool fallback_heading_valid = lua_gettop(state) >= 3 && !lua_isnil(state, 3);
    float fallback_heading = 0.0f;
    if (fallback_heading_valid) {
        if (!lua_isnumber(state, 3)) {
            return luaL_error(state, "sd.bots.face_target fallback_angle must be a number");
        }
        fallback_heading = static_cast<float>(lua_tonumber(state, 3));
    }

    lua_pushboolean(
        state,
        multiplayer::FaceBotTarget(
            bot_id,
            target_actor_address,
            fallback_heading_valid,
            fallback_heading) ? 1 : 0);
    return 1;
}

int LuaBotsCast(lua_State* state) {
    multiplayer::BotCastRequest request;
    std::string error_message;
    if (!ParseBotCastRequest(state, 1, &request, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_pushboolean(state, multiplayer::QueueBotCast(request) ? 1 : 0);
    return 1;
}

int LuaBotsGetCount(lua_State* state) {
    lua_pushinteger(state, static_cast<lua_Integer>(multiplayer::GetBotCount()));
    return 1;
}

int LuaBotsGetState(lua_State* state) {
    if (lua_gettop(state) >= 1 && !lua_isnil(state, 1)) {
        std::uint64_t bot_id = 0;
        std::string error_message;
        if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }

        multiplayer::BotSnapshot snapshot;
        if (!multiplayer::ReadBotSnapshot(bot_id, &snapshot)) {
            lua_pushnil(state);
            return 1;
        }

        PushBotSnapshot(state, snapshot);
        return 1;
    }

    PushBotSnapshotArray(state);
    return 1;
}

void PushBotSkillChoiceSnapshot(lua_State* state, const multiplayer::BotSkillChoiceSnapshot& snapshot) {
    lua_createtable(state, 0, 5);
    lua_pushboolean(state, snapshot.pending ? 1 : 0);
    lua_setfield(state, -2, "pending");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.generation));
    lua_setfield(state, -2, "generation");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.level));
    lua_setfield(state, -2, "level");
    lua_pushinteger(state, static_cast<lua_Integer>(snapshot.experience));
    lua_setfield(state, -2, "experience");
    lua_createtable(state, static_cast<int>(snapshot.options.size()), 0);
    for (std::size_t index = 0; index < snapshot.options.size(); ++index) {
        const auto& option = snapshot.options[index];
        lua_createtable(state, 0, 2);
        lua_pushinteger(state, static_cast<lua_Integer>(option.option_id));
        lua_setfield(state, -2, "id");
        lua_pushinteger(state, static_cast<lua_Integer>(option.apply_count));
        lua_setfield(state, -2, "apply_count");
        lua_rawseti(state, -2, static_cast<lua_Integer>(index + 1));
    }
    lua_setfield(state, -2, "options");
}

int LuaBotsGetSkillChoices(lua_State* state) {
    std::uint64_t bot_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    multiplayer::BotSkillChoiceSnapshot snapshot;
    if (!multiplayer::ReadBotSkillChoices(bot_id, &snapshot)) {
        lua_pushnil(state);
        return 1;
    }

    PushBotSkillChoiceSnapshot(state, snapshot);
    return 1;
}

bool ReadOptionalLuaIntegerField(
    lua_State* state,
    int table_index,
    const char* field_name,
    lua_Integer* value) {
    lua_getfield(state, table_index, field_name);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        return false;
    }
    if (!lua_isinteger(state, -1) && !lua_isnumber(state, -1)) {
        lua_pop(state, 1);
        return false;
    }
    *value = lua_tointeger(state, -1);
    lua_pop(state, 1);
    return true;
}

int LuaBotsChooseSkill(lua_State* state) {
    multiplayer::BotSkillChoiceRequest request;
    std::string error_message;
    if (lua_istable(state, 1)) {
        lua_Integer value = 0;
        if (!ReadOptionalLuaIntegerField(state, 1, "id", &value) &&
            !ReadOptionalLuaIntegerField(state, 1, "bot_id", &value)) {
            return luaL_error(state, "sd.bots.choose_skill table requires id");
        }
        if (value <= 0) {
            return luaL_error(state, "sd.bots.choose_skill id must be positive");
        }
        request.bot_id = static_cast<std::uint64_t>(value);
        if (ReadOptionalLuaIntegerField(state, 1, "generation", &value)) {
            if (value < 0) {
                return luaL_error(state, "sd.bots.choose_skill generation must be non-negative");
            }
            request.generation = static_cast<std::uint64_t>(value);
        }
        if (ReadOptionalLuaIntegerField(state, 1, "option_index", &value) ||
            ReadOptionalLuaIntegerField(state, 1, "index", &value)) {
            request.option_index = static_cast<std::int32_t>(value);
        }
        if (ReadOptionalLuaIntegerField(state, 1, "option_id", &value) ||
            ReadOptionalLuaIntegerField(state, 1, "choice_id", &value)) {
            request.option_id = static_cast<std::int32_t>(value);
        }
    } else {
        if (!ParseBotIdArgument(state, 1, &request.bot_id, &error_message)) {
            return luaL_error(state, "%s", error_message.c_str());
        }
        if (!lua_isinteger(state, 2) && !lua_isnumber(state, 2)) {
            return luaL_error(state, "sd.bots.choose_skill expects (id, option_index[, generation])");
        }
        request.option_index = static_cast<std::int32_t>(lua_tointeger(state, 2));
        if (lua_gettop(state) >= 3 && !lua_isnil(state, 3)) {
            if (!lua_isinteger(state, 3) && !lua_isnumber(state, 3)) {
                return luaL_error(state, "sd.bots.choose_skill generation must be an integer");
            }
            const auto generation = lua_tointeger(state, 3);
            if (generation < 0) {
                return luaL_error(state, "sd.bots.choose_skill generation must be non-negative");
            }
            request.generation = static_cast<std::uint64_t>(generation);
        }
    }

    if (!multiplayer::ChooseBotSkill(request, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    lua_pushboolean(state, 1);
    return 1;
}

int LuaBotsDebugSyncLevelUp(lua_State* state) {
    lua_Integer level = 0;
    lua_Integer experience = 0;
    lua_Integer source_progression_address = 0;

    if (lua_istable(state, 1)) {
        if (!ReadOptionalLuaIntegerField(state, 1, "level", &level) || level <= 0) {
            return luaL_error(state, "sd.bots.debug_sync_level_up table requires positive level");
        }
        if (!ReadOptionalLuaIntegerField(state, 1, "experience", &experience) &&
            !ReadOptionalLuaIntegerField(state, 1, "xp", &experience)) {
            return luaL_error(state, "sd.bots.debug_sync_level_up table requires experience");
        }
        (void)ReadOptionalLuaIntegerField(state, 1, "source_progression_address", &source_progression_address);
    } else {
        if (!lua_isinteger(state, 1) && !lua_isnumber(state, 1)) {
            return luaL_error(state, "sd.bots.debug_sync_level_up expects (level, experience[, source_progression])");
        }
        if (!lua_isinteger(state, 2) && !lua_isnumber(state, 2)) {
            return luaL_error(state, "sd.bots.debug_sync_level_up expects (level, experience[, source_progression])");
        }
        level = lua_tointeger(state, 1);
        experience = lua_tointeger(state, 2);
        if (lua_gettop(state) >= 3 && !lua_isnil(state, 3)) {
            if (!lua_isinteger(state, 3) && !lua_isnumber(state, 3)) {
                return luaL_error(state, "sd.bots.debug_sync_level_up source_progression must be an integer address");
            }
            source_progression_address = lua_tointeger(state, 3);
        }
    }

    if (level <= 0) {
        return luaL_error(state, "sd.bots.debug_sync_level_up level must be positive");
    }
    if (experience < 0) {
        return luaL_error(state, "sd.bots.debug_sync_level_up experience must be non-negative");
    }
    if (source_progression_address < 0) {
        return luaL_error(state, "sd.bots.debug_sync_level_up source_progression must be non-negative");
    }

    multiplayer::SyncBotsToSharedLevelUp(
        static_cast<std::int32_t>(level),
        static_cast<std::int32_t>(experience),
        static_cast<uintptr_t>(source_progression_address));
    lua_pushboolean(state, 1);
    return 1;
}

}  // namespace

void RegisterLuaBotBindings(lua_State* state) {
    lua_createtable(state, 0, 14);
    RegisterFunction(state, &LuaBotsCreate, "create");
    RegisterFunction(state, &LuaBotsDestroy, "destroy");
    RegisterFunction(state, &LuaBotsClear, "clear");
    RegisterFunction(state, &LuaBotsUpdate, "update");
    RegisterFunction(state, &LuaBotsMoveTo, "move_to");
    RegisterFunction(state, &LuaBotsStop, "stop");
    RegisterFunction(state, &LuaBotsFace, "face");
    RegisterFunction(state, &LuaBotsFaceTarget, "face_target");
    RegisterFunction(state, &LuaBotsCast, "cast");
    RegisterFunction(state, &LuaBotsGetCount, "get_count");
    RegisterFunction(state, &LuaBotsGetState, "get_state");
    RegisterFunction(state, &LuaBotsGetSkillChoices, "get_skill_choices");
    RegisterFunction(state, &LuaBotsChooseSkill, "choose_skill");
    RegisterFunction(state, &LuaBotsDebugSyncLevelUp, "debug_sync_level_up");
    lua_setfield(state, -2, "bots");
}

}  // namespace sdmod::detail
