struct AirChainTargetRuntimeInfo {
    std::uint16_t ordinal = 0;
    std::uint64_t network_actor_id = 0;
    uintptr_t local_actor_address = 0;
    uintptr_t fallback_actor_address = 0;
    bool matched = false;
    bool authoritative_null = false;
    bool source_override_attempted = false;
    bool source_override_applied = false;
    bool target_override_attempted = false;
    bool target_override_applied = false;
    float source_x = 0.0f;
    float source_y = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float local_source_x = 0.0f;
    float local_source_y = 0.0f;
    float local_target_x = 0.0f;
    float local_target_y = 0.0f;
    float source_error = 0.0f;
    float source_error_before_override = 0.0f;
    float target_error = 0.0f;
    float target_error_before_override = 0.0f;
};

struct AirChainSnapshotRuntimeInfo {
    bool valid = false;
    bool active = false;
    bool terminal = false;
    bool truncated = false;
    std::uint64_t owner_participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t run_nonce = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t frame_sequence = 0;
    std::uint32_t target_total_count = 0;
    std::vector<AirChainTargetRuntimeInfo> targets;
};

struct AirChainApplyRuntimeInfo {
    bool valid = false;
    std::uint64_t applied_ms = 0;
    std::uint64_t owner_participant_id = 0;
    std::uint32_t cast_sequence = 0;
    std::uint32_t frame_sequence = 0;
    std::uint64_t cumulative_override_attempt_count = 0;
    std::uint64_t cumulative_override_success_count = 0;
    std::uint64_t cumulative_authoritative_null_count = 0;
    std::uint64_t cumulative_missing_snapshot_fallback_count = 0;
    std::uint64_t cumulative_stale_snapshot_fallback_count = 0;
    std::uint64_t cumulative_unmapped_target_count = 0;
    std::uint64_t cumulative_source_override_success_count = 0;
    std::uint64_t cumulative_source_override_failure_count = 0;
    std::uint64_t cumulative_target_override_success_count = 0;
    std::uint64_t cumulative_target_override_failure_count = 0;
    std::uint32_t max_applied_target_count = 0;
    std::vector<AirChainTargetRuntimeInfo> bindings;
};

struct LootPickupResultRuntimeInfo {
    bool valid = false;
    std::uint64_t authority_participant_id = 0;
    std::uint64_t participant_id = 0;
    std::uint64_t received_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t request_sequence = 0;
    std::uint32_t run_nonce = 0;
    std::uint64_t network_drop_id = 0;
    LootPickupResultCode result_code = LootPickupResultCode::Rejected;
    LootDropKind drop_kind = LootDropKind::Unknown;
    std::int32_t amount = 0;
    std::int32_t resulting_gold = 0;
    std::uint32_t gold_revision = 0;
    std::int32_t resource_kind = -1;
    float resource_delta = 0.0f;
    float resulting_life_current = 0.0f;
    float resulting_life_max = 0.0f;
    float resulting_mana_current = 0.0f;
    float resulting_mana_max = 0.0f;
    std::uint32_t item_type_id = 0;
    std::uint32_t item_recipe_uid = 0;
    std::uint64_t item_content_id = 0;
    bool item_color_state_valid = false;
    std::array<std::uint8_t, kParticipantVisualLinkColorBlockBytes> item_color_state = {};
    std::int32_t item_slot = -1;
    std::int32_t stack_count = 0;
    std::uint32_t inventory_revision = 0;
    PowerupRewardKind powerup_kind = PowerupRewardKind::BonusSkillPoint;
    std::int32_t powerup_skill_entry_index = -1;
    std::int32_t powerup_skill_apply_count = 0;
    std::uint16_t powerup_skill_resulting_active = 0;
    std::int32_t damage_x4_remaining_ticks = 0;
    std::uint32_t spellbook_revision = 0;
    std::uint32_t statbook_revision = 0;
};

struct WorldSnapshotApplyRuntimeInfo {
    bool valid = false;
    bool holding_stale_snapshot = false;
    std::uint64_t applied_ms = 0;
    std::uint64_t source_snapshot_age_ms = 0;
    std::uint32_t sequence = 0;
    std::uint32_t scene_epoch = 0;
    std::uint32_t presentation_sequence = 0;
    std::uint32_t presentation_scene_epoch = 0;
    std::uint64_t presentation_received_ms = 0;
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
    std::uint32_t removed_actor_total_count = 0;
    std::uint32_t failed_remove_actor_count = 0;
    std::uint32_t failed_remove_actor_total_count = 0;
    std::vector<WorldSnapshotActorBindingRuntimeInfo> actor_bindings;
};

enum class SessionStatus {
    Idle,
    WaitingForInvite,
    CreatingLobby,
    JoiningLobby,
    Handshaking,
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
    bool session_is_host = false;
    bool steam_route_relayed = false;
    std::uint32_t steam_app_id = 0;
    std::uint64_t steam_lobby_id = 0;
    std::uint64_t steam_host_id = 0;
    std::uint32_t session_max_participants = 0;
    std::uint32_t authenticated_peer_count = 0;
    std::int32_t steam_route_ping_ms = 0;
    std::uint64_t local_steam_id = 0;
    std::uint64_t service_tick_count = 0;
    std::uint64_t last_service_tick_ms = 0;
    std::uint64_t steam_callback_pump_count = 0;
    std::uint64_t last_steam_callback_pump_ms = 0;
    std::uint64_t transport_packets_sent = 0;
    std::uint64_t transport_packets_received = 0;
    std::uint64_t steam_send_failures = 0;
    std::uint64_t steam_reliable_send_failures = 0;
    std::int32_t last_steam_send_failure_result = 0;
    std::string multiplayer_manifest_sha256;
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
    std::vector<SpellEffectSnapshotRuntimeInfo> spell_effect_snapshots;
    SpellEffectApplyRuntimeInfo spell_effect_apply;
    AirChainSnapshotRuntimeInfo local_air_chain_capture;
    std::vector<AirChainSnapshotRuntimeInfo> local_air_chain_history;
    std::vector<AirChainSnapshotRuntimeInfo> air_chain_snapshots;
    std::vector<AirChainSnapshotRuntimeInfo> air_chain_snapshot_history;
    AirChainApplyRuntimeInfo air_chain_apply;
    LootPickupResultRuntimeInfo last_loot_pickup_result;
    LevelUpOfferRuntimeInfo active_level_up_offer;
    LevelUpChoiceResultRuntimeInfo last_level_up_choice_result;
    LevelUpWaitStatusRuntimeInfo level_up_wait_status;
    SharedGameplayPauseRuntimeInfo shared_gameplay_pause;
    DeathSpectatorRuntimeInfo death_spectator;
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
bool TryGetLocalParticipantRuntimeInfo(ParticipantRuntimeInfo* runtime);
bool TryGetRemoteParticipantDisplayState(
    std::uint64_t participant_id,
    std::string* display_name,
    ParticipantRuntimeInfo* runtime,
    bool* transport_connected);
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
bool AppendLootSnapshot(RuntimeState* state, LootSnapshotRuntimeInfo snapshot);
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
const char* DeathSpectatorPhaseLabel(DeathSpectatorPhase phase);
const char* ParticipantKindLabel(ParticipantKind kind);
const char* ParticipantControllerKindLabel(ParticipantControllerKind kind);
const char* ParticipantSceneIntentKindLabel(ParticipantSceneIntentKind kind);
const char* LootDropKindLabel(LootDropKind kind);
const char* PowerupRewardKindLabel(PowerupRewardKind kind);
const char* LootPickupResultCodeLabel(LootPickupResultCode code);
// Reproduce the stock pickup/attraction radii from the participant's native
// progression+0xCC value. Gold and item carriers use 30 world units per
// pickup-range unit, orbs enter their stock pull behavior at 60, and powerups
// collect at 20. Keeping this shared prevents client presentation and host
// authority from silently granting every participant one fixed pickup radius.
float StockLootBehaviorDistance(LootDropKind kind, float pickup_range);

}  // namespace sdmod::multiplayer

#include "multiplayer_runtime_state.inl"
