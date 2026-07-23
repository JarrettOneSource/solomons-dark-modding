#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace sdmod {

inline constexpr std::uint32_t kLuaTimeScaleUnitsPerOne = 1'000'000;
inline constexpr std::uint32_t kLuaTimeMaximumStepFrames = 120;
inline constexpr std::size_t kLuaTimeMaximumControllingMods = 64;

struct LuaTimeControlSnapshot {
    std::uint32_t scale_units = kLuaTimeScaleUnitsPerOne;
    std::uint32_t revision = 1;
    std::uint64_t step_sequence = 0;
    std::uint64_t consumed_step_sequence = 0;
    std::uint32_t unsent_step_frames = 0;
    std::uint64_t authority_participant_id = 0;
    std::uint32_t run_nonce = 0;
    bool replicated = false;
};

void InitializeLuaTimeRuntime();
void ShutdownLuaTimeRuntime();
void ResetLuaTimeControlForRun();
bool SetLuaTimeScaleRequest(
    std::string_view mod_id,
    std::uint32_t scale_units,
    std::string* error_message);
bool QueueLuaTimeStepFrames(
    std::string_view mod_id,
    std::uint32_t frame_count,
    std::uint64_t* step_sequence,
    std::string* error_message);
bool TryGetLuaTimeScaleRequest(
    std::string_view mod_id,
    std::uint32_t* scale_units);
void ClearLuaTimeScaleRequest(std::string_view mod_id);
LuaTimeControlSnapshot SnapshotLuaTimeControl();
bool ApplyReplicatedLuaTimeControl(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint32_t scale_units,
    std::uint32_t revision,
    std::uint64_t step_sequence,
    std::uint32_t step_frames);
void ResetReplicatedLuaTimeControl(
    std::uint64_t authority_participant_id = 0);
void MarkLuaTimeControlUpdateSent(std::uint32_t revision);

bool BeginLuaTimeSimulationFrame(bool external_pause_active);
void EndLuaTimeSimulationFrame();
bool ShouldHoldLuaTimeSimulationFrame();

}  // namespace sdmod
