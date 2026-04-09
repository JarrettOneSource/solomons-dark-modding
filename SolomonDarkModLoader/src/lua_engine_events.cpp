#include "lua_engine_internal.h"

#include "logger.h"

extern "C" {
#include "lua.h"
#include "lauxlib.h"
}

#include <string>

namespace sdmod::detail {
namespace {

void PushEventNameField(lua_State* state, const char* event_name) {
    lua_pushstring(state, event_name);
    lua_setfield(state, -2, "event");
}

void PushVec2Field(lua_State* state, const char* field_name, float x, float y) {
    lua_createtable(state, 0, 2);
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
    lua_setfield(state, -2, field_name);
}

void PushRuntimeTickPayload(lua_State* state, const SDModRuntimeTickContext& context) {
    lua_createtable(state, 0, 3);

    lua_pushinteger(state, static_cast<lua_Integer>(context.tick_count));
    lua_setfield(state, -2, "tick_count");

    lua_pushinteger(state, static_cast<lua_Integer>(context.tick_interval_ms));
    lua_setfield(state, -2, "tick_interval_ms");

    lua_pushinteger(state, static_cast<lua_Integer>(context.monotonic_milliseconds));
    lua_setfield(state, -2, "monotonic_milliseconds");
}

void PushRunStartedPayload(lua_State* state) {
    lua_createtable(state, 0, 1);
    PushEventNameField(state, kRunStartedEventName);
}

void PushRunEndedPayload(lua_State* state, const char* reason) {
    lua_createtable(state, 0, 2);
    PushEventNameField(state, kRunEndedEventName);
    if (reason != nullptr) {
        lua_pushstring(state, reason);
    } else {
        lua_pushnil(state);
    }
    lua_setfield(state, -2, "reason");
}

void PushWavePayload(lua_State* state, const char* event_name, int wave_number) {
    lua_createtable(state, 0, 2);
    PushEventNameField(state, event_name);
    lua_pushinteger(state, static_cast<lua_Integer>(wave_number));
    lua_setfield(state, -2, "wave");
}

void PushEnemyDeathPayload(lua_State* state, int enemy_type, float x, float y, const char* kill_method) {
    lua_createtable(state, 0, 6);
    PushEventNameField(state, kEnemyDeathEventName);
    lua_pushinteger(state, static_cast<lua_Integer>(enemy_type));
    lua_setfield(state, -2, "enemy_type");
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
    PushVec2Field(state, "position", x, y);
    if (kill_method != nullptr) {
        lua_pushstring(state, kill_method);
    } else {
        lua_pushnil(state);
    }
    lua_setfield(state, -2, "kill_method");
}

void PushEnemySpawnedPayload(lua_State* state, int enemy_type, float x, float y) {
    lua_createtable(state, 0, 5);
    PushEventNameField(state, kEnemySpawnedEventName);
    lua_pushinteger(state, static_cast<lua_Integer>(enemy_type));
    lua_setfield(state, -2, "enemy_type");
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
    PushVec2Field(state, "position", x, y);
}

void PushSpellCastPayload(lua_State* state, int spell_id, float x, float y, float direction_x, float direction_y) {
    lua_createtable(state, 0, 8);
    PushEventNameField(state, kSpellCastEventName);
    lua_pushinteger(state, static_cast<lua_Integer>(spell_id));
    lua_setfield(state, -2, "spell_id");
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
    lua_pushnumber(state, static_cast<lua_Number>(direction_x));
    lua_setfield(state, -2, "dx");
    lua_pushnumber(state, static_cast<lua_Number>(direction_y));
    lua_setfield(state, -2, "dy");
    PushVec2Field(state, "position", x, y);
    PushVec2Field(state, "direction", direction_x, direction_y);
}

void PushGoldChangedPayload(lua_State* state, int gold, int delta, const char* source) {
    lua_createtable(state, 0, 4);
    PushEventNameField(state, kGoldChangedEventName);
    lua_pushinteger(state, static_cast<lua_Integer>(gold));
    lua_setfield(state, -2, "gold");
    lua_pushinteger(state, static_cast<lua_Integer>(delta));
    lua_setfield(state, -2, "delta");
    if (source != nullptr) {
        lua_pushstring(state, source);
    } else {
        lua_pushnil(state);
    }
    lua_setfield(state, -2, "source");
}

void PushDropSpawnedPayload(lua_State* state, const char* kind, float x, float y) {
    lua_createtable(state, 0, 5);
    PushEventNameField(state, kDropSpawnedEventName);
    if (kind != nullptr) {
        lua_pushstring(state, kind);
    } else {
        lua_pushnil(state);
    }
    lua_setfield(state, -2, "kind");
    lua_pushnumber(state, static_cast<lua_Number>(x));
    lua_setfield(state, -2, "x");
    lua_pushnumber(state, static_cast<lua_Number>(y));
    lua_setfield(state, -2, "y");
    PushVec2Field(state, "position", x, y);
}

void PushLevelUpPayload(lua_State* state, int level, int xp) {
    lua_createtable(state, 0, 3);
    PushEventNameField(state, kLevelUpEventName);
    lua_pushinteger(state, static_cast<lua_Integer>(level));
    lua_setfield(state, -2, "level");
    lua_pushinteger(state, static_cast<lua_Integer>(xp));
    lua_setfield(state, -2, "xp");
}

template <typename PayloadBuilder>
void DispatchEventToMod(
    LoadedLuaMod* mod,
    const char* event_name,
    bool is_registered,
    PayloadBuilder&& build_payload) {
    if (mod == nullptr || mod->state == nullptr || !is_registered) {
        return;
    }

    lua_getfield(mod->state, LUA_REGISTRYINDEX, kLuaEventHandlersRegistryKey);
    if (!lua_istable(mod->state, -1)) {
        lua_pop(mod->state, 1);
        return;
    }

    lua_getfield(mod->state, -1, event_name);
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

        build_payload(mod->state);
        if (lua_pcall(mod->state, 1, 0, 0) != LUA_OK) {
            const auto* message = lua_tostring(mod->state, -1);
            LogLuaMessage(*mod, std::string(event_name) + " handler failed: " + (message == nullptr ? "unknown" : message));
            lua_pop(mod->state, 1);
        }
    }

    lua_pop(mod->state, 2);
}

void DispatchRuntimeTickToMod(LoadedLuaMod* mod, const SDModRuntimeTickContext& context) {
    DispatchEventToMod(
        mod,
        kRuntimeTickEventName,
        mod != nullptr && mod->runtime_tick_registered,
        [&context](lua_State* state) {
            PushRuntimeTickPayload(state, context);
        });
}

void DispatchRunStartedToMod(LoadedLuaMod* mod) {
    DispatchEventToMod(
        mod,
        kRunStartedEventName,
        mod != nullptr && mod->run_started_registered,
        [](lua_State* state) {
            PushRunStartedPayload(state);
        });
}

void DispatchRunEndedToMod(LoadedLuaMod* mod, const char* reason) {
    DispatchEventToMod(
        mod,
        kRunEndedEventName,
        mod != nullptr && mod->run_ended_registered,
        [reason](lua_State* state) {
            PushRunEndedPayload(state, reason);
        });
}

void DispatchWaveStartedToMod(LoadedLuaMod* mod, int wave_number) {
    DispatchEventToMod(
        mod,
        kWaveStartedEventName,
        mod != nullptr && mod->wave_started_registered,
        [wave_number](lua_State* state) {
            PushWavePayload(state, kWaveStartedEventName, wave_number);
        });
}

void DispatchWaveCompletedToMod(LoadedLuaMod* mod, int wave_number) {
    DispatchEventToMod(
        mod,
        kWaveCompletedEventName,
        mod != nullptr && mod->wave_completed_registered,
        [wave_number](lua_State* state) {
            PushWavePayload(state, kWaveCompletedEventName, wave_number);
        });
}

void DispatchEnemyDeathToMod(LoadedLuaMod* mod, int enemy_type, float x, float y, const char* kill_method) {
    DispatchEventToMod(
        mod,
        kEnemyDeathEventName,
        mod != nullptr && mod->enemy_death_registered,
        [enemy_type, x, y, kill_method](lua_State* state) {
            PushEnemyDeathPayload(state, enemy_type, x, y, kill_method);
        });
}

void DispatchEnemySpawnedToMod(LoadedLuaMod* mod, int enemy_type, float x, float y) {
    DispatchEventToMod(
        mod,
        kEnemySpawnedEventName,
        mod != nullptr && mod->enemy_spawned_registered,
        [enemy_type, x, y](lua_State* state) {
            PushEnemySpawnedPayload(state, enemy_type, x, y);
        });
}

void DispatchSpellCastToMod(
    LoadedLuaMod* mod,
    int spell_id,
    float x,
    float y,
    float direction_x,
    float direction_y) {
    DispatchEventToMod(
        mod,
        kSpellCastEventName,
        mod != nullptr && mod->spell_cast_registered,
        [spell_id, x, y, direction_x, direction_y](lua_State* state) {
            PushSpellCastPayload(state, spell_id, x, y, direction_x, direction_y);
        });
}

void DispatchGoldChangedToMod(LoadedLuaMod* mod, int gold, int delta, const char* source) {
    DispatchEventToMod(
        mod,
        kGoldChangedEventName,
        mod != nullptr && mod->gold_changed_registered,
        [gold, delta, source](lua_State* state) {
            PushGoldChangedPayload(state, gold, delta, source);
        });
}

void DispatchDropSpawnedToMod(LoadedLuaMod* mod, const char* kind, float x, float y) {
    DispatchEventToMod(
        mod,
        kDropSpawnedEventName,
        mod != nullptr && mod->drop_spawned_registered,
        [kind, x, y](lua_State* state) {
            PushDropSpawnedPayload(state, kind, x, y);
        });
}

void DispatchLevelUpToMod(LoadedLuaMod* mod, int level, int xp) {
    DispatchEventToMod(
        mod,
        kLevelUpEventName,
        mod != nullptr && mod->level_up_registered,
        [level, xp](lua_State* state) {
            PushLevelUpPayload(state, level, xp);
        });
}

}  // namespace

void DispatchRuntimeTickToLuaMods(const SDModRuntimeTickContext& context) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchRuntimeTickToMod(mod.get(), context);
    }
}

bool HasAnyLuaRuntimeTickHandlers() {
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod != nullptr && mod->runtime_tick_registered) {
            return true;
        }
    }

    return false;
}

void DispatchRunStartedToLuaMods() {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchRunStartedToMod(mod.get());
    }
}

void DispatchRunEndedToLuaMods(const char* reason) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchRunEndedToMod(mod.get(), reason);
    }
}

void DispatchWaveStartedToLuaMods(int wave_number) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchWaveStartedToMod(mod.get(), wave_number);
    }
}

void DispatchWaveCompletedToLuaMods(int wave_number) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchWaveCompletedToMod(mod.get(), wave_number);
    }
}

void DispatchEnemyDeathToLuaMods(int enemy_type, float x, float y, const char* kill_method) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchEnemyDeathToMod(mod.get(), enemy_type, x, y, kill_method);
    }
}

void DispatchEnemySpawnedToLuaMods(int enemy_type, float x, float y) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchEnemySpawnedToMod(mod.get(), enemy_type, x, y);
    }
}

void DispatchSpellCastToLuaMods(int spell_id, float x, float y, float direction_x, float direction_y) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchSpellCastToMod(mod.get(), spell_id, x, y, direction_x, direction_y);
    }
}

void DispatchGoldChangedToLuaMods(int gold, int delta, const char* source) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchGoldChangedToMod(mod.get(), gold, delta, source);
    }
}

void DispatchDropSpawnedToLuaMods(const char* kind, float x, float y) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchDropSpawnedToMod(mod.get(), kind, x, y);
    }
}

void DispatchLevelUpToLuaMods(int level, int xp) {
    for (const auto& mod : LoadedLuaModsStorage()) {
        DispatchLevelUpToMod(mod.get(), level, xp);
    }
}

}  // namespace sdmod::detail

namespace sdmod {

void DispatchLuaRunStarted() {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchRunStartedToLuaMods();
}

void DispatchLuaRunEnded(const char* reason) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchRunEndedToLuaMods(reason);
}

void DispatchLuaWaveStarted(int wave_number) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchWaveStartedToLuaMods(wave_number);
}

void DispatchLuaWaveCompleted(int wave_number) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchWaveCompletedToLuaMods(wave_number);
}

void DispatchLuaEnemyDeath(int enemy_type, float x, float y, const char* kill_method) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchEnemyDeathToLuaMods(enemy_type, x, y, kill_method);
}

void DispatchLuaEnemySpawned(int enemy_type, float x, float y) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchEnemySpawnedToLuaMods(enemy_type, x, y);
}

void DispatchLuaSpellCast(int spell_id, float x, float y, float direction_x, float direction_y) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchSpellCastToLuaMods(spell_id, x, y, direction_x, direction_y);
}

void DispatchLuaGoldChanged(int gold, int delta, const char* source) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchGoldChangedToLuaMods(gold, delta, source);
}

void DispatchLuaDropSpawned(const char* kind, float x, float y) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchDropSpawnedToLuaMods(kind, x, y);
}

void DispatchLuaLevelUp(int level, int xp) {
    std::scoped_lock lock(detail::LuaEngineMutex());
    if (!detail::LuaEngineInitializedFlag()) {
        return;
    }

    detail::DispatchLevelUpToLuaMods(level, xp);
}

}  // namespace sdmod
