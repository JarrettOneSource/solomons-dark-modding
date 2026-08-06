#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod {

struct NativeAudioAttributionContext {
    uintptr_t actor_address = 0;
    std::uint64_t participant_id = 0;
    std::int32_t skill_id = 0;
    std::uint32_t cast_sequence = 0;
    bool remote = false;
};

struct NativeAudioChannelSnapshot {
    std::uint64_t event_sequence = 0;
    uintptr_t object_address = 0;
    uintptr_t channel_handle = 0;
    uintptr_t start_return_address = 0;
    uintptr_t last_return_address = 0;
    uintptr_t actor_address = 0;
    std::uint64_t participant_id = 0;
    std::uint64_t started_ms = 0;
    std::uint64_t stopped_ms = 0;
    std::uint64_t age_ms = 0;
    std::uint32_t start_count = 0;
    std::uint32_t stop_count = 0;
    std::uint32_t cast_sequence = 0;
    std::int32_t native_reference_count = 0;
    std::int32_t registry_index = -1;
    std::int32_t skill_id = 0;
    bool active = false;
    bool loop_flag = true;
    bool remote = false;
    std::string asset;
    std::string owner;
};

struct NativeAudioDispatchSnapshot {
    std::uint64_t event_sequence = 0;
    std::uint64_t native_tick = 0;
    std::uint64_t monotonic_ms = 0;
    uintptr_t object_address = 0;
    uintptr_t caller_return_address = 0;
    std::int32_t registry_index = -1;
    std::int32_t native_reference_count = 0;
    float gain = 1.0f;
    float pitch = 1.0f;
    float transition_ticks = 0.0f;
    bool engine_enabled = false;
    bool caller_in_game_image = false;
    std::string native_class;
    std::string operation;
    std::string requested_name;
    std::string requested_track;
};

class ScopedNativeAudioAttribution final {
public:
    explicit ScopedNativeAudioAttribution(uintptr_t actor_address);
    ~ScopedNativeAudioAttribution();

    ScopedNativeAudioAttribution(const ScopedNativeAudioAttribution&) = delete;
    ScopedNativeAudioAttribution& operator=(
        const ScopedNativeAudioAttribution&) = delete;

    void SetParticipantCast(
        std::uint64_t participant_id,
        bool remote,
        std::int32_t skill_id,
        std::uint32_t cast_sequence);

private:
    NativeAudioAttributionContext previous_;
};

bool InitializeNativeAudioObservability(std::string* error_message);
void ShutdownNativeAudioObservability();

bool DispatchNativeWizardFootstep(uintptr_t actor_address);
bool TryDispatchNativeWizardOuchSound(
    uintptr_t actor_address,
    float health_after,
    std::uint64_t participant_id,
    std::uint32_t event_sequence,
    std::int32_t* sound_index,
    float* gain);

std::vector<NativeAudioChannelSnapshot> SnapshotNativeAudioChannels(
    bool include_inactive);
std::size_t ClearInactiveNativeAudioChannelHistory();
std::size_t DumpNativeAudioChannelsToLog(bool include_inactive);

bool IsNativeAudioDispatchCaptureEnabled();
std::vector<NativeAudioDispatchSnapshot> SnapshotNativeAudioDispatchEvents();
std::size_t ClearNativeAudioDispatchEvents();
bool DispatchNativeAudioCensusProbe(
    std::int32_t registry_index,
    const std::string& operation,
    float gain,
    float pitch,
    std::string* error_message);

}  // namespace sdmod
