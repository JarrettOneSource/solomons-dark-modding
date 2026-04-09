#pragma once

#include "steam_bootstrap.h"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod::multiplayer {

enum class ParticipantKind {
    LocalHuman,
    RemoteHuman,
    LuaBot,
};

struct BotLoadoutInfo {
    std::int32_t primary_skill_id = -1;
    std::int32_t primary_combo_id = -1;
    std::array<std::int32_t, 3> secondary_skill_ids = {-1, -1, -1};
};

struct ParticipantRuntimeInfo {
    bool valid = false;
    bool in_run = false;
    bool transform_valid = false;
    std::uint32_t run_nonce = 0;
    std::int32_t wizard_id = -1;
    std::int32_t level = 0;
    std::int32_t wave = 0;
    std::int32_t life_current = 0;
    std::int32_t life_max = 0;
    std::int32_t mana_current = 0;
    std::int32_t mana_max = 0;
    std::int32_t experience_current = 0;
    std::int32_t experience_next = 0;
    std::int32_t primary_skill_id = -1;
    std::int32_t primary_combo_id = -1;
    std::array<std::int32_t, 3> queued_secondary_ids = {-1, -1, -1};
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
};

struct ParticipantInfo {
    std::uint64_t participant_id = 0;
    ParticipantKind kind = ParticipantKind::LocalHuman;
    std::uint64_t steam_id = 0;
    std::string name;
    std::int32_t wizard_id = -1;
    bool ready = false;
    bool is_owner = false;
    bool transport_connected = false;
    bool transport_using_relay = false;
    std::uint64_t last_packet_ms = 0;
    ParticipantRuntimeInfo runtime;
    BotLoadoutInfo loadout;
};

enum class SessionStatus {
    Idle,
    Ready,
    Error,
};

enum class SessionTransportKind {
    None,
    Steam,
};

struct RuntimeState {
    bool shutting_down = false;
    bool foundation_ready = false;
    bool service_loop_running = false;
    bool steam_requested = false;
    bool steam_available = false;
    bool steam_transport_ready = false;
    bool transport_ready = false;
    std::uint64_t local_steam_id = 0;
    std::uint64_t service_tick_count = 0;
    std::uint64_t last_service_tick_ms = 0;
    std::uint64_t steam_callback_pump_count = 0;
    std::uint64_t last_steam_callback_pump_ms = 0;
    std::uint32_t next_outbound_sequence = 1;
    SessionStatus session_status = SessionStatus::Idle;
    SessionTransportKind session_transport = SessionTransportKind::None;
    std::string status_text;
    std::string error_text;
    std::vector<ParticipantInfo> participants;
};

constexpr std::uint64_t kLocalParticipantId = 1ull;
constexpr std::uint64_t kFirstLuaBotParticipantId = 0x1000000000001000ull;

void InitializeRuntimeState();
void ShutdownRuntimeState();
void MarkRuntimeShuttingDown();

template <typename Fn>
void UpdateRuntimeState(Fn&& updater);

RuntimeState SnapshotRuntimeState();
void ApplySteamSnapshotToRuntime(std::uint64_t now_ms, const SteamBootstrapSnapshot& steam_snapshot);

ParticipantInfo* FindParticipant(RuntimeState& state, std::uint64_t participant_id);
const ParticipantInfo* FindParticipant(const RuntimeState& state, std::uint64_t participant_id);
ParticipantInfo* FindLocalParticipant(RuntimeState& state);
const ParticipantInfo* FindLocalParticipant(const RuntimeState& state);
ParticipantInfo* UpsertLocalParticipant(RuntimeState& state);
ParticipantInfo* UpsertRemoteHumanParticipant(RuntimeState& state, std::uint64_t participant_id);
ParticipantInfo* UpsertLuaBotParticipant(RuntimeState& state, std::uint64_t participant_id);
bool IsLocalHumanParticipant(const ParticipantInfo& participant);
bool IsRemoteHumanParticipant(const ParticipantInfo& participant);
bool IsLuaBotParticipant(const ParticipantInfo& participant);

const char* SessionStatusLabel(SessionStatus status);
const char* SessionTransportLabel(SessionTransportKind kind);
const char* ParticipantKindLabel(ParticipantKind kind);

}  // namespace sdmod::multiplayer

#include "multiplayer_runtime_state.inl"
