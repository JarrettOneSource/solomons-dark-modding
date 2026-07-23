#pragma once

#include "lua_mod_runtime.h"
#include "sdmod_plugin_api.h"
#include "wave_intelligence.h"

#include <cstdint>
#include <string>

namespace sdmod {

void DispatchLuaRunStarted();
void DispatchLuaRunEnded(const char* reason);
void DispatchLuaWaveStarted(const WaveSummary& summary);
void DispatchLuaWaveCompleted(int wave_number);
void DispatchLuaEnemyDeath(int enemy_type, float x, float y, const char* kill_method);
void DispatchLuaEnemySpawned(int enemy_type, float x, float y);
void DispatchLuaSpellCast(int spell_id, float x, float y, float direction_x, float direction_y);
void DispatchLuaGoldChanged(int gold, int delta, const char* source);
void DispatchLuaDropSpawned(const char* kind, float x, float y);
void DispatchLuaLevelUp(int level, int xp);
void DispatchLuaCustomEvent(
    const std::string& mod_id,
    const std::string& event_name,
    const LuaModValue& payload,
    std::uint64_t authority_participant_id,
    std::uint64_t stream_sequence);

}  // namespace sdmod

namespace sdmod::detail {

void DispatchRuntimeTickToLuaMods(const SDModRuntimeTickContext& context);
bool HasAnyLuaRuntimeTickHandlers();
void DispatchRunStartedToLuaMods();
void DispatchRunEndedToLuaMods(const char* reason);
void DispatchWaveStartedToLuaMods(const WaveSummary& summary);
void DispatchWaveCompletedToLuaMods(int wave_number);
void DispatchEnemyDeathToLuaMods(int enemy_type, float x, float y, const char* kill_method);
void DispatchEnemySpawnedToLuaMods(int enemy_type, float x, float y);
void DispatchSpellCastToLuaMods(int spell_id, float x, float y, float direction_x, float direction_y);
void DispatchGoldChangedToLuaMods(int gold, int delta, const char* source);
void DispatchDropSpawnedToLuaMods(const char* kind, float x, float y);
void DispatchLevelUpToLuaMods(int level, int xp);
void DispatchCustomEventToLuaMods(
    const std::string& mod_id,
    const std::string& event_name,
    const LuaModValue& payload,
    std::uint64_t authority_participant_id,
    std::uint64_t stream_sequence);

}  // namespace sdmod::detail
