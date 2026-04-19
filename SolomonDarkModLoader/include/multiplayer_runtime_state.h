#pragma once

#include "steam_bootstrap.h"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace sdmod::multiplayer {

enum class ParticipantKind {
    LocalHuman,
    RemoteParticipant,
};

enum class ParticipantControllerKind {
    Native,
    LuaBrain,
};

struct BotLoadoutInfo {
    std::int32_t primary_skill_id = -1;
    std::int32_t primary_combo_id = -1;
    std::array<std::int32_t, 3> secondary_skill_ids = {-1, -1, -1};
};

enum class CharacterDisciplineId : std::int32_t {
    Mind = 0,
    Body = 1,
    Arcane = 2,
};

enum class ParticipantSceneIntentKind : std::int32_t {
    SharedHub = 0,
    PrivateRegion = 1,
    Run = 2,
};

struct CharacterAppearanceInfo {
    std::array<std::int32_t, 4> choice_ids = {-1, -1, -1, -1};
};

struct MultiplayerCharacterProfile {
    std::int32_t element_id = 0;
    CharacterDisciplineId discipline_id = CharacterDisciplineId::Arcane;
    CharacterAppearanceInfo appearance;
    BotLoadoutInfo loadout;
    std::int32_t level = 0;
    std::int32_t experience = 0;
};

struct ParticipantSceneIntent {
    ParticipantSceneIntentKind kind = ParticipantSceneIntentKind::SharedHub;
    std::int32_t region_index = -1;
    std::int32_t region_type_id = -1;
};

struct ParticipantRuntimeInfo {
    bool valid = false;
    bool in_run = false;
    bool transform_valid = false;
    std::uint32_t run_nonce = 0;
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
    ParticipantSceneIntent scene_intent;
};

struct ParticipantInfo {
    std::uint64_t participant_id = 0;
    ParticipantKind kind = ParticipantKind::LocalHuman;
    ParticipantControllerKind controller_kind = ParticipantControllerKind::Native;
    std::uint64_t steam_id = 0;
    std::string name;
    bool ready = false;
    bool is_owner = false;
    bool transport_connected = false;
    bool transport_using_relay = false;
    std::uint64_t last_packet_ms = 0;
    MultiplayerCharacterProfile character_profile;
    ParticipantRuntimeInfo runtime;
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
constexpr std::uint64_t kFirstLuaControlledParticipantId = 0x1000000000001000ull;

MultiplayerCharacterProfile DefaultCharacterProfile();
bool IsValidCharacterProfile(const MultiplayerCharacterProfile& profile);
bool IsValidParticipantSceneIntent(const ParticipantSceneIntent& scene_intent);
ParticipantSceneIntent DefaultParticipantSceneIntent();

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
ParticipantInfo* UpsertRemoteParticipant(
    RuntimeState& state,
    std::uint64_t participant_id,
    ParticipantControllerKind controller_kind);
bool IsLocalHumanParticipant(const ParticipantInfo& participant);
bool IsRemoteParticipant(const ParticipantInfo& participant);
bool IsLuaControlledParticipant(const ParticipantInfo& participant);
bool IsNativeControlledParticipant(const ParticipantInfo& participant);

const char* SessionStatusLabel(SessionStatus status);
const char* SessionTransportLabel(SessionTransportKind kind);
const char* ParticipantKindLabel(ParticipantKind kind);
const char* ParticipantControllerKindLabel(ParticipantControllerKind kind);
const char* ParticipantSceneIntentKindLabel(ParticipantSceneIntentKind kind);

}  // namespace sdmod::multiplayer

#include "multiplayer_runtime_state.inl"
