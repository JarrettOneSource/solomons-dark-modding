#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace sdmod {

constexpr std::size_t kWaveCompositionMaxRows = 20;

enum class WavePhase : std::uint8_t {
    Idle = 0,
    Spawning = 1,
    Clearing = 2,
    Completed = 3,
};

struct WaveCompositionRow {
    std::int32_t enemy_type = 0;
    std::int32_t planned = 0;
    std::int32_t spawned = 0;
    std::int32_t alive = 0;
    std::int32_t killed = 0;
};

struct WaveSummary {
    bool valid = false;
    std::int32_t wave = 0;
    WavePhase phase = WavePhase::Idle;
    std::int32_t remaining_to_spawn = 0;
    std::int32_t spawned = 0;
    std::int32_t alive = 0;
    std::int32_t killed = 0;
    std::vector<WaveCompositionRow> composition;
};

struct WaveScheduleEntry {
    std::int32_t wave = 0;
    std::int32_t spawn_budget = 0;
    std::int32_t spawn_delay_min = 0;
    std::int32_t spawn_delay_max = 0;
    std::int32_t wave_delay_min = 0;
    std::int32_t wave_delay_max = 0;
    std::int32_t max_enemies = 0;
    bool zombie_wave = false;
    bool random_group_projection = true;
    std::vector<WaveCompositionRow> composition;
};

struct WaveSummaryUpdate {
    WaveSummary summary;
    std::int32_t started_wave = 0;
    std::int32_t completed_wave = 0;
};

bool InitializeWaveIntelligence(
    const std::filesystem::path& stage_root,
    std::string* error_message);
void ShutdownWaveIntelligence();
bool IsWaveIntelligenceInitialized();
void ResetWaveIntelligenceRun();

WaveSummary SnapshotWaveSummary();
std::vector<WaveScheduleEntry> GetUpcomingWaveSchedule(std::size_t count);

WaveSummaryUpdate ObserveAuthorityWaveSpawner(
    std::uintptr_t spawner_address,
    std::uintptr_t action_record_address,
    std::int32_t remaining_to_spawn,
    std::int32_t native_wave_hint);
void ObserveAuthorityWaveEnemySpawn(
    std::uintptr_t enemy_address,
    std::int32_t enemy_type,
    std::int32_t wave);
WaveSummaryUpdate ObserveAuthorityWaveEnemyDeath(
    std::uintptr_t enemy_address);

WaveSummaryUpdate ApplyReplicatedWaveSummary(const WaveSummary& summary);
const char* WavePhaseLabel(WavePhase phase);

}  // namespace sdmod
