#include "bot_runtime.h"
#include "d3d9_end_scene_hook.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "lua_engine.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "runtime_debug.h"
#include "runtime_tick_service.h"
#include "sdmod_plugin_api.h"
#include "x86_hook.h"

#include <Windows.h>
#include <d3d9.h>
#include <intrin.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <cwctype>
#include <deque>
#include <filesystem>
#include <fstream>
#include <limits>
#include <malloc.h>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

using GameplayKeyboardEdgeFn = std::uint8_t(__thiscall*)(void* self, std::uint32_t scancode);
using GameplayMouseRefreshFn = void(__fastcall*)(void* self, void* unused_edx);
using PlayerActorTickFn = void(__thiscall*)(void* self);
using PlayerActorNoArgMethodFn = void(__thiscall*)(void* self);
using PlayerActorDtorFn = void(__thiscall*)(void* self, char free_flag);
using PuppetManagerDeletePuppetFn = void(__thiscall*)(void* self, void* actor);
using PointerListDeleteBatchFn = void(__thiscall*)(void* self, void* list);
using ObjectDeleteFn = void(__thiscall*)(void* self);
using GameplaySwitchRegionFn = void(__thiscall*)(void* self, int region_index);
using ArenaStartWavesFn = void(__thiscall*)(void* self);
using GameplayCombatPreludeModeFn = void(__thiscall*)(void* self, std::uint32_t arg0, std::uint32_t arg1);
using ArenaCombatPreludeDispatchFn = void(__thiscall*)(void* self, int mode);
using GameplayCreatePlayerSlotFn = void(__thiscall*)(void* self, int slot_index);
using WizardCloneFromSourceActorFn = void*(__fastcall*)(void* source_actor);
using PlayerActorCtorFn = void*(__thiscall*)(void* self);
using RawObjectCtorFn = void*(__thiscall*)(void* self);
using GameObjectAllocateFn = void*(__cdecl*)(std::size_t size);
using GameObjectFactoryFn = uintptr_t(__thiscall*)(void* self, int type_id);
using GameOperatorNewFn = void*(__cdecl*)(std::size_t size);
using ActorWorldRegisterFn = std::uint32_t(__thiscall*)(void* self, int actor_group, void* actor, int slot_index, char use_alt_list);
using ActorWorldUnregisterFn = void(__thiscall*)(void* self, void* actor, char remove_from_container);
using ActorWorldRegisterGameplaySlotActorFn = void(__thiscall*)(void* self, int slot_index);
using ActorWorldUnregisterGameplaySlotActorFn = void(__thiscall*)(void* self, int slot_index);
using WorldCellGridRebindActorFn = void(__thiscall*)(void* self, void* actor);
using MonsterPathfindingRefreshTargetFn = void(__fastcall*)(void* self, void* unused_edx);
using PlayerActorMoveStepFn = std::uint32_t(__thiscall*)(void* self, void* actor, float move_x, float move_y, unsigned int flags);
using SpellCastDispatcherFn = void(__thiscall*)(void* actor);
using PurePrimarySpellStartFn = void(__thiscall*)(void* actor);
using CastActiveHandleCleanupFn = void(__thiscall*)(void* actor);
using ActorGetProfileFn = void*(__thiscall*)(void* self);
using ProfileResolveStatEntryFn = void*(__thiscall*)(void* self, int stat_index);
using StatBookComputeValueFn = float(__thiscall*)(void* self, float base_value, int entry_idx, char apply_modifier);
using MovementCollisionTestCirclePlacementFn = std::uint32_t(__thiscall*)(void* self, float x, float y, float radius, std::uint32_t mask);
using MovementCollisionTestCirclePlacementExtendedFn =
    std::uint32_t(__thiscall*)(
        void* self,
        float x,
        float y,
        float radius,
        std::uint32_t circle_block_mask,
        std::uint32_t overlap_allow_mask);
using ActorMoveByDeltaFn = void(__thiscall*)(void* self, float move_x, float move_y, int flags);
using ActorAnimationAdvanceFn = void(__thiscall*)(void* self);
using PlayerActorRefreshRuntimeHandlesFn = void(__thiscall*)(void* self);
using ActorProgressionRefreshFn = void(__thiscall*)(void* self);
using PlayerAppearanceApplyChoiceFn = void(__thiscall*)(void* progression, int choice_id, int ensure_assets);
using SkillsWizardBuildPrimarySpellFn = void(__thiscall*)(void* self, float primary_entry, float combo_entry);
using GameNpcSetMoveGoalFn = void(__thiscall*)(void* self, std::uint8_t mode, int follow_flag, float x, float y, float extra_scalar);
using GameNpcSetTrackedSlotAssistFn = void(__thiscall*)(void* self, int slot_index, int require_callback);
using EquipAttachmentSinkGetCurrentItemFn = int(__fastcall*)(int sink);
using SpellActionBuilderFn = void(__thiscall*)(void* self, int mode, int arg2);
using SpellBuilderResetFn = void(__cdecl*)();
using SpellBuilderFinalizeFn = void(__cdecl*)();
using GameplayActorAttachFn = void(__thiscall*)(void* self, void* actor);
using StandaloneWizardVisualLinkAttachFn = std::uint8_t(__thiscall*)(void* self, void* value);
using ActorBuildRenderDescriptorFromSourceFn = void(__thiscall*)(void* self);
using ScalarDeletingDestructorFn = void(__thiscall*)(void* self, int flags);
using SpawnRewardGoldFn = void(__thiscall*)(void* self, std::uint32_t x_bits, std::uint32_t y_bits, int amount, int lifetime);
using EnemyConfigCtorFn = void(__thiscall*)(void* self);
using EnemyConfigDtorFn = void(__thiscall*)(void* self);
using EnemyConfigBuildFn = void(__thiscall*)(void* self, int type_id, int variant, void* config_buffer, void* modifier_list);
using EnemySpawnFn =
    void* (__thiscall*)(void* self, void* spawn_anchor, void* enemy_config, int spawn_mode, int param_5, int param_6, char allow_override);
using GameFreeFn = void(__cdecl*)(void* memory);
using GameplayHudRenderDispatchFn = void(__thiscall*)(void* self, int render_case);

struct SehExceptionDetails {
    DWORD code = 0;
    uintptr_t exception_address = 0;
    uintptr_t eip = 0;
    DWORD access_type = 0;
    uintptr_t access_address = 0;
};

bool CallActorWorldUnregisterSafe(
    uintptr_t actor_world_unregister_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    char remove_from_container,
    DWORD* exception_code);
bool CallPuppetManagerDeletePuppetSafe(
    uintptr_t delete_puppet_address,
    uintptr_t manager_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallObjectDeleteSafe(
    uintptr_t object_delete_address,
    uintptr_t object_address,
    DWORD* exception_code);
bool CallActorWorldRegisterSafe(
    uintptr_t actor_world_register_address,
    uintptr_t world_address,
    int actor_group,
    uintptr_t actor_address,
    int slot_index,
    char use_alt_list,
    DWORD* exception_code);
bool CallGameplayCreatePlayerSlotSafe(
    uintptr_t create_player_slot_address,
    uintptr_t gameplay_address,
    int slot_index,
    DWORD* exception_code);
bool CallPlayerActorEnsureProgressionHandleSafe(
    uintptr_t ensure_progression_handle_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallActorWorldRegisterGameplaySlotActorSafe(
    uintptr_t register_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code);
bool CallWorldCellGridRebindActorSafe(
    uintptr_t rebind_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallActorWorldUnregisterGameplaySlotActorSafe(
    uintptr_t unregister_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code);
bool CallActorBuildRenderDescriptorFromSourceSafe(
    uintptr_t build_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallSpellCastDispatcherSafe(
    uintptr_t dispatcher_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallPurePrimarySpellStartSafe(
    uintptr_t startup_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallCastActiveHandleCleanupSafe(
    uintptr_t cleanup_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallWizardCloneFromSourceActorSafe(
    uintptr_t clone_address,
    uintptr_t source_actor_address,
    uintptr_t* clone_actor_address,
    DWORD* exception_code);
bool CallScalarDeletingDestructorSafe(
    uintptr_t object_address,
    int flags,
    DWORD* exception_code);
bool CallScalarDeletingDestructorDetailedSafe(
    uintptr_t object_address,
    int flags,
    SehExceptionDetails* exception_details);
std::string FormatSehExceptionDetails(const SehExceptionDetails& details);

constexpr std::size_t kGameplayMouseRefreshHookPatchSize = 8;
constexpr std::size_t kGameplayKeyboardEdgeHookPatchSize = 9;
constexpr std::size_t kPlayerActorTickHookPatchSize = 6;
constexpr std::size_t kPlayerActorEnsureProgressionHandleHookPatchSize = 7;
constexpr std::size_t kPlayerActorDtorHookPatchSize = 12;
constexpr bool kEnablePlayerActorDtorHook = false;
constexpr std::size_t kPlayerActorVtable28HookPatchSize = 6;
constexpr std::size_t kPlayerActorPurePrimaryGateHookMinimumPatchSize = 5;
constexpr std::size_t kPlayerControlBrainUpdateHookMinimumPatchSize = 5;
constexpr std::size_t kPurePrimarySpellStartHookMinimumPatchSize = 5;
constexpr std::size_t kSpellCastDispatcherHookMinimumPatchSize = 5;
constexpr std::size_t kEquipAttachmentSinkGetCurrentItemHookMinimumPatchSize = 5;
// 0x0044F5F0 starts with two whole instructions:
//   push -1           (2 bytes)
//   push 0x76559b     (5 bytes)
// A 5-byte hook splits the second instruction and makes the trampoline invalid.
constexpr std::size_t kSpellActionBuilderHookMinimumPatchSize = 7;
constexpr std::size_t kSpellBuilderResetHookMinimumPatchSize = 5;
constexpr std::size_t kSpellBuilderFinalizeHookMinimumPatchSize = 5;
constexpr std::size_t kGameplayHudRenderDispatchHookPatchSize = 6;
constexpr std::size_t kPuppetManagerDeletePuppetHookPatchSize = 6;
// 0x004024C0 starts with 5 bytes of whole instructions:
//   push ebp; mov ebp, esp; push ebx; push esi
// Using 6 bytes splits the following `mov esi, [ebp+0x8]` and corrupts the
// trampoline. Keep this hook boundary at 5 unless the function prologue is
// re-audited.
constexpr std::size_t kPointerListDeleteBatchHookPatchSize = 5;
constexpr std::size_t kActorWorldUnregisterHookPatchSize = 6;
constexpr std::size_t kGameplaySwitchRegionHookMinimumPatchSize = 5;
constexpr int kWizardSourceActorFactoryTypeId = 0x1397;
constexpr std::size_t kActorAnimationAdvanceHookPatchSize = 6;
constexpr std::size_t kMonsterPathfindingRefreshTargetHookMinimumPatchSize = 5;
constexpr int kArenaRegionIndex = 5;
constexpr std::size_t kStandaloneWizardVisualRuntimeSize = 0x8E4;
constexpr std::size_t kStandaloneWizardVisualLinkSize = 0xA8;
constexpr std::size_t kStandaloneWizardVisualLinkColorBlockOffset = 0x88;
constexpr std::size_t kStandaloneWizardVisualLinkResetStateOffset = 0x1C;
constexpr std::size_t kStandaloneWizardVisualLinkActiveFlagOffset = 0x58;
constexpr int kStandaloneWizardHiddenSelectionState = -2;
constexpr std::size_t kGameplayRegionStride = 4;
constexpr std::size_t kGameplayPlayerSlotStride = 4;
constexpr std::size_t kGameplayPlayerSlotCount = 4;
constexpr int kStandaloneWizardVisualSlotBase = 1;
constexpr int kStandaloneWizardVisualSlotMax =
    static_cast<int>(kGameplayPlayerSlotCount) - 1;
constexpr int kWizardProgressionFactoryTypeId = 0x0BBB;
constexpr std::size_t kPlayerActorSize = 0x398;
constexpr std::size_t kStandaloneWizardEquipSize = 100;
constexpr std::size_t kStandaloneWizardAttachmentItemSize = 0x88;
constexpr std::size_t kGameplayPlayerFallbackPositionStride = 8;
// Object_Ctor treats +0x04..+0x07 as object-header state, not an actor-owned
// render-context pointer. Keep the raw word available for dumps and probes, but
// do not treat it as a transferable render node.
constexpr std::size_t kActorAnimationConfigBlockSize = 0x0C;
constexpr std::size_t kGameplayIndexStateActorSelectionBaseIndex = 0x0C;
// Legacy name: +0x22C is a packed discrete frame offset/countdown field, not a pointer.
constexpr std::size_t kActorHubVisualDescriptorBlockSize = 0x20;
constexpr int kActorAnimationStateSlotBias = 0x0C;
constexpr int kUnknownAnimationStateId = -1;
constexpr std::uint8_t kDeadWizardBotCorpseDriveState = 1;
constexpr float kWizardHeadingRadiansToDegrees = 57.2957795130823208767981548141051703f;
constexpr std::size_t kGameplayInputBufferStride = 0x203;
constexpr std::uint64_t kWaveStartRetryDelayMs = 250;
constexpr std::uint64_t kWizardBotSyncRetryDelayMs = 250;
constexpr std::uint64_t kWizardBotSyncDispatchSpacingMs = 500;
constexpr std::uint64_t kWizardBotSceneBindingTickIntervalMs = 50;
constexpr float kWizardBotPathWaypointArrivalThreshold = 12.0f;
constexpr float kWizardBotPathFinalArrivalThreshold = 8.0f;
constexpr std::uint64_t kWizardBotPathRetryDelayMs = 500;
constexpr std::uint64_t kGameplayRegionSwitchRetryDelayMs = 250;
constexpr std::uint64_t kGameplayRegionSwitchDispatchSpacingMs = 500;
constexpr std::uint64_t kGameplaySceneChurnDelayMs = 1500;
constexpr DWORD kHubStartTestrunDispatchCooldownMs = 5000;
constexpr std::uint32_t kInjectedGameplayMouseClickFrames = 2;
constexpr std::size_t kEnemyConfigBufferSize = 216;
constexpr std::size_t kEnemyConfigWrapperSize = 4 + kEnemyConfigBufferSize;
constexpr std::size_t kQueuedGameplayWorldActionLimit = 64;
constexpr int kSpawnRewardDefaultLifetime = 0;
constexpr int kUnknownXpSentinel = -1;
constexpr int kSpawnEnemyVariantDefault = 0;
constexpr int kSpawnEnemyModeDefault = 0;
constexpr int kSpawnEnemyParam5Default = 0;
constexpr int kSpawnEnemyParam6Default = 0;
constexpr char kSpawnEnemyAllowOverrideDefault = 0;
constexpr int kFirstWizardBotSlot = 1;
constexpr int kHubRegionIndex = 0;
constexpr float kDefaultWizardBotOffsetX = 32.0f;
constexpr float kDefaultWizardBotOffsetY = 0.0f;
constexpr std::size_t kActorCurrentTargetActorOffset = 0x168;
constexpr std::size_t kActorContinuousPrimaryModeOffset = 0x258;
constexpr std::size_t kActorContinuousPrimaryActiveOffset = 0x264;
constexpr std::size_t kHostileCurrentTargetActorOffset = 0x168;
constexpr std::size_t kHostileTargetBucketDeltaOffset = 0x164;
constexpr std::int32_t kActorWorldBucketStride = 0x800;
constexpr std::size_t kActorWorldBucketTableOffset = 0x500;
constexpr std::size_t kSceneActorBucketScanCount = 0x2000;
constexpr int kSceneTypeHub = 0xFA1;
constexpr int kSceneTypeMemorator = 0xFA2;
constexpr int kSceneTypeDowser = 0xFA3;
constexpr int kSceneTypeLibrarian = 0xFA4;
constexpr int kSceneTypePolisherArch = 0xFA5;
constexpr int kSceneTypeArena = 0xFA6;

// ---- Synthetic wizard source profile for independent bot visuals ----
// FUN_005E3080 reads these offsets from the source profile at actor+0x178.
// We allocate a small buffer with these fields set so the engine builds
// the bot's descriptor block, variant bytes, and weapon attachment natively.
constexpr std::size_t kSyntheticSourceProfileSize = 0x100;
constexpr std::int32_t kStandaloneWizardVisualSourceKind = 3;

struct ElementColorDescriptor {
    float primary_r, primary_g, primary_b, primary_a;
    float secondary_r, secondary_g, secondary_b, secondary_a;
};

ElementColorDescriptor GetWizardElementColor(int wizard_id);
int ResolveStandaloneWizardRenderSelectionIndex(int wizard_id);

struct WizardSourceProfileTemplate {
    std::int8_t variant_primary = 0;
    std::int8_t variant_secondary = 0;
    std::int8_t weapon_type = 1;
    std::uint8_t variant_tertiary = 0;
};

struct WizardAppearanceChoiceIds {
    int primary_a = 0;
    int primary_b = 8;
    int primary_c = 0x0B;
    int secondary = 7;
};

// Gameplay-slot actors and temporary source actors are not the same contract.
// Real gameplay-slot actors settle at `0/0/0/1/0`, but the stock source/preview
// side compiles a fuller wizard render window before helper-item and attachment
// extraction. Keep the gameplay-slot actor clean later; let the source actor
// use the richer selector window so `ActorBuildRenderDescriptorFromSource` can
// still synthesize the staff/orb attachment and helper visuals.
constexpr WizardSourceProfileTemplate kWizardSourceProfileTemplates[] = {
    {1, 1, 1, 0},  // fire source actor
    {1, 1, 1, 0},  // water source actor
    {1, 1, 1, 0},  // earth source actor
    {1, 1, 1, 0},  // air source actor
    {1, 1, 1, 0},  // ether source actor
};
constexpr int kWizardSourceProfileTemplateCount =
    static_cast<int>(sizeof(kWizardSourceProfileTemplates) / sizeof(kWizardSourceProfileTemplates[0]));

WizardAppearanceChoiceIds ResolveWizardAppearanceChoiceIds(int wizard_id) {
    switch ((std::max)(0, (std::min)(wizard_id, 4))) {
    case 0:
        return {1, 0x10, 0x15, 6};   // fire + arcane
    case 1:
        return {3, 0x20, 0x23, 6};   // water + arcane
    case 2:
        return {4, 0x28, 0x2D, 6};   // earth + arcane
    case 3:
        return {2, 0x18, 0x1B, 6};   // air + arcane
    case 4:
    default:
        return {0, 0x08, 0x0B, 6};   // ether + arcane
    }
}

std::int32_t ResolveProfileElementId(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return character_profile.element_id;
}

bool HasExplicitProfileAppearanceChoices(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return std::all_of(
        character_profile.appearance.choice_ids.begin(),
        character_profile.appearance.choice_ids.end(),
        [](std::int32_t value) {
            return value >= 0;
        });
}

WizardAppearanceChoiceIds ResolveProfileAppearanceChoiceIds(
    const multiplayer::MultiplayerCharacterProfile& character_profile) {
    if (HasExplicitProfileAppearanceChoices(character_profile)) {
        return {
            character_profile.appearance.choice_ids[0],
            character_profile.appearance.choice_ids[1],
            character_profile.appearance.choice_ids[2],
            character_profile.appearance.choice_ids[3],
        };
    }

    auto choice_ids = ResolveWizardAppearanceChoiceIds(ResolveProfileElementId(character_profile));
    switch (character_profile.discipline_id) {
    case multiplayer::CharacterDisciplineId::Mind:
        choice_ids.secondary = 4;
        break;
    case multiplayer::CharacterDisciplineId::Body:
        choice_ids.secondary = 5;
        break;
    case multiplayer::CharacterDisciplineId::Arcane:
    default:
        choice_ids.secondary = 6;
        break;
    }
    return choice_ids;
}

uintptr_t CreateSyntheticWizardSourceProfile(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    const auto wizard_id = ResolveProfileElementId(character_profile);
    const auto& profile = kWizardSourceProfileTemplates[
        (wizard_id >= 0 && wizard_id < kWizardSourceProfileTemplateCount) ? wizard_id : 0];
    const auto element_color = GetWizardElementColor(wizard_id);

    auto* buffer = static_cast<std::uint8_t*>(_aligned_malloc(kSyntheticSourceProfileSize, 16));
    if (buffer == nullptr) {
        return 0;
    }
    std::memset(buffer, 0, kSyntheticSourceProfileSize);

    // +0x4C must be 3 or FUN_005E3080 returns early
    *reinterpret_cast<std::int32_t*>(buffer + kSourceProfileVisualSourceTypeOffset) =
        kStandaloneWizardVisualSourceKind;

    // Variant bytes that drive the wizard descriptor build and staff/orb
    // attachment creation while the synthetic source profile is staged. The
    // coarse render-selection byte is the stock element branch consumed by the
    // attachment/orb path; keep it aligned with the public element semantics.
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantPrimaryOffset) =
        profile.variant_primary;
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantSecondaryOffset) =
        profile.variant_secondary;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileRenderSelectionOffset) =
        static_cast<std::uint8_t>(ResolveStandaloneWizardRenderSelectionIndex(wizard_id));
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileWeaponTypeOffset) =
        profile.weapon_type;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileVariantTertiaryOffset) =
        profile.variant_tertiary;

    auto write_color = [&](std::size_t offset, float r, float g, float b, float a) {
        *reinterpret_cast<float*>(buffer + offset + 0x00) = r;
        *reinterpret_cast<float*>(buffer + offset + 0x04) = g;
        *reinterpret_cast<float*>(buffer + offset + 0x08) = b;
        *reinterpret_cast<float*>(buffer + offset + 0x0C) = a;
    };
    write_color(
        kSourceProfileClothColorOffset,
        element_color.primary_r,
        element_color.primary_g,
        element_color.primary_b,
        element_color.primary_a);
    write_color(
        kSourceProfileTrimColorOffset,
        element_color.secondary_r,
        element_color.secondary_g,
        element_color.secondary_b,
        element_color.secondary_a);

    return reinterpret_cast<uintptr_t>(buffer);
}

void DestroySyntheticWizardSourceProfile(uintptr_t address) {
    if (address != 0) {
        _aligned_free(reinterpret_cast<void*>(address));
    }
}

struct EnemyModifierList {
    uintptr_t vtable = 0;
    void* items = nullptr;
    int count = 0;
    std::uint16_t capacity = 0;
    std::uint16_t reserved = 0;
};

static_assert(sizeof(EnemyModifierList) == 16, "EnemyModifierList layout must match the in-game Array<int>.");

struct SpawnEnemyCallContext {
    uintptr_t arena_address = 0;
    EnemyConfigCtorFn config_ctor = nullptr;
    EnemyConfigDtorFn config_dtor = nullptr;
    EnemyConfigBuildFn build_config = nullptr;
    EnemySpawnFn spawn_enemy = nullptr;
    EnemyModifierList* modifiers = nullptr;
    void* config_wrapper = nullptr;
    void* config_buffer = nullptr;
    int type_id = 0;
    void* enemy = nullptr;
};

struct ArenaWaveStartState {
    std::int32_t combat_section_index = 0;
    std::int32_t combat_wave_index = 0;
    std::int32_t combat_wait_ticks = 0;
    std::int32_t combat_advance_mode = 0;
    std::int32_t combat_advance_threshold = 0;
    std::int32_t combat_wave_counter = 0;
    std::uint8_t combat_started_music = 0;
    std::uint8_t combat_transition_requested = 0;
    std::uint8_t combat_active = 0;
};

struct PendingEnemySpawnRequest {
    int type_id = 0;
    float x = 0.0f;
    float y = 0.0f;
};

struct PendingRewardSpawnRequest {
    std::string kind;
    int amount = 0;
    float x = 0.0f;
    float y = 0.0f;
};

struct PendingParticipantEntitySyncRequest {
    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    bool has_transform = false;
    bool has_heading = false;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    std::uint64_t next_attempt_ms = 0;
};

struct PendingGameplayRegionSwitchRequest {
    int region_index = -1;
    std::uint64_t next_attempt_ms = 0;
};

struct GameplayKeyboardInjectionState {
    X86Hook mouse_refresh_hook;
    X86Hook edge_hook;
    X86Hook player_actor_tick_hook;
    X86Hook player_actor_progression_handle_hook;
    X86Hook player_actor_dtor_hook;
    X86Hook player_actor_vtable28_hook;
    X86Hook player_actor_pure_primary_gate_hook;
    X86Hook player_control_brain_update_hook;
    X86Hook pure_primary_spell_start_hook;
    X86Hook pure_primary_post_builder_hook;
    X86Hook spell_cast_dispatcher_hook;
    X86Hook equip_attachment_get_current_item_hook;
    X86Hook spell_action_builder_hook;
    X86Hook spell_builder_reset_hook;
    X86Hook spell_builder_finalize_hook;
    X86Hook gameplay_hud_render_dispatch_hook;
    X86Hook actor_animation_advance_hook;
    X86Hook puppet_manager_delete_puppet_hook;
    X86Hook pointer_list_delete_batch_hook;
    X86Hook actor_world_unregister_hook;
    X86Hook gameplay_switch_region_hook;
    X86Hook monster_pathfinding_refresh_target_hook;
    bool initialized = false;
    std::array<std::atomic<std::uint32_t>, 256> pending_scancodes{};
    std::atomic<bool> last_observed_mouse_left_down{false};
    std::atomic<std::uint64_t> mouse_left_edge_serial{0};
    std::atomic<std::uint64_t> mouse_left_edge_tick_ms{0};
    std::atomic<std::uint32_t> pending_mouse_left_edge_events{0};
    std::atomic<std::uint32_t> pending_mouse_left_frames{0};
    std::atomic<std::uint32_t> pending_hub_start_testrun_requests{0};
    std::atomic<std::uint32_t> pending_start_waves_requests{0};
    std::atomic<std::uint32_t> pending_enable_combat_prelude_requests{0};
    std::atomic<std::uint64_t> hub_start_testrun_cooldown_until_ms{0};
    std::atomic<std::uint64_t> start_waves_retry_not_before_ms{0};
    std::atomic<std::uint64_t> wizard_bot_sync_not_before_ms{0};
    std::atomic<std::uint64_t> gameplay_region_switch_not_before_ms{0};
    std::atomic<std::uint64_t> scene_churn_not_before_ms{0};
    std::mutex pending_gameplay_world_actions_mutex;
    std::deque<PendingEnemySpawnRequest> pending_enemy_spawn_requests;
    std::deque<PendingRewardSpawnRequest> pending_reward_spawn_requests;
    std::deque<PendingParticipantEntitySyncRequest> pending_participant_sync_requests;
    std::deque<PendingGameplayRegionSwitchRequest> pending_gameplay_region_switch_requests;
    std::deque<std::uint64_t> pending_participant_destroy_requests;
} g_gameplay_keyboard_injection;

struct ObservedActorAnimationDriveProfile {
    bool valid = false;
    std::array<std::uint8_t, kActorAnimationConfigBlockSize> config_bytes{};
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
};

struct BotPathWaypoint {
    int grid_x = -1;
    int grid_y = -1;
    float x = 0.0f;
    float y = 0.0f;
};

struct ParticipantEntityBinding {
    enum class Kind : std::uint8_t {
        PlaceholderEnemy = 0,
        StandaloneWizard = 1,
        GameplaySlotWizard = 2,
        RegisteredGameNpc = 3,
    };

    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    uintptr_t actor_address = 0;
    int gameplay_slot = -1;
    Kind kind = Kind::PlaceholderEnemy;
    multiplayer::BotControllerState controller_state = multiplayer::BotControllerState::Idle;
    std::uint64_t movement_intent_revision = 0;
    bool movement_active = false;
    float last_movement_displacement = 0.0f;
    bool has_target = false;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    bool desired_heading_valid = false;
    float desired_heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
    bool path_active = false;
    bool path_failed = false;
    std::uint64_t active_path_revision = 0;
    std::uint64_t next_path_retry_not_before_ms = 0;
    std::uint64_t last_path_debug_log_ms = 0;
    std::size_t path_waypoint_index = 0;
    float current_waypoint_x = 0.0f;
    float current_waypoint_y = 0.0f;
    std::vector<BotPathWaypoint> path_waypoints;
    std::uint64_t next_scene_materialize_retry_ms = 0;
    uintptr_t materialized_scene_address = 0;
    uintptr_t materialized_world_address = 0;
    int materialized_region_index = -1;
    int last_applied_animation_state_id = kUnknownAnimationStateId - 1;
    ObservedActorAnimationDriveProfile standalone_idle_animation_drive_profile;
    ObservedActorAnimationDriveProfile standalone_moving_animation_drive_profile;
    float dynamic_walk_cycle_primary = 0.0f;
    float dynamic_walk_cycle_secondary = 0.0f;
    float dynamic_render_drive_stride = 0.0f;
    float dynamic_render_advance_rate = 0.0f;
    float dynamic_render_advance_phase = 0.0f;
    float dynamic_render_drive_move_blend = 0.0f;
    uintptr_t standalone_progression_wrapper_address = 0;
    uintptr_t standalone_progression_inner_address = 0;
    uintptr_t standalone_equip_wrapper_address = 0;
    uintptr_t standalone_equip_inner_address = 0;
    bool registered_gamenpc_goal_active = false;
    bool registered_gamenpc_following_local_slot = false;
    float registered_gamenpc_goal_x = 0.0f;
    float registered_gamenpc_goal_y = 0.0f;
    bool gameplay_attach_applied = false;
    bool raw_allocation = false;
    uintptr_t synthetic_source_profile_address = 0;
    // "Currently facing" heading pinned across ticks. Sources: movement step
    // and cast dispatch each write this when they fire. Last setter wins, and
    // within a single tick cast is processed after movement so it takes
    // priority. The tick hook writes this value to the actor's heading field
    // every tick while valid, so the bot keeps facing whichever direction was
    // last set until something explicitly changes it again.
    float facing_heading_value = 0.0f;
    bool facing_heading_valid = false;
    uintptr_t facing_target_actor_address = 0;
    bool stock_tick_facing_origin_valid = false;
    float stock_tick_facing_origin_x = 0.0f;
    float stock_tick_facing_origin_y = 0.0f;
    bool death_transition_stock_tick_seen = false;

    // Ongoing cast state. The loader primes the cast once and, for gameplay-slot
    // bots, keeps a stock-owned startup/watch state alive across ticks. Startup
    // runs by letting the native PlayerActorTick see the prepared actor/progression
    // fields while the bot is temporarily presented as local slot 0. After the
    // stock handler latches or allocates a spell object, the loader just watches
    // actor+0x160 (animation_drive_state), actor+0x1EC (mNoInterrupt), and the
    // cached spell handle (actor+0x27C / +0x27E) until cleanup.
    struct OngoingCastState {
        enum class Lane : std::uint8_t {
            Dispatcher = 0,
            PurePrimary = 1,
        };
        bool active = false;
        Lane lane = Lane::Dispatcher;
        std::int32_t skill_id = 0;
        std::int32_t dispatcher_skill_id = 0;
        int selection_state_target = kUnknownAnimationStateId;
        bool uses_dispatcher_skill_id = false;
        bool have_aim_heading = false;
        float aim_heading = 0.0f;
        bool have_aim_target = false;
        float aim_target_x = 0.0f;
        float aim_target_y = 0.0f;
        uintptr_t target_actor_address = 0;
        float heading_before = 0.0f;
        float aim_x_before = 0.0f;
        float aim_y_before = 0.0f;
        std::uint32_t aim_aux0_before = 0;
        std::uint32_t aim_aux1_before = 0;
        std::uint8_t spread_before = 0;
        uintptr_t current_target_actor_before = 0;
        bool current_target_actor_override_active = false;
        uintptr_t selection_state_pointer = 0;
        int selection_state_before = kUnknownAnimationStateId;
        bool selection_state_object_snapshot_valid = false;
        std::array<std::uint8_t, 0x38> selection_state_object_snapshot = {};
        std::uint8_t selection_target_group_before = 0xFF;
        std::uint16_t selection_target_slot_before = 0xFFFF;
        std::int32_t selection_retarget_ticks_before = 0;
        std::int32_t selection_target_cooldown_before = 0;
        std::int32_t selection_target_extra_before = 0;
        std::int32_t selection_target_flags_before = 0;
        bool selection_target_seed_active = false;
        std::uint8_t selection_target_group_seed = 0xFF;
        std::uint16_t selection_target_slot_seed = 0xFFFF;
        std::int32_t selection_target_hold_ticks = 0;
        bool selection_brain_override_active = false;
        bool selection_state_override_active = false;
        int gameplay_selection_state_before = kUnknownAnimationStateId;
        bool gameplay_selection_state_override_active = false;
        uintptr_t progression_runtime_address = 0;
        std::int32_t progression_spell_id_before = 0;
        bool progression_spell_id_override_active = false;
        int ticks_waiting = 0;
        int startup_ticks_waiting = 0;
        int targetless_ticks_waiting = 0;
        bool saw_latch = false;
        bool saw_activity = false;
        bool startup_in_progress = false;
        bool requires_local_slot_native_tick = false;
        bool post_stock_dispatch_attempted = false;
        uintptr_t pure_primary_item_sink_fallback = 0;
        static constexpr int kMaxTicksWaiting = 300;
        static constexpr int kMaxStartupTicksWaiting = 12;
        // Lua retargets every 100 ms. Keep a live pure-primary action through
        // transient target handoffs instead of ending it and rearming a new cast.
        static constexpr int kTargetlessRetargetGraceTicks = kMaxStartupTicksWaiting * 2;
    };
    OngoingCastState ongoing_cast{};
};

struct LocalPlayerCastShimState {
    bool active = false;
    uintptr_t actor_address = 0;
    std::uint8_t saved_actor_slot = 0;
};

bool IsStandaloneWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::StandaloneWizard;
}

bool IsGameplaySlotWizardKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::GameplaySlotWizard;
}

bool IsRegisteredGameNpcKind(ParticipantEntityBinding::Kind kind) {
    return kind == ParticipantEntityBinding::Kind::RegisteredGameNpc;
}

bool IsWizardParticipantKind(ParticipantEntityBinding::Kind kind) {
    return IsStandaloneWizardKind(kind) || IsGameplaySlotWizardKind(kind) ||
           IsRegisteredGameNpcKind(kind);
}

struct SceneContextSnapshot {
    uintptr_t gameplay_scene_address = 0;
    uintptr_t world_address = 0;
    uintptr_t arena_address = 0;
    uintptr_t region_state_address = 0;
    int current_region_index = -1;
    int region_type_id = -1;
};

struct ParticipantRematerializationRequest {
    std::uint64_t bot_id = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    bool has_transform = false;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    uintptr_t previous_scene_address = 0;
    uintptr_t previous_world_address = 0;
    int previous_region_index = -1;
    uintptr_t next_scene_address = 0;
    uintptr_t next_world_address = 0;
    int next_region_index = -1;
};

struct ParticipantGameplaySnapshot {
    std::uint64_t bot_id = 0;
    bool entity_materialized = false;
    bool moving = false;
    int entity_kind = kSDModParticipantGameplayKindUnknown;
    std::uint64_t movement_intent_revision = 0;
    multiplayer::MultiplayerCharacterProfile character_profile;
    multiplayer::ParticipantSceneIntent scene_intent;
    uintptr_t actor_address = 0;
    uintptr_t world_address = 0;
    uintptr_t animation_state_ptr = 0;
    uintptr_t render_frame_table = 0;
    uintptr_t hub_visual_attachment_ptr = 0;
    uintptr_t hub_visual_proxy_address = 0;
    uintptr_t hub_visual_source_profile_address = 0;
    uintptr_t progression_handle_address = 0;
    uintptr_t equip_handle_address = 0;
    uintptr_t progression_runtime_state_address = 0;
    uintptr_t equip_runtime_state_address = 0;
    int gameplay_slot = -1;
    int actor_slot = -1;
    int slot_anim_state_index = -1;
    int resolved_animation_state_id = kUnknownAnimationStateId;
    int hub_visual_source_kind = 0;
    std::uint32_t hub_visual_descriptor_signature = 0;
    std::uint32_t render_drive_flags = 0;
    std::uint8_t anim_drive_state = 0;
    std::uint8_t no_interrupt = 0;
    std::uint8_t active_cast_group = 0xFF;
    std::uint16_t active_cast_slot = 0xFFFF;
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
    bool cast_active = false;
    bool cast_startup_in_progress = false;
    bool cast_saw_activity = false;
    std::int32_t cast_skill_id = 0;
    int cast_ticks_waiting = 0;
    uintptr_t cast_target_actor_address = 0;
    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    float hp = 0.0f;
    float max_hp = 0.0f;
    float mp = 0.0f;
    float max_mp = 0.0f;
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
    float render_advance_rate = 0.0f;
    float render_advance_phase = 0.0f;
    float render_drive_overlay_alpha = 0.0f;
    float render_drive_move_blend = 0.0f;
    bool gameplay_attach_applied = false;
    SDModEquipVisualLaneState primary_visual_lane;
    SDModEquipVisualLaneState secondary_visual_lane;
    SDModEquipVisualLaneState attachment_visual_lane;
};

SDModEquipVisualLaneState ReadEquipVisualLaneState(
    uintptr_t equip_runtime_state_address,
    std::size_t lane_offset) {
    SDModEquipVisualLaneState lane;
    if (equip_runtime_state_address == 0) {
        return lane;
    }

    auto& memory = ProcessMemory::Instance();
    lane.wrapper_address =
        memory.ReadFieldOr<uintptr_t>(equip_runtime_state_address, lane_offset, 0);
    if (lane.wrapper_address == 0) {
        return lane;
    }

    lane.holder_address = memory.ReadValueOr<uintptr_t>(lane.wrapper_address, 0);
    if (lane.holder_address == 0) {
        return lane;
    }

    lane.holder_kind =
        memory.ReadFieldOr<std::uint32_t>(lane.holder_address, kVisualLaneHolderKindOffset, 0);
    lane.current_object_address = memory.ReadFieldOr<uintptr_t>(
        lane.holder_address,
        kVisualLaneHolderCurrentObjectOffset,
        0);
    if (lane.current_object_address == 0) {
        return lane;
    }

    lane.current_object_vtable =
        memory.ReadValueOr<uintptr_t>(lane.current_object_address, 0);
    lane.current_object_type_id = memory.ReadFieldOr<std::uint32_t>(
        lane.current_object_address,
        kGameObjectTypeIdOffset,
        0);
    return lane;
}

void AppendEquipVisualLaneSummary(
    std::ostringstream* out,
    std::string_view label,
    const SDModEquipVisualLaneState& lane) {
    if (out == nullptr) {
        return;
    }

    *out << " " << label
         << "{wrapper=" << HexString(lane.wrapper_address)
         << " holder=" << HexString(lane.holder_address)
         << " kind=" << lane.holder_kind
         << " object=" << HexString(lane.current_object_address)
         << " vtbl=" << HexString(lane.current_object_vtable)
         << " type=0x" << HexString(static_cast<uintptr_t>(lane.current_object_type_id))
         << "}";
}

std::vector<ParticipantEntityBinding> g_participant_entities;
std::recursive_mutex g_participant_entities_mutex;
std::mutex g_wizard_bot_snapshot_mutex;
std::vector<ParticipantGameplaySnapshot> g_participant_gameplay_snapshots;
std::recursive_mutex g_gameplay_action_pump_mutex;
std::uint64_t g_last_wizard_bot_crash_summary_refresh_ms = 0;
std::uint64_t g_last_gameplay_hud_case100_log_ms = 0;
std::uint64_t g_gameplay_slot_hud_probe_until_ms = 0;
uintptr_t g_gameplay_slot_hud_probe_actor = 0;

ObservedActorAnimationDriveProfile g_observed_idle_animation_profile;
ObservedActorAnimationDriveProfile g_observed_moving_animation_profile;
bool g_local_player_animation_probe_has_last_position = false;
float g_local_player_animation_probe_last_x = 0.0f;
float g_local_player_animation_probe_last_y = 0.0f;

void AppendMovementControllerSummary(std::ostringstream* out, uintptr_t world_address) {
    if (out == nullptr || world_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto movement_controller_address = world_address + kActorOwnerMovementControllerOffset;
    const auto primary_count = memory.ReadFieldOr<std::int32_t>(movement_controller_address, 0x40, 0);
    const auto primary_list = memory.ReadFieldOr<uintptr_t>(movement_controller_address, 0x4C, 0);
    const auto secondary_count = memory.ReadFieldOr<std::int32_t>(movement_controller_address, 0x70, 0);
    const auto secondary_list = memory.ReadFieldOr<uintptr_t>(movement_controller_address, 0x7C, 0);

    *out << " movement{ctx=" << HexString(movement_controller_address)
         << " primary_count=" << primary_count
         << " primary_list=" << HexString(primary_list);

    if (primary_list != 0) {
        *out << " primary0=" << HexString(memory.ReadFieldOr<uintptr_t>(primary_list, 0x0, 0))
             << " primary1=" << HexString(memory.ReadFieldOr<uintptr_t>(primary_list, 0x4, 0));
    }

    *out << " secondary_count=" << secondary_count
         << " secondary_list=" << HexString(secondary_list);

    if (secondary_list != 0) {
        *out << " secondary0=" << HexString(memory.ReadFieldOr<uintptr_t>(secondary_list, 0x0, 0))
             << " secondary1=" << HexString(memory.ReadFieldOr<uintptr_t>(secondary_list, 0x4, 0));
    }

    *out << "}";
}

void AppendActorCoreStateSummary(std::ostringstream* out, uintptr_t actor_address) {
    if (out == nullptr || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    *out << " actor_core{cell=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x54, 0))
         << " owner_field=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x58, 0))
         << " slot=" << std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                -1)))
         << " world_slot=" << std::to_string(static_cast<int>(memory.ReadFieldOr<std::int16_t>(
                actor_address,
                kActorWorldSlotOffset,
                static_cast<std::int16_t>(-1))))
         << " radius=" << std::to_string(memory.ReadFieldOr<float>(actor_address, kActorCollisionRadiusOffset, 0.0f))
         << " mask=" << HexString(static_cast<uintptr_t>(memory.ReadFieldOr<std::uint32_t>(
                actor_address,
                kActorPrimaryFlagMaskOffset,
                0)))
         << " mask2=" << HexString(static_cast<uintptr_t>(memory.ReadFieldOr<std::uint32_t>(
                actor_address,
                kActorSecondaryFlagMaskOffset,
                0)))
         << "}";
}

void AppendGameNpcStateSummary(std::ostringstream* out, uintptr_t actor_address) {
    if (out == nullptr || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    *out << " gamenpc{source_kind=" << std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, 0x174, 0))
         << " source_profile=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x178, 0))
         << " source_aux=" << HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x17C, 0))
         << " branch=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x181, 0))
         << " active=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x180, 0))
         << " desired_yaw=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x188, 0.0f))
         << " source_profile_74_mirror=" << HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x194, 0))
         << " tick_counter=" << std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, 0x18C, 0))
         << " goal_x=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x19C, 0.0f))
         << " goal_y=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1A0, 0.0f))
         << " move_flag=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x198, 0))
         << " move_speed=" << std::to_string(memory.ReadFieldOr<float>(actor_address, 0x1B4, 0.0f))
         << " source_profile_56_mirror=" << HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x1C0, 0))
         << " tracked_slot=" << std::to_string(memory.ReadFieldOr<std::int8_t>(actor_address, 0x1C2, -1))
         << " callback=" << std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x1C3, 0))
         << " render_drive_effect_timer=" << std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, 0x1C4, 0))
         << "}";
}

std::string BuildWizardBotCrashSummaryLocked() {
    std::ostringstream out;
    out << "participant_snapshots count=" << g_participant_gameplay_snapshots.size()
        << " gameplay_injection_initialized="
        << (g_gameplay_keyboard_injection.initialized ? "true" : "false");
    for (const auto& snapshot : g_participant_gameplay_snapshots) {
        out << "\r\n"
            << "  bot_id=" << snapshot.bot_id
            << " element_id=" << snapshot.character_profile.element_id
            << " discipline_id=" << static_cast<std::int32_t>(snapshot.character_profile.discipline_id)
            << " materialized=" << (snapshot.entity_materialized ? "true" : "false")
            << " moving=" << (snapshot.moving ? "true" : "false")
            << " slot=" << snapshot.gameplay_slot
            << " actor_slot=" << snapshot.actor_slot
            << " actor=" << HexString(snapshot.actor_address)
            << " world=" << HexString(snapshot.world_address)
            << " progression=" << HexString(snapshot.progression_runtime_state_address)
            << " equip=" << HexString(snapshot.equip_runtime_state_address)
            << " source=" << HexString(snapshot.hub_visual_source_profile_address)
            << " attach=" << HexString(snapshot.hub_visual_attachment_ptr)
            << " variants="
            << std::to_string(snapshot.render_variant_primary) + "/" +
                   std::to_string(snapshot.render_variant_secondary) + "/" +
                   std::to_string(snapshot.render_weapon_type) + "/" +
                   std::to_string(snapshot.render_variant_tertiary) + "/" +
                   std::to_string(snapshot.render_selection_byte)
            << " anim=" << snapshot.resolved_animation_state_id
            << " desc=0x" << HexString(snapshot.hub_visual_descriptor_signature)
            << " pos=(" << snapshot.x << "," << snapshot.y << ")"
            << " heading=" << snapshot.heading;
        AppendEquipVisualLaneSummary(&out, "primary", snapshot.primary_visual_lane);
        AppendEquipVisualLaneSummary(&out, "secondary", snapshot.secondary_visual_lane);
        AppendEquipVisualLaneSummary(&out, "attachment", snapshot.attachment_visual_lane);
        AppendActorCoreStateSummary(&out, snapshot.actor_address);
        AppendGameNpcStateSummary(&out, snapshot.actor_address);
        AppendMovementControllerSummary(&out, snapshot.world_address);
    }
    return out.str();
}

void RefreshWizardBotCrashSummaryLocked() {
    SetCrashContextSummary(BuildWizardBotCrashSummaryLocked());
}

void PumpQueuedGameplayActions();
ParticipantEntityBinding* FindParticipantEntity(std::uint64_t participant_id);
ParticipantEntityBinding* FindParticipantEntityForGameplaySlot(int gameplay_slot);
void StopWizardBotActorMotion(uintptr_t actor_address);
void StopDeadWizardBotActorMotion(uintptr_t actor_address);
void StopRegisteredGameNpcMotion(ParticipantEntityBinding* binding);
void ApplyObservedBotAnimationState(ParticipantEntityBinding* binding, uintptr_t actor_address, bool moving);
void PublishParticipantGameplaySnapshot(const ParticipantEntityBinding& binding);
void RememberParticipantEntity(
    std::uint64_t bot_id,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    uintptr_t actor_address,
    ParticipantEntityBinding::Kind kind,
    int gameplay_slot,
    bool raw_allocation);
void ResetParticipantEntityMaterializationState(ParticipantEntityBinding* binding);
bool TryResolveLocalPlayerWorldContext(
    uintptr_t gameplay_address,
    uintptr_t* actor_address,
    uintptr_t* progression_address,
    uintptr_t* world_address);
uintptr_t ReadSmartPointerInnerObject(uintptr_t wrapper_address);
bool AssignActorSmartPointerWrapperSafe(
    uintptr_t actor_address,
    std::size_t wrapper_offset,
    std::size_t runtime_state_offset,
    uintptr_t source_wrapper_address,
    DWORD* exception_code);
bool RetainSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code);
bool ReleaseSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code);
bool CallPlayerActorEnsureProgressionHandleSafe(
    uintptr_t ensure_progression_handle_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallPlayerActorRefreshRuntimeHandlesSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallActorProgressionRefreshSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallSkillsWizardBuildPrimarySpellSafe(
    uintptr_t build_address,
    uintptr_t progression_address,
    float primary_entry_arg,
    float combo_entry_arg,
    DWORD* exception_code);
bool CallPlayerAppearanceApplyChoiceSafe(
    uintptr_t apply_choice_address,
    uintptr_t progression_address,
    int choice_id,
    int ensure_assets,
    DWORD* exception_code);
bool EnterLocalPlayerCastShim(
    const ParticipantEntityBinding* binding,
    LocalPlayerCastShimState* state);
void LeaveLocalPlayerCastShim(const LocalPlayerCastShimState& state);
bool CallGameNpcSetMoveGoalSafe(
    uintptr_t set_move_goal_address,
    uintptr_t npc_address,
    std::uint8_t mode,
    int follow_flag,
    float x,
    float y,
    float extra_scalar,
    DWORD* exception_code,
    SehExceptionDetails* exception_details);
bool CallGameNpcSetTrackedSlotAssistSafe(
    uintptr_t set_tracked_slot_assist_address,
    uintptr_t npc_address,
    int slot_index,
    int require_callback,
    DWORD* exception_code,
    SehExceptionDetails* exception_details);
bool CallGameplayActorAttachSafe(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallStandaloneWizardVisualLinkAttachSafe(
    uintptr_t attach_address,
    uintptr_t self_address,
    uintptr_t value_address,
    DWORD* exception_code);
bool CallGameObjectAllocateSafe(
    uintptr_t object_allocate_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code);
bool CallGameFreeSafe(
    uintptr_t free_address,
    uintptr_t allocation_address,
    DWORD* exception_code);
bool CallGameObjectFactorySafe(
    uintptr_t factory_address,
    uintptr_t factory_context_address,
    int type_id,
    uintptr_t* object_address,
    DWORD* exception_code);
bool CallGameOperatorNewSafe(
    uintptr_t operator_new_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code);
bool CallRawObjectCtorSafe(
    uintptr_t ctor_address,
    void* object_memory,
    uintptr_t* object_address,
    DWORD* exception_code);
bool CallPlayerActorCtorSafe(
    uintptr_t ctor_address,
    void* actor_memory,
    uintptr_t* actor_address,
    DWORD* exception_code);
bool PrimeStandaloneWizardProgressionSelectionState(
    uintptr_t progression_inner_address,
    int selection_state,
    std::string* error_message);
bool PrimeGameplaySlotBotSelectionState(
    uintptr_t actor_address,
    uintptr_t progression_address,
    int slot_index,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    std::string* error_message);
bool WireGameplaySlotBotRuntimeHandles(
    uintptr_t actor_address,
    std::string* error_message);
bool SeedGameplaySlotBotRenderStateFromSourceActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    std::string* error_message);
bool AttachGameplaySlotBotStaffItem(
    uintptr_t actor_address,
    std::string* error_message);
bool PrimeGameplaySlotBotActor(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t slot_progression_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    std::string* error_message);
bool PreparePendingGameplaySlotBotCast(ParticipantEntityBinding* binding, std::string* error_message);
bool CreateGameplaySlotBotActor(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    uintptr_t* actor_address,
    uintptr_t* progression_address,
    std::string* error_message);
bool FinalizeGameplaySlotBotRegistration(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    uintptr_t actor_address,
    ParticipantEntityBinding* binding,
    std::string* error_message);
bool DestroyLoaderOwnedWizardActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    bool raw_allocation,
    std::string* error_message);
bool DestroyRegisteredGameNpcActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string* error_message);
void DestroyParticipantEntityNow(std::uint64_t participant_id);

bool EnsureStandaloneWizardWorldOwner(
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string_view stage,
    std::string* error_message) {
    if (actor_address == 0 || world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone owner repair requires live actor and world addresses.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto current_owner = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    if (current_owner == world_address) {
        return true;
    }

    if (!memory.TryWriteField<uintptr_t>(actor_address, kActorOwnerOffset, world_address)) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to restore standalone actor owner after " + std::string(stage) + ".";
        }
        return false;
    }

    const auto repaired_owner = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    if (repaired_owner != world_address) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone actor owner repair did not stick after " + std::string(stage) + ".";
        }
        return false;
    }

    Log(
        "[bots] restored standalone owner after " + std::string(stage) +
        ". actor=" + HexString(actor_address) +
        " old_owner=" + HexString(current_owner) +
        " world=" + HexString(world_address));
    return true;
}

#include "mod_loader_gameplay/scene_and_animation.inl"
#include "mod_loader_gameplay/standalone_materialization.inl"
#include "mod_loader_gameplay/bot_pathfinding.inl"
#include "mod_loader_gameplay/bot_registry_and_movement.inl"
#include "mod_loader_gameplay/dispatch_and_hooks.inl"

}  // namespace

#include "mod_loader_gameplay/public_api.inl"

}  // namespace sdmod
