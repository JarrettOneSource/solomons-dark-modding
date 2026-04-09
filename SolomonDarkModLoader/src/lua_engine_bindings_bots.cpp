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

}  // namespace

void RegisterLuaBotBindings(lua_State* state) {
    lua_createtable(state, 0, 10);
    RegisterFunction(state, &LuaBotsCreate, "create");
    RegisterFunction(state, &LuaBotsDestroy, "destroy");
    RegisterFunction(state, &LuaBotsClear, "clear");
    RegisterFunction(state, &LuaBotsUpdate, "update");
    RegisterFunction(state, &LuaBotsMoveTo, "move_to");
    RegisterFunction(state, &LuaBotsStop, "stop");
    RegisterFunction(state, &LuaBotsFace, "face");
    RegisterFunction(state, &LuaBotsCast, "cast");
    RegisterFunction(state, &LuaBotsGetCount, "get_count");
    RegisterFunction(state, &LuaBotsGetState, "get_state");
    lua_setfield(state, -2, "bots");
}

}  // namespace sdmod::detail
