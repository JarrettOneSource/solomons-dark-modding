#include "lua_engine_bindings_internal.h"
#include "gameplay_seams.h"
#include "memory_access.h"
#include "native_spell_stats.h"

#include <algorithm>
#include <cmath>

namespace sdmod::detail {
namespace {

struct PrimaryAttackWindow {
    bool resolved = false;
    bool native_backed = false;
    float min_range = 0.0f;
    float max_range = 0.0f;
    const char* source = "unresolved";
};

bool TryReadResolvedGameFloat(uintptr_t absolute_address, float* value) {
    if (value != nullptr) {
        *value = 0.0f;
    }
    if (absolute_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0 ||
        !memory.IsReadableRange(resolved_address, sizeof(float))) {
        return false;
    }

    const auto candidate = memory.ReadValueOr<float>(resolved_address, 0.0f);
    if (!std::isfinite(candidate) || candidate <= 0.0f) {
        return false;
    }

    if (value != nullptr) {
        *value = candidate;
    }
    return true;
}

bool ReadNativePrimarySelectionPursuitRange(
    uintptr_t actor_address,
    int element_id,
    float* range,
    const char** source) {
    if (range != nullptr) {
        *range = 0.0f;
    }
    if (source != nullptr) {
        *source = "unresolved";
    }

    if (element_id == 1) {
        float water_range = 0.0f;
        if (TryReadResolvedGameFloat(kWaterPrimaryControlBrainRangeGlobal, &water_range)) {
            if (range != nullptr) {
                *range = water_range;
            }
            if (source != nullptr) {
                *source = "native_water_control_brain_range";
            }
            return true;
        }
    }

    if (actor_address == 0 ||
        kActorAnimationSelectionStateOffset == 0 ||
        kActorControlBrainPursuitRangeOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(actor_address + kActorAnimationSelectionStateOffset, sizeof(uintptr_t))) {
        return false;
    }

    const auto selection_state =
        memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorAnimationSelectionStateOffset,
            0);
    if (selection_state == 0 ||
        !memory.IsReadableRange(selection_state + kActorControlBrainPursuitRangeOffset, sizeof(float))) {
        return false;
    }

    const auto pursuit_range =
        memory.ReadValueOr<float>(
            selection_state + kActorControlBrainPursuitRangeOffset,
            0.0f);
    if (!std::isfinite(pursuit_range) || pursuit_range <= 0.0f) {
        return false;
    }

    if (range != nullptr) {
        *range = pursuit_range;
    }
    if (source != nullptr) {
        *source = "native_selection_pursuit_range";
    }
    return true;
}

PrimaryAttackWindow ResolvePrimaryAttackWindow(int element_id, uintptr_t actor_address) {
    PrimaryAttackWindow window{};
    float max_range = 0.0f;
    const char* source = "unresolved";
    if (!ReadNativePrimarySelectionPursuitRange(actor_address, element_id, &max_range, &source)) {
        return window;
    }

    window.resolved = true;
    window.native_backed = true;
    window.max_range = max_range;
    window.source = source;
    return window;
}

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
        return luaL_error(state, "sd.bots.face_target expects (id, actor_address[, default_angle])");
    }

    const auto target_actor_value = static_cast<lua_Integer>(lua_tointeger(state, 2));
    if (target_actor_value < 0) {
        return luaL_error(state, "sd.bots.face_target actor_address must be non-negative");
    }
    const auto target_actor_address = static_cast<uintptr_t>(target_actor_value);
    const bool default_heading_valid = lua_gettop(state) >= 3 && !lua_isnil(state, 3);
    float default_heading = 0.0f;
    if (default_heading_valid) {
        if (!lua_isnumber(state, 3)) {
            return luaL_error(state, "sd.bots.face_target default_angle must be a number");
        }
        default_heading = static_cast<float>(lua_tonumber(state, 3));
    }

    lua_pushboolean(
        state,
        multiplayer::FaceBotTarget(
            bot_id,
            target_actor_address,
            default_heading_valid,
            default_heading) ? 1 : 0);
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

int LuaBotsResolvePrimaryEntry(lua_State* state) {
    if (!lua_isinteger(state, 1) && !lua_isnumber(state, 1)) {
        return luaL_error(state, "sd.bots.resolve_primary_entry expects (element_id)");
    }

    const auto element_id = static_cast<int>(lua_tointeger(state, 1));
    const auto primary_entry = ResolveNativePrimaryEntryForElement(element_id);
    if (primary_entry < 0) {
        lua_pushnil(state);
        return 1;
    }

    lua_pushinteger(state, static_cast<lua_Integer>(primary_entry));
    return 1;
}

int LuaBotsGetPrimaryAttackWindow(lua_State* state) {
    std::uint64_t bot_id = 0;
    std::string error_message;
    if (!ParseBotIdArgument(state, 1, &bot_id, &error_message)) {
        return luaL_error(state, "%s", error_message.c_str());
    }

    int element_id = -1;
    if (lua_gettop(state) >= 2 && !lua_isnil(state, 2)) {
        if (!lua_isinteger(state, 2) && !lua_isnumber(state, 2)) {
            return luaL_error(state, "sd.bots.get_primary_attack_window element_id must be an integer");
        }
        element_id = static_cast<int>(lua_tointeger(state, 2));
    }

    uintptr_t actor_address = 0;
    multiplayer::BotSnapshot snapshot;
    if (multiplayer::ReadBotSnapshot(bot_id, &snapshot) && snapshot.available) {
        if (element_id < 0) {
            element_id = snapshot.character_profile.element_id;
        }
        actor_address = snapshot.actor_address;
    }

    const auto window = ResolvePrimaryAttackWindow(element_id, actor_address);
    if (!window.resolved) {
        lua_pushnil(state);
        return 1;
    }

    lua_createtable(state, 0, 4);
    lua_pushnumber(state, static_cast<lua_Number>(window.min_range));
    lua_setfield(state, -2, "min_range");
    lua_pushnumber(state, static_cast<lua_Number>(window.max_range));
    lua_setfield(state, -2, "max_range");
    lua_pushboolean(state, window.native_backed ? 1 : 0);
    lua_setfield(state, -2, "native_backed");
    lua_pushstring(state, window.source);
    lua_setfield(state, -2, "source");
    return 1;
}

}  // namespace

void RegisterLuaBotBindings(lua_State* state) {
    lua_createtable(state, 0, 16);
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
    RegisterFunction(state, &LuaBotsResolvePrimaryEntry, "resolve_primary_entry");
    RegisterFunction(state, &LuaBotsGetPrimaryAttackWindow, "get_primary_attack_window");
    lua_setfield(state, -2, "bots");
}

}  // namespace sdmod::detail
