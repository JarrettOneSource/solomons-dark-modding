#pragma once

#include <cstdint>

namespace sdmod::multiplayer {

constexpr std::uint16_t kProtocolVersion = 50;
constexpr char kProtocolMagic[4] = {'S', 'D', 'M', 'P'};
constexpr std::uint32_t kParticipantDisplayNameBytes = 32;
constexpr std::uint32_t kParticipantVisualLinkColorBlockBytes = 32;
constexpr std::uint32_t kParticipantInventorySnapshotMaxItems = 64;
constexpr std::uint32_t kParticipantProgressionBookSnapshotMaxEntries = 128;
constexpr std::uint32_t kWorldSnapshotMaxActors = 64;
constexpr std::uint32_t kWorldActorStudentVisualStateBytes = 32;
constexpr std::uint32_t kLootSnapshotMaxDrops = 64;
constexpr std::uint32_t kLevelUpOfferMaxOptions = 8;
constexpr std::uint32_t kLevelUpWaitStatusMaxParticipants = 8;
constexpr std::uint32_t kSpellEffectSnapshotMaxEffects = 32;
constexpr std::uint32_t kAirChainSnapshotMaxTargets = 8;
constexpr std::uint32_t kSecondaryLoadoutSlotCount = 8;

enum class PacketKind : std::uint16_t {
    State = 1,
    SessionHello = 2,
    Cast = 3,
    SessionHelloAck = 4,
    WorldSnapshot = 5,
    LootSnapshot = 6,
    EnemyDamageClaim = 7,
    EnemyDamageResult = 8,
    LootPickupRequest = 9,
    LootPickupResult = 10,
    LevelUpOffer = 11,
    LevelUpChoice = 12,
    LevelUpChoiceResult = 13,
    SpellEffectSnapshot = 14,
    AirChainSnapshot = 15,
    ParticipantVitalsCorrection = 16,
    SessionGoodbye = 17,
};

enum class SessionPeerRole : std::uint8_t {
    Host = 1,
    Client = 2,
};

enum class SessionHelloResultCode : std::uint8_t {
    Accepted = 1,
    ProtocolMismatch = 2,
    ManifestMismatch = 3,
    LobbyMismatch = 4,
    IdentityMismatch = 5,
    LobbyFull = 6,
    HostMismatch = 7,
    CapabilityMismatch = 8,
};

enum class SessionGoodbyeReason : std::uint8_t {
    Leaving = 1,
    LobbyClosed = 2,
    Rejected = 3,
    TransportFailure = 4,
};

enum SessionCapabilityFlags : std::uint32_t {
    SessionCapabilityHostAuthority = 1u << 0,
    SessionCapabilityFragmentedSnapshots = 1u << 1,
    SessionCapabilityProgressionOwnership = 1u << 2,
    SessionCapabilitySpellEffectOwnership = 1u << 3,
};

constexpr std::uint32_t kRequiredSessionCapabilities =
    SessionCapabilityHostAuthority |
    SessionCapabilityFragmentedSnapshots |
    SessionCapabilityProgressionOwnership |
    SessionCapabilitySpellEffectOwnership;

enum class CastKind : std::uint8_t {
    Primary = 1,
    Secondary = 2,
};

enum class CastInputPhase : std::uint8_t {
    Pressed = 1,
    Held = 2,
    Released = 3,
};

enum class EnemyDamageResultCode : std::uint8_t {
    Accepted = 1,
    Rejected = 2,
};

enum class WorldSceneKind : std::uint8_t {
    Unknown = 0,
    SharedHub = 1,
    PrivateRegion = 2,
    Run = 3,
};

enum class LootDropKind : std::uint8_t {
    Unknown = 0,
    Gold = 1,
    Item = 2,
    Potion = 3,
    Orb = 4,
    Powerup = 5,
};

enum class LootPickupResultCode : std::uint8_t {
    Accepted = 1,
    Rejected = 2,
    AlreadyGone = 3,
    OutOfRange = 4,
    WrongRun = 5,
    Unsupported = 6,
};

enum class LevelUpChoiceResultCode : std::uint8_t {
    Accepted = 1,
    Rejected = 2,
    StaleOffer = 3,
    InvalidOption = 4,
    ApplyFailed = 5,
};

enum LevelUpOfferFlags : std::uint8_t {
    LevelUpOfferFlagSuppressNativePicker = 1 << 0,
};

enum WorldActorSnapshotFlags : std::uint8_t {
    WorldActorSnapshotFlagDead = 1 << 0,
    WorldActorSnapshotFlagTrackedEnemy = 1 << 1,
    WorldActorSnapshotFlagLifecycleOwned = 1 << 2,
    WorldActorSnapshotFlagRunStatic = 1 << 3,
    WorldActorSnapshotFlagTargetAuthoritative = 1 << 4,
    WorldActorSnapshotFlagPlayerCreated = 1 << 5,
};

constexpr std::uint32_t kRaiseGolemNativeTypeId = 0x07F4;

inline bool IsReplicatedRunPlayerCreatedActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case kRaiseGolemNativeTypeId:
        return true;
    default:
        return false;
    }
}

enum WorldActorPresentationFlags : std::uint16_t {
    WorldActorPresentationFlagAnimationDriveWord = 1 << 0,
    WorldActorPresentationFlagStudentVisualState = 1 << 1,
    WorldActorPresentationFlagStudentVariantBytes = 1 << 2,
    WorldActorPresentationFlagLocomotionFloats = 1 << 3,
};

enum WorldSnapshotFlags : std::uint8_t {
    WorldSnapshotFlagTruncated = 1 << 0,
};

enum LootDropSnapshotFlags : std::uint8_t {
    LootDropSnapshotFlagActive = 1 << 0,
};

enum LootSnapshotFlags : std::uint8_t {
    LootSnapshotFlagTruncated = 1 << 0,
};

enum SpellEffectSnapshotFlags : std::uint16_t {
    SpellEffectSnapshotFlagTruncated = 1 << 0,
};

enum SpellEffectStateFlags : std::uint16_t {
    SpellEffectStateFlagActive = 1 << 0,
    SpellEffectStateFlagTerminal = 1 << 1,
    SpellEffectStateFlagTransform = 1 << 2,
    SpellEffectStateFlagMotion = 1 << 3,
    SpellEffectStateFlagEmberRuntime = 1 << 4,
    SpellEffectStateFlagFirewalkerRuntime = 1 << 5,
};

enum AirChainSnapshotFlags : std::uint8_t {
    AirChainSnapshotFlagActive = 1 << 0,
    AirChainSnapshotFlagTerminal = 1 << 1,
    AirChainSnapshotFlagTruncated = 1 << 2,
};

enum ParticipantPresentationFlags : std::uint16_t {
    ParticipantPresentationFlagAnimationDriveWord = 1 << 0,
    ParticipantPresentationFlagRenderDriveFloats = 1 << 1,
    ParticipantPresentationFlagStaffVisualState = 1 << 2,
    ParticipantPresentationFlagRenderSelectorBytes = 1 << 3,
    ParticipantPresentationFlagVisualLinkColorBlocks = 1 << 4,
};

enum ParticipantPersistentStatusFlags : std::uint8_t {
    ParticipantPersistentStatusFlagFirewalker = 1 << 0,
    ParticipantPersistentStatusFlagMindstar = 1 << 1,
    ParticipantPersistentStatusFlagRegenerate = 1 << 2,
    ParticipantPersistentStatusFlagSnapshotValid = 1 << 7,
};

constexpr std::uint8_t kParticipantPersistentStatusValueMask =
    ParticipantPersistentStatusFlagFirewalker |
    ParticipantPersistentStatusFlagMindstar |
    ParticipantPersistentStatusFlagRegenerate;

enum ParticipantTransientStatusFlags : std::uint8_t {
    ParticipantTransientStatusFlagPoisoned = 1 << 0,
    ParticipantTransientStatusFlagSnapshotValid = 1 << 7,
};

constexpr std::uint8_t kParticipantTransientStatusValueMask =
    ParticipantTransientStatusFlagPoisoned;
constexpr std::int32_t kParticipantPoisonMaxDurationTicks = 100000;

enum ParticipantInventorySnapshotFlags : std::uint16_t {
    ParticipantInventorySnapshotFlagTruncated = 1 << 0,
};

enum ParticipantProgressionBookSnapshotFlags : std::uint16_t {
    ParticipantProgressionBookSnapshotFlagTruncated = 1 << 0,
};

#pragma pack(push, 1)
struct PacketHeader {
    char magic[4];
    std::uint16_t version;
    std::uint16_t kind;
    std::uint32_t sequence;
};

struct ParticipantInventoryItemPacketState {
    std::uint32_t type_id;
    std::int32_t slot;
    std::int32_t stack_count;
};

struct ParticipantProgressionBookEntryPacketState {
    std::int32_t entry_index;
    std::int32_t internal_id;
    std::uint16_t active;
    std::uint16_t visible;
    std::uint16_t category;
    std::uint16_t reserved = 0;
    std::int32_t statbook_max_level;
};

struct LevelUpOfferOptionPacketState {
    std::int32_t option_id;
    std::int32_t apply_count;
};

struct ParticipantDerivedStatPacketState {
    std::uint8_t valid;
    std::uint8_t reserved[3] = {};
    float cast_speed_multiplier;
    float mana_recovery_multiplier;
    float resist_magic_fraction;
    float resist_poison_fraction;
    float deflect_chance;
    float staff_melee_damage_a;
    float staff_melee_damage_b;
    float pickup_range;
    float secondary_recharge_multiplier;
    float offensive_damage_multiplier;
    float offensive_mana_multiplier;
    float meditation_recovery_bonus;
    std::int32_t meditation_idle_ticks;
};

struct StatePacket {
    PacketHeader header;
    std::uint64_t participant_id;
    std::uint64_t authority_participant_id;
    char display_name[kParticipantDisplayNameBytes];
    std::uint8_t ready;
    std::uint8_t in_run;
    std::uint8_t transform_valid;
    std::uint8_t controller_kind;
    std::uint32_t run_nonce;
    std::uint32_t participant_vitals_correction_ack_sequence;
    std::int32_t element_id;
    std::int32_t discipline_id;
    std::int32_t appearance_choice_ids[4];
    std::int32_t level;
    std::int32_t wave;
    float life_current;
    float life_max;
    float mana_current;
    float mana_max;
    float move_speed;
    std::int32_t experience_current;
    std::int32_t experience_next;
    std::int32_t owned_gold;
    std::uint32_t gold_revision;
    std::uint32_t inventory_revision;
    std::uint32_t spellbook_revision;
    std::uint32_t statbook_revision;
    std::uint32_t loadout_revision;
    std::uint32_t concentration_revision;
    std::uint8_t concentration_selection_valid;
    std::uint8_t concentration_reserved[3] = {};
    std::int32_t concentration_entry_a;
    std::int32_t concentration_entry_b;
    std::uint32_t derived_stat_revision;
    ParticipantDerivedStatPacketState derived_stats;
    std::uint8_t level_up_pause_active;
    std::uint8_t level_up_waiting_count;
    std::uint16_t level_up_waiting_reserved = 0;
    std::uint64_t level_up_waiting_participant_ids[kLevelUpWaitStatusMaxParticipants];
    std::uint16_t inventory_item_count;
    std::uint16_t inventory_item_total_count;
    std::uint16_t inventory_snapshot_flags;
    std::uint16_t inventory_reserved;
    ParticipantInventoryItemPacketState inventory_items[kParticipantInventorySnapshotMaxItems];
    std::uint16_t progression_book_entry_count;
    std::uint16_t progression_book_entry_total_count;
    std::uint16_t progression_book_snapshot_flags;
    std::uint16_t progression_book_reserved;
    ParticipantProgressionBookEntryPacketState
        progression_book_entries[kParticipantProgressionBookSnapshotMaxEntries];
    std::int32_t primary_entry_index;
    std::int32_t primary_combo_entry_index;
    std::int32_t queued_secondary_entry_indices[kSecondaryLoadoutSlotCount];
    float position_x;
    float position_y;
    float heading;
    std::uint8_t anim_drive_state;
    std::uint8_t persistent_status_flags;
    std::uint8_t transient_status_flags;
    std::uint8_t transient_status_reserved[3] = {};
    std::int32_t poison_remaining_ticks;
    std::uint16_t presentation_flags;
    std::uint32_t attachment_staff_visual_state;
    std::uint8_t render_variant_primary;
    std::uint8_t render_variant_secondary;
    std::uint8_t render_weapon_type;
    std::uint8_t render_selection_byte;
    std::uint8_t render_variant_tertiary;
    std::uint8_t visual_link_reserved[3] = {};
    std::uint32_t primary_visual_link_type_id;
    std::uint32_t secondary_visual_link_type_id;
    std::uint8_t primary_visual_link_color_block[kParticipantVisualLinkColorBlockBytes];
    std::uint8_t secondary_visual_link_color_block[kParticipantVisualLinkColorBlockBytes];
    std::uint32_t anim_drive_state_word;
    float walk_cycle_primary;
    float walk_cycle_secondary;
    float render_drive_stride;
    float render_advance_rate;
    float render_advance_phase;
    float render_drive_effect_timer;
    float render_drive_effect_progress;
    float render_drive_overlay_alpha;
    float render_drive_move_blend;
};

struct SessionHelloPacket {
    PacketHeader header;
    std::uint64_t lobby_id;
    std::uint64_t participant_id;
    std::uint64_t steam_id;
    std::uint64_t host_steam_id;
    std::uint64_t session_nonce;
    std::uint32_t app_id;
    std::uint32_t capabilities;
    std::uint8_t role;
    std::uint8_t reserved[3] = {};
    char display_name[kParticipantDisplayNameBytes];
    std::uint8_t manifest_sha256[32];
};

struct CastPacket {
    PacketHeader header;
    std::uint64_t participant_id;
    std::uint32_t cast_sequence;
    std::uint8_t cast_kind;
    std::int8_t secondary_slot;
    std::uint8_t input_phase;
    std::uint8_t input_flags;
    std::uint32_t run_nonce;
    std::uint64_t target_network_actor_id;
    std::int32_t skill_id;
    std::int32_t element_id;
    std::int32_t discipline_id;
    std::int32_t primary_entry_index;
    std::int32_t primary_combo_entry_index;
    std::int32_t queued_secondary_entry_indices[kSecondaryLoadoutSlotCount];
    float position_x;
    float position_y;
    float heading;
    float direction_x;
    float direction_y;
    float aim_target_x;
    float aim_target_y;
};

struct SessionHelloAckPacket {
    PacketHeader header;
    std::uint64_t lobby_id;
    std::uint64_t authority_participant_id;
    std::uint64_t target_participant_id;
    std::uint64_t target_steam_id;
    std::uint64_t session_nonce;
    std::uint32_t capabilities;
    std::uint8_t result_code;
    std::uint8_t authority_role;
    std::uint8_t max_participants;
    std::uint8_t reserved = 0;
    std::uint8_t manifest_sha256[32];
};

struct SessionGoodbyePacket {
    PacketHeader header;
    std::uint64_t lobby_id;
    std::uint64_t participant_id;
    std::uint64_t steam_id;
    std::uint8_t reason;
    std::uint8_t reserved[7] = {};
};

struct LevelUpOfferPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint64_t target_participant_id;
    std::uint64_t offer_id;
    std::uint32_t run_nonce;
    std::int32_t level;
    std::int32_t experience;
    std::uint8_t option_count;
    std::uint8_t flags;
    std::uint16_t reserved = 0;
    LevelUpOfferOptionPacketState options[kLevelUpOfferMaxOptions];
};

struct LevelUpChoicePacket {
    PacketHeader header;
    std::uint64_t participant_id;
    std::uint64_t offer_id;
    std::uint32_t run_nonce;
    std::int32_t option_index;
    std::int32_t option_id;
};

struct LevelUpChoiceResultPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint64_t target_participant_id;
    std::uint64_t offer_id;
    std::uint32_t run_nonce;
    std::int32_t level;
    std::int32_t experience;
    std::int32_t option_index;
    std::int32_t option_id;
    std::int32_t apply_count;
    std::uint8_t result_code;
    std::uint8_t flags;
    std::uint16_t resulting_active;
};

struct WorldActorSnapshotPacketState {
    std::uint64_t network_actor_id;
    std::uint32_t native_type_id;
    std::int32_t enemy_type;
    std::int32_t actor_slot;
    std::int32_t world_slot;
    std::uint64_t target_participant_id;
    std::uint32_t target_native_type_id;
    std::int32_t target_actor_slot;
    std::int32_t target_world_slot;
    std::int32_t target_bucket_delta;
    std::uint8_t flags;
    std::uint8_t anim_drive_state;
    std::uint16_t presentation_flags;
    float position_x;
    float position_y;
    float radius;
    float heading;
    float hp;
    float max_hp;
    std::uint32_t anim_drive_state_word;
    float walk_cycle_primary;
    float walk_cycle_secondary;
    std::uint8_t render_variant_primary;
    std::uint8_t render_variant_secondary;
    std::uint8_t render_weapon_type;
    std::uint8_t render_selection_byte;
    std::uint8_t render_variant_tertiary;
    std::uint8_t presentation_reserved[3];
    std::uint8_t student_visual_state[kWorldActorStudentVisualStateBytes];
};

struct WorldSnapshotPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint32_t scene_epoch;
    std::uint32_t run_nonce;
    std::uint8_t scene_kind;
    std::uint8_t actor_count;
    std::uint8_t actor_total_count;
    std::uint8_t snapshot_flags;
    WorldActorSnapshotPacketState actors[kWorldSnapshotMaxActors];
};

struct LootDropSnapshotPacketState {
    std::uint64_t network_drop_id;
    std::uint32_t native_type_id;
    std::uint8_t drop_kind;
    std::uint8_t flags;
    std::uint8_t presentation_state;
    std::uint8_t reserved = 0;
    std::int32_t amount;
    std::int32_t amount_tier;
    float value;
    float motion;
    float progress;
    std::uint32_t item_type_id;
    std::int32_t item_slot;
    std::int32_t stack_count;
    std::int32_t actor_slot;
    std::int32_t world_slot;
    std::uint32_t lifetime;
    float position_x;
    float position_y;
    float radius;
};

struct LootSnapshotPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint32_t scene_epoch;
    std::uint32_t run_nonce;
    std::uint8_t scene_kind;
    std::uint8_t drop_count;
    std::uint8_t drop_total_count;
    std::uint8_t snapshot_flags;
    LootDropSnapshotPacketState drops[kLootSnapshotMaxDrops];
};

struct SpellEffectPacketState {
    std::uint32_t effect_serial;
    std::uint32_t cast_sequence;
    std::uint32_t native_type_id;
    std::uint16_t effect_ordinal;
    std::uint16_t flags;
    float position_x;
    float position_y;
    float radius;
    float heading;
    float motion_x;
    float motion_y;
    float ember_vertical_position;
    float ember_vertical_velocity;
    float ember_damage;
    float ember_lifetime;
    float ember_initial_lifetime;
    float ember_animation_progress;
    std::uint32_t ember_variant;
    std::uint32_t ember_frame_interval;
    std::uint16_t ember_config_primary;
    std::uint16_t ember_config_secondary;
    std::uint16_t ember_config_tertiary;
    std::uint16_t reserved = 0;
    float firewalker_collision_scale;
    float firewalker_phase;
    float firewalker_phase_step;
    float firewalker_lifetime;
    float firewalker_fade;
    float firewalker_direction;
    float firewalker_visual_scale;
    float firewalker_damage;
    std::int8_t firewalker_source_slot;
    std::uint8_t firewalker_active;
    std::uint8_t firewalker_variant;
    std::uint8_t firewalker_reserved = 0;
    std::int32_t firewalker_aux;
    std::uint32_t firewalker_damage_mask;
};

struct SpellEffectSnapshotPacket {
    PacketHeader header;
    std::uint64_t owner_participant_id;
    std::uint32_t run_nonce;
    std::uint32_t scene_epoch;
    std::uint8_t effect_count;
    std::uint8_t effect_total_count;
    std::uint16_t snapshot_flags;
    SpellEffectPacketState effects[kSpellEffectSnapshotMaxEffects];
};

struct AirChainTargetPacketState {
    std::uint64_t network_actor_id;
    std::uint16_t ordinal;
    std::uint16_t reserved = 0;
    float source_x;
    float source_y;
    float target_x;
    float target_y;
};

struct AirChainSnapshotPacket {
    PacketHeader header;
    std::uint64_t owner_participant_id;
    std::uint32_t run_nonce;
    std::uint32_t cast_sequence;
    std::uint32_t frame_sequence;
    std::uint8_t target_count;
    std::uint8_t target_total_count;
    std::uint8_t flags;
    std::uint8_t reserved = 0;
    AirChainTargetPacketState targets[kAirChainSnapshotMaxTargets];
};

struct ParticipantVitalsCorrectionPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint64_t target_participant_id;
    std::uint32_t correction_sequence;
    std::uint32_t run_nonce;
    float life_current;
    float life_max;
    std::uint8_t transient_status_flags;
    std::uint8_t reserved[3] = {};
    std::int32_t poison_remaining_ticks;
    float poison_damage_per_tick;
};

struct EnemyDamageClaimPacket {
    PacketHeader header;
    std::uint64_t participant_id;
    std::uint32_t claim_sequence;
    std::uint32_t run_nonce;
    std::uint64_t target_network_actor_id;
    std::int32_t skill_id;
    float claimed_damage;
    float client_before_hp;
    float client_after_hp;
    float caster_position_x;
    float caster_position_y;
    float target_position_x;
    float target_position_y;
    std::uint8_t lethal;
    // Native collision resolution can change a client's local target transform
    // before the next authority snapshot reaches it. Such automatically
    // observed HP deltas may omit transform authority while still claiming the
    // damage; explicit/scripted claims keep the strict position contract.
    std::uint8_t claim_flags;
    std::uint8_t reserved[2] = {};
};

constexpr std::uint8_t kEnemyDamageClaimFlagTargetPositionOptional = 1u << 0;
constexpr std::uint8_t kEnemyDamageClaimKnownFlags =
    kEnemyDamageClaimFlagTargetPositionOptional;

struct EnemyDamageResultPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint64_t claimant_participant_id;
    std::uint32_t claim_sequence;
    std::uint32_t run_nonce;
    std::uint64_t target_network_actor_id;
    std::uint8_t result_code;
    std::uint8_t dead;
    std::uint16_t reserved = 0;
    float authoritative_hp;
    float authoritative_max_hp;
};

struct LootPickupRequestPacket {
    PacketHeader header;
    std::uint64_t participant_id;
    std::uint32_t request_sequence;
    std::uint32_t run_nonce;
    std::uint64_t network_drop_id;
    float requester_position_x;
    float requester_position_y;
    float drop_position_x;
    float drop_position_y;
    std::uint8_t request_flags;
    std::uint8_t reserved[3] = {};
};

struct LootPickupResultPacket {
    PacketHeader header;
    std::uint64_t authority_participant_id;
    std::uint64_t participant_id;
    std::uint32_t request_sequence;
    std::uint32_t run_nonce;
    std::uint64_t network_drop_id;
    std::uint8_t result_code;
    std::uint8_t drop_kind;
    std::uint16_t reserved = 0;
    std::int32_t amount;
    std::int32_t resulting_gold;
    std::uint32_t gold_revision;
    std::int32_t resource_kind;
    float resource_delta;
    float resulting_life_current;
    float resulting_life_max;
    float resulting_mana_current;
    float resulting_mana_max;
    std::uint32_t item_type_id;
    std::int32_t item_slot;
    std::int32_t stack_count;
    std::uint32_t inventory_revision;
};
#pragma pack(pop)

inline PacketHeader MakePacketHeader(PacketKind kind, std::uint32_t sequence) {
    PacketHeader header{};
    header.magic[0] = kProtocolMagic[0];
    header.magic[1] = kProtocolMagic[1];
    header.magic[2] = kProtocolMagic[2];
    header.magic[3] = kProtocolMagic[3];
    header.version = kProtocolVersion;
    header.kind = static_cast<std::uint16_t>(kind);
    header.sequence = sequence;
    return header;
}

inline bool IsValidPacketHeader(const PacketHeader& header) {
    return header.magic[0] == kProtocolMagic[0] &&
           header.magic[1] == kProtocolMagic[1] &&
           header.magic[2] == kProtocolMagic[2] &&
           header.magic[3] == kProtocolMagic[3] &&
           header.version == kProtocolVersion;
}

inline bool IsValidHeader(const PacketHeader& header, PacketKind expected_kind) {
    return IsValidPacketHeader(header) &&
           header.kind == static_cast<std::uint16_t>(expected_kind);
}

static_assert(sizeof(PacketHeader) == 12, "Unexpected packet header size");
static_assert(sizeof(ParticipantInventoryItemPacketState) == 12, "Unexpected inventory item packet size");
static_assert(sizeof(ParticipantProgressionBookEntryPacketState) == 20, "Unexpected progression book entry packet size");
static_assert(sizeof(LevelUpOfferOptionPacketState) == 8, "Unexpected level-up option packet size");
static_assert(sizeof(ParticipantDerivedStatPacketState) == 56, "Unexpected derived stat packet size");
static_assert(sizeof(StatePacket) == 3832, "Unexpected state packet size");
static_assert(sizeof(SessionHelloPacket) == 128, "Unexpected session hello packet size");
static_assert(sizeof(CastPacket) == 120, "Unexpected cast packet size");
static_assert(sizeof(SessionHelloAckPacket) == 92, "Unexpected session hello acknowledgement packet size");
static_assert(sizeof(SessionGoodbyePacket) == 44, "Unexpected session goodbye packet size");
static_assert(sizeof(LevelUpOfferPacket) == 116, "Unexpected level-up offer packet size");
static_assert(sizeof(LevelUpChoicePacket) == 40, "Unexpected level-up choice packet size");
static_assert(sizeof(LevelUpChoiceResultPacket) == 64, "Unexpected level-up choice result packet size");
static_assert(sizeof(WorldActorSnapshotPacketState) == 128, "Unexpected world actor snapshot size");
static_assert(sizeof(WorldSnapshotPacket) == 8224, "Unexpected world snapshot packet size");
static_assert(sizeof(LootDropSnapshotPacketState) == 72, "Unexpected loot drop snapshot size");
static_assert(sizeof(LootSnapshotPacket) == 4640, "Unexpected loot snapshot packet size");
static_assert(sizeof(SpellEffectPacketState) == 124, "Unexpected spell effect packet state size");
static_assert(sizeof(SpellEffectSnapshotPacket) == 4000, "Unexpected spell effect snapshot packet size");
static_assert(sizeof(AirChainTargetPacketState) == 28, "Unexpected Air chain target packet size");
static_assert(sizeof(AirChainSnapshotPacket) == 260, "Unexpected Air chain snapshot packet size");
static_assert(sizeof(ParticipantVitalsCorrectionPacket) == 56, "Unexpected participant vitals correction packet size");
static_assert(sizeof(EnemyDamageClaimPacket) == 72, "Unexpected enemy damage claim packet size");
static_assert(sizeof(EnemyDamageResultPacket) == 56, "Unexpected enemy damage result packet size");
static_assert(sizeof(LootPickupRequestPacket) == 56, "Unexpected loot pickup request packet size");
static_assert(sizeof(LootPickupResultPacket) == 100, "Unexpected loot pickup result packet size");

}  // namespace sdmod::multiplayer
