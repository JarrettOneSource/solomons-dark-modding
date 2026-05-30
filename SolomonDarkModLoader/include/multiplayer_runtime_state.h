#pragma once

#include "multiplayer_runtime_protocol.h"
#include "steam_bootstrap.h"

#include <array>
#include <cstddef>
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
    // Stock Skills_Wizard primary selection is expressed as entry indices,
    // not as a direct spell id. A primary attack is a pair of entry indices
    // that later resolve to the concrete spell id at runtime.
    std::int32_t primary_entry_index = -1;
    std::int32_t primary_combo_entry_index = -1;
    std::array<std::int32_t, 3> secondary_entry_indices = {-1, -1, -1};
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
    std::int32_t primary_entry_index = -1;
    std::int32_t primary_combo_entry_index = -1;
    std::array<std::int32_t, 3> queued_secondary_entry_indices = {-1, -1, -1};
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
    ParticipantSceneIntent scene_intent;
};

struct ParticipantOwnedProgressionState {
    bool initialized = false;
    std::int32_t gold = 0;
    std::uint32_t inventory_revision = 0;
    std::uint32_t spellbook_revision = 0;
    std::uint32_t statbook_revision = 0;
    std::uint32_t loadout_revision = 0;
};

struct ParticipantTransformSample {
    bool valid = false;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t run_nonce = 0;
    ParticipantSceneIntent scene_intent;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float heading = 0.0f;
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
    ParticipantOwnedProgressionState owned_progression;
    std::vector<ParticipantTransformSample> transform_history;
};

struct WorldActorSnapshot {
    std::uint64_t network_actor_id = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t enemy_type = -1;
    std::int32_t actor_slot = -1;
    std::int32_t world_slot = -1;
    bool dead = false;
    bool tracked_enemy = false;
    bool lifecycle_owned = false;
    std::uint8_t anim_drive_state = 0;
    std::uint16_t presentation_flags = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
    float heading = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    std::uint32_t anim_drive_state_word = 0;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    std::array<std::uint8_t, kWorldActorStudentVisualStateBytes> student_visual_state = {};
};

struct WorldSnapshotActorBindingRuntimeInfo {
    std::uint64_t network_actor_id = 0;
    uintptr_t local_actor_address = 0;
    std::uint32_t native_type_id = 0;
    std::int32_t enemy_type = -1;
    bool matched = false;
    bool parked = false;
    bool removed = false;
};

struct WorldSnapshotRuntimeInfo {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t actor_total_count = 0;
    bool truncated = false;
    ParticipantSceneIntent scene_intent;
    std::vector<WorldActorSnapshot> actors;
};

struct LootDropSnapshot {
    std::uint64_t network_drop_id = 0;
    std::uint32_t native_type_id = 0;
    LootDropKind drop_kind = LootDropKind::Unknown;
    bool active = false;
    std::int32_t amount = 0;
    std::int32_t amount_tier = 0;
    std::int32_t actor_slot = -1;
    std::int32_t world_slot = -1;
    std::uint32_t lifetime = 0;
    float position_x = 0.0f;
    float position_y = 0.0f;
    float radius = 0.0f;
};

struct LootSnapshotRuntimeInfo {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t drop_total_count = 0;
    bool truncated = false;
    ParticipantSceneIntent scene_intent;
    std::vector<LootDropSnapshot> drops;
};

struct WorldSnapshotApplyRuntimeInfo {
    bool valid = false;
    std::uint64_t applied_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t local_actor_count = 0;
    std::uint32_t matched_actor_count = 0;
    std::uint32_t created_actor_count = 0;
    std::uint32_t created_actor_total_count = 0;
    std::uint32_t transform_write_count = 0;
    std::uint32_t presentation_write_count = 0;
    std::uint32_t health_write_count = 0;
    std::uint32_t dead_actor_count = 0;
    std::uint32_t parked_actor_count = 0;
    std::uint32_t removed_actor_count = 0;
    std::uint32_t failed_remove_actor_count = 0;
    std::vector<WorldSnapshotActorBindingRuntimeInfo> actor_bindings;
};

enum class SessionStatus {
    Idle,
    Ready,
    Error,
};

enum class SessionTransportKind {
    None,
    Steam,
    LocalUdp,
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
    WorldSnapshotRuntimeInfo world_snapshot;
    std::vector<WorldSnapshotRuntimeInfo> world_snapshot_history;
    WorldSnapshotApplyRuntimeInfo world_snapshot_apply;
    LootSnapshotRuntimeInfo loot_snapshot;
};

constexpr std::uint64_t kLocalParticipantId = 1ull;
constexpr std::uint64_t kFirstLuaControlledParticipantId = 0x1000000000001000ull;
constexpr std::size_t kParticipantTransformHistoryCapacity = 8;
constexpr std::size_t kWorldSnapshotHistoryCapacity = 8;

MultiplayerCharacterProfile DefaultCharacterProfile();
bool IsValidCharacterProfile(const MultiplayerCharacterProfile& profile);
bool IsValidParticipantSceneIntent(const ParticipantSceneIntent& scene_intent);
ParticipantSceneIntent DefaultParticipantSceneIntent();
bool SameParticipantSceneIntent(const ParticipantSceneIntent& left, const ParticipantSceneIntent& right);
float InterpolateHeadingDegrees(float from_degrees, float to_degrees, float alpha);

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
void AppendParticipantTransformSample(ParticipantInfo* participant, const ParticipantTransformSample& sample);
bool TrySampleParticipantTransform(
    const ParticipantInfo& participant,
    std::uint64_t now_ms,
    std::uint64_t interpolation_delay_ms,
    ParticipantTransformSample* sample);
void AppendWorldSnapshot(RuntimeState* state, WorldSnapshotRuntimeInfo snapshot);
bool TrySampleWorldSnapshot(
    const RuntimeState& state,
    std::uint64_t now_ms,
    std::uint64_t interpolation_delay_ms,
    WorldSnapshotRuntimeInfo* snapshot);
bool IsLocalHumanParticipant(const ParticipantInfo& participant);
bool IsRemoteParticipant(const ParticipantInfo& participant);
bool IsLuaControlledParticipant(const ParticipantInfo& participant);
bool IsNativeControlledParticipant(const ParticipantInfo& participant);

const char* SessionStatusLabel(SessionStatus status);
const char* SessionTransportLabel(SessionTransportKind kind);
const char* ParticipantKindLabel(ParticipantKind kind);
const char* ParticipantControllerKindLabel(ParticipantControllerKind kind);
const char* ParticipantSceneIntentKindLabel(ParticipantSceneIntentKind kind);
const char* LootDropKindLabel(LootDropKind kind);

}  // namespace sdmod::multiplayer

#include "multiplayer_runtime_state.inl"
