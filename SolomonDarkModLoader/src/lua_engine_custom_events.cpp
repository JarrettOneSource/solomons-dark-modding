#include "lua_engine_internal.h"

#include "lua_engine_values.h"

extern "C" {
#include "lua.h"
}

#include <cstdint>
#include <string>

namespace sdmod::detail {
namespace {

void DispatchCustomEventToMod(
    LoadedLuaMod* mod,
    const std::string& event_name,
    const LuaModValue& payload,
    std::uint64_t authority_participant_id,
    std::uint64_t stream_sequence) {
    if (mod == nullptr || mod->state == nullptr) {
        return;
    }

    lua_getfield(
        mod->state,
        LUA_REGISTRYINDEX,
        kLuaEventHandlersRegistryKey);
    if (!lua_istable(mod->state, -1)) {
        lua_pop(mod->state, 1);
        return;
    }
    lua_getfield(mod->state, -1, event_name.c_str());
    if (!lua_istable(mod->state, -1)) {
        lua_pop(mod->state, 2);
        return;
    }

    const auto handler_count = lua_rawlen(mod->state, -1);
    for (lua_Unsigned index = 1; index <= handler_count; ++index) {
        lua_rawgeti(mod->state, -1, static_cast<lua_Integer>(index));
        if (!lua_isfunction(mod->state, -1)) {
            lua_pop(mod->state, 1);
            continue;
        }
        PushLuaModValue(mod->state, payload);
        lua_createtable(mod->state, 0, 4);
        lua_pushstring(mod->state, event_name.c_str());
        lua_setfield(mod->state, -2, "event");
        lua_pushstring(mod->state, mod->descriptor.id.c_str());
        lua_setfield(mod->state, -2, "mod_id");
        lua_pushinteger(
            mod->state,
            static_cast<lua_Integer>(authority_participant_id));
        lua_setfield(mod->state, -2, "authority_participant_id");
        lua_pushinteger(
            mod->state,
            static_cast<lua_Integer>(stream_sequence));
        lua_setfield(mod->state, -2, "stream_sequence");
        if (lua_pcall(mod->state, 2, 0, 0) != LUA_OK) {
            const auto* message = lua_tostring(mod->state, -1);
            LogLuaMessage(
                *mod,
                event_name + " handler failed: " +
                    (message == nullptr ? "unknown" : message));
            lua_pop(mod->state, 1);
        }
    }
    lua_pop(mod->state, 2);
}

}  // namespace

void DispatchCustomEventToLuaMods(
    const std::string& mod_id,
    const std::string& event_name,
    const LuaModValue& payload,
    std::uint64_t authority_participant_id,
    std::uint64_t stream_sequence) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod != nullptr && mod->descriptor.id == mod_id) {
            DispatchCustomEventToMod(
                mod.get(),
                event_name,
                payload,
                authority_participant_id,
                stream_sequence);
        }
    }
}

}  // namespace sdmod::detail
