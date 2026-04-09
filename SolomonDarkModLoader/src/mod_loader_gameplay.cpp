#include "bot_runtime.h"
#include "d3d9_end_scene_hook.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "x86_hook.h"

#include <Windows.h>
#include <d3d9.h>

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
#include <mutex>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

using GameplayKeyboardEdgeFn = std::uint8_t(__thiscall*)(void* self, std::uint32_t scancode);
using GameplayMouseRefreshFn = void(__fastcall*)(void* self, void* unused_edx);
using PlayerActorTickFn = void(__thiscall*)(void* self);
using GameplaySwitchRegionFn = void(__thiscall*)(void* self, int region_index);
using ArenaStartWavesFn = void(__thiscall*)(void* self);
using GameplayCreatePlayerSlotFn = void(__thiscall*)(void* self, int slot_index);
using PlayerActorCtorFn = void*(__thiscall*)(void* self);
using RawObjectCtorFn = void*(__thiscall*)(void* self);
using GameObjectAllocateFn = void*(__cdecl*)(std::size_t size);
using GameObjectFactoryFn = uintptr_t(__thiscall*)(void* self, int type_id);
using GameOperatorNewFn = void*(__cdecl*)(std::size_t size);
using ActorWorldRegisterFn = std::uint32_t(__thiscall*)(void* self, int actor_group, void* actor, int slot_index, char use_alt_list);
using ActorWorldUnregisterFn = void(__thiscall*)(void* self, void* actor, char remove_from_container);
using PlayerActorMoveStepFn = std::uint32_t(__thiscall*)(void* self, void* actor, float move_x, float move_y, int flags);
using ActorMoveByDeltaFn = void(__thiscall*)(void* self, float move_x, float move_y, int flags);
using ActorAnimationAdvanceFn = void(__thiscall*)(void* self);
using PlayerActorRefreshRuntimeHandlesFn = void(__thiscall*)(void* self);
using ActorProgressionRefreshFn = void(__thiscall*)(void* self);
using GameplayActorAttachFn = void(__thiscall*)(void* self, void* actor);
using StandaloneWizardVisualLinkAttachFn = std::uint8_t(__thiscall*)(void* self, void* value);
using ActorRefreshVisualStateFn = void(__thiscall*)(void* self);
using ActorBuildRenderDescriptorFromSourceFn = void(__thiscall*)(void* self);
using ScalarDeletingDestructorFn = void(__thiscall*)(void* self, int flags);
using SpawnRewardGoldFn = void(__thiscall*)(void* self, std::uint32_t x_bits, std::uint32_t y_bits, int amount, int lifetime);
using EnemyConfigCtorFn = void(__thiscall*)(void* self);
using EnemyConfigDtorFn = void(__thiscall*)(void* self);
using EnemyConfigBuildFn = void(__thiscall*)(void* self, int type_id, int variant, void* config_buffer, void* modifier_list);
using EnemySpawnFn =
    void* (__thiscall*)(void* self, void* spawn_anchor, void* enemy_config, int spawn_mode, int param_5, int param_6, char allow_override);
using GameFreeFn = void(__cdecl*)(void* memory);

bool CallActorWorldUnregisterSafe(
    uintptr_t actor_world_unregister_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    char remove_from_container,
    DWORD* exception_code);
bool CallActorBuildRenderDescriptorFromSourceSafe(
    uintptr_t build_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallScalarDeletingDestructorSafe(
    uintptr_t object_address,
    int flags,
    DWORD* exception_code);

constexpr uintptr_t kGameplayMouseRefreshHelper = 0x00429820;
constexpr std::size_t kGameplayMouseRefreshHookPatchSize = 8;
constexpr uintptr_t kGameplayKeyboardEdgeHelper = 0x00429950;
constexpr std::size_t kGameplayKeyboardEdgeHookPatchSize = 9;
constexpr uintptr_t kPlayerActorTick = 0x00548B00;
constexpr std::size_t kPlayerActorTickHookPatchSize = 6;
constexpr uintptr_t kMenuKeybindingGlobal = 0x00B3BCCC;
constexpr uintptr_t kInventoryKeybindingGlobal = 0x00B3BCC4;
constexpr uintptr_t kSkillsKeybindingGlobal = 0x00B3BCC8;
constexpr std::array<uintptr_t, 8> kBeltSlotKeybindingGlobals = {
    0x00B3BCD0,
    0x00B3BCD4,
    0x00B3BCD8,
    0x00B3BCDC,
    0x00B3BCE0,
    0x00B3BCE4,
    0x00B3BCE8,
    0x00B3BCEC,
};
constexpr uintptr_t kGameObjectGlobal = 0x0081C264;
constexpr uintptr_t kArenaGlobal = 0x00819844;
constexpr uintptr_t kEnemyCountGlobal = 0x0081984C;
constexpr uintptr_t kGoldGlobal = 0x0081A388;
constexpr uintptr_t kTransitionTargetAGlobal = 0x0080807C;
constexpr uintptr_t kTransitionTargetBGlobal = 0x00808080;
constexpr uintptr_t kPendingLevelKindGlobal = 0x00B3BEDC;
constexpr uintptr_t kGameplaySwitchRegion = 0x005CDDD0;
constexpr uintptr_t kGameplayCreatePlayerSlot = 0x005CB870;
constexpr uintptr_t kObjectAllocate = 0x00402030;
constexpr uintptr_t kGameObjectFactory = 0x005B7080;
constexpr uintptr_t kGameObjectFactoryContextGlobal = 0x0081F630;
constexpr uintptr_t kPlayerActorCtor = 0x0052B4C0;
constexpr uintptr_t kStandaloneWizardVisualRuntimeCtor = 0x00674EE0;
constexpr uintptr_t kStandaloneWizardVisualLinkPrimaryCtor = 0x00461F70;
constexpr uintptr_t kStandaloneWizardVisualLinkSecondaryCtor = 0x00461ED0;
constexpr uintptr_t kStandaloneWizardVisualLinkAttach = 0x00575850;
constexpr uintptr_t kActorBuildRenderDescriptorFromSource = 0x005E3080;
constexpr uintptr_t kPlayerActorMoveStep = 0x00525800;
constexpr uintptr_t kActorMoveByDelta = 0x00623C60;
constexpr uintptr_t kActorAnimationAdvance = 0x0054BA80;
constexpr uintptr_t kGameplayIndexStateTableGlobal = 0x00819E84;
constexpr uintptr_t kGameplayIndexStateCountGlobal = 0x00819E88;
constexpr uintptr_t kLocalPlayerActorGlobal = 0x0081D5BC;
constexpr uintptr_t kActorWorldRegister = 0x0063F6D0;
constexpr uintptr_t kActorWorldUnregister = 0x0063F600;
constexpr uintptr_t kActorProgressionRefresh = 0x0065F9A0;
constexpr uintptr_t kPlayerActorRefreshRuntimeHandles = 0x0052A370;
constexpr uintptr_t kStandaloneWizardEquipCtor = 0x00552FB0;
constexpr uintptr_t kArenaStartRunDispatch = 0x0063F460;
constexpr uintptr_t kArenaCreate = 0x0046EA90;
constexpr uintptr_t kArenaStartWaves = 0x00465C00;
constexpr uintptr_t kSpawnRewardGold = 0x0046AA90;
constexpr uintptr_t kEnemyConfigCtor = 0x006400C0;
constexpr uintptr_t kEnemyConfigDtor = 0x00463A80;
constexpr uintptr_t kBuildEnemyConfig = 0x0046B390;
constexpr uintptr_t kSpawnEnemy = 0x00469580;
constexpr uintptr_t kGameFree = 0x0074734B;
constexpr uintptr_t kGameOperatorNew = 0x0074784D;
constexpr uintptr_t kEnemyModifierListVtable = 0x007848EC;
constexpr int kArenaRegionIndex = 5;
constexpr std::size_t kStandaloneWizardVisualRuntimeSize = 0x8E4;
constexpr std::size_t kStandaloneWizardVisualLinkSize = 0xA8;
constexpr int kStandaloneWizardHiddenSelectionState = -2;
constexpr std::size_t kStandaloneWizardProgressionTableBaseOffset = 0x20;
constexpr std::size_t kStandaloneWizardProgressionTableCountOffset = 0x24;
constexpr std::size_t kStandaloneWizardProgressionEntryStride = 0x70;
constexpr std::size_t kStandaloneWizardProgressionActiveFlagOffset = 0x20;
constexpr std::size_t kStandaloneWizardProgressionVisibleFlagOffset = 0x22;
constexpr std::size_t kStandaloneWizardProgressionRefreshModeOffset = 0x14;
constexpr std::size_t kGameplayTestrunModeFlagOffset = 0x1BB4;
constexpr std::size_t kGameplayCastIntentOffset = 0x1E4;
constexpr std::size_t kGameplayRegionTableOffset = 0x133C;
constexpr std::size_t kGameplayRegionStride = 4;
constexpr std::size_t kGameplayPlayerActorOffset = 0x1358;
constexpr std::size_t kGameplayPlayerSlotStride = 4;
constexpr std::size_t kGameplayPlayerSlotCount = 4;
constexpr int kStandaloneWizardVisualSlotBase = 1;
constexpr int kStandaloneWizardVisualSlotMax =
    static_cast<int>(kGameplayPlayerSlotCount) - 1;
constexpr int kWizardProgressionFactoryTypeId = 0x0BBB;
constexpr std::size_t kPlayerActorSize = 0x398;
constexpr std::size_t kStandaloneWizardEquipSize = 100;
constexpr std::size_t kGameplayPlayerFallbackPositionOffset = 0x1368;
constexpr std::size_t kGameplayPlayerFallbackPositionStride = 8;
constexpr std::size_t kGameplayPlayerProgressionHandleOffset = 0x1654;
constexpr std::size_t kRegionObjectTypeIdOffset = 0x08;
constexpr std::size_t kActorOwnerOffset = 0x58;
constexpr std::size_t kActorSlotOffset = 0x5C;
constexpr std::size_t kActorPositionXOffset = 0x18;
constexpr std::size_t kActorPositionYOffset = 0x1C;
constexpr std::size_t kActorUnknownResetOffset = 0x38;
constexpr std::size_t kActorPrimaryFlagMaskOffset = 0x38;
constexpr std::size_t kActorSecondaryFlagMaskOffset = 0x3C;
constexpr std::size_t kActorHeadingOffset = 0x6C;
constexpr std::size_t kActorMoveSpeedScaleOffset = 0x74;
constexpr std::size_t kActorRenderDriveFlagsOffset = 0x138;
constexpr std::size_t kActorMovementSpeedMultiplierOffset = 0x120;
constexpr std::size_t kActorAnimationConfigBlockOffset = 0x158;
constexpr std::size_t kActorAnimationConfigBlockSize = 0x0C;
constexpr std::size_t kActorAnimationDriveParameterOffset = 0x15C;
constexpr std::size_t kActorMoveStepScaleOffset = 0x218;
constexpr std::size_t kActorAnimationDriveStateByteOffset = 0x160;
constexpr std::size_t kActorRegisteredSlotMirrorOffset = 0x164;
constexpr std::size_t kActorRegisteredSlotIdMirrorOffset = 0x166;
constexpr std::size_t kActorAnimationMoveDurationTicksOffset = 0x1BC;
constexpr std::size_t kActorHubVisualSourceKindOffset = 0x174;
constexpr std::size_t kActorHubVisualSourceProfileOffset = 0x178;
constexpr std::size_t kActorWalkCyclePrimaryOffset = 0x220;
constexpr std::size_t kActorWalkCycleSecondaryOffset = 0x224;
constexpr std::size_t kActorRenderDriveStrideScaleOffset = 0x228;
constexpr std::size_t kActorRenderDriveOverlayAlphaOffset = 0x248;
constexpr std::size_t kActorRenderDriveMoveBlendOffset = 0x268;
constexpr std::size_t kActorRenderDriveEffectTimerOffset = 0x1C4;
constexpr std::size_t kActorRenderDriveEffectProgressOffset = 0x1D0;
constexpr std::size_t kActorRenderDriveIdleBobOffset = 0x1F0;
constexpr std::size_t kActorEquipRuntimeStateOffset = 0x1FC;
constexpr std::size_t kActorProgressionRuntimeStateOffset = 0x200;
constexpr std::size_t kActorAnimationSelectionStateOffset = 0x21C;
constexpr std::size_t kActorControlBrainTargetSlotOffset = 0x04;
constexpr std::size_t kActorControlBrainTargetHandleOffset = 0x06;
constexpr std::size_t kActorControlBrainRetargetTicksOffset = 0x08;
constexpr std::size_t kActorControlBrainActionCooldownTicksOffset = 0x10;
constexpr std::size_t kActorControlBrainActionBurstTicksOffset = 0x14;
constexpr std::size_t kActorControlBrainHeadingLockTicksOffset = 0x18;
constexpr std::size_t kActorControlBrainHeadingAccumulatorOffset = 0x1C;
constexpr std::size_t kActorControlBrainPursuitRangeOffset = 0x20;
constexpr std::size_t kActorControlBrainFollowLeaderOffset = 0x24;
constexpr std::size_t kActorControlBrainDesiredFacingOffset = 0x28;
constexpr std::size_t kActorControlBrainDesiredFacingSmoothedOffset = 0x2C;
constexpr std::size_t kActorControlBrainMoveInputXOffset = 0x30;
constexpr std::size_t kActorControlBrainMoveInputYOffset = 0x34;
constexpr std::size_t kActorProgressionHandleOffset = 0x300;
constexpr std::size_t kActorEquipHandleOffset = 0x304;
constexpr std::size_t kActorSpatialHandleOffset = 0x27E;
constexpr std::size_t kActorRenderFrameTableOffset = 0x22C;
constexpr std::size_t kActorRenderAdvanceRateOffset = 0x234;
constexpr std::size_t kActorRenderAdvancePhaseOffset = 0x238;
constexpr std::size_t kActorRenderVariantPrimaryOffset = 0x23C;
constexpr std::size_t kActorRenderVariantSecondaryOffset = 0x23D;
constexpr std::size_t kActorRenderWeaponTypeOffset = 0x23E;
constexpr std::size_t kActorRenderSelectionByteOffset = 0x23F;
constexpr std::size_t kActorRenderVariantTertiaryOffset = 0x240;
constexpr std::size_t kActorHubVisualDescriptorBlockOffset = 0x244;
constexpr std::size_t kActorHubVisualDescriptorBlockSize = 0x20;
constexpr std::size_t kActorHubVisualAttachmentPtrOffset = 0x264;
constexpr std::size_t kStandaloneWizardVisualLinkResetOffset = 0x1C;
constexpr std::size_t kStandaloneWizardVisualLinkActiveByteOffset = 0x58;
constexpr std::size_t kStandaloneWizardVisualLinkDescriptorBlockOffset = 0x88;
constexpr std::size_t kActorEquipRuntimeVisualLinkPrimaryOffset = 0x1C;
constexpr std::size_t kActorEquipRuntimeVisualLinkSecondaryOffset = 0x18;
constexpr std::size_t kActorEquipRuntimeVisualLinkAttachmentOffset = 0x30;
constexpr std::size_t kActorRenderStateWindowOffset = kActorRenderDriveFlagsOffset;
constexpr std::size_t kActorRenderStateWindowEndExclusive = kActorHubVisualAttachmentPtrOffset + sizeof(uintptr_t);
constexpr std::size_t kActorRenderStateWindowSize =
    kActorRenderStateWindowEndExclusive - kActorRenderStateWindowOffset;
constexpr int kActorAnimationStateSlotBias = 0x0C;
constexpr int kUnknownAnimationStateId = -1;
constexpr std::size_t kGameplayInputBufferIndexOffset = 0x480;
constexpr std::size_t kGameplayActorAttachSubobjectOffset = 0x1388;
constexpr std::size_t kGameplayInputBufferStride = 0x203;
constexpr std::size_t kGameplayMouseLeftButtonOffset = 0x279;
constexpr std::size_t kArenaCombatSectionIndexOffset = 0x8FEC;
constexpr std::size_t kArenaCombatWaveIndexOffset = 0x8FF0;
constexpr std::size_t kArenaCombatWaitTicksOffset = 0x8FF4;
constexpr std::size_t kArenaCombatAdvanceModeOffset = 0x8FF8;
constexpr std::size_t kArenaCombatAdvanceThresholdOffset = 0x8FFC;
constexpr std::size_t kArenaCombatStartedMusicOffset = 0x8F14;
constexpr std::size_t kArenaCombatTransitionRequestedOffset = 0x902A;
constexpr std::size_t kArenaCombatWaveCounterOffset = 0x88;
constexpr std::size_t kArenaCombatActiveFlagOffset = 0x872C;
constexpr std::size_t kProgressionLevelOffset = 0x30;
constexpr std::size_t kProgressionXpOffset = 0x34;
constexpr std::size_t kProgressionHpOffset = 0x70;
constexpr std::size_t kProgressionMaxHpOffset = 0x74;
constexpr std::size_t kProgressionMpOffset = 0x7C;
constexpr std::size_t kProgressionMaxMpOffset = 0x80;
constexpr std::size_t kProgressionMoveSpeedOffset = 0x90;
constexpr std::size_t kActorOwnerMovementControllerOffset = 0x378;
constexpr uintptr_t kActorWalkCyclePrimaryDivisorGlobal = 0x007DE810;
constexpr uintptr_t kActorWalkCycleSecondaryDivisorGlobal = 0x007DE960;
constexpr uintptr_t kActorWalkCyclePrimaryWrapThresholdGlobal = 0x007DE970;
constexpr uintptr_t kActorWalkCycleSecondaryWrapThresholdGlobal = 0x007849F8;
constexpr uintptr_t kActorWalkCycleStrideStepGlobal = 0x007DE8D8;
constexpr uintptr_t kActorWalkCycleSecondaryWrapStepGlobal = 0x007DE8C8;
constexpr std::uint64_t kWaveStartRetryDelayMs = 250;
constexpr std::uint64_t kWizardBotSyncRetryDelayMs = 250;
constexpr std::uint64_t kWizardBotSyncDispatchSpacingMs = 500;
constexpr std::uint64_t kGameplayRegionSwitchRetryDelayMs = 250;
constexpr std::uint64_t kGameplayRegionSwitchDispatchSpacingMs = 500;
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
constexpr uintptr_t kMovementDirectionScaleGlobal = 0x007848B0;
constexpr uintptr_t kMovementSpeedScalarGlobal = 0x00784740;
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
constexpr std::size_t kSourceProfileVisualSourceTypeOffset = 0x4C;
constexpr std::size_t kSourceProfileUnknown56Offset = 0x56;
constexpr std::size_t kSourceProfileUnknown74Offset = 0x74;
constexpr std::size_t kSourceProfileVariantPrimaryOffset = 0x9C;
constexpr std::size_t kSourceProfileVariantSecondaryOffset = 0x9D;
constexpr std::size_t kSourceProfileRenderSelectionOffset = 0xA0;
constexpr std::size_t kSourceProfileWeaponTypeOffset = 0xA4;
constexpr std::size_t kSourceProfileVariantTertiaryOffset = 0xA8;
constexpr std::size_t kSourceProfileDescriptorCheckFloat1Offset = 0xC0;
constexpr std::size_t kSourceProfileDescriptorCheckFloat2Offset = 0xD0;
constexpr std::int32_t kStandaloneWizardVisualSourceKind = 3;

struct WizardVisualProfile {
    std::uint8_t render_selection;    // wizard type index (0-4)
    std::int8_t  variant_primary;     // robe color (0-4)
    std::int8_t  variant_secondary;   // secondary variant (0-4)
    std::int8_t  weapon_type;         // 1=staff, 2=wand
    std::uint8_t variant_tertiary;    // tertiary variant
};

// Approximate mapping — render_selection is the critical field that picks
// the sprite atlas entry.  The variant bytes tint/shade/accessorize.
// weapon_type 1 = staff, 2 = wand.
constexpr WizardVisualProfile kWizardVisualProfiles[] = {
    {0, 0, 0, 1, 0},   // wizard 0
    {1, 1, 1, 1, 0},   // wizard 1
    {2, 2, 2, 1, 0},   // wizard 2
    {3, 3, 3, 2, 0},   // wizard 3
    {4, 4, 0, 1, 1},   // wizard 4
};
constexpr int kWizardVisualProfileCount =
    static_cast<int>(sizeof(kWizardVisualProfiles) / sizeof(kWizardVisualProfiles[0]));

uintptr_t CreateSyntheticWizardSourceProfile(int wizard_id) {
    const auto& profile = kWizardVisualProfiles[
        (wizard_id >= 0 && wizard_id < kWizardVisualProfileCount) ? wizard_id : 0];

    auto* buffer = static_cast<std::uint8_t*>(_aligned_malloc(kSyntheticSourceProfileSize, 16));
    if (buffer == nullptr) {
        return 0;
    }
    std::memset(buffer, 0, kSyntheticSourceProfileSize);

    // +0x4C must be 3 or FUN_005E3080 returns early
    *reinterpret_cast<std::int32_t*>(buffer + kSourceProfileVisualSourceTypeOffset) =
        kStandaloneWizardVisualSourceKind;

    // Variant bytes that drive robe color, weapon, atlas selection
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantPrimaryOffset) = profile.variant_primary;
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileVariantSecondaryOffset) = profile.variant_secondary;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileRenderSelectionOffset) = profile.render_selection;
    *reinterpret_cast<std::int8_t*>(buffer + kSourceProfileWeaponTypeOffset) = profile.weapon_type;
    *reinterpret_cast<std::uint8_t*>(buffer + kSourceProfileVariantTertiaryOffset) = profile.variant_tertiary;

    // Non-zero floats required by the descriptor generation branch
    *reinterpret_cast<float*>(buffer + kSourceProfileDescriptorCheckFloat1Offset) = 1.0f;
    *reinterpret_cast<float*>(buffer + kSourceProfileDescriptorCheckFloat2Offset) = 1.0f;

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

struct PendingWizardBotSyncRequest {
    std::uint64_t bot_id = 0;
    std::int32_t wizard_id = 0;
    bool has_transform = false;
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
    bool initialized = false;
    std::array<std::atomic<std::uint32_t>, 256> pending_scancodes{};
    std::atomic<bool> last_observed_mouse_left_down{false};
    std::atomic<std::uint64_t> mouse_left_edge_serial{0};
    std::atomic<std::uint64_t> mouse_left_edge_tick_ms{0};
    std::atomic<std::uint32_t> pending_mouse_left_edge_events{0};
    std::atomic<std::uint32_t> pending_mouse_left_frames{0};
    std::atomic<std::uint32_t> pending_hub_start_testrun_requests{0};
    std::atomic<std::uint32_t> pending_start_waves_requests{0};
    std::atomic<std::uint64_t> hub_start_testrun_cooldown_until_ms{0};
    std::atomic<std::uint64_t> start_waves_retry_not_before_ms{0};
    std::atomic<std::uint64_t> wizard_bot_sync_not_before_ms{0};
    std::atomic<std::uint64_t> gameplay_region_switch_not_before_ms{0};
    std::mutex pending_gameplay_world_actions_mutex;
    std::deque<PendingEnemySpawnRequest> pending_enemy_spawn_requests;
    std::deque<PendingRewardSpawnRequest> pending_reward_spawn_requests;
    std::deque<PendingWizardBotSyncRequest> pending_wizard_bot_sync_requests;
    std::deque<PendingGameplayRegionSwitchRequest> pending_gameplay_region_switch_requests;
    std::deque<std::uint64_t> pending_wizard_bot_destroy_requests;
} g_gameplay_keyboard_injection;

struct BotEntityBinding {
    enum class Kind : std::uint8_t {
        PlaceholderEnemy = 0,
        StandaloneWizard = 1,
    };

    std::uint64_t bot_id = 0;
    std::int32_t wizard_id = 0;
    uintptr_t actor_address = 0;
    int gameplay_slot = -1;
    Kind kind = Kind::PlaceholderEnemy;
    multiplayer::BotControllerState controller_state = multiplayer::BotControllerState::Idle;
    bool movement_active = false;
    bool has_target = false;
    float direction_x = 0.0f;
    float direction_y = 0.0f;
    bool desired_heading_valid = false;
    float desired_heading = 0.0f;
    float target_x = 0.0f;
    float target_y = 0.0f;
    float distance_to_target = 0.0f;
    std::uint64_t last_movement_log_ms = 0;
    std::uint64_t next_scene_materialize_retry_ms = 0;
    int home_region_index = -1;
    int home_region_type_id = -1;
    uintptr_t materialized_scene_address = 0;
    uintptr_t materialized_world_address = 0;
    int materialized_region_index = -1;
    int last_applied_animation_state_id = kUnknownAnimationStateId - 1;
    uintptr_t standalone_progression_wrapper_address = 0;
    uintptr_t standalone_progression_inner_address = 0;
    uintptr_t standalone_equip_wrapper_address = 0;
    uintptr_t standalone_equip_inner_address = 0;
    bool gameplay_attach_applied = false;
    bool raw_allocation = false;
    uintptr_t synthetic_source_profile_address = 0;
};

struct SceneContextSnapshot {
    uintptr_t gameplay_scene_address = 0;
    uintptr_t world_address = 0;
    uintptr_t arena_address = 0;
    uintptr_t region_state_address = 0;
    int current_region_index = -1;
    int region_type_id = -1;
};

struct BotRematerializationRequest {
    std::uint64_t bot_id = 0;
    std::int32_t wizard_id = 0;
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

struct WizardBotGameplaySnapshot {
    std::uint64_t bot_id = 0;
    bool entity_materialized = false;
    bool moving = false;
    std::int32_t wizard_id = 0;
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
    std::uint8_t render_variant_primary = 0;
    std::uint8_t render_variant_secondary = 0;
    std::uint8_t render_weapon_type = 0;
    std::uint8_t render_selection_byte = 0;
    std::uint8_t render_variant_tertiary = 0;
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
};

std::vector<BotEntityBinding> g_bot_entities;
std::recursive_mutex g_bot_entities_mutex;
std::mutex g_wizard_bot_snapshot_mutex;
std::vector<WizardBotGameplaySnapshot> g_wizard_bot_gameplay_snapshots;
std::recursive_mutex g_gameplay_action_pump_mutex;
int g_observed_idle_animation_state_id = kUnknownAnimationStateId;
int g_observed_moving_animation_state_id = kUnknownAnimationStateId;

struct ObservedActorAnimationDriveProfile {
    bool valid = false;
    std::array<std::uint8_t, kActorAnimationConfigBlockSize> config_bytes{};
    float walk_cycle_primary = 0.0f;
    float walk_cycle_secondary = 0.0f;
    float render_drive_stride = 0.0f;
};

ObservedActorAnimationDriveProfile g_observed_idle_animation_profile;
ObservedActorAnimationDriveProfile g_observed_moving_animation_profile;

void PumpQueuedGameplayActions();
BotEntityBinding* FindBotEntity(std::uint64_t bot_id);
BotEntityBinding* FindBotEntityForGameplaySlot(int gameplay_slot);
void StopWizardBotActorMotion(uintptr_t actor_address);
void PublishWizardBotGameplaySnapshot(const BotEntityBinding& binding);
void RememberBotEntity(
    std::uint64_t bot_id,
    std::int32_t wizard_id,
    uintptr_t actor_address,
    BotEntityBinding::Kind kind,
    int gameplay_slot,
    bool raw_allocation);
void ResetBotEntityMaterializationState(BotEntityBinding* binding);
bool TryResolveLocalPlayerWorldContext(
    uintptr_t gameplay_address,
    uintptr_t* actor_address,
    uintptr_t* progression_address,
    uintptr_t* world_address);
bool AssignActorSmartPointerWrapperSafe(
    uintptr_t actor_address,
    std::size_t wrapper_offset,
    std::size_t runtime_state_offset,
    uintptr_t source_wrapper_address,
    DWORD* exception_code);
bool ReleaseSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code);
bool CallPlayerActorRefreshRuntimeHandlesSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallActorProgressionRefreshSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallGameplayActorAttachSafe(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    DWORD* exception_code);
bool CallActorRefreshVisualStateSafe(uintptr_t actor_address, DWORD* exception_code);
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
bool CallGameObjectFactorySafe(
    uintptr_t factory_address,
    uintptr_t factory_self_address,
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
bool TryResolveStandaloneWizardVisualLinkObjects(
    uintptr_t actor_address,
    uintptr_t* primary_visual_link_address,
    uintptr_t* secondary_visual_link_address,
    uintptr_t* attachment_visual_link_address);
uintptr_t ResolveStandaloneWizardVisualDonorActor(
    uintptr_t gameplay_address,
    uintptr_t slot0_actor_address);
bool PrimeWizardActorResolvedRenderStateFromActor(
    uintptr_t donor_actor_address,
    uintptr_t bot_actor_address,
    std::string* error_message);
bool PrimeWizardActorRenderDescriptorFromActor(
    uintptr_t donor_actor_address,
    uintptr_t bot_actor_address,
    std::string* error_message);
uintptr_t ResolveIndirectPointerMember(uintptr_t object_address, std::size_t pointer_offset);
bool DestroyLoaderOwnedWizardActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    bool raw_allocation,
    std::string* error_message);
void DestroyWizardBotEntityNow(std::uint64_t bot_id);

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

void RecordGameplayMouseLeftEdge() {
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(
        static_cast<std::uint64_t>(GetTickCount64()),
        std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.fetch_add(1, std::memory_order_acq_rel);
}

std::string NormalizeInjectedKeyName(std::string_view value) {
    std::string normalized;
    normalized.reserve(value.size());
    for (char raw : value) {
        const auto ch = static_cast<unsigned char>(raw);
        if (std::isspace(ch) || ch == '_' || ch == '-') {
            continue;
        }
        normalized.push_back(static_cast<char>(std::tolower(ch)));
    }
    return normalized;
}

bool TryResolveInjectedBindingGlobal(std::string_view binding_name, uintptr_t* absolute_global) {
    if (absolute_global == nullptr) {
        return false;
    }

    const auto normalized = NormalizeInjectedKeyName(binding_name);
    if (normalized == "menu" || normalized == "pause" || normalized == "escape") {
        *absolute_global = kMenuKeybindingGlobal;
        return true;
    }
    if (normalized == "inventory" || normalized == "inv") {
        *absolute_global = kInventoryKeybindingGlobal;
        return true;
    }
    if (normalized == "skills" || normalized == "skill") {
        *absolute_global = kSkillsKeybindingGlobal;
        return true;
    }
    if (normalized.size() == 9 && normalized.rfind("beltslot", 0) == 0) {
        const auto slot_char = normalized[8];
        if (slot_char >= '1' && slot_char <= '8') {
            *absolute_global = kBeltSlotKeybindingGlobals[static_cast<std::size_t>(slot_char - '1')];
            return true;
        }
    }
    if (normalized.size() == 5 && normalized.rfind("slot", 0) == 0) {
        const auto slot_char = normalized[4];
        if (slot_char >= '1' && slot_char <= '8') {
            *absolute_global = kBeltSlotKeybindingGlobals[static_cast<std::size_t>(slot_char - '1')];
            return true;
        }
    }

    return false;
}

bool TryReadInjectedBindingCode(uintptr_t absolute_global, std::uint32_t* raw_binding_code) {
    if (raw_binding_code == nullptr) {
        return false;
    }

    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_global);
    if (resolved == 0) {
        return false;
    }

    std::uint32_t raw = 0;
    if (!ProcessMemory::Instance().TryReadValue(resolved, &raw)) {
        return false;
    }

    *raw_binding_code = raw;
    return true;
}

bool TryReadResolvedGamePointerAbsolute(uintptr_t absolute_address, uintptr_t* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0;
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return resolved != 0 && ProcessMemory::Instance().TryReadValue(resolved, value);
}

bool TryResolveCurrentGameplayScene(uintptr_t* scene_address) {
    if (scene_address == nullptr) {
        return false;
    }

    *scene_address = 0;
    return TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, scene_address) && *scene_address != 0;
}

bool TryResolveArena(uintptr_t* arena_address) {
    if (arena_address == nullptr) {
        return false;
    }

    *arena_address = 0;
    return TryReadResolvedGamePointerAbsolute(kArenaGlobal, arena_address) && *arena_address != 0;
}

int ReadResolvedGlobalIntOr(uintptr_t absolute_address, int fallback = 0) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(absolute_address);
    return ProcessMemory::Instance().ReadValueOr<int>(resolved, fallback);
}

bool TryResolveGameplayIndexState(uintptr_t* table_address, int* entry_count) {
    if (table_address != nullptr) {
        *table_address = 0;
    }
    if (entry_count != nullptr) {
        *entry_count = 0;
    }

    uintptr_t resolved_table_address = 0;
    if (!TryReadResolvedGamePointerAbsolute(kGameplayIndexStateTableGlobal, &resolved_table_address) ||
        resolved_table_address == 0) {
        return false;
    }

    const auto resolved_entry_count = ReadResolvedGlobalIntOr(kGameplayIndexStateCountGlobal, 0);
    if (resolved_entry_count <= 0) {
        return false;
    }

    if (table_address != nullptr) {
        *table_address = resolved_table_address;
    }
    if (entry_count != nullptr) {
        *entry_count = resolved_entry_count;
    }
    return true;
}

bool TryReadGameplayIndexStateValue(int index, int* value) {
    if (value == nullptr || index < 0) {
        return false;
    }

    *value = 0;
    uintptr_t table_address = 0;
    int entry_count = 0;
    if (!TryResolveGameplayIndexState(&table_address, &entry_count) || table_address == 0 || index >= entry_count) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadValue(table_address + static_cast<uintptr_t>(index) * sizeof(int), value);
}

bool TryResolveGameplayRegionObject(uintptr_t gameplay_address, int region_index, uintptr_t* region_address) {
    if (region_address == nullptr || gameplay_address == 0 || region_index < 0 ||
        region_index >= static_cast<int>(kGameplayPlayerSlotCount + 2)) {
        return false;
    }

    *region_address = 0;
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               gameplay_address,
               kGameplayRegionTableOffset + static_cast<std::size_t>(region_index) * kGameplayRegionStride,
               region_address) &&
           *region_address != 0;
}

bool TryReadGameplayRegionTypeId(uintptr_t gameplay_address, int region_index, int* region_type_id) {
    if (region_type_id == nullptr) {
        return false;
    }

    *region_type_id = -1;
    uintptr_t region_address = 0;
    if (!TryResolveGameplayRegionObject(gameplay_address, region_index, &region_address) || region_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(region_address, kRegionObjectTypeIdOffset, region_type_id);
}

bool IsShopRegionType(int region_type_id) {
    switch (region_type_id) {
    case kSceneTypeMemorator:
    case kSceneTypeDowser:
    case kSceneTypeLibrarian:
    case kSceneTypePolisherArch:
        return true;
    default:
        return false;
    }
}

std::string DescribeRegionNameByType(int region_type_id) {
    switch (region_type_id) {
    case kSceneTypeHub:
        return "hub";
    case kSceneTypeMemorator:
        return "memorator";
    case kSceneTypeDowser:
        return "dowser";
    case kSceneTypeLibrarian:
        return "librarian";
    case kSceneTypePolisherArch:
        return "polisher_arch";
    case kSceneTypeArena:
        return "testrun";
    default:
        return std::string();
    }
}

bool TryBuildSceneContextSnapshot(uintptr_t gameplay_address, SceneContextSnapshot* snapshot) {
    if (snapshot == nullptr || gameplay_address == 0) {
        return false;
    }

    *snapshot = SceneContextSnapshot{};
    snapshot->gameplay_scene_address = gameplay_address;
    (void)TryResolveArena(&snapshot->arena_address);
    uintptr_t local_actor_address = 0;
    (void)TryResolveLocalPlayerWorldContext(
        gameplay_address,
        &local_actor_address,
        nullptr,
        &snapshot->world_address);
    (void)TryResolveGameplayIndexState(&snapshot->region_state_address, nullptr);
    (void)TryReadGameplayIndexStateValue(0, &snapshot->current_region_index);
    if (snapshot->current_region_index >= 0) {
        (void)TryReadGameplayRegionTypeId(gameplay_address, snapshot->current_region_index, &snapshot->region_type_id);
    }
    return true;
}

std::string DescribeSceneKind(const SceneContextSnapshot& snapshot) {
    if (snapshot.world_address == 0) {
        return "transition";
    }
    if (snapshot.region_type_id == kSceneTypeHub || snapshot.current_region_index == kHubRegionIndex) {
        return "hub";
    }
    if (snapshot.region_type_id == kSceneTypeArena || snapshot.current_region_index == kArenaRegionIndex) {
        return "arena";
    }
    if (IsShopRegionType(snapshot.region_type_id)) {
        return "shop";
    }
    return "region";
}

std::string DescribeSceneName(const SceneContextSnapshot& snapshot) {
    if (snapshot.world_address == 0) {
        return "transition";
    }

    const auto typed_name = DescribeRegionNameByType(snapshot.region_type_id);
    if (!typed_name.empty()) {
        return typed_name;
    }
    if (snapshot.current_region_index == kHubRegionIndex) {
        return "hub";
    }
    if (snapshot.current_region_index == kArenaRegionIndex) {
        return "testrun";
    }
    if (snapshot.current_region_index >= 0) {
        return "region_" + std::to_string(snapshot.current_region_index);
    }
    return "gameplay";
}

bool HasBotMaterializedSceneChanged(const BotEntityBinding& binding, const SceneContextSnapshot& scene_context) {
    const bool scene_changed =
        binding.materialized_scene_address != 0 &&
        scene_context.gameplay_scene_address != 0 &&
        binding.materialized_scene_address != scene_context.gameplay_scene_address;
    const bool world_changed =
        binding.materialized_world_address != 0 &&
        scene_context.world_address != 0 &&
        binding.materialized_world_address != scene_context.world_address;
    const bool region_changed =
        binding.materialized_region_index >= 0 &&
        scene_context.current_region_index >= 0 &&
        binding.materialized_region_index != scene_context.current_region_index;

    return scene_changed || world_changed || region_changed;
}

void UpdateBotHomeScene(BotEntityBinding* binding, const SceneContextSnapshot& scene_context) {
    if (binding == nullptr || scene_context.world_address == 0) {
        return;
    }

    if (scene_context.current_region_index == kArenaRegionIndex || scene_context.region_type_id == kSceneTypeArena) {
        return;
    }

    if (scene_context.current_region_index >= 0) {
        binding->home_region_index = scene_context.current_region_index;
    }
    if (scene_context.region_type_id >= 0) {
        binding->home_region_type_id = scene_context.region_type_id;
    }
}

bool ShouldBotBeMaterializedInScene(const BotEntityBinding& binding, const SceneContextSnapshot& scene_context) {
    if (scene_context.world_address == 0) {
        return false;
    }

    if (scene_context.current_region_index == kArenaRegionIndex || scene_context.region_type_id == kSceneTypeArena) {
        return true;
    }

    const bool have_home_region_index = binding.home_region_index >= 0;
    const bool have_home_region_type_id = binding.home_region_type_id >= 0;
    if (!have_home_region_index && !have_home_region_type_id) {
        return true;
    }

    const bool region_matches =
        have_home_region_index &&
        scene_context.current_region_index >= 0 &&
        binding.home_region_index == scene_context.current_region_index;
    const bool type_matches =
        have_home_region_type_id &&
        scene_context.region_type_id >= 0 &&
        binding.home_region_type_id == scene_context.region_type_id;
    return region_matches || type_matches;
}

int ResolveActorAnimationStateSlotIndex(uintptr_t actor_address) {
    if (actor_address == 0) {
        return -1;
    }

    const auto slot = ProcessMemory::Instance().ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1);
    if (slot < 0) {
        return -1;
    }

    return static_cast<int>(slot) + kActorAnimationStateSlotBias;
}

bool TryResolveActorAnimationStateSlotAddress(uintptr_t actor_address, uintptr_t* slot_address) {
    if (slot_address == nullptr) {
        return false;
    }

    *slot_address = 0;
    const auto slot_index = ResolveActorAnimationStateSlotIndex(actor_address);
    if (slot_index < 0) {
        return false;
    }

    const auto entry_count = ReadResolvedGlobalIntOr(kGameplayIndexStateCountGlobal, 0);
    if (entry_count <= slot_index) {
        return false;
    }

    const auto table_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayIndexStateTableGlobal);
    if (table_address == 0) {
        return false;
    }

    *slot_address = table_address + static_cast<uintptr_t>(slot_index) * sizeof(int);
    return true;
}

int ResolveActorAnimationStateId(uintptr_t actor_address) {
    if (actor_address == 0) {
        return kUnknownAnimationStateId;
    }

    auto& memory = ProcessMemory::Instance();
    const auto state_pointer = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (state_pointer != 0) {
        return memory.ReadValueOr<int>(state_pointer, kUnknownAnimationStateId);
    }

    uintptr_t slot_address = 0;
    if (!TryResolveActorAnimationStateSlotAddress(actor_address, &slot_address) || slot_address == 0) {
        return kUnknownAnimationStateId;
    }

    return memory.ReadValueOr<int>(slot_address, kUnknownAnimationStateId);
}

bool TryWriteActorAnimationStateId(uintptr_t actor_address, int state_id) {
    if (actor_address == 0 || state_id == kUnknownAnimationStateId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto state_pointer = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (state_pointer != 0) {
        return memory.TryWriteValue<int>(state_pointer, state_id);
    }

    uintptr_t slot_address = 0;
    return TryResolveActorAnimationStateSlotAddress(actor_address, &slot_address) &&
           slot_address != 0 &&
           memory.TryWriteValue<int>(slot_address, state_id);
}

bool TryWriteActorAnimationStateIdDirect(uintptr_t actor_address, int state_id) {
    if (actor_address == 0 || state_id == kUnknownAnimationStateId) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto state_pointer = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    return state_pointer != 0 && memory.TryWriteValue<int>(state_pointer, state_id);
}

bool CaptureActorAnimationDriveProfile(
    uintptr_t actor_address,
    ObservedActorAnimationDriveProfile* profile) {
    if (actor_address == 0 || profile == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            actor_address + kActorAnimationConfigBlockOffset,
            profile->config_bytes.data(),
            profile->config_bytes.size())) {
        return false;
    }

    profile->walk_cycle_primary =
        memory.ReadFieldOr<float>(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    profile->walk_cycle_secondary =
        memory.ReadFieldOr<float>(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    profile->render_drive_stride =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    profile->valid = true;
    return true;
}

bool ApplyActorAnimationDriveProfile(
    uintptr_t actor_address,
    const ObservedActorAnimationDriveProfile& profile) {
    if (actor_address == 0 || !profile.valid) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote_config = memory.TryWrite(
        actor_address + kActorAnimationConfigBlockOffset,
        profile.config_bytes.data(),
        profile.config_bytes.size());
    const bool wrote_primary =
        memory.TryWriteField(actor_address, kActorWalkCyclePrimaryOffset, profile.walk_cycle_primary);
    const bool wrote_secondary =
        memory.TryWriteField(actor_address, kActorWalkCycleSecondaryOffset, profile.walk_cycle_secondary);
    const bool wrote_stride = memory.TryWriteField(
        actor_address,
        kActorRenderDriveStrideScaleOffset,
        profile.render_drive_stride);
    return wrote_config || wrote_primary || wrote_secondary || wrote_stride;
}

void CaptureObservedPlayerAnimationDriveProfile(uintptr_t actor_address, bool moving_now) {
    ObservedActorAnimationDriveProfile profile;
    if (!CaptureActorAnimationDriveProfile(actor_address, &profile)) {
        return;
    }

    if (moving_now) {
        g_observed_moving_animation_profile = profile;
    } else {
        g_observed_idle_animation_profile = profile;
    }
}

const ObservedActorAnimationDriveProfile* SelectObservedAnimationDriveProfile(bool moving) {
    if (moving && g_observed_moving_animation_profile.valid) {
        return &g_observed_moving_animation_profile;
    }
    if (!moving && g_observed_idle_animation_profile.valid) {
        return &g_observed_idle_animation_profile;
    }
    if (g_observed_idle_animation_profile.valid) {
        return &g_observed_idle_animation_profile;
    }
    if (g_observed_moving_animation_profile.valid) {
        return &g_observed_moving_animation_profile;
    }
    return nullptr;
}

void SeedBotAnimationDriveProfile(uintptr_t source_actor_address, uintptr_t destination_actor_address) {
    if (source_actor_address == 0 || destination_actor_address == 0) {
        return;
    }

    ObservedActorAnimationDriveProfile profile;
    if (!CaptureActorAnimationDriveProfile(source_actor_address, &profile)) {
        return;
    }

    (void)ApplyActorAnimationDriveProfile(destination_actor_address, profile);
}

void ApplyActorAnimationDriveState(uintptr_t actor_address, bool moving) {
    if (actor_address == 0) {
        return;
    }

    if (const auto* observed_profile = SelectObservedAnimationDriveProfile(moving);
        observed_profile != nullptr) {
        (void)ApplyActorAnimationDriveProfile(actor_address, *observed_profile);
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(
        actor_address,
        kActorAnimationDriveStateByteOffset,
        static_cast<std::uint8_t>(moving ? 1 : 0));

    if (!moving) {
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
        return;
    }

    auto move_duration =
        memory.ReadFieldOr<std::int32_t>(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    if (move_duration < 1) {
        move_duration = 1;
    } else if (move_duration < (std::numeric_limits<std::int32_t>::max)()) {
        ++move_duration;
    }
    (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, move_duration);
}

void ResetStandaloneWizardControlBrain(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto control_brain_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (control_brain_address == 0) {
        return;
    }

    (void)memory.TryWriteValue<std::int8_t>(control_brain_address + kActorControlBrainTargetSlotOffset, -1);
    (void)memory.TryWriteValue<std::uint16_t>(
        control_brain_address + kActorControlBrainTargetHandleOffset,
        static_cast<std::uint16_t>(0xFFFF));
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainRetargetTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainActionCooldownTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainActionBurstTicksOffset, 0);
    (void)memory.TryWriteValue<int>(control_brain_address + kActorControlBrainHeadingLockTicksOffset, 0);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainHeadingAccumulatorOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainPursuitRangeOffset, 0.0f);
    (void)memory.TryWriteValue<std::uint8_t>(control_brain_address + kActorControlBrainFollowLeaderOffset, 0);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainDesiredFacingOffset, 0.0f);
    (void)memory.TryWriteValue<float>(
        control_brain_address + kActorControlBrainDesiredFacingSmoothedOffset,
        0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputXOffset, 0.0f);
    (void)memory.TryWriteValue<float>(control_brain_address + kActorControlBrainMoveInputYOffset, 0.0f);
}

void ApplyStandaloneWizardPuppetDriveState(uintptr_t actor_address, bool moving) {
    if (actor_address == 0) {
        return;
    }

    if (const auto* observed_profile = SelectObservedAnimationDriveProfile(moving);
        observed_profile != nullptr) {
        (void)ApplyActorAnimationDriveProfile(actor_address, *observed_profile);
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorAnimationDriveStateByteOffset, static_cast<std::uint8_t>(1));
    if (!moving) {
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
    } else {
        auto move_duration =
            memory.ReadFieldOr<std::int32_t>(actor_address, kActorAnimationMoveDurationTicksOffset, 0);
        if (move_duration < 1) {
            move_duration = 1;
        } else if (move_duration < (std::numeric_limits<std::int32_t>::max)()) {
            ++move_duration;
        }
        (void)memory.TryWriteField(actor_address, kActorAnimationMoveDurationTicksOffset, move_duration);
    }

    ResetStandaloneWizardControlBrain(actor_address);
}

bool TryReadMemoryBlock(uintptr_t address, std::size_t size, std::vector<std::uint8_t>* bytes) {
    if (address == 0 || size == 0 || bytes == nullptr) {
        return false;
    }

    bytes->assign(size, 0);
    if (!ProcessMemory::Instance().TryRead(address, bytes->data(), size)) {
        bytes->clear();
        return false;
    }

    return true;
}

std::uint32_t HashMemoryBlockFNV1a32(uintptr_t address, std::size_t size) {
    if (address == 0 || size == 0) {
        return 0;
    }

    std::vector<std::uint8_t> bytes;
    if (!TryReadMemoryBlock(address, size, &bytes) || bytes.empty()) {
        return 0;
    }

    std::uint32_t hash = 2166136261u;
    for (const auto byte : bytes) {
        hash ^= static_cast<std::uint32_t>(byte);
        hash *= 16777619u;
    }
    return hash;
}

std::uint32_t FloatToBits(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    return bits;
}

int ReadRoundedXpOrUnknown(uintptr_t progression_address) {
    if (progression_address == 0) {
        return kUnknownXpSentinel;
    }

    const auto xp = ProcessMemory::Instance().ReadFieldOr<float>(
        progression_address,
        kProgressionXpOffset,
        static_cast<float>(kUnknownXpSentinel));
    if (xp < 0.0f) {
        return kUnknownXpSentinel;
    }

    return static_cast<int>(std::lround(xp));
}

bool TryResolvePlayerProgression(uintptr_t gameplay_address, uintptr_t* progression_address) {
    if (progression_address == nullptr) {
        return false;
    }

    *progression_address = 0;
    const auto handle = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerProgressionHandleOffset,
        0);
    if (handle == 0) {
        return false;
    }

    const auto progression = ProcessMemory::Instance().ReadValueOr<uintptr_t>(handle, 0);
    if (progression == 0) {
        return false;
    }

    *progression_address = progression;
    return true;
}

bool TryResolvePlayerActor(uintptr_t gameplay_address, uintptr_t* actor_address) {
    if (actor_address == nullptr) {
        return false;
    }

    *actor_address = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerActorOffset,
        0);
    return *actor_address != 0;
}

bool TryResolvePlayerActorForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* actor_address) {
    if (actor_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *actor_address = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
        0);
    return *actor_address != 0;
}

bool TryResolvePlayerProgressionForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* progression_address) {
    if (progression_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *progression_address = 0;
    const auto handle = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
        0);
    if (handle == 0) {
        return false;
    }

    const auto progression = ProcessMemory::Instance().ReadValueOr<uintptr_t>(handle, 0);
    if (progression == 0) {
        return false;
    }

    *progression_address = progression;
    return true;
}

bool TryResolvePlayerProgressionHandleForSlot(uintptr_t gameplay_address, int slot_index, uintptr_t* handle_address) {
    if (handle_address == nullptr || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return false;
    }

    *handle_address = 0;
    const auto handle = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
        gameplay_address,
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride,
        0);
    if (handle == 0) {
        return false;
    }

    *handle_address = handle;
    return true;
}

void WriteGameplayFallbackPosition(uintptr_t gameplay_address, int slot_index, float x, float y) {
    if (gameplay_address == 0 || slot_index < 0 || slot_index >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto offset =
        kGameplayPlayerFallbackPositionOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerFallbackPositionStride;
    memory.TryWriteField(gameplay_address, offset + 0, x);
    memory.TryWriteField(gameplay_address, offset + 4, y);
}

void CopyPlayerProgressionVitals(uintptr_t source_progression_address, uintptr_t destination_progression_address) {
    if (source_progression_address == 0 || destination_progression_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    memory.TryWriteField(
        destination_progression_address,
        kProgressionLevelOffset,
        memory.ReadFieldOr<int>(source_progression_address, kProgressionLevelOffset, 0));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionXpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionXpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionHpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionHpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionMaxHpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionMaxHpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionMpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionMpOffset, 0.0f));
    memory.TryWriteField(
        destination_progression_address,
        kProgressionMaxMpOffset,
        memory.ReadFieldOr<float>(source_progression_address, kProgressionMaxMpOffset, 0.0f));
}

bool ResolveGameplayWorldFromLocalActor(uintptr_t gameplay_address, uintptr_t* world_address) {
    if (world_address == nullptr) {
        return false;
    }

    *world_address = 0;
    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) || local_actor_address == 0) {
        return false;
    }

    *world_address = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(local_actor_address, kActorOwnerOffset, 0);
    return *world_address != 0;
}

bool TryResolveActorProgressionRuntime(uintptr_t actor_address, uintptr_t* progression_address) {
    if (progression_address == nullptr) {
        return false;
    }

    *progression_address = 0;
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    auto resolved_progression_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (resolved_progression_address == 0) {
        const auto progression_handle =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        if (progression_handle != 0) {
            resolved_progression_address = memory.ReadValueOr<uintptr_t>(progression_handle, 0);
        }
    }

    if (resolved_progression_address == 0) {
        return false;
    }

    *progression_address = resolved_progression_address;
    return true;
}

bool TryResolveLocalPlayerWorldContext(
    uintptr_t gameplay_address,
    uintptr_t* actor_address,
    uintptr_t* progression_address,
    uintptr_t* world_address) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (progression_address != nullptr) {
        *progression_address = 0;
    }
    if (world_address != nullptr) {
        *world_address = 0;
    }
    if (gameplay_address == 0) {
        return false;
    }

    uintptr_t resolved_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &resolved_actor_address) || resolved_actor_address == 0) {
        (void)TryReadResolvedGamePointerAbsolute(kLocalPlayerActorGlobal, &resolved_actor_address);
        if (resolved_actor_address == 0) {
            return false;
        }
    }

    const auto resolved_world_address =
        ProcessMemory::Instance().ReadFieldOr<uintptr_t>(resolved_actor_address, kActorOwnerOffset, 0);
    if (resolved_world_address == 0) {
        return false;
    }

    if (actor_address != nullptr) {
        *actor_address = resolved_actor_address;
    }
    if (world_address != nullptr) {
        *world_address = resolved_world_address;
    }
    if (progression_address != nullptr) {
        if (!TryResolvePlayerProgressionForSlot(gameplay_address, 0, progression_address) ||
            *progression_address == 0) {
            if (!TryResolveActorProgressionRuntime(resolved_actor_address, progression_address)) {
                *progression_address = 0;
                return false;
            }
        }
    }

    return true;
}

bool ReserveWizardBotGameplaySlot(std::uint64_t bot_id, int* slot_index) {
    if (slot_index == nullptr) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    *slot_index = -1;
    if (auto* binding = FindBotEntity(bot_id); binding != nullptr && binding->gameplay_slot >= kFirstWizardBotSlot) {
        *slot_index = binding->gameplay_slot;
        return true;
    }

    for (int candidate = kFirstWizardBotSlot; candidate < static_cast<int>(kGameplayPlayerSlotCount); ++candidate) {
        if (FindBotEntityForGameplaySlot(candidate) == nullptr) {
            *slot_index = candidate;
            return true;
        }
    }

    return false;
}

void DetachGameplaySlotActorFromPlayerHierarchy(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address) {
    if (gameplay_address == 0 || actor_address == 0 || slot_index < 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    (void)memory.TryWriteField<uintptr_t>(gameplay_address, actor_slot_offset, 0);
    (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorRegisteredSlotMirrorOffset, 0xFF);
    (void)memory.TryWriteField<std::uint16_t>(actor_address, kActorRegisteredSlotIdMirrorOffset, 0xFFFF);
}

void PrimeGameplaySlotBotActor(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t progression_address,
    float x,
    float y,
    float heading) {
    if (gameplay_address == 0 || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t local_actor_address = 0;
    uintptr_t local_progression_address = 0;
    (void)TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address);
    (void)TryResolvePlayerProgressionForSlot(gameplay_address, 0, &local_progression_address);

    WriteGameplayFallbackPosition(gameplay_address, slot_index, x, y);
    (void)memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    (void)memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);

    if (local_actor_address != 0) {
        // Preserve the slot constructor's own visual/runtime resources. Only
        // seed the animation profile plus the player-facing descriptor state.
        SeedBotAnimationDriveProfile(local_actor_address, actor_address);
        std::string prime_error;
        if (!PrimeWizardActorRenderDescriptorFromActor(local_actor_address, actor_address, &prime_error) &&
            !prime_error.empty()) {
            Log(
                "[bots] render descriptor prime skipped. actor=" + HexString(actor_address) +
                " source=" + HexString(local_actor_address) +
                " detail=" + prime_error);
        }
        (void)memory.TryWriteField(
            actor_address,
            kActorHubVisualSourceKindOffset,
            memory.ReadFieldOr<std::int32_t>(local_actor_address, kActorHubVisualSourceKindOffset, 0));
    }

    if (local_progression_address != 0 && progression_address != 0) {
        CopyPlayerProgressionVitals(local_progression_address, progression_address);
    }

    ApplyActorAnimationDriveState(actor_address, false);
}

int ResolveStandaloneWizardRenderSelectionIndex(int wizard_id) {
    return (std::max)(0, (std::min)(wizard_id, 5));
}

int ResolveStandaloneWizardSelectionState(int wizard_id) {
    switch (ResolveStandaloneWizardRenderSelectionIndex(wizard_id)) {
    case 0:
        return 0x08;
    case 1:
        return 0x10;
    case 2:
        return 0x18;
    case 3:
        return 0x20;
    case 4:
        return 0x28;
    default:
        return kStandaloneWizardHiddenSelectionState;
    }
}

bool PrimeStandaloneWizardProgressionSelectionState(
    uintptr_t progression_inner_address,
    int selection_state,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection_state < 0) {
        return true;
    }
    if (progression_inner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone progression selection prime requires a live runtime object.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto progression_table_address = memory.ReadFieldOr<uintptr_t>(
        progression_inner_address,
        kStandaloneWizardProgressionTableBaseOffset,
        0);
    const auto progression_table_count = memory.ReadFieldOr<int>(
        progression_inner_address,
        kStandaloneWizardProgressionTableCountOffset,
        0);
    if (progression_table_address == 0 || progression_table_count <= selection_state) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression selection table is unavailable for state=" +
                std::to_string(selection_state) + ".";
        }
        return false;
    }

    const auto selection_offset =
        static_cast<std::size_t>(selection_state) * kStandaloneWizardProgressionEntryStride;
    if (!memory.TryWriteField<std::uint16_t>(
            progression_table_address,
            selection_offset + kStandaloneWizardProgressionActiveFlagOffset,
            1) ||
        !memory.TryWriteField<std::uint16_t>(
            progression_table_address,
            selection_offset + kStandaloneWizardProgressionVisibleFlagOffset,
            1)) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to mark standalone progression state=" + std::to_string(selection_state) +
                " as active.";
        }
        return false;
    }

    return true;
}

void ReleaseStandaloneWizardSmartPointerResource(
    uintptr_t actor_address,
    std::size_t handle_offset,
    std::size_t runtime_state_offset,
    uintptr_t wrapper_address,
    uintptr_t inner_address,
    const char* label) {
    auto& memory = ProcessMemory::Instance();
    if (actor_address != 0 &&
        memory.ReadFieldOr<uintptr_t>(actor_address, handle_offset, 0) == wrapper_address) {
        (void)memory.TryWriteField<uintptr_t>(actor_address, handle_offset, 0);
        (void)memory.TryWriteField<uintptr_t>(actor_address, runtime_state_offset, 0);
    }

    if (wrapper_address != 0) {
        DWORD exception_code = 0;
        if (!ReleaseSmartPointerWrapperSafe(wrapper_address, &exception_code)) {
            Log(
                "[bots] standalone " + std::string(label) + " release skipped. wrapper=" +
                HexString(wrapper_address) +
                " inner=" + HexString(inner_address) +
                " code=0x" + HexString(exception_code));
        }
    }
}

void ReleaseStandaloneWizardVisualResources(
    uintptr_t actor_address,
    uintptr_t progression_wrapper_address,
    uintptr_t progression_inner_address,
    uintptr_t equip_wrapper_address,
    uintptr_t equip_inner_address) {
    ReleaseStandaloneWizardSmartPointerResource(
        actor_address,
        kActorProgressionHandleOffset,
        kActorProgressionRuntimeStateOffset,
        progression_wrapper_address,
        progression_inner_address,
        "visual");
    ReleaseStandaloneWizardSmartPointerResource(
        actor_address,
        kActorEquipHandleOffset,
        kActorEquipRuntimeStateOffset,
        equip_wrapper_address,
        equip_inner_address,
        "equip");
}

void DetachStandaloneWizardFromGameplaySlotState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorSlotOffset, static_cast<std::int8_t>(-1));
    (void)memory.TryWriteField(actor_address, kActorRegisteredSlotMirrorOffset, static_cast<std::uint8_t>(0xFF));
    (void)memory.TryWriteField(actor_address, kActorRegisteredSlotIdMirrorOffset, static_cast<std::uint16_t>(0xFFFF));
}

bool CreateStandaloneWizardProgressionWrapper(
    uintptr_t* wrapper_address,
    uintptr_t* inner_address,
    std::string* error_message) {
    if (wrapper_address != nullptr) {
        *wrapper_address = 0;
    }
    if (inner_address != nullptr) {
        *inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto object_allocate_address = memory.ResolveGameAddressOrZero(kObjectAllocate);
    const auto visual_ctor_address = memory.ResolveGameAddressOrZero(kStandaloneWizardVisualRuntimeCtor);
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    if (object_allocate_address == 0 || visual_ctor_address == 0 || operator_new_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone visual runtime entrypoints.";
        }
        return false;
    }

    uintptr_t progression_object_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectAllocateSafe(
            object_allocate_address,
            kStandaloneWizardVisualRuntimeSize,
            &progression_object_address,
            &exception_code) ||
        progression_object_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone visual runtime allocation failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            visual_ctor_address,
            reinterpret_cast<void*>(progression_object_address),
            &progression_object_address,
            &exception_code) ||
        progression_object_address == 0) {
        DWORD release_exception_code = 0;
        (void)CallScalarDeletingDestructorSafe(progression_object_address, 1, &release_exception_code);
        if (error_message != nullptr) {
            *error_message = "Standalone visual runtime ctor failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t progression_wrapper_address = 0;
    exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &progression_wrapper_address,
            &exception_code) ||
        progression_wrapper_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(progression_object_address, 1, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone visual object cleanup skipped. inner=" +
                HexString(progression_object_address) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone visual wrapper allocation failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    auto* wrapper_words = reinterpret_cast<std::uint32_t*>(progression_wrapper_address);
    wrapper_words[0] = static_cast<std::uint32_t>(progression_object_address);
    wrapper_words[1] = 0;

    if (wrapper_address != nullptr) {
        *wrapper_address = progression_wrapper_address;
    }
    if (inner_address != nullptr) {
        *inner_address = progression_object_address;
    }
    return true;
}

bool CreateStandaloneWizardEquipWrapper(
    uintptr_t* wrapper_address,
    uintptr_t* inner_address,
    std::string* error_message) {
    if (wrapper_address != nullptr) {
        *wrapper_address = 0;
    }
    if (inner_address != nullptr) {
        *inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto operator_new_address = memory.ResolveGameAddressOrZero(kGameOperatorNew);
    const auto equip_ctor_address = memory.ResolveGameAddressOrZero(kStandaloneWizardEquipCtor);
    if (operator_new_address == 0 || equip_ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone equip entrypoints.";
        }
        return false;
    }

    uintptr_t equip_object_memory = 0;
    DWORD exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            kStandaloneWizardEquipSize,
            &equip_object_memory,
            &exception_code) ||
        equip_object_memory == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone equip allocation failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t equip_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            equip_ctor_address,
            reinterpret_cast<void*>(equip_object_memory),
            &equip_object_address,
            &exception_code) ||
        equip_object_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(equip_object_memory, 1, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone equip cleanup skipped. inner=" +
                HexString(equip_object_memory) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone equip ctor failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t equip_wrapper_address = 0;
    exception_code = 0;
    if (!CallGameOperatorNewSafe(
            operator_new_address,
            sizeof(std::uint32_t) * 2,
            &equip_wrapper_address,
            &exception_code) ||
        equip_wrapper_address == 0) {
        DWORD release_exception_code = 0;
        if (!CallScalarDeletingDestructorSafe(equip_object_address, 1, &release_exception_code) &&
            release_exception_code != 0) {
            Log(
                "[bots] standalone equip object cleanup skipped. inner=" +
                HexString(equip_object_address) +
                " code=0x" + HexString(release_exception_code));
        }
        if (error_message != nullptr) {
            *error_message = "Standalone equip wrapper allocation failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    auto* wrapper_words = reinterpret_cast<std::uint32_t*>(equip_wrapper_address);
    wrapper_words[0] = static_cast<std::uint32_t>(equip_object_address);
    wrapper_words[1] = 0;

    if (wrapper_address != nullptr) {
        *wrapper_address = equip_wrapper_address;
    }
    if (inner_address != nullptr) {
        *inner_address = equip_object_address;
    }
    return true;
}

bool WireStandaloneWizardRuntimeHandles(
    uintptr_t local_actor_address,
    uintptr_t actor_address,
    int wizard_id,
    uintptr_t* progression_wrapper_address,
    uintptr_t* progression_inner_address,
    uintptr_t* equip_wrapper_address,
    uintptr_t* equip_inner_address,
    std::string* error_message) {
    if (progression_wrapper_address != nullptr) {
        *progression_wrapper_address = 0;
    }
    if (progression_inner_address != nullptr) {
        *progression_inner_address = 0;
    }
    if (equip_wrapper_address != nullptr) {
        *equip_wrapper_address = 0;
    }
    if (equip_inner_address != nullptr) {
        *equip_inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone runtime handle wiring requires a live actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    (void)local_actor_address;

    uintptr_t created_progression_wrapper_address = 0;
    uintptr_t created_progression_inner_address = 0;
    if (!CreateStandaloneWizardProgressionWrapper(
            &created_progression_wrapper_address,
            &created_progression_inner_address,
            error_message)) {
        return false;
    }
    Log(
        "[bots] standalone prime stage=progression_wrapper_ready actor=" + HexString(actor_address) +
        " wrapper=" + HexString(created_progression_wrapper_address) +
        " runtime=" + HexString(created_progression_inner_address));

    auto cleanup_created_progression = [&]() {
        ReleaseStandaloneWizardVisualResources(
            actor_address,
            created_progression_wrapper_address,
            created_progression_inner_address,
            0,
            0);
        created_progression_wrapper_address = 0;
        created_progression_inner_address = 0;
    };

    DWORD exception_code = 0;
    if (!AssignActorSmartPointerWrapperSafe(
            actor_address,
            kActorProgressionHandleOffset,
            kActorProgressionRuntimeStateOffset,
            created_progression_wrapper_address,
            &exception_code)) {
        cleanup_created_progression();
        if (error_message != nullptr) {
            *error_message =
                "Assigning the standalone progression handle failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }
    Log(
        "[bots] standalone prime stage=progression_assigned actor=" + HexString(actor_address) +
        " wrapper=" + HexString(created_progression_wrapper_address));

    uintptr_t created_equip_wrapper_address = 0;
    uintptr_t created_equip_inner_address = 0;
    if (!CreateStandaloneWizardEquipWrapper(
            &created_equip_wrapper_address,
            &created_equip_inner_address,
            error_message)) {
        cleanup_created_progression();
        return false;
    }
    auto cleanup_created_equip = [&]() {
        ReleaseStandaloneWizardVisualResources(
            actor_address,
            created_progression_wrapper_address,
            created_progression_inner_address,
            created_equip_wrapper_address,
            created_equip_inner_address);
        created_equip_wrapper_address = 0;
        created_equip_inner_address = 0;
    };

    exception_code = 0;
    if (!AssignActorSmartPointerWrapperSafe(
            actor_address,
            kActorEquipHandleOffset,
            kActorEquipRuntimeStateOffset,
            created_equip_wrapper_address,
            &exception_code)) {
        cleanup_created_equip();
        if (error_message != nullptr) {
            *error_message =
                "Assigning the standalone equip handle failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }
    Log(
        "[bots] standalone prime stage=equip_assigned actor=" + HexString(actor_address) +
        " wrapper=" + HexString(created_equip_wrapper_address) +
        " runtime=" + HexString(created_equip_inner_address));

    const auto refresh_runtime_handles_address =
        memory.ResolveGameAddressOrZero(kPlayerActorRefreshRuntimeHandles);
    if (refresh_runtime_handles_address == 0) {
        cleanup_created_equip();
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerActor_RefreshRuntimeHandles.";
        }
        return false;
    }

    exception_code = 0;
    if (!CallPlayerActorRefreshRuntimeHandlesSafe(
            refresh_runtime_handles_address,
            actor_address,
            &exception_code)) {
        cleanup_created_equip();
        if (error_message != nullptr) {
            *error_message =
                "PlayerActor_RefreshRuntimeHandles failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }
    Log("[bots] standalone prime stage=runtime_handles_refreshed actor=" + HexString(actor_address));

    (void)memory.TryWriteField(actor_address, kActorUnknownResetOffset, static_cast<std::uint32_t>(0));
    const auto render_selection = ResolveStandaloneWizardRenderSelectionIndex(wizard_id);
    const auto selection_state = ResolveStandaloneWizardSelectionState(wizard_id);
    (void)memory.TryWriteField(
        actor_address,
        kActorRenderSelectionByteOffset,
        static_cast<std::uint8_t>(render_selection));
    const auto animation_selection_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (animation_selection_state_address != 0) {
        (void)memory.TryWriteValue(animation_selection_state_address, selection_state);
    }

    if (!PrimeStandaloneWizardProgressionSelectionState(
            created_progression_inner_address,
            selection_state,
            error_message)) {
        cleanup_created_equip();
        return false;
    }
    Log(
        "[bots] standalone prime stage=selection_primed actor=" + HexString(actor_address) +
        " state=" + std::to_string(selection_state) +
        " render=" + std::to_string(render_selection) +
        " runtime=" + HexString(created_progression_inner_address));

    // The standalone wizard progression ctor leaves the mode field at -1. The
    // native refresh path at 0x0065F9A0 only applies the wizard visual tables
    // when this field is 0, which is what the live player progression carries.
    (void)memory.TryWriteField(
        created_progression_inner_address,
        kStandaloneWizardProgressionRefreshModeOffset,
        static_cast<std::int32_t>(0));

    const auto refresh_progression_address = memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
    if (refresh_progression_address != 0 && selection_state >= 0) {
        exception_code = 0;
        if (!CallActorProgressionRefreshSafe(refresh_progression_address, actor_address, &exception_code)) {
            cleanup_created_equip();
            if (error_message != nullptr) {
                *error_message =
                    "Actor progression refresh failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
        Log(
            "[bots] standalone prime stage=progression_refreshed actor=" + HexString(actor_address) +
            " runtime=" + HexString(created_progression_inner_address));
    }

    if (progression_wrapper_address != nullptr) {
        *progression_wrapper_address = created_progression_wrapper_address;
    }
    if (progression_inner_address != nullptr) {
        *progression_inner_address = created_progression_inner_address;
    }
    if (equip_wrapper_address != nullptr) {
        *equip_wrapper_address = created_equip_wrapper_address;
    }
    if (equip_inner_address != nullptr) {
        *equip_inner_address = created_equip_inner_address;
    }
    return true;
}

bool PrimeStandaloneWizardBotActor(
    uintptr_t local_actor_address,
    uintptr_t actor_address,
    int wizard_id,
    float x,
    float y,
    float heading,
    uintptr_t* progression_wrapper_address,
    uintptr_t* progression_inner_address,
    uintptr_t* equip_wrapper_address,
    uintptr_t* equip_inner_address,
    uintptr_t* out_synthetic_source_profile,
    std::string* error_message) {
    if (out_synthetic_source_profile != nullptr) {
        *out_synthetic_source_profile = 0;
    }
    if (progression_wrapper_address != nullptr) {
        *progression_wrapper_address = 0;
    }
    if (progression_inner_address != nullptr) {
        *progression_inner_address = 0;
    }
    if (equip_wrapper_address != nullptr) {
        *equip_wrapper_address = 0;
    }
    if (equip_inner_address != nullptr) {
        *equip_inner_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (local_actor_address == 0 || actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone priming requires live local and bot actors.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    (void)memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);
    (void)memory.TryWriteField(
        actor_address,
        kActorMoveSpeedScaleOffset,
        memory.ReadFieldOr<float>(local_actor_address, kActorMoveSpeedScaleOffset, 1.0f));
    (void)memory.TryWriteField(
        actor_address,
        kActorMovementSpeedMultiplierOffset,
        memory.ReadFieldOr<float>(local_actor_address, kActorMovementSpeedMultiplierOffset, 1.0f));

    SeedBotAnimationDriveProfile(local_actor_address, actor_address);
    if (!WireStandaloneWizardRuntimeHandles(
            local_actor_address,
            actor_address,
            wizard_id,
            progression_wrapper_address,
            progression_inner_address,
            equip_wrapper_address,
            equip_inner_address,
            error_message)) {
        return false;
    }

    // Dump the local player's source profile for diagnostic comparison
    {
        const auto donor_profile =
            memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorHubVisualSourceProfileOffset, 0);
        const auto donor_kind =
            memory.ReadFieldOr<std::int32_t>(local_actor_address, kActorHubVisualSourceKindOffset, 0);
        if (donor_profile != 0) {
            Log(
                "[bots] donor source-profile dump. profile=" + HexString(donor_profile) +
                " kind=" + std::to_string(donor_kind) +
                " +4C=" + std::to_string(memory.ReadValueOr<std::int32_t>(donor_profile + 0x4C, -1)) +
                " +56=" + std::to_string(memory.ReadValueOr<std::int8_t>(donor_profile + 0x56, -1)) +
                " +74=" + HexString(memory.ReadValueOr<std::uint32_t>(donor_profile + 0x74, 0)) +
                " +9C=" + std::to_string(memory.ReadValueOr<std::int8_t>(donor_profile + 0x9C, -1)) +
                " +9D=" + std::to_string(memory.ReadValueOr<std::int8_t>(donor_profile + 0x9D, -1)) +
                " +A0=" + std::to_string(memory.ReadValueOr<std::uint8_t>(donor_profile + 0xA0, 0xFF)) +
                " +A4=" + std::to_string(memory.ReadValueOr<std::int8_t>(donor_profile + 0xA4, -1)) +
                " +A8=" + std::to_string(memory.ReadValueOr<std::uint8_t>(donor_profile + 0xA8, 0xFF)) +
                " +C0=" + std::to_string(memory.ReadValueOr<float>(donor_profile + 0xC0, 0.0f)) +
                " +D0=" + std::to_string(memory.ReadValueOr<float>(donor_profile + 0xD0, 0.0f)));
        } else {
            Log("[bots] donor source-profile is null. kind=" + std::to_string(donor_kind));
        }
    }

    const auto synthetic_profile = CreateSyntheticWizardSourceProfile(wizard_id);
    if (synthetic_profile != 0) {
        if (out_synthetic_source_profile != nullptr) {
            *out_synthetic_source_profile = synthetic_profile;
        }
        if (!memory.TryWriteField(
                actor_address,
                kActorHubVisualSourceKindOffset,
                kStandaloneWizardVisualSourceKind) ||
            !memory.TryWriteField(
                actor_address,
                kActorHubVisualSourceProfileOffset,
                synthetic_profile)) {
            if (error_message != nullptr) {
                *error_message = "Failed to assign the synthetic wizard source profile.";
            }
            return false;
        }
        const auto build_descriptor_address =
            memory.ResolveGameAddressOrZero(kActorBuildRenderDescriptorFromSource);
        if (build_descriptor_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve Actor_BuildRenderDescriptorFromSource.";
            }
            return false;
        }

        DWORD descriptor_exception = 0;
        if (!CallActorBuildRenderDescriptorFromSourceSafe(
                build_descriptor_address,
                actor_address,
                &descriptor_exception)) {
            if (error_message != nullptr) {
                *error_message =
                    "Actor render descriptor build from synthetic source failed with 0x" +
                    HexString(descriptor_exception) + ".";
            }
            return false;
        }

        // Dump descriptor blocks for comparison
        {
            std::array<std::uint8_t, 0x20> bot_desc{};
            std::array<std::uint8_t, 0x20> donor_desc{};
            memory.TryRead(actor_address + kActorHubVisualDescriptorBlockOffset, bot_desc.data(), bot_desc.size());
            memory.TryRead(local_actor_address + kActorHubVisualDescriptorBlockOffset, donor_desc.data(), donor_desc.size());
            std::string bot_hex, donor_hex;
            for (std::size_t i = 0; i < bot_desc.size(); ++i) {
                char buf[4]; std::snprintf(buf, sizeof(buf), "%02X", bot_desc[i]); bot_hex += buf;
            }
            for (std::size_t i = 0; i < donor_desc.size(); ++i) {
                char buf[4]; std::snprintf(buf, sizeof(buf), "%02X", donor_desc[i]); donor_hex += buf;
            }
            Log("[bots] descriptor block comparison bot=" + bot_hex + " donor=" + donor_hex);
            Log("[bots] bot variants +23C=" +
                std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x23C, 0xFF)) +
                " +23D=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x23D, 0xFF)) +
                " +23E=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x23E, 0xFF)) +
                " +23F=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x23F, 0xFF)) +
                " +240=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(actor_address, 0x240, 0xFF)));
            Log("[bots] donor variants +23C=" +
                std::to_string(memory.ReadFieldOr<std::uint8_t>(local_actor_address, 0x23C, 0xFF)) +
                " +23D=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(local_actor_address, 0x23D, 0xFF)) +
                " +23E=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(local_actor_address, 0x23E, 0xFF)) +
                " +23F=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(local_actor_address, 0x23F, 0xFF)) +
                " +240=" + std::to_string(memory.ReadFieldOr<std::uint8_t>(local_actor_address, 0x240, 0xFF)));
        }

        // The synthetic profile correctly sets variant bytes (+23C..+240) and
        // creates the weapon attachment at +264, but FUN_0040fc60 produced empty
        // descriptor block bytes because the atlas context isn't available from
        // a synthetic profile alone.  Copy the full resolved render-state window
        // from the donor — this includes the descriptor block, render frame
        // table, and all fields the sprite renderer needs.  Then re-apply the
        // bot's own variant bytes and weapon type on top.
        {
            std::string render_copy_error;
            if (PrimeWizardActorResolvedRenderStateFromActor(
                    local_actor_address, actor_address, &render_copy_error)) {
                // Restore the bot's own variant bytes (set by FUN_005E3080)
                // on top of the donor render state
                (void)memory.TryWriteField(actor_address, kActorRenderVariantPrimaryOffset,
                    static_cast<std::uint8_t>(kWizardVisualProfiles[
                        (wizard_id >= 0 && wizard_id < kWizardVisualProfileCount) ? wizard_id : 0].variant_primary));
                (void)memory.TryWriteField(actor_address, kActorRenderVariantSecondaryOffset,
                    static_cast<std::uint8_t>(kWizardVisualProfiles[
                        (wizard_id >= 0 && wizard_id < kWizardVisualProfileCount) ? wizard_id : 0].variant_secondary));
                (void)memory.TryWriteField(actor_address, kActorRenderWeaponTypeOffset,
                    static_cast<std::uint8_t>(kWizardVisualProfiles[
                        (wizard_id >= 0 && wizard_id < kWizardVisualProfileCount) ? wizard_id : 0].weapon_type));
                (void)memory.TryWriteField(actor_address, kActorRenderSelectionByteOffset,
                    static_cast<std::uint8_t>(kWizardVisualProfiles[
                        (wizard_id >= 0 && wizard_id < kWizardVisualProfileCount) ? wizard_id : 0].render_selection));
                (void)memory.TryWriteField(actor_address, kActorRenderVariantTertiaryOffset,
                    static_cast<std::uint8_t>(kWizardVisualProfiles[
                        (wizard_id >= 0 && wizard_id < kWizardVisualProfileCount) ? wizard_id : 0].variant_tertiary));
            } else if (!render_copy_error.empty()) {
                Log("[bots] render state copy for synthetic profile failed: " + render_copy_error);
            }
        }

        Log(
            "[bots] synthetic source profile built visuals. actor=" + HexString(actor_address) +
            " wizard_id=" + std::to_string(wizard_id) +
            " profile=" + HexString(synthetic_profile) +
            " selection=" +
            std::to_string(
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderSelectionByteOffset, 0xFF)) +
            " weapon=" +
            std::to_string(
                memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderWeaponTypeOffset, 0xFF)) +
            " attachment=" +
            HexString(
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0)));
    } else {
        std::string render_state_prime_error;
        if (!PrimeWizardActorResolvedRenderStateFromActor(
                local_actor_address,
                actor_address,
                &render_state_prime_error) &&
            !render_state_prime_error.empty()) {
            Log(
                "[bots] fallback donor render-state prime skipped. actor=" +
                HexString(actor_address) + " detail=" + render_state_prime_error);
        }

        const auto donor_source_profile_address =
            memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorHubVisualSourceProfileOffset, 0);
        bool donor_descriptor_built = false;
        bool donor_descriptor_primed = false;
        DWORD donor_descriptor_exception = 0;
        (void)memory.TryWriteField(
            actor_address,
            kActorHubVisualSourceKindOffset,
            memory.ReadFieldOr<std::int32_t>(local_actor_address, kActorHubVisualSourceKindOffset, 0));
        if (donor_source_profile_address != 0) {
            (void)memory.TryWriteField(
                actor_address,
                kActorHubVisualSourceProfileOffset,
                donor_source_profile_address);

            const auto build_descriptor_address =
                memory.ResolveGameAddressOrZero(kActorBuildRenderDescriptorFromSource);
            if (build_descriptor_address != 0 &&
                CallActorBuildRenderDescriptorFromSourceSafe(
                    build_descriptor_address,
                    actor_address,
                    &donor_descriptor_exception)) {
                donor_descriptor_built = true;
            }

            std::string prime_error;
            if (PrimeWizardActorRenderDescriptorFromActor(
                    local_actor_address,
                    actor_address,
                    &prime_error)) {
                donor_descriptor_primed = true;
            } else if (!prime_error.empty()) {
                Log(
                    "[bots] donor descriptor prime skipped. actor=" + HexString(actor_address) +
                    " donor=" + HexString(local_actor_address) +
                    " detail=" + prime_error);
            }

            if (!donor_descriptor_built &&
                (build_descriptor_address == 0 || donor_descriptor_exception != 0)) {
                Log(
                    "[bots] donor source descriptor build skipped. actor=" +
                    HexString(actor_address) +
                    " donor=" + HexString(local_actor_address) +
                    " source=" + HexString(donor_source_profile_address) +
                    " code=0x" + HexString(donor_descriptor_exception));
            }
        }

        if (donor_source_profile_address == 0) {
            std::string prime_error;
            if (PrimeWizardActorRenderDescriptorFromActor(
                    local_actor_address,
                    actor_address,
                    &prime_error)) {
                donor_descriptor_primed = true;
            } else if (!prime_error.empty()) {
                Log(
                    "[bots] donor descriptor prime skipped. actor=" + HexString(actor_address) +
                    " donor=" + HexString(local_actor_address) +
                    " detail=" + prime_error);
            }
        }

        if (!donor_descriptor_built && !donor_descriptor_primed) {
            (void)memory.TryWriteField(
                actor_address,
                kActorRenderSelectionByteOffset,
                static_cast<std::uint8_t>(ResolveStandaloneWizardRenderSelectionIndex(wizard_id)));
        }
    }
    (void)memory.TryWriteField(
        actor_address,
        kActorRenderAdvanceRateOffset,
        memory.ReadFieldOr<float>(local_actor_address, kActorRenderAdvanceRateOffset, 0.0f));
    (void)memory.TryWriteField(
        actor_address,
        kActorRenderAdvancePhaseOffset,
        memory.ReadFieldOr<float>(local_actor_address, kActorRenderAdvancePhaseOffset, 0.0f));
    (void)memory.TryWriteField(
        actor_address,
        kActorRenderDriveOverlayAlphaOffset,
        memory.ReadFieldOr<float>(local_actor_address, kActorRenderDriveOverlayAlphaOffset, 0.0f));
    (void)memory.TryWriteField(
        actor_address,
        kActorRenderDriveMoveBlendOffset,
        memory.ReadFieldOr<float>(local_actor_address, kActorRenderDriveMoveBlendOffset, 0.0f));

    DWORD refresh_visual_exception = 0;
    if (!CallActorRefreshVisualStateSafe(actor_address, &refresh_visual_exception) &&
        refresh_visual_exception != 0) {
        Log(
            "[bots] standalone actor visual refresh skipped. actor=" + HexString(actor_address) +
            " code=0x" + HexString(refresh_visual_exception));
    }

    const auto desired_animation_state = ResolveActorAnimationStateId(local_actor_address);
    if (!TryWriteActorAnimationStateIdDirect(actor_address, desired_animation_state)) {
        Log(
            "[bots] standalone actor animation prime skipped. actor=" + HexString(actor_address) +
            " source=" + HexString(local_actor_address) +
            " desired=" + std::to_string(desired_animation_state));
    }

    ApplyStandaloneWizardPuppetDriveState(actor_address, false);
    return true;
}

bool WireGameplaySlotBotRuntimeHandles(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t local_actor_address,
    uintptr_t actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || actor_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay slot runtime handle wiring is missing required addresses.";
        }
        return false;
    }

    uintptr_t progression_handle_address = 0;
    if (!TryResolvePlayerProgressionHandleForSlot(gameplay_address, slot_index, &progression_handle_address) ||
        progression_handle_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve gameplay slot progression handle.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_handle_address =
        local_actor_address != 0
            ? memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorEquipHandleOffset, 0)
            : 0;

    DWORD exception_code = 0;
    if (!AssignActorSmartPointerWrapperSafe(
            actor_address,
            kActorProgressionHandleOffset,
            kActorProgressionRuntimeStateOffset,
            progression_handle_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message = "Assigning the progression handle failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    if (equip_handle_address != 0) {
        exception_code = 0;
        if (!AssignActorSmartPointerWrapperSafe(
                actor_address,
                kActorEquipHandleOffset,
                kActorEquipRuntimeStateOffset,
                equip_handle_address,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message = "Assigning the equip handle failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
    }

    const auto refresh_runtime_handles_address =
        memory.ResolveGameAddressOrZero(kPlayerActorRefreshRuntimeHandles);
    if (refresh_runtime_handles_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerActor_RefreshRuntimeHandles.";
        }
        return false;
    }

    exception_code = 0;
    if (!CallPlayerActorRefreshRuntimeHandlesSafe(
            refresh_runtime_handles_address,
            actor_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "PlayerActor_RefreshRuntimeHandles failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    return true;
}

bool FinalizeGameplaySlotBotVisualState(
    uintptr_t gameplay_address,
    uintptr_t local_actor_address,
    uintptr_t actor_address,
    BotEntityBinding* binding,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay attach requires live gameplay and actor addresses.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (local_actor_address != 0) {
        (void)TryWriteActorAnimationStateId(actor_address, ResolveActorAnimationStateId(local_actor_address));
    }

    const auto refresh_progression_address = memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
    if (refresh_progression_address != 0) {
        DWORD exception_code = 0;
        if (!CallActorProgressionRefreshSafe(refresh_progression_address, actor_address, &exception_code)) {
            Log(
                "[bots] progression refresh skipped. actor=" + HexString(actor_address) +
                " code=0x" + HexString(exception_code));
        }
    }

    DWORD exception_code = 0;
    if (!CallGameplayActorAttachSafe(gameplay_address, actor_address, &exception_code)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay actor attach failed with 0x" + HexString(exception_code) + ".";
        }
        if (binding != nullptr) {
            binding->gameplay_attach_applied = false;
        }
        return false;
    }

    if (binding != nullptr) {
        binding->gameplay_attach_applied = true;
    }
    return true;
}

bool DestroyGameplaySlotBotResources(
    uintptr_t gameplay_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay slot cleanup requires a live gameplay scene and slot index.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (actor_address == 0) {
        (void)TryResolvePlayerActorForSlot(gameplay_address, slot_index, &actor_address);
    }

    if (actor_address != 0) {
        std::string destroy_error;
        if (!DestroyLoaderOwnedWizardActor(actor_address, world_address, false, &destroy_error)) {
            if (error_message != nullptr) {
                *error_message = destroy_error.empty() ? "Gameplay slot actor destruction failed." : destroy_error;
            }
            return false;
        }
    }

    const auto actor_slot_offset =
        kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    (void)memory.TryWriteField<uintptr_t>(gameplay_address, actor_slot_offset, 0);

    uintptr_t progression_handle_address = 0;
    (void)TryResolvePlayerProgressionHandleForSlot(gameplay_address, slot_index, &progression_handle_address);
    const auto progression_slot_offset =
        kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
    (void)memory.TryWriteField<uintptr_t>(gameplay_address, progression_slot_offset, 0);

    if (progression_handle_address != 0) {
        DWORD exception_code = 0;
        if (!ReleaseSmartPointerWrapperSafe(progression_handle_address, &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "Gameplay slot progression handle release failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
    }

    return true;
}

bool DestroyLoaderOwnedWizardActor(
    uintptr_t actor_address,
    uintptr_t world_address,
    bool raw_allocation,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    if (world_address == 0) {
        world_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    }

    if (world_address != 0) {
        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        if (unregister_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve ActorWorld_Unregister.";
            }
            return false;
        }

        DWORD exception_code = 0;
        if (!CallActorWorldUnregisterSafe(
                unregister_address,
                world_address,
                actor_address,
                1,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message = "ActorWorld_Unregister failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
    }

    DWORD exception_code = 0;
    if (!CallScalarDeletingDestructorSafe(actor_address, raw_allocation ? 0 : 1, &exception_code)) {
        if (error_message != nullptr) {
            *error_message = "Actor scalar deleting destructor failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    if (raw_allocation) {
        _aligned_free(reinterpret_cast<void*>(actor_address));
    }

    return true;
}

bool PrimeWizardActorRenderDescriptorFromActor(
    uintptr_t donor_actor_address,
    uintptr_t bot_actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (donor_actor_address == 0 || bot_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Direct render priming requires live donor and bot actors.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> descriptor_bytes{};
    if (!memory.TryRead(
            donor_actor_address + kActorHubVisualDescriptorBlockOffset,
            descriptor_bytes.data(),
            descriptor_bytes.size())) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the donor actor render descriptor block.";
        }
        return false;
    }

    const auto selection_byte =
        memory.ReadFieldOr<std::uint8_t>(donor_actor_address, kActorRenderSelectionByteOffset, 0);
    const auto variant_primary =
        memory.ReadFieldOr<std::uint8_t>(donor_actor_address, kActorRenderVariantPrimaryOffset, 0);
    const auto variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(donor_actor_address, kActorRenderVariantSecondaryOffset, 0);
    const auto weapon_type =
        memory.ReadFieldOr<std::uint8_t>(donor_actor_address, kActorRenderWeaponTypeOffset, 0);
    const auto variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(donor_actor_address, kActorRenderVariantTertiaryOffset, 0);
    if (!memory.TryWrite(
            bot_actor_address + kActorHubVisualDescriptorBlockOffset,
            descriptor_bytes.data(),
            descriptor_bytes.size()) ||
        !memory.TryWriteField(bot_actor_address, kActorRenderVariantPrimaryOffset, variant_primary) ||
        !memory.TryWriteField(bot_actor_address, kActorRenderVariantSecondaryOffset, variant_secondary) ||
        !memory.TryWriteField(bot_actor_address, kActorRenderWeaponTypeOffset, weapon_type) ||
        !memory.TryWriteField(bot_actor_address, kActorRenderSelectionByteOffset, selection_byte) ||
        !memory.TryWriteField(bot_actor_address, kActorRenderVariantTertiaryOffset, variant_tertiary)) {
        if (error_message != nullptr) {
            *error_message = "Failed to write the direct actor render descriptor block.";
        }
        return false;
    }

    return true;
}

bool TryResolveStandaloneWizardVisualLinkObjects(
    uintptr_t actor_address,
    uintptr_t* primary_visual_link_address,
    uintptr_t* secondary_visual_link_address,
    uintptr_t* attachment_visual_link_address) {
    if (primary_visual_link_address != nullptr) {
        *primary_visual_link_address = 0;
    }
    if (secondary_visual_link_address != nullptr) {
        *secondary_visual_link_address = 0;
    }
    if (attachment_visual_link_address != nullptr) {
        *attachment_visual_link_address = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    if (equip_runtime_state_address == 0) {
        if (attachment_visual_link_address != nullptr) {
            *attachment_visual_link_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
        }
        return false;
    }

    if (primary_visual_link_address != nullptr) {
        *primary_visual_link_address = ResolveIndirectPointerMember(
            equip_runtime_state_address,
            kActorEquipRuntimeVisualLinkPrimaryOffset);
    }
    if (secondary_visual_link_address != nullptr) {
        *secondary_visual_link_address = ResolveIndirectPointerMember(
            equip_runtime_state_address,
            kActorEquipRuntimeVisualLinkSecondaryOffset);
    }
    if (attachment_visual_link_address != nullptr) {
        *attachment_visual_link_address = ResolveIndirectPointerMember(
            equip_runtime_state_address,
            kActorEquipRuntimeVisualLinkAttachmentOffset);
        if (*attachment_visual_link_address == 0) {
            *attachment_visual_link_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
        }
    }

    return true;
}

uintptr_t ResolveStandaloneWizardVisualDonorActor(
    uintptr_t gameplay_address,
    uintptr_t slot0_actor_address) {
    auto& memory = ProcessMemory::Instance();
    uintptr_t global_actor_address = 0;
    (void)TryReadResolvedGamePointerAbsolute(kLocalPlayerActorGlobal, &global_actor_address);

    const auto score_actor = [&](uintptr_t actor_address) {
        if (actor_address == 0) {
            return -1;
        }

        int score = 0;
        uintptr_t primary_visual_link_address = 0;
        uintptr_t secondary_visual_link_address = 0;
        uintptr_t attachment_visual_link_address = 0;
        (void)TryResolveStandaloneWizardVisualLinkObjects(
            actor_address,
            &primary_visual_link_address,
            &secondary_visual_link_address,
            &attachment_visual_link_address);
        if (primary_visual_link_address != 0) {
            score += 8;
        }
        if (secondary_visual_link_address != 0) {
            score += 8;
        }
        if (attachment_visual_link_address != 0) {
            score += 4;
        }
        if (memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0) != 0) {
            score += 2;
        }
        if (memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0) != 0) {
            score += 1;
        }
        if (gameplay_address != 0 &&
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0) == gameplay_address) {
            score += 1;
        }
        return score;
    };

    const int slot0_score = score_actor(slot0_actor_address);
    const int global_score = score_actor(global_actor_address);
    if (global_score > slot0_score) {
        return global_actor_address;
    }

    return slot0_actor_address != 0 ? slot0_actor_address : global_actor_address;
}

bool PrimeWizardActorResolvedRenderStateFromActor(
    uintptr_t donor_actor_address,
    uintptr_t bot_actor_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (donor_actor_address == 0 || bot_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Resolved render-state prime requires live donor and bot actors.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    struct CopyWindow {
        std::size_t offset;
        std::size_t size;
    };
    constexpr CopyWindow kCopyWindows[] = {
        {kActorRenderDriveFlagsOffset, kActorRegisteredSlotMirrorOffset - kActorRenderDriveFlagsOffset},
        {kActorHubVisualSourceKindOffset, kActorEquipRuntimeStateOffset - kActorHubVisualSourceKindOffset},
        {kActorAnimationSelectionStateOffset, kActorHubVisualAttachmentPtrOffset - kActorAnimationSelectionStateOffset},
    };

    for (const auto& window : kCopyWindows) {
        std::array<std::uint8_t, 0x90> buffer{};
        static_assert(
            sizeof(buffer) >= (kActorEquipRuntimeStateOffset - kActorHubVisualSourceKindOffset),
            "copy buffer must fit the largest resolved render-state window");
        if (!memory.TryRead(
                donor_actor_address + window.offset,
                buffer.data(),
                window.size) ||
            !memory.TryWrite(
                bot_actor_address + window.offset,
                buffer.data(),
                window.size)) {
            if (error_message != nullptr) {
                *error_message =
                    "Failed to copy donor resolved render-state window at +" +
                    HexString(static_cast<uintptr_t>(window.offset)) + ".";
            }
            return false;
        }
    }

    return true;
}

void DestroyStandaloneWizardVisualLinkObject(uintptr_t object_address) {
    if (object_address == 0) {
        return;
    }

    DWORD exception_code = 0;
    if (!CallScalarDeletingDestructorSafe(object_address, 1, &exception_code) && exception_code != 0) {
        Log(
            "[bots] standalone visual-link cleanup skipped. object=" + HexString(object_address) +
            " code=0x" + HexString(exception_code));
    }
}

uintptr_t ResolveIndirectPointerMember(uintptr_t object_address, std::size_t pointer_offset) {
    if (object_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto holder_address = memory.ReadFieldOr<uintptr_t>(object_address, pointer_offset, 0);
    if (holder_address == 0) {
        return 0;
    }

    return memory.ReadValueOr<uintptr_t>(holder_address, 0);
}

bool CreateStandaloneWizardVisualLinkObject(
    uintptr_t source_actor_address,
    uintptr_t donor_visual_link_address,
    uintptr_t ctor_address,
    uintptr_t* visual_link_address,
    std::string* error_message) {
    if (visual_link_address != nullptr) {
        *visual_link_address = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (source_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link creation requires a source actor.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto object_allocate_address = memory.ResolveGameAddressOrZero(kObjectAllocate);
    if (object_allocate_address == 0 || ctor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve standalone visual-link entrypoints.";
        }
        return false;
    }

    uintptr_t object_memory_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectAllocateSafe(
            object_allocate_address,
            kStandaloneWizardVisualLinkSize,
            &object_memory_address,
            &exception_code) ||
        object_memory_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link allocation failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    uintptr_t created_object_address = 0;
    exception_code = 0;
    if (!CallRawObjectCtorSafe(
            ctor_address,
            reinterpret_cast<void*>(object_memory_address),
            &created_object_address,
            &exception_code) ||
        created_object_address == 0) {
        DestroyStandaloneWizardVisualLinkObject(object_memory_address);
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link ctor failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    bool seeded_from_donor_visual_link = false;
    if (donor_visual_link_address != 0) {
        constexpr std::size_t kStandaloneWizardVisualCloneOffset =
            kStandaloneWizardVisualLinkResetOffset;
        constexpr std::size_t kStandaloneWizardVisualCloneSize =
            kStandaloneWizardVisualLinkSize - kStandaloneWizardVisualCloneOffset;
        std::array<std::uint8_t, kStandaloneWizardVisualCloneSize> donor_visual_bytes{};
        if (memory.TryRead(
                donor_visual_link_address + kStandaloneWizardVisualCloneOffset,
                donor_visual_bytes.data(),
                donor_visual_bytes.size()) &&
            memory.TryWrite(
                created_object_address + kStandaloneWizardVisualCloneOffset,
                donor_visual_bytes.data(),
                donor_visual_bytes.size())) {
            seeded_from_donor_visual_link = true;
        } else {
            Log(
                "[bots] donor visual-link clone fallback. donor=" +
                HexString(donor_visual_link_address) +
                " created=" + HexString(created_object_address));
        }
    }

    if (!seeded_from_donor_visual_link) {
        std::array<std::uint8_t, kActorHubVisualDescriptorBlockSize> descriptor_bytes{};
        if (!memory.TryRead(
                source_actor_address + kActorHubVisualDescriptorBlockOffset,
                descriptor_bytes.data(),
                descriptor_bytes.size()) ||
            !memory.TryWriteField(
                created_object_address,
                kStandaloneWizardVisualLinkActiveByteOffset,
                static_cast<std::uint8_t>(1)) ||
            !memory.TryWriteField(
                created_object_address,
                kStandaloneWizardVisualLinkResetOffset,
                static_cast<std::uint32_t>(0)) ||
            !memory.TryWrite(
                created_object_address + kStandaloneWizardVisualLinkDescriptorBlockOffset,
                descriptor_bytes.data(),
                descriptor_bytes.size())) {
            DestroyStandaloneWizardVisualLinkObject(created_object_address);
            if (error_message != nullptr) {
                *error_message = "Failed to seed the standalone visual-link descriptor state.";
            }
            return false;
        }
    }

    if (visual_link_address != nullptr) {
        *visual_link_address = created_object_address;
    }
    return true;
}

bool AttachStandaloneWizardVisualLinkObject(
    uintptr_t actor_address,
    std::size_t sink_offset,
    uintptr_t visual_link_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || visual_link_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link attach is missing an actor or link object.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto attach_address = memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkAttach);
    const auto equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto sink_self_address =
        ResolveIndirectPointerMember(equip_runtime_state_address, sink_offset);
    if (attach_address == 0 || sink_self_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the standalone visual-link attach target.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallStandaloneWizardVisualLinkAttachSafe(
            attach_address,
            sink_self_address,
            visual_link_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message = "Standalone visual-link attach failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    return true;
}

bool FinalizeStandaloneWizardBotActorState(
    uintptr_t gameplay_address,
    uintptr_t donor_actor_address,
    uintptr_t actor_address,
    uintptr_t world_address,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || actor_address == 0 || world_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone actor finalization requires live gameplay, bot, and world addresses.";
        }
        return false;
    }

    uintptr_t primary_visual_link_address = 0;
    uintptr_t secondary_visual_link_address = 0;
    auto cleanup_unattached_links = [&]() {
        DestroyStandaloneWizardVisualLinkObject(primary_visual_link_address);
        DestroyStandaloneWizardVisualLinkObject(secondary_visual_link_address);
        primary_visual_link_address = 0;
        secondary_visual_link_address = 0;
    };

    auto& memory = ProcessMemory::Instance();
    (void)donor_actor_address;
    uintptr_t donor_primary_visual_link_address = 0;
    uintptr_t donor_secondary_visual_link_address = 0;
    uintptr_t donor_attachment_visual_link_address = 0;
    const auto primary_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkPrimaryCtor);
    const auto secondary_ctor_address =
        memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkSecondaryCtor);
    if (!CreateStandaloneWizardVisualLinkObject(
            actor_address,
            donor_primary_visual_link_address,
            primary_ctor_address,
            &primary_visual_link_address,
            error_message)) {
        return false;
    }
    if (!AttachStandaloneWizardVisualLinkObject(
            actor_address,
            kActorEquipRuntimeVisualLinkPrimaryOffset,
            primary_visual_link_address,
            error_message)) {
        cleanup_unattached_links();
        return false;
    }
    primary_visual_link_address = 0;

    if (!CreateStandaloneWizardVisualLinkObject(
            actor_address,
            donor_secondary_visual_link_address,
            secondary_ctor_address,
            &secondary_visual_link_address,
            error_message)) {
        cleanup_unattached_links();
        return false;
    }
    if (!AttachStandaloneWizardVisualLinkObject(
            actor_address,
            kActorEquipRuntimeVisualLinkSecondaryOffset,
            secondary_visual_link_address,
            error_message)) {
        cleanup_unattached_links();
        return false;
    }
    secondary_visual_link_address = 0;

    const auto attachment_sink_address = ResolveIndirectPointerMember(
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0),
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    const auto attachment_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    const auto attach_address = memory.ResolveGameAddressOrZero(kStandaloneWizardVisualLinkAttach);
    if (attach_address != 0 && attachment_sink_address != 0) {
        DWORD exception_code = 0;
        if (!CallStandaloneWizardVisualLinkAttachSafe(
                attach_address,
                attachment_sink_address,
                attachment_address,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "Standalone attachment-link sync failed with 0x" + HexString(exception_code) + ".";
            }
            return false;
        }
        (void)memory.TryWriteField<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    }

    auto& mem_pre = ProcessMemory::Instance();
    const auto pre_04 = mem_pre.ReadFieldOr<uintptr_t>(actor_address, 0x04, 0);

    DWORD exception_code = 0;
    if (!CallGameplayActorAttachSafe(gameplay_address, actor_address, &exception_code)) {
        if (error_message != nullptr) {
            *error_message = "Standalone gameplay attach failed with 0x" +
                             HexString(exception_code) + ".";
        }
        return false;
    }

    const auto post_04 = mem_pre.ReadFieldOr<uintptr_t>(actor_address, 0x04, 0);
    Log("[bots] +04 before/after gameplay attach: " + HexString(pre_04) + " -> " + HexString(post_04));

    {
        auto& mem = ProcessMemory::Instance();
        const auto assigned_slot = static_cast<int>(mem.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1));
        constexpr int kBotSlot = 1;
        if (assigned_slot != kBotSlot) {
            (void)mem.TryWriteField(actor_address, kActorSlotOffset, static_cast<std::int8_t>(kBotSlot));
            (void)mem.TryWriteField(
                gameplay_address,
                kGameplayPlayerActorOffset + static_cast<std::size_t>(kBotSlot) * kGameplayPlayerSlotStride,
                actor_address);
            Log("[bots] assigned bot to slot " + std::to_string(kBotSlot));
        }

        uintptr_t slot0_actor = 0;
        TryResolvePlayerActor(gameplay_address, &slot0_actor);
        if (slot0_actor != 0) {
            const auto player_04 = mem.ReadFieldOr<uintptr_t>(slot0_actor, 0x04, 0);
            if (player_04 != 0) {
                (void)mem.TryWriteField<uintptr_t>(actor_address, 0x04, player_04);
            }
        }

        uintptr_t anim_slot_address = 0;
        if (TryResolveActorAnimationStateSlotAddress(actor_address, &anim_slot_address) &&
            anim_slot_address != 0) {
            (void)mem.TryWriteField(actor_address, kActorAnimationSelectionStateOffset, anim_slot_address);
            Log("[bots] wired anim_state_ptr to slot table at " + HexString(anim_slot_address));
        }
        auto dump = [&](const char* label, uintptr_t addr) {
            Log(std::string("[bots] ") + label +
                " vtable=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x00, 0)) +
                " +04=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x04, 0)) +
                " +05=" + std::to_string(mem.ReadFieldOr<std::uint8_t>(addr, 0x05, 0xFF)) +
                " +08=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x08, 0)) +
                " +0C=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x0C, 0)) +
                " +10=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x10, 0)) +
                " +14=" + std::to_string(mem.ReadFieldOr<std::int32_t>(addr, 0x14, -1)) +
                " +58=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x58, 0)) +
                " +5C=" + std::to_string(static_cast<int>(mem.ReadFieldOr<std::int8_t>(addr, 0x5C, -1))) +
                " +138=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x138, 0)) +
                " +174=" + std::to_string(mem.ReadFieldOr<std::int32_t>(addr, 0x174, -1)) +
                " +178=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x178, 0)) +
                " +1FC=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x1FC, 0)) +
                " +200=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x200, 0)) +
                " +208=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x208, 0)) +
                " +21C=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x21C, 0)) +
                " +22C=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x22C, 0)) +
                " +264=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x264, 0)) +
                " +300=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x300, 0)) +
                " +304=" + HexString(mem.ReadFieldOr<uintptr_t>(addr, 0x304, 0)));
        };
        uintptr_t local_actor = 0;
        TryResolvePlayerActor(gameplay_address, &local_actor);
        if (local_actor != 0) dump("PLAYER", local_actor);
        dump("BOT   ", actor_address);
    }

    if (!EnsureStandaloneWizardWorldOwner(actor_address, world_address, "gameplay_attach", error_message)) {
        return false;
    }
    Log(
        "[bots] standalone visual-link finalize donor_primary=" +
        HexString(donor_primary_visual_link_address) +
        " donor_secondary=" + HexString(donor_secondary_visual_link_address) +
        " donor_attachment=" + HexString(donor_attachment_visual_link_address) +
        " actor=" + HexString(actor_address));
    return true;
}

BotEntityBinding* FindBotEntity(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_bot_entities.begin(),
        g_bot_entities.end(),
        [&](const BotEntityBinding& binding) {
            return binding.bot_id == bot_id;
        });
    return it == g_bot_entities.end() ? nullptr : &(*it);
}

BotEntityBinding* FindBotEntityForActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return nullptr;
    }

    const auto it = std::find_if(
        g_bot_entities.begin(),
        g_bot_entities.end(),
        [&](const BotEntityBinding& binding) {
            return binding.actor_address == actor_address;
        });
    return it == g_bot_entities.end() ? nullptr : &(*it);
}

BotEntityBinding* EnsureBotEntity(std::uint64_t bot_id) {
    auto* binding = FindBotEntity(bot_id);
    if (binding != nullptr) {
        return binding;
    }

    g_bot_entities.push_back(BotEntityBinding{});
    g_bot_entities.back().bot_id = bot_id;
    return &g_bot_entities.back();
}

BotEntityBinding* FindBotEntityForGameplaySlot(int gameplay_slot) {
    const auto it = std::find_if(
        g_bot_entities.begin(),
        g_bot_entities.end(),
        [&](const BotEntityBinding& binding) {
            return binding.gameplay_slot == gameplay_slot;
        });
    return it == g_bot_entities.end() ? nullptr : &(*it);
}

PendingWizardBotSyncRequest* FindPendingWizardBotSyncRequest(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.begin(),
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end(),
        [&](const PendingWizardBotSyncRequest& request) {
            return request.bot_id == bot_id;
        });
    return it == g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end() ? nullptr : &(*it);
}

void UpsertPendingWizardBotSyncRequest(const PendingWizardBotSyncRequest& request) {
    auto* pending_request = FindPendingWizardBotSyncRequest(request.bot_id);
    if (pending_request == nullptr) {
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.push_back(request);
        return;
    }

    *pending_request = request;
}

void RemovePendingWizardBotSyncRequest(std::uint64_t bot_id) {
    g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.erase(
        std::remove_if(
            g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.begin(),
            g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end(),
            [&](const PendingWizardBotSyncRequest& request) {
                return request.bot_id == bot_id;
            }),
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end());
}

void RemovePendingWizardBotDestroyRequest(std::uint64_t bot_id) {
    g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.erase(
        std::remove(
            g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.begin(),
            g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end(),
            bot_id),
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end());
}

void UpsertPendingWizardBotDestroyRequest(std::uint64_t bot_id) {
    if (bot_id == 0) {
        return;
    }

    const auto it = std::find(
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.begin(),
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end(),
        bot_id);
    if (it == g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end()) {
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.push_back(bot_id);
    }
}

void RememberBotEntity(
    std::uint64_t bot_id,
    std::int32_t wizard_id,
    uintptr_t actor_address,
    BotEntityBinding::Kind kind,
    int gameplay_slot = -1,
    bool raw_allocation = false) {
    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    auto* binding = EnsureBotEntity(bot_id);
    if (binding == nullptr) {
        return;
    }

    if (binding->actor_address != 0 && binding->actor_address != actor_address) {
        binding->materialized_scene_address = 0;
        binding->materialized_world_address = 0;
        binding->materialized_region_index = -1;
        binding->gameplay_attach_applied = false;
        binding->standalone_progression_wrapper_address = 0;
        binding->standalone_progression_inner_address = 0;
        binding->standalone_equip_wrapper_address = 0;
        binding->standalone_equip_inner_address = 0;
        binding->synthetic_source_profile_address = 0;
    }

    binding->wizard_id = wizard_id;
    binding->actor_address = actor_address;
    binding->gameplay_slot = gameplay_slot;
    binding->kind = kind;
    binding->raw_allocation = raw_allocation;
    if (actor_address == 0) {
        binding->gameplay_attach_applied = false;
        binding->standalone_progression_wrapper_address = 0;
        binding->standalone_progression_inner_address = 0;
        binding->standalone_equip_wrapper_address = 0;
        binding->standalone_equip_inner_address = 0;
        binding->synthetic_source_profile_address = 0;
        binding->raw_allocation = false;
    }
}

void ResetBotEntityMaterializationState(BotEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->actor_address = 0;
    binding->next_scene_materialize_retry_ms = 0;
    binding->materialized_scene_address = 0;
    binding->materialized_world_address = 0;
    binding->materialized_region_index = -1;
    binding->last_applied_animation_state_id = kUnknownAnimationStateId - 1;
    binding->standalone_progression_wrapper_address = 0;
    binding->standalone_progression_inner_address = 0;
    binding->standalone_equip_wrapper_address = 0;
    binding->standalone_equip_inner_address = 0;
    binding->gameplay_attach_applied = false;
    binding->raw_allocation = false;
    binding->synthetic_source_profile_address = 0;
}

void ForgetBotEntity(std::uint64_t bot_id) {
    std::lock_guard<std::recursive_mutex> entity_lock(g_bot_entities_mutex);
    g_bot_entities.erase(
        std::remove_if(
            g_bot_entities.begin(),
            g_bot_entities.end(),
            [&](const BotEntityBinding& binding) {
                return binding.bot_id == bot_id;
            }),
        g_bot_entities.end());

    std::lock_guard<std::mutex> snapshot_lock(g_wizard_bot_snapshot_mutex);
    g_wizard_bot_gameplay_snapshots.erase(
        std::remove_if(
            g_wizard_bot_gameplay_snapshots.begin(),
            g_wizard_bot_gameplay_snapshots.end(),
            [&](const WizardBotGameplaySnapshot& snapshot) {
                return snapshot.bot_id == bot_id;
            }),
    g_wizard_bot_gameplay_snapshots.end());
}

void DematerializeWizardBotEntityNow(std::uint64_t bot_id, bool forget_binding, std::string_view reason) {
    auto& memory = ProcessMemory::Instance();
    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    auto* binding = FindBotEntity(bot_id);
    if (binding == nullptr) {
        if (forget_binding) {
            ForgetBotEntity(bot_id);
        }
        return;
    }

    if (binding->actor_address != 0) {
        StopWizardBotActorMotion(binding->actor_address);

        std::string destroy_error;
        bool destroyed = false;
        if (binding->kind == BotEntityBinding::Kind::StandaloneWizard &&
            binding->gameplay_slot >= kFirstWizardBotSlot) {
            auto gameplay_address = binding->materialized_scene_address;
            if (gameplay_address == 0) {
                (void)TryResolveCurrentGameplayScene(&gameplay_address);
            }

            if (gameplay_address != 0) {
                destroyed = DestroyGameplaySlotBotResources(
                    gameplay_address,
                    binding->gameplay_slot,
                    binding->actor_address,
                    binding->materialized_world_address,
                    &destroy_error);
            } else {
                destroy_error = "Gameplay slot cleanup could not resolve a gameplay scene.";
            }
        } else {
            if (binding->kind == BotEntityBinding::Kind::StandaloneWizard &&
                (binding->standalone_progression_wrapper_address != 0 ||
                 binding->standalone_progression_inner_address != 0 ||
                 binding->standalone_equip_wrapper_address != 0 ||
                 binding->standalone_equip_inner_address != 0)) {
                ReleaseStandaloneWizardVisualResources(
                    binding->actor_address,
                    binding->standalone_progression_wrapper_address,
                    binding->standalone_progression_inner_address,
                    binding->standalone_equip_wrapper_address,
                    binding->standalone_equip_inner_address);
                binding->standalone_progression_wrapper_address = 0;
                binding->standalone_progression_inner_address = 0;
                binding->standalone_equip_wrapper_address = 0;
                binding->standalone_equip_inner_address = 0;
            }
            destroyed = DestroyLoaderOwnedWizardActor(
                binding->actor_address,
                binding->materialized_world_address,
                binding->raw_allocation,
                &destroy_error);
        }
        if (destroyed) {
            DestroySyntheticWizardSourceProfile(binding->synthetic_source_profile_address);
            binding->synthetic_source_profile_address = 0;
        }
        if (!destroyed) {
            (void)memory.TryWriteField(binding->actor_address, kActorPositionXOffset, 100000.0f);
            (void)memory.TryWriteField(binding->actor_address, kActorPositionYOffset, 100000.0f);
            (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, 0.0f);
        }
        Log(
            "[bots] dematerialized bot entity. bot_id=" + std::to_string(bot_id) +
            " slot=" + std::to_string(binding->gameplay_slot) +
            " kind=" + std::to_string(static_cast<int>(binding->kind)) +
            " actor=" + HexString(binding->actor_address) +
            " reason=" + std::string(reason) +
            (destroy_error.empty() ? std::string() : " detail=" + destroy_error));
    }

    ResetBotEntityMaterializationState(binding);
    PublishWizardBotGameplaySnapshot(*binding);
    if (forget_binding) {
        ForgetBotEntity(bot_id);
    }
}

WizardBotGameplaySnapshot BuildWizardBotGameplaySnapshot(const BotEntityBinding& binding) {
    WizardBotGameplaySnapshot snapshot;
    snapshot.bot_id = binding.bot_id;
    snapshot.entity_materialized = binding.actor_address != 0;
    snapshot.moving = binding.movement_active;
    snapshot.wizard_id = binding.wizard_id;
    snapshot.actor_address = binding.actor_address;
    snapshot.hub_visual_proxy_address = 0;
    snapshot.gameplay_slot = binding.gameplay_slot;
    snapshot.gameplay_attach_applied = binding.gameplay_attach_applied;

    if (binding.actor_address == 0) {
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    const auto render_probe_address = binding.actor_address;
    snapshot.world_address = memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
    snapshot.actor_slot = memory.ReadFieldOr<std::int8_t>(binding.actor_address, kActorSlotOffset, -1);
    snapshot.slot_anim_state_index = ResolveActorAnimationStateSlotIndex(binding.actor_address);
    snapshot.animation_state_ptr =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorAnimationSelectionStateOffset, 0);
    snapshot.render_frame_table =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorRenderFrameTableOffset, 0);
    snapshot.hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorHubVisualAttachmentPtrOffset, 0);
    snapshot.hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorHubVisualSourceProfileOffset, 0);
    snapshot.hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_probe_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    snapshot.progression_handle_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorProgressionHandleOffset, 0);
    snapshot.equip_handle_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorEquipHandleOffset, 0);
    snapshot.progression_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorProgressionRuntimeStateOffset, 0);
    snapshot.equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorEquipRuntimeStateOffset, 0);
    if (snapshot.progression_runtime_state_address == 0 && snapshot.progression_handle_address != 0) {
        snapshot.progression_runtime_state_address =
            memory.ReadValueOr<uintptr_t>(snapshot.progression_handle_address, 0);
    }
    if (snapshot.equip_runtime_state_address == 0 && snapshot.equip_handle_address != 0) {
        snapshot.equip_runtime_state_address =
            memory.ReadValueOr<uintptr_t>(snapshot.equip_handle_address, 0);
    }
    snapshot.resolved_animation_state_id = ResolveActorAnimationStateId(render_probe_address);
    snapshot.hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(render_probe_address, kActorHubVisualSourceKindOffset, 0);
    snapshot.render_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(render_probe_address, kActorRenderDriveFlagsOffset, 0);
    snapshot.anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorAnimationDriveStateByteOffset, 0);
    snapshot.render_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantPrimaryOffset, 0);
    snapshot.render_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantSecondaryOffset, 0);
    snapshot.render_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderWeaponTypeOffset, 0);
    snapshot.render_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderSelectionByteOffset, 0);
    snapshot.render_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantTertiaryOffset, 0);
    snapshot.x = memory.ReadFieldOr<float>(binding.actor_address, kActorPositionXOffset, 0.0f);
    snapshot.y = memory.ReadFieldOr<float>(binding.actor_address, kActorPositionYOffset, 0.0f);
    snapshot.heading = memory.ReadFieldOr<float>(binding.actor_address, kActorHeadingOffset, 0.0f);
    snapshot.walk_cycle_primary =
        memory.ReadFieldOr<float>(render_probe_address, kActorWalkCyclePrimaryOffset, 0.0f);
    snapshot.walk_cycle_secondary =
        memory.ReadFieldOr<float>(render_probe_address, kActorWalkCycleSecondaryOffset, 0.0f);
    snapshot.render_drive_stride =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    snapshot.render_advance_rate =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderAdvanceRateOffset, 0.0f);
    snapshot.render_advance_phase =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderAdvancePhaseOffset, 0.0f);
    snapshot.render_drive_overlay_alpha =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveOverlayAlphaOffset, 0.0f);
    snapshot.render_drive_move_blend =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveMoveBlendOffset, 0.0f);

    auto progression_address =
        memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (progression_address == 0 && snapshot.progression_handle_address != 0) {
        progression_address = memory.ReadValueOr<uintptr_t>(snapshot.progression_handle_address, 0);
    }
    if (progression_address != 0) {
        snapshot.hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
        snapshot.max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
        snapshot.mp = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
        snapshot.max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    }

    return snapshot;
}

void PublishWizardBotGameplaySnapshot(const BotEntityBinding& binding) {
    const auto snapshot = BuildWizardBotGameplaySnapshot(binding);
    std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
    const auto it = std::find_if(
        g_wizard_bot_gameplay_snapshots.begin(),
        g_wizard_bot_gameplay_snapshots.end(),
        [&](const WizardBotGameplaySnapshot& existing) {
            return existing.bot_id == binding.bot_id;
        });
    if (it == g_wizard_bot_gameplay_snapshots.end()) {
        g_wizard_bot_gameplay_snapshots.push_back(snapshot);
        return;
    }

    *it = snapshot;
}

bool TryBuildBotRematerializationRequest(
    uintptr_t gameplay_address,
    const BotEntityBinding& binding,
    BotRematerializationRequest* request) {
    if (request == nullptr || binding.actor_address == 0) {
        return false;
    }

    *request = BotRematerializationRequest{};
    if (binding.materialized_scene_address == 0 && binding.materialized_world_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
        return false;
    }

    if (!HasBotMaterializedSceneChanged(binding, scene_context)) {
        return false;
    }

    multiplayer::BotSnapshot bot_snapshot;
    if (!multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) || !bot_snapshot.available) {
        return false;
    }

    request->bot_id = binding.bot_id;
    request->wizard_id = bot_snapshot.wizard_id;
    request->has_transform = bot_snapshot.transform_valid;
    request->x = bot_snapshot.position_x;
    request->y = bot_snapshot.position_y;
    request->heading = bot_snapshot.heading;
    request->previous_scene_address = binding.materialized_scene_address;
    request->previous_world_address = binding.materialized_world_address;
    request->previous_region_index = binding.materialized_region_index;
    request->next_scene_address = scene_context.gameplay_scene_address;
    request->next_world_address = scene_context.world_address;
    request->next_region_index = scene_context.current_region_index;
    return true;
}

void QueueBotRematerialization(const BotRematerializationRequest& request) {
    Log(
        "[bots] rematerializing entity. bot_id=" + std::to_string(request.bot_id) +
        " old_scene=" + HexString(request.previous_scene_address) +
        " new_scene=" + HexString(request.next_scene_address) +
        " old_world=" + HexString(request.previous_world_address) +
        " new_world=" + HexString(request.next_world_address) +
        " old_region=" + std::to_string(request.previous_region_index) +
        " new_region=" + std::to_string(request.next_region_index));

    DematerializeWizardBotEntityNow(request.bot_id, false, "scene transition");

    std::string error_message;
    if (!QueueWizardBotEntitySync(
            request.bot_id,
            request.wizard_id,
            request.has_transform,
            request.x,
            request.y,
            request.heading,
            &error_message)) {
        Log(
            "[bots] rematerialize queue failed. bot_id=" + std::to_string(request.bot_id) +
            " error=" + error_message);
    }
}

bool ResolveWizardBotTransform(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    float* out_x,
    float* out_y,
    float* out_heading) {
    if (out_x == nullptr || out_y == nullptr || out_heading == nullptr) {
        return false;
    }

    float x = request.x;
    float y = request.y;
    float heading = request.heading;
    if (!request.has_transform) {
        uintptr_t local_actor_address = 0;
        if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) || local_actor_address == 0) {
            return false;
        }

        auto& memory = ProcessMemory::Instance();
        x = memory.ReadFieldOr<float>(local_actor_address, kActorPositionXOffset, 0.0f) + kDefaultWizardBotOffsetX;
        y = memory.ReadFieldOr<float>(local_actor_address, kActorPositionYOffset, 0.0f) + kDefaultWizardBotOffsetY;
        heading = memory.ReadFieldOr<float>(local_actor_address, kActorHeadingOffset, 0.0f);
    }

    *out_x = x;
    *out_y = y;
    *out_heading = heading;
    return true;
}

void ResetEnemyModifierList(EnemyModifierList* modifier_list) {
    if (modifier_list == nullptr) {
        return;
    }

    modifier_list->vtable =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kEnemyModifierListVtable);
    modifier_list->items = nullptr;
    modifier_list->count = 0;
    modifier_list->capacity = 0;
    modifier_list->reserved = 0;
}

void CleanupEnemyModifierList(EnemyModifierList* modifier_list) {
    if (modifier_list == nullptr) {
        return;
    }

    const auto free_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameFree);
    auto* items = modifier_list->items;
    ResetEnemyModifierList(modifier_list);
    if (items == nullptr || free_address == 0) {
        return;
    }

    auto free_memory = reinterpret_cast<GameFreeFn>(free_address);
    free_memory(items);
}

int CaptureSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
        if (exception_pointers != nullptr && exception_pointers->ExceptionRecord != nullptr) {
            *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallGameplayCreatePlayerSlotSafe(
    uintptr_t create_player_slot_address,
    uintptr_t gameplay_address,
    int slot_index,
    DWORD* exception_code) {
    auto* create_player_slot = reinterpret_cast<GameplayCreatePlayerSlotFn>(create_player_slot_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (create_player_slot == nullptr || gameplay_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        create_player_slot(reinterpret_cast<void*>(gameplay_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameObjectFactorySafe(
    uintptr_t factory_address,
    uintptr_t factory_self_address,
    int type_id,
    uintptr_t* object_address,
    DWORD* exception_code) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* factory = reinterpret_cast<GameObjectFactoryFn>(factory_address);
    if (factory == nullptr || factory_self_address == 0) {
        return false;
    }

    __try {
        const auto object_address_value = factory(reinterpret_cast<void*>(factory_self_address), type_id);
        if (object_address != nullptr) {
            *object_address = object_address_value;
        }
        return object_address_value != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameOperatorNewSafe(
    uintptr_t operator_new_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code) {
    if (allocation_address != nullptr) {
        *allocation_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* operator_new_fn = reinterpret_cast<GameOperatorNewFn>(operator_new_address);
    if (operator_new_fn == nullptr) {
        return false;
    }

    __try {
        const auto allocation = operator_new_fn(allocation_size);
        if (allocation_address != nullptr) {
            *allocation_address = reinterpret_cast<uintptr_t>(allocation);
        }
        return allocation != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameObjectAllocateSafe(
    uintptr_t object_allocate_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code) {
    if (allocation_address != nullptr) {
        *allocation_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* object_allocate_fn = reinterpret_cast<GameObjectAllocateFn>(object_allocate_address);
    if (object_allocate_fn == nullptr) {
        return false;
    }

    __try {
        const auto allocation = object_allocate_fn(allocation_size);
        if (allocation_address != nullptr) {
            *allocation_address = reinterpret_cast<uintptr_t>(allocation);
        }
        return allocation != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallRawObjectCtorSafe(
    uintptr_t ctor_address,
    void* object_memory,
    uintptr_t* object_address,
    DWORD* exception_code) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* ctor = reinterpret_cast<RawObjectCtorFn>(ctor_address);
    if (ctor == nullptr || object_memory == nullptr) {
        return false;
    }

    __try {
        auto* object = ctor(object_memory);
        if (object_address != nullptr) {
            *object_address = reinterpret_cast<uintptr_t>(object);
        }
        return object != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorCtorSafe(
    uintptr_t ctor_address,
    void* actor_memory,
    uintptr_t* actor_address,
    DWORD* exception_code) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* ctor = reinterpret_cast<PlayerActorCtorFn>(ctor_address);
    if (ctor == nullptr || actor_memory == nullptr) {
        return false;
    }

    __try {
        auto* actor = ctor(actor_memory);
        if (actor_address != nullptr) {
            *actor_address = reinterpret_cast<uintptr_t>(actor);
        }
        return actor != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

uintptr_t ReadSmartPointerInnerObject(uintptr_t wrapper_address) {
    if (wrapper_address == 0) {
        return 0;
    }

    return ProcessMemory::Instance().ReadValueOr<uintptr_t>(wrapper_address, 0);
}

bool RetainSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (wrapper_address == 0) {
        return true;
    }

    __try {
        auto* wrapper = reinterpret_cast<std::int32_t*>(wrapper_address);
        ++wrapper[1];
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ReleaseSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (wrapper_address == 0) {
        return true;
    }

    const auto free_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameFree);
    if (free_address == 0) {
        return false;
    }

    __try {
        auto* wrapper = reinterpret_cast<std::int32_t*>(wrapper_address);
        --wrapper[1];
        if (wrapper[1] > 0) {
            return true;
        }

        auto* inner_object = reinterpret_cast<void*>(static_cast<uintptr_t>(wrapper[0]));
        if (inner_object != nullptr) {
            const auto vtable = *reinterpret_cast<uintptr_t*>(inner_object);
            const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
            auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
            destructor(inner_object, 1);
        }

        auto* free_memory = reinterpret_cast<GameFreeFn>(free_address);
        free_memory(reinterpret_cast<void*>(wrapper_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool AssignActorSmartPointerWrapperSafe(
    uintptr_t actor_address,
    std::size_t wrapper_offset,
    std::size_t runtime_state_offset,
    uintptr_t source_wrapper_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto existing_wrapper_address = memory.ReadFieldOr<uintptr_t>(actor_address, wrapper_offset, 0);
    if (existing_wrapper_address == source_wrapper_address) {
        const auto inner_object = ReadSmartPointerInnerObject(source_wrapper_address);
        return memory.TryWriteField(actor_address, runtime_state_offset, inner_object);
    }

    if (source_wrapper_address != 0 &&
        !RetainSmartPointerWrapperSafe(source_wrapper_address, exception_code)) {
        return false;
    }

    if (!memory.TryWriteField(actor_address, wrapper_offset, source_wrapper_address)) {
        if (source_wrapper_address != 0) {
            DWORD release_exception = 0;
            (void)ReleaseSmartPointerWrapperSafe(source_wrapper_address, &release_exception);
        }
        return false;
    }

    const auto inner_object = ReadSmartPointerInnerObject(source_wrapper_address);
    if (!memory.TryWriteField(actor_address, runtime_state_offset, inner_object)) {
        return false;
    }

    if (existing_wrapper_address != 0) {
        DWORD release_exception = 0;
        if (!ReleaseSmartPointerWrapperSafe(existing_wrapper_address, &release_exception) &&
            exception_code != nullptr &&
            *exception_code == 0) {
            *exception_code = release_exception;
        }
    }

    return true;
}

bool CallPlayerActorRefreshRuntimeHandlesSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_runtime_handles = reinterpret_cast<PlayerActorRefreshRuntimeHandlesFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_runtime_handles == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        refresh_runtime_handles(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorProgressionRefreshSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_progression = reinterpret_cast<ActorProgressionRefreshFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_progression == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        auto& memory = ProcessMemory::Instance();
        const auto progression_handle =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        const auto progression_runtime = progression_handle != 0 ? memory.ReadValueOr<uintptr_t>(progression_handle, 0) : 0;
        if (progression_runtime == 0) {
            return false;
        }

        refresh_progression(reinterpret_cast<void*>(progression_runtime));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameplayActorAttachSafe(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (gameplay_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        const auto subobject_address = gameplay_address + kGameplayActorAttachSubobjectOffset;
        const auto vtable = *reinterpret_cast<uintptr_t*>(subobject_address);
        if (vtable == 0) {
            return false;
        }

        const auto attach_address = *reinterpret_cast<uintptr_t*>(vtable + 0x10);
        if (attach_address == 0) {
            return false;
        }

        auto* attach_actor = reinterpret_cast<GameplayActorAttachFn>(attach_address);
        attach_actor(reinterpret_cast<void*>(subobject_address), reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorRefreshVisualStateSafe(uintptr_t actor_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(actor_address);
        if (vtable == 0) {
            return false;
        }

        const auto refresh_address = *reinterpret_cast<uintptr_t*>(vtable + 0x18);
        if (refresh_address == 0) {
            return false;
        }

        auto* refresh_visual_state = reinterpret_cast<ActorRefreshVisualStateFn>(refresh_address);
        refresh_visual_state(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorBuildRenderDescriptorFromSourceSafe(
    uintptr_t build_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* build_descriptor = reinterpret_cast<ActorBuildRenderDescriptorFromSourceFn>(build_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_descriptor == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        build_descriptor(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallStandaloneWizardVisualLinkAttachSafe(
    uintptr_t attach_address,
    uintptr_t self_address,
    uintptr_t value_address,
    DWORD* exception_code) {
    auto* attach = reinterpret_cast<StandaloneWizardVisualLinkAttachFn>(attach_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (attach == nullptr || self_address == 0) {
        return false;
    }

    __try {
        return attach(reinterpret_cast<void*>(self_address), reinterpret_cast<void*>(value_address)) != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldRegisterSafe(
    uintptr_t actor_world_register_address,
    uintptr_t world_address,
    int actor_group,
    uintptr_t actor_address,
    int slot_index,
    char use_alt_list,
    DWORD* exception_code) {
    auto* actor_world_register = reinterpret_cast<ActorWorldRegisterFn>(actor_world_register_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_register == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        return actor_world_register(
                   reinterpret_cast<void*>(world_address),
                   actor_group,
                   reinterpret_cast<void*>(actor_address),
                   slot_index,
                   use_alt_list) != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorMoveStepSafe(
    uintptr_t move_step_address,
    uintptr_t owner_address,
    uintptr_t actor_address,
    float move_x,
    float move_y,
    int flags,
    DWORD* exception_code) {
    auto* move_step = reinterpret_cast<PlayerActorMoveStepFn>(move_step_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (move_step == nullptr || owner_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        move_step(reinterpret_cast<void*>(owner_address), reinterpret_cast<void*>(actor_address), move_x, move_y, flags);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorMoveByDeltaSafe(
    uintptr_t move_by_delta_address,
    uintptr_t actor_address,
    float move_x,
    float move_y,
    DWORD* exception_code) {
    auto* move_by_delta = reinterpret_cast<ActorMoveByDeltaFn>(move_by_delta_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (move_by_delta == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        move_by_delta(reinterpret_cast<void*>(actor_address), move_x, move_y, 0);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorAnimationAdvanceSafe(
    uintptr_t animation_advance_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* animation_advance = reinterpret_cast<ActorAnimationAdvanceFn>(animation_advance_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (animation_advance == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        animation_advance(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldUnregisterSafe(
    uintptr_t actor_world_unregister_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    char remove_from_container,
    DWORD* exception_code) {
    auto* actor_world_unregister = reinterpret_cast<ActorWorldUnregisterFn>(actor_world_unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_unregister == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        actor_world_unregister(
            reinterpret_cast<void*>(world_address),
            reinterpret_cast<void*>(actor_address),
            remove_from_container);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorSafe(
    uintptr_t object_address,
    int flags,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

float ReadResolvedGameFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return memory.ReadValueOr<float>(resolved_address, fallback);
}

void StopWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    BotEntityBinding* binding = nullptr;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        binding = FindBotEntityForActor(actor_address);
    }

    if (binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
        ApplyStandaloneWizardPuppetDriveState(actor_address, false);
        return;
    }

    ApplyActorAnimationDriveState(actor_address, false);
}

void ReadActorAnimationDebugFields(
    uintptr_t actor_address,
    uintptr_t* animation_state_pointer,
    int* animation_state_value) {
    if (animation_state_pointer != nullptr) {
        *animation_state_pointer = 0;
    }
    if (animation_state_value != nullptr) {
        *animation_state_value = 0;
    }
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto state_pointer = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (animation_state_pointer != nullptr) {
        *animation_state_pointer = state_pointer;
    }
    if (animation_state_value != nullptr && state_pointer != 0) {
        *animation_state_value = memory.ReadValueOr<int>(state_pointer, 0);
    }
}

void ApplyObservedBotAnimationState(BotEntityBinding* binding, uintptr_t actor_address, bool moving) {
    if (binding == nullptr || actor_address == 0 || binding->kind != BotEntityBinding::Kind::StandaloneWizard) {
        return;
    }

    ApplyStandaloneWizardPuppetDriveState(actor_address, moving);

    const auto desired_state_id = moving ? g_observed_moving_animation_state_id : g_observed_idle_animation_state_id;
    if (TryWriteActorAnimationStateIdDirect(actor_address, desired_state_id)) {
        binding->last_applied_animation_state_id = desired_state_id;
        return;
    }

    binding->last_applied_animation_state_id = ResolveActorAnimationStateId(actor_address);
}

void LogWizardBotMovementFrame(
    BotEntityBinding* binding,
    uintptr_t actor_address,
    uintptr_t owner_address,
    uintptr_t movement_controller_address,
    float direction_x,
    float direction_y,
    float velocity_x,
    float velocity_y,
    float position_before_x,
    float position_before_y,
    float position_after_x,
    float position_after_y,
    const char* path_label) {
    (void)binding;
    (void)actor_address;
    (void)owner_address;
    (void)movement_controller_address;
    (void)direction_x;
    (void)direction_y;
    (void)velocity_x;
    (void)velocity_y;
    (void)position_before_x;
    (void)position_before_y;
    (void)position_after_x;
    (void)position_after_y;
    (void)path_label;
}

void LogLocalPlayerAnimationProbe() {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) ||
        actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto animation_drive_state =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    const auto resolved_anim_state_id = ResolveActorAnimationStateId(actor_address);
    CaptureObservedPlayerAnimationDriveProfile(actor_address, animation_drive_state != 0);

    if (resolved_anim_state_id != kUnknownAnimationStateId) {
        if (animation_drive_state != 0) {
            g_observed_moving_animation_state_id = resolved_anim_state_id;
        } else {
            g_observed_idle_animation_state_id = resolved_anim_state_id;
        }
    }
}

bool ApplyWizardBotMovementStep(BotEntityBinding* binding, std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Bot actor is not materialized.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    if (binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            binding->materialized_world_address,
            "movement_step",
            nullptr);
    }
    const auto magnitude = std::sqrt(
        binding->direction_x * binding->direction_x + binding->direction_y * binding->direction_y);
    if (!binding->movement_active || magnitude <= 0.0001f) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        StopWizardBotActorMotion(binding->actor_address);
        PublishWizardBotGameplaySnapshot(*binding);
        return true;
    }

    float direction_x = binding->direction_x / magnitude;
    float direction_y = binding->direction_y / magnitude;

    const auto position_before_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto position_before_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    const auto speed_scalar = ReadResolvedGameFloatOr(kMovementSpeedScalarGlobal, 1.0f);
    const auto speed_scale_a = memory.ReadFieldOr<float>(actor_address, kActorMoveSpeedScaleOffset, 1.0f);
    const auto speed_scale_b =
        memory.ReadFieldOr<float>(actor_address, kActorMovementSpeedMultiplierOffset, 1.0f);
    auto move_step_scale = memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 1.0f);
    const auto progression_address =
        binding->kind == BotEntityBinding::Kind::StandaloneWizard
            ? static_cast<uintptr_t>(0)
            : memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    const auto progression_speed =
        progression_address != 0
            ? memory.ReadFieldOr<float>(progression_address, kProgressionMoveSpeedOffset, 1.0f)
            : 1.0f;

    if (!std::isfinite(move_step_scale) || std::fabs(move_step_scale) <= 0.0001f) {
        move_step_scale = 1.0f;
    }

    auto movement_speed = progression_speed * speed_scale_a * speed_scale_b * speed_scalar;
    if (!std::isfinite(movement_speed) || std::fabs(movement_speed) <= 0.0001f) {
        movement_speed = 1.0f;
    }

    const auto velocity_x = movement_speed * direction_x;
    const auto velocity_y = movement_speed * direction_y;
    ApplyObservedBotAnimationState(binding, actor_address, true);

    const auto owner_address =
        binding->kind == BotEntityBinding::Kind::StandaloneWizard
            ? static_cast<uintptr_t>(0)
            : memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto movement_controller_address =
        binding->kind == BotEntityBinding::Kind::StandaloneWizard || owner_address == 0
            ? static_cast<uintptr_t>(0)
            : owner_address + kActorOwnerMovementControllerOffset;
    const auto move_step_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorMoveStep);
    const auto move_by_delta_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kActorMoveByDelta);
    auto move_step_x = velocity_x * move_step_scale;
    auto move_step_y = velocity_y * move_step_scale;
    if ((binding->kind == BotEntityBinding::Kind::PlaceholderEnemy ||
         binding->kind == BotEntityBinding::Kind::StandaloneWizard) &&
        std::fabs(move_step_x) <= 0.0001f &&
        std::fabs(move_step_y) <= 0.0001f) {
        move_step_x = direction_x;
        move_step_y = direction_y;
    }
    DWORD exception_code = 0;
    bool player_step_succeeded = false;
    float player_step_after_x = position_before_x;
    float player_step_after_y = position_before_y;
    const char* player_step_path_label = nullptr;
    struct MoveStepAttempt {
        uintptr_t self_address = 0;
        const char* path_label = nullptr;
    };
    const MoveStepAttempt move_step_attempts[] = {
        {owner_address, "player_step_owner"},
        {movement_controller_address, "player_step_controller"},
    };
    for (const auto& attempt : move_step_attempts) {
        if (attempt.self_address == 0 || move_step_address == 0) {
            continue;
        }
        if (player_step_path_label != nullptr && attempt.self_address == owner_address) {
            continue;
        }
        if (owner_address != 0 &&
            movement_controller_address != 0 &&
            movement_controller_address == owner_address &&
            attempt.self_address == movement_controller_address &&
            player_step_path_label != nullptr) {
            continue;
        }

        DWORD attempt_exception_code = 0;
        if (!CallPlayerActorMoveStepSafe(
                move_step_address,
                attempt.self_address,
                actor_address,
                move_step_x,
                move_step_y,
                0,
                &attempt_exception_code)) {
            if (exception_code == 0 && attempt_exception_code != 0) {
                exception_code = attempt_exception_code;
            }
            continue;
        }

        player_step_succeeded = true;
        player_step_path_label = attempt.path_label;
        player_step_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        player_step_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto player_step_delta_x = player_step_after_x - position_before_x;
        const auto player_step_delta_y = player_step_after_y - position_before_y;
        if (std::fabs(player_step_delta_x) > 0.001f || std::fabs(player_step_delta_y) > 0.001f) {
            LogWizardBotMovementFrame(
                binding,
                actor_address,
                owner_address,
                movement_controller_address,
                direction_x,
                direction_y,
                velocity_x,
                velocity_y,
                position_before_x,
                position_before_y,
                player_step_after_x,
                player_step_after_y,
                attempt.path_label);
            PublishWizardBotGameplaySnapshot(*binding);
            return true;
        }
    }

    if ((binding->kind == BotEntityBinding::Kind::PlaceholderEnemy ||
         binding->kind == BotEntityBinding::Kind::StandaloneWizard) &&
        move_by_delta_address != 0 &&
        CallActorMoveByDeltaSafe(
            move_by_delta_address,
            actor_address,
            move_step_x,
            move_step_y,
            &exception_code)) {
        const auto position_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const std::string fallback_path_label =
            player_step_succeeded && player_step_path_label != nullptr
                ? std::string(player_step_path_label) + "_plus_actor_delta"
                : "actor_delta";
        LogWizardBotMovementFrame(
            binding,
            actor_address,
            owner_address,
            movement_controller_address,
            direction_x,
            direction_y,
            velocity_x,
            velocity_y,
            player_step_succeeded ? player_step_after_x : position_before_x,
            player_step_succeeded ? player_step_after_y : position_before_y,
            position_after_x,
            position_after_y,
            fallback_path_label.c_str());
        PublishWizardBotGameplaySnapshot(*binding);
        return true;
    }

    if (exception_code != 0 && error_message != nullptr) {
        *error_message = "PlayerActor_MoveStep threw 0x" + HexString(exception_code) + ".";
    }

    PublishWizardBotGameplaySnapshot(*binding);
    return true;
}

void SyncWizardBotMovementIntent(BotEntityBinding* binding) {
    if (binding == nullptr || binding->bot_id == 0) {
        return;
    }

    multiplayer::BotMovementIntentSnapshot intent;
    if (!multiplayer::ReadBotMovementIntent(binding->bot_id, &intent) || !intent.available) {
        return;
    }

    binding->controller_state = intent.state;
    binding->movement_active = intent.moving;
    binding->has_target = intent.has_target;
    binding->direction_x = intent.direction_x;
    binding->direction_y = intent.direction_y;
    binding->desired_heading_valid = intent.desired_heading_valid;
    binding->desired_heading = intent.desired_heading;
    binding->target_x = intent.target_x;
    binding->target_y = intent.target_y;
    binding->distance_to_target = intent.distance_to_target;
}

void TickWizardBotMovementControllers(uintptr_t gameplay_address, std::uint64_t now_ms) {
    SceneContextSnapshot scene_context;
    const bool have_scene_context = TryBuildSceneContextSnapshot(gameplay_address, &scene_context);
    std::vector<BotRematerializationRequest> rematerialization_requests;
    std::vector<std::uint64_t> dematerialize_requests;
    std::vector<PendingWizardBotSyncRequest> materialize_requests;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        for (auto& binding : g_bot_entities) {
            SyncWizardBotMovementIntent(&binding);
            const bool should_be_materialized =
                have_scene_context && ShouldBotBeMaterializedInScene(binding, scene_context);
            if (binding.actor_address == 0) {
                if (should_be_materialized && now_ms >= binding.next_scene_materialize_retry_ms) {
                    multiplayer::BotSnapshot bot_snapshot;
                    if (multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) && bot_snapshot.available) {
                        PendingWizardBotSyncRequest sync_request;
                        sync_request.bot_id = binding.bot_id;
                        sync_request.wizard_id = bot_snapshot.wizard_id;
                        sync_request.has_transform = bot_snapshot.transform_valid;
                        sync_request.x = bot_snapshot.position_x;
                        sync_request.y = bot_snapshot.position_y;
                        sync_request.heading = bot_snapshot.heading;
                        materialize_requests.push_back(sync_request);
                        binding.next_scene_materialize_retry_ms = now_ms + kWizardBotSyncRetryDelayMs;
                    }
                }
                PublishWizardBotGameplaySnapshot(binding);
                continue;
            }

            if (have_scene_context && HasBotMaterializedSceneChanged(binding, scene_context)) {
                if (should_be_materialized) {
                    BotRematerializationRequest rematerialization_request;
                    if (TryBuildBotRematerializationRequest(gameplay_address, binding, &rematerialization_request)) {
                        rematerialization_requests.push_back(rematerialization_request);
                    }
                } else {
                    dematerialize_requests.push_back(binding.bot_id);
                }
                continue;
            }

            std::string error_message;
            if (!ApplyWizardBotMovementStep(&binding, &error_message) && !error_message.empty()) {
                Log(
                    "[bots] movement step failed. bot_id=" + std::to_string(binding.bot_id) +
                    " actor=" + HexString(binding.actor_address) +
                    " error=" + error_message);
            }
            PublishWizardBotGameplaySnapshot(binding);
        }
    }

    for (const auto bot_id : dematerialize_requests) {
        DematerializeWizardBotEntityNow(bot_id, false, "scene mismatch");
    }

    for (const auto& rematerialization_request : rematerialization_requests) {
        QueueBotRematerialization(rematerialization_request);
    }

    for (const auto& sync_request : materialize_requests) {
        std::string error_message;
        if (!QueueWizardBotEntitySync(
                sync_request.bot_id,
                sync_request.wizard_id,
                sync_request.has_transform,
                sync_request.x,
                sync_request.y,
                sync_request.heading,
                &error_message)) {
            Log(
                "[bots] queued scene materialize failed. bot_id=" + std::to_string(sync_request.bot_id) +
                " wizard_id=" + std::to_string(sync_request.wizard_id) +
                " error=" + error_message);
        }
    }
}

void TickWizardBotMovementControllersIfActive() {
    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    TickWizardBotMovementControllers(gameplay_address, static_cast<std::uint64_t>(::GetTickCount64()));
}

void* CallSpawnEnemyInternal(SpawnEnemyCallContext* context, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (context == nullptr ||
        context->arena_address == 0 ||
        context->config_ctor == nullptr ||
        context->config_dtor == nullptr ||
        context->build_config == nullptr ||
        context->spawn_enemy == nullptr ||
        context->modifiers == nullptr ||
        context->config_wrapper == nullptr ||
        context->config_buffer == nullptr) {
        return nullptr;
    }

    __try {
        context->config_ctor(context->config_wrapper);
        context->build_config(
            reinterpret_cast<void*>(context->arena_address),
            context->type_id,
            kSpawnEnemyVariantDefault,
            context->config_buffer,
            context->modifiers);
        context->enemy = context->spawn_enemy(
            reinterpret_cast<void*>(context->arena_address),
            nullptr,
            context->config_buffer,
            kSpawnEnemyModeDefault,
            kSpawnEnemyParam5Default,
            kSpawnEnemyParam6Default,
            kSpawnEnemyAllowOverrideDefault);
        context->config_dtor(context->config_wrapper);
        return context->enemy;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return nullptr;
    }
}

bool QueueEnemySpawnRequest(const PendingEnemySpawnRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_enemy_spawn_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The enemy spawn queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_enemy_spawn_requests.push_back(request);
    return true;
}

bool QueueRewardSpawnRequest(const PendingRewardSpawnRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_reward_spawn_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The reward spawn queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_reward_spawn_requests.push_back(request);
    return true;
}

bool QueueWizardBotSyncRequest(const PendingWizardBotSyncRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    auto immediate_request = request;
    immediate_request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (FindPendingWizardBotSyncRequest(immediate_request.bot_id) != nullptr) {
        UpsertPendingWizardBotSyncRequest(immediate_request);
        Log(
            "[bots] queued sync update bot_id=" + std::to_string(immediate_request.bot_id) +
            " wizard_id=" + std::to_string(immediate_request.wizard_id) +
            " has_transform=" + std::to_string(immediate_request.has_transform ? 1 : 0) +
            " x=" + std::to_string(immediate_request.x) +
            " y=" + std::to_string(immediate_request.y) +
            " heading=" + std::to_string(immediate_request.heading));
        return true;
    }

    if (g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The wizard bot sync queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.push_back(immediate_request);
    Log(
        "[bots] queued sync bot_id=" + std::to_string(immediate_request.bot_id) +
        " wizard_id=" + std::to_string(immediate_request.wizard_id) +
        " has_transform=" + std::to_string(immediate_request.has_transform ? 1 : 0) +
        " x=" + std::to_string(immediate_request.x) +
        " y=" + std::to_string(immediate_request.y) +
        " heading=" + std::to_string(immediate_request.heading));
    return true;
}

bool QueueWizardBotDestroyRequest(std::uint64_t bot_id, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    UpsertPendingWizardBotDestroyRequest(bot_id);
    return true;
}

bool TryUpdateBotEntity(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* /*error_message*/) {
    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    auto* binding = FindBotEntity(request.bot_id);
    if (binding == nullptr || binding->actor_address == 0) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveWizardBotTransform(gameplay_address, request, &x, &y, &heading)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(binding->actor_address, kActorPositionXOffset, x) ||
        !memory.TryWriteField(binding->actor_address, kActorPositionYOffset, y)) {
        DematerializeWizardBotEntityNow(request.bot_id, true, "update transform write failed");
        return false;
    }

    (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, heading);
    binding->wizard_id = request.wizard_id;
    PublishWizardBotGameplaySnapshot(*binding);
    return true;
}

bool TrySpawnStandaloneWizardBotEntity(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* error_message);

bool TrySpawnStandaloneWizardBotEntitySafe(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnStandaloneWizardBotEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteWizardBotSyncNow(const PendingWizardBotSyncRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (TryUpdateBotEntity(gameplay_address, request, error_message)) {
        Log(
            "[bots] sync updated existing entity. bot_id=" + std::to_string(request.bot_id) +
            " wizard_id=" + std::to_string(request.wizard_id));
        return true;
    }

    Log(
        "[bots] sync spawning standalone actor. bot_id=" + std::to_string(request.bot_id) +
        " wizard_id=" + std::to_string(request.wizard_id) +
        " gameplay=" + HexString(gameplay_address));
    DWORD exception_code = 0;
    if (TrySpawnStandaloneWizardBotEntitySafe(gameplay_address, request, error_message, &exception_code)) {
        return true;
    }
    if (error_message != nullptr && error_message->empty()) {
        if (exception_code != 0) {
            *error_message = "TrySpawnStandaloneWizardBotEntity threw 0x" + HexString(exception_code) + ".";
        } else {
            *error_message = "TrySpawnStandaloneWizardBotEntity returned false without an error message.";
        }
    }
    return false;
}

void DestroyWizardBotEntityNow(std::uint64_t bot_id) {
    RemovePendingWizardBotSyncRequest(bot_id);
    RemovePendingWizardBotDestroyRequest(bot_id);
    DematerializeWizardBotEntityNow(bot_id, true, "destroy");
}

bool ExecuteSpawnEnemyNow(int type_id, float x, float y, uintptr_t* out_enemy_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (out_enemy_address != nullptr) {
        *out_enemy_address = 0;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto enemy_config_ctor_address = memory.ResolveGameAddressOrZero(kEnemyConfigCtor);
    const auto enemy_config_dtor_address = memory.ResolveGameAddressOrZero(kEnemyConfigDtor);
    const auto build_config_address = memory.ResolveGameAddressOrZero(kBuildEnemyConfig);
    const auto spawn_enemy_address = memory.ResolveGameAddressOrZero(kSpawnEnemy);
    if (enemy_config_ctor_address == 0 ||
        enemy_config_dtor_address == 0 ||
        build_config_address == 0 ||
        spawn_enemy_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve one or more enemy spawn entrypoints.";
        }
        return false;
    }

    EnemyModifierList modifiers;
    ResetEnemyModifierList(&modifiers);
    if (modifiers.vtable == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the Array<int> vtable used by enemy modifiers.";
        }
        return false;
    }

    alignas(void*) std::array<std::uint8_t, kEnemyConfigWrapperSize> config_wrapper{};
    void* const config_wrapper_address = config_wrapper.data();
    void* const config_buffer_address = config_wrapper.data() + 4;

    SpawnEnemyCallContext call_context;
    call_context.arena_address = arena_address;
    call_context.config_ctor = reinterpret_cast<EnemyConfigCtorFn>(enemy_config_ctor_address);
    call_context.config_dtor = reinterpret_cast<EnemyConfigDtorFn>(enemy_config_dtor_address);
    call_context.build_config = reinterpret_cast<EnemyConfigBuildFn>(build_config_address);
    call_context.spawn_enemy = reinterpret_cast<EnemySpawnFn>(spawn_enemy_address);
    call_context.modifiers = &modifiers;
    call_context.config_wrapper = config_wrapper_address;
    call_context.config_buffer = config_buffer_address;
    call_context.type_id = type_id;

    DWORD exception_code = 0;
    auto* enemy = CallSpawnEnemyInternal(&call_context, &exception_code);
    CleanupEnemyModifierList(&modifiers);
    if (enemy == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "Enemy_Create failed for type_id=" + std::to_string(type_id) +
                " exception=" + HexString(exception_code);
        }
        return false;
    }

    const auto enemy_address = reinterpret_cast<uintptr_t>(enemy);
    if (out_enemy_address != nullptr) {
        *out_enemy_address = enemy_address;
    }
    const bool wrote_x = memory.TryWriteField(enemy_address, kActorPositionXOffset, x);
    const bool wrote_y = memory.TryWriteField(enemy_address, kActorPositionYOffset, y);
    if (!wrote_x || !wrote_y) {
        Log(
            "spawn_enemy: created enemy but failed to overwrite final position. type_id=" +
            std::to_string(type_id) +
            " enemy=" + HexString(enemy_address) +
            " wrote_x=" + std::to_string(wrote_x ? 1 : 0) +
            " wrote_y=" + std::to_string(wrote_y ? 1 : 0));
    }

    return true;
}

bool TrySpawnStandaloneWizardBotEntity(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player actor is not ready.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address =
        memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorOwnerOffset, 0);
    if (world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player world is not ready.";
        }
        return false;
    }

    const auto donor_actor_address =
        ResolveStandaloneWizardVisualDonorActor(gameplay_address, local_actor_address);
    if (donor_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local player visual donor actor is not ready.";
        }
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveWizardBotTransform(gameplay_address, request, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    const auto player_actor_ctor_address = memory.ResolveGameAddressOrZero(kPlayerActorCtor);
    const auto actor_world_register_address = memory.ResolveGameAddressOrZero(kActorWorldRegister);
    if (player_actor_ctor_address == 0 || actor_world_register_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve standalone actor entrypoints.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    void* actor_memory = nullptr;
    uintptr_t progression_address = 0;
    uintptr_t standalone_progression_wrapper_address = 0;
    uintptr_t standalone_progression_inner_address = 0;
    uintptr_t standalone_equip_wrapper_address = 0;
    uintptr_t standalone_equip_inner_address = 0;
    uintptr_t synthetic_source_profile_address = 0;
    bool actor_world_registered = false;
    bool provisional_binding_registered = false;
    auto clear_provisional_binding = [&](uintptr_t expected_actor_address) {
        if (!provisional_binding_registered) {
            return;
        }

        std::lock_guard<std::recursive_mutex> binding_lock(g_bot_entities_mutex);
        if (auto* binding = FindBotEntity(request.bot_id);
            binding != nullptr &&
            (expected_actor_address == 0 || binding->actor_address == expected_actor_address)) {
            ResetBotEntityMaterializationState(binding);
            binding->wizard_id = request.wizard_id;
            binding->kind = BotEntityBinding::Kind::StandaloneWizard;
            binding->controller_state = multiplayer::BotControllerState::Idle;
            binding->movement_active = false;
            binding->has_target = false;
            binding->desired_heading_valid = false;
            binding->raw_allocation = false;
        }
        provisional_binding_registered = false;
    };
    auto cleanup_actor = [&](std::string_view failure_message) {
        if (actor_address != 0) {
            const auto failed_actor_address = actor_address;
            if (standalone_progression_wrapper_address != 0 ||
                standalone_progression_inner_address != 0 ||
                standalone_equip_wrapper_address != 0 ||
                standalone_equip_inner_address != 0) {
                ReleaseStandaloneWizardVisualResources(
                    actor_address,
                    standalone_progression_wrapper_address,
                    standalone_progression_inner_address,
                    standalone_equip_wrapper_address,
                    standalone_equip_inner_address);
                standalone_progression_wrapper_address = 0;
                standalone_progression_inner_address = 0;
                standalone_equip_wrapper_address = 0;
                standalone_equip_inner_address = 0;
            }
            if (!actor_world_registered) {
                (void)memory.TryWriteField(actor_address, kActorOwnerOffset, static_cast<uintptr_t>(0));
            }
            std::string cleanup_error;
            const bool cleaned = DestroyLoaderOwnedWizardActor(
                actor_address,
                actor_world_registered ? world_address : 0,
                true,
                &cleanup_error);
            if (cleaned) {
                DestroySyntheticWizardSourceProfile(synthetic_source_profile_address);
                synthetic_source_profile_address = 0;
            }
            actor_address = 0;
            clear_provisional_binding(failed_actor_address);
            if (error_message != nullptr) {
                *error_message = std::string(failure_message);
                if (!cleanup_error.empty()) {
                    *error_message += " cleanup=" + cleanup_error;
                } else if (!cleaned) {
                    *error_message += " cleanup=failed";
                }
            }
            return false;
        }

        if (actor_memory != nullptr) {
            _aligned_free(actor_memory);
            actor_memory = nullptr;
        }
        DestroySyntheticWizardSourceProfile(synthetic_source_profile_address);
        synthetic_source_profile_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
        }
        return false;
    };

    actor_memory = _aligned_malloc(kPlayerActorSize, 16);
    if (actor_memory == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Failed to allocate standalone actor memory.";
        }
        return false;
    }
    std::memset(actor_memory, 0, kPlayerActorSize);

    DWORD exception_code = 0;
    if (!CallPlayerActorCtorSafe(
            player_actor_ctor_address,
            actor_memory,
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Player actor ctor failed for bot=" + std::to_string(request.bot_id) +
                " with 0x" + HexString(exception_code) + ".";
        }
        _aligned_free(actor_memory);
        return false;
    }
    actor_memory = nullptr;
    Log("[bots] standalone prime stage=ctor_complete actor=" + HexString(actor_address));

    std::string prime_error;
    if (!PrimeStandaloneWizardBotActor(
            donor_actor_address,
            actor_address,
            request.wizard_id,
            x,
            y,
            heading,
            &standalone_progression_wrapper_address,
            &standalone_progression_inner_address,
            &standalone_equip_wrapper_address,
            &standalone_equip_inner_address,
            &synthetic_source_profile_address,
            &prime_error)) {
        return cleanup_actor(
            prime_error.empty() ? "Standalone actor priming failed." : prime_error);
    }
    Log(
        "[bots] standalone prime stage=actor_primed actor=" + HexString(actor_address) +
        " wrapper=" + HexString(standalone_progression_wrapper_address) +
        " runtime=" + HexString(standalone_progression_inner_address));

    RememberBotEntity(
        request.bot_id,
        request.wizard_id,
        actor_address,
        BotEntityBinding::Kind::StandaloneWizard,
        -1,
        true);
    provisional_binding_registered = true;
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_bot_entities_mutex);
        if (auto* binding = FindBotEntity(request.bot_id); binding != nullptr) {
            binding->controller_state = multiplayer::BotControllerState::Idle;
            binding->movement_active = false;
            binding->has_target = false;
            binding->desired_heading_valid = false;
            binding->next_scene_materialize_retry_ms = 0;
            binding->materialized_scene_address = gameplay_address;
            binding->materialized_world_address = world_address;
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = false;
            binding->gameplay_slot = -1;
            binding->raw_allocation = true;
            binding->standalone_progression_wrapper_address = standalone_progression_wrapper_address;
            binding->standalone_progression_inner_address = standalone_progression_inner_address;
            binding->standalone_equip_wrapper_address = standalone_equip_wrapper_address;
            binding->standalone_equip_inner_address = standalone_equip_inner_address;
            binding->synthetic_source_profile_address = synthetic_source_profile_address;
        }
    }

    exception_code = 0;
    if (!CallActorWorldRegisterSafe(
            actor_world_register_address,
            world_address,
            0,
            actor_address,
            -1,
            0,
            &exception_code)) {
        return cleanup_actor(
            "ActorWorld_Register failed for bot=" + std::to_string(request.bot_id) +
            " with 0x" + HexString(exception_code) + ".");
    }
    actor_world_registered = true;
    Log(
        "[bots] standalone prime stage=world_registered actor=" + HexString(actor_address) +
        " world=" + HexString(world_address));

    std::string finalize_error;
    if (!FinalizeStandaloneWizardBotActorState(
            gameplay_address,
            donor_actor_address,
            actor_address,
            world_address,
            &finalize_error)) {
        return cleanup_actor(
            finalize_error.empty() ? "Standalone actor finalization failed." : finalize_error);
    }
    Log(
        "[bots] standalone prime stage=scene_attached actor=" + HexString(actor_address) +
        " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))));

    ApplyStandaloneWizardPuppetDriveState(actor_address, false);
    progression_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);

    RememberBotEntity(
        request.bot_id,
        request.wizard_id,
        actor_address,
        BotEntityBinding::Kind::StandaloneWizard,
        -1,
        true);
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_bot_entities_mutex);
        if (auto* binding = FindBotEntity(request.bot_id); binding != nullptr) {
            binding->wizard_id = request.wizard_id;
            binding->next_scene_materialize_retry_ms = 0;
            binding->materialized_scene_address = gameplay_address;
            binding->materialized_world_address = world_address;
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = true;
            binding->gameplay_slot = -1;
            binding->raw_allocation = true;
            binding->standalone_progression_wrapper_address = standalone_progression_wrapper_address;
            binding->standalone_progression_inner_address = standalone_progression_inner_address;
            binding->standalone_equip_wrapper_address = standalone_equip_wrapper_address;
            binding->standalone_equip_inner_address = standalone_equip_inner_address;
            binding->synthetic_source_profile_address = synthetic_source_profile_address;

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
                UpdateBotHomeScene(binding, scene_context);
            }

            PublishWizardBotGameplaySnapshot(*binding);
        }
    }

    Log(
        "[bots] created standalone actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(world_address) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " slot_anim_state=" + std::to_string(ResolveActorAnimationStateSlotIndex(actor_address)) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " render_desc=" + HexString(HashMemoryBlockFNV1a32(
            actor_address + kActorHubVisualDescriptorBlockOffset,
            kActorHubVisualDescriptorBlockSize)) +
        " progression_handle=" +
        HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0)) +
        " equip_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0)) +
        " anim_state_ptr=" + HexString(memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorAnimationSelectionStateOffset,
            0)) +
        " world_register=true");

    Log(
        "[bots] created remote wizard entity. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " heading=" + std::to_string(heading) +
        " progression=" + HexString(progression_address) +
        " wizard_id=" + std::to_string(request.wizard_id));
    return true;
}

bool ExecuteSpawnRewardNow(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (kind != "gold") {
        if (error_message != nullptr) {
            *error_message = "Only gold rewards are supported right now.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    const auto spawn_reward_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kSpawnRewardGold);
    if (spawn_reward_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the gold reward spawn function.";
        }
        return false;
    }

    auto spawn_reward = reinterpret_cast<SpawnRewardGoldFn>(spawn_reward_address);
    spawn_reward(
        reinterpret_cast<void*>(arena_address),
        FloatToBits(x),
        FloatToBits(y),
        amount,
        kSpawnRewardDefaultLifetime);
    return true;
}

struct DispatchException {
    DWORD code = 0;
};

int CaptureDispatchException(EXCEPTION_POINTERS* exception_pointers, DispatchException* exception) {
    if (exception == nullptr || exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_EXECUTE_HANDLER;
    }

    exception->code = exception_pointers->ExceptionRecord->ExceptionCode;
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallGameplaySwitchRegionSafe(
    uintptr_t switch_region_address,
    uintptr_t gameplay_address,
    int region_index,
    DispatchException* exception) {
    auto* switch_region = reinterpret_cast<GameplaySwitchRegionFn>(switch_region_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        switch_region(reinterpret_cast<void*>(gameplay_address), region_index);
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryDispatchGameplaySwitchRegionOnGameThread(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    if (region_index < 0 || region_index > kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message = "Region index is out of range.";
        }
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    const auto switch_region_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    if (switch_region_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Gameplay_SwitchRegion.";
        }
        return false;
    }

    SceneContextSnapshot before;
    (void)TryBuildSceneContextSnapshot(gameplay_address, &before);
    if (before.current_region_index == region_index && before.world_address != 0) {
        Log(
            "gameplay.switch_region: already in target region. region=" + std::to_string(region_index) +
            " scene=" + DescribeSceneName(before));
        return true;
    }

    DispatchException exception;
    if (!CallGameplaySwitchRegionSafe(switch_region_address, gameplay_address, region_index, &exception)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay_SwitchRegion raised 0x" + HexString(exception.code) + ".";
        }
        Log(
            "gameplay.switch_region: dispatch failed. gameplay=" + HexString(gameplay_address) +
            " switch_region=" + HexString(switch_region_address) +
            " from=" + DescribeSceneName(before) +
            " target_region=" + std::to_string(region_index) +
            " exception_code=" + HexString(exception.code));
        return false;
    }

    SceneContextSnapshot after;
    (void)TryBuildSceneContextSnapshot(gameplay_address, &after);
    Log(
        "gameplay.switch_region: dispatched. gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(switch_region_address) +
        " from=" + DescribeSceneName(before) +
        " to=" + DescribeSceneName(after) +
        " target_region=" + std::to_string(region_index));
    return true;
}

bool CallArenaStartWavesSafe(uintptr_t start_waves_address, uintptr_t arena_address, DispatchException* exception) {
    auto* start_waves = reinterpret_cast<ArenaStartWavesFn>(start_waves_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        start_waves(reinterpret_cast<void*>(arena_address));
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryReadArenaWaveStartState(uintptr_t arena_address, ArenaWaveStartState* state) {
    if (state == nullptr || arena_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable = 0;
    if (!memory.TryReadValue(arena_address, &vtable) || vtable == 0) {
        return false;
    }

    ArenaWaveStartState snapshot;
    memory.TryReadField(arena_address, kArenaCombatSectionIndexOffset, &snapshot.combat_section_index);
    memory.TryReadField(arena_address, kArenaCombatWaveIndexOffset, &snapshot.combat_wave_index);
    memory.TryReadField(arena_address, kArenaCombatWaitTicksOffset, &snapshot.combat_wait_ticks);
    memory.TryReadField(arena_address, kArenaCombatAdvanceModeOffset, &snapshot.combat_advance_mode);
    memory.TryReadField(arena_address, kArenaCombatAdvanceThresholdOffset, &snapshot.combat_advance_threshold);
    memory.TryReadField(arena_address, kArenaCombatWaveCounterOffset, &snapshot.combat_wave_counter);
    memory.TryReadField(arena_address, kArenaCombatStartedMusicOffset, &snapshot.combat_started_music);
    memory.TryReadField(arena_address, kArenaCombatTransitionRequestedOffset, &snapshot.combat_transition_requested);
    memory.TryReadField(arena_address, kArenaCombatActiveFlagOffset, &snapshot.combat_active);

    *state = snapshot;
    return true;
}

std::string DescribeArenaWaveStartState(const ArenaWaveStartState& candidate) {
    return
        "section=" + std::to_string(candidate.combat_section_index) +
        " wave=" + std::to_string(candidate.combat_wave_index) +
        " wait_ticks=" + std::to_string(candidate.combat_wait_ticks) +
        " advance_mode=" + std::to_string(candidate.combat_advance_mode) +
        " advance_threshold=" + std::to_string(candidate.combat_advance_threshold) +
        " wave_counter=" + std::to_string(candidate.combat_wave_counter) +
        " music_started=" + std::to_string(static_cast<unsigned>(candidate.combat_started_music)) +
        " transition_requested=" + std::to_string(static_cast<unsigned>(candidate.combat_transition_requested)) +
        " combat_active=" + std::to_string(static_cast<unsigned>(candidate.combat_active));
}

bool TryStartWavesOnGameThread() {
    auto& memory = ProcessMemory::Instance();
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        Log("start_waves: arena is not active. arena=" + HexString(arena_address));
        return false;
    }

    const auto start_waves_address = memory.ResolveGameAddressOrZero(kArenaStartWaves);
    if (start_waves_address == 0) {
        Log(
            "start_waves: missing arena combat entrypoint. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address));
        return false;
    }

    ArenaWaveStartState before;
    const bool have_before = TryReadArenaWaveStartState(arena_address, &before);
    if (have_before && before.combat_started_music != 0 && before.combat_wave_index > 0) {
        Log(
            "start_waves: arena combat is already active. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address) +
            " state=" + DescribeArenaWaveStartState(before));
        return true;
    }

    DispatchException start_waves_exception;
    if (!CallArenaStartWavesSafe(start_waves_address, arena_address, &start_waves_exception)) {
        Log(
            "start_waves: arena combat entrypoint raised an exception. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address) +
            " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
            " exception_code=" + HexString(start_waves_exception.code));
        return false;
    }

    ArenaWaveStartState after;
    const bool have_after = TryReadArenaWaveStartState(arena_address, &after);
    Log(
        "start_waves: arena combat entrypoint dispatched. arena=" + HexString(arena_address) +
        " start_waves=" + HexString(start_waves_address) +
        " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
        " after=" + (have_after ? DescribeArenaWaveStartState(after) : std::string("unreadable")));
    return true;
}

bool TryDispatchHubStartTestrunOnGameThread() {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto cooldown_until =
        g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.load(std::memory_order_acquire);
    if (now_ms < cooldown_until) {
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return false;
    }

    const auto switch_region_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    if (switch_region_address == 0) {
        return false;
    }
    const auto arena_dispatch_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kArenaStartRunDispatch);

    auto& memory = ProcessMemory::Instance();
    std::uint8_t testrun_mode_flag = 0;
    const bool have_testrun_mode_flag =
        memory.TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    uintptr_t arena_vtable = 0;
    const bool have_arena_vtable = memory.TryReadValue(arena_address, &arena_vtable);

    DispatchException exception;
    if (!CallGameplaySwitchRegionSafe(
            switch_region_address,
            gameplay_address,
            kArenaRegionIndex,
            &exception)) {
        g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(
            now_ms + kHubStartTestrunDispatchCooldownMs,
            std::memory_order_release);
        Log(
            "Hub testrun region switch raised an exception. switch_region=" +
            HexString(switch_region_address) +
            " arena=" + HexString(arena_address) +
            " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
            " gameplay=" + HexString(gameplay_address) +
            " target_region=" + std::to_string(kArenaRegionIndex) +
            " arena_enter_dispatch=" +
            (arena_dispatch_address != 0 ? HexString(arena_dispatch_address) : std::string("unresolved")) +
            " testrun_mode_flag=" +
            (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")) +
            " exception_code=" + HexString(exception.code));
        return false;
    }

    g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(
        now_ms + kHubStartTestrunDispatchCooldownMs,
        std::memory_order_release);
    Log(
        "Hub testrun region switch completed. switch_region=" + HexString(switch_region_address) +
        " arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" +
        (arena_dispatch_address != 0 ? HexString(arena_dispatch_address) : std::string("unresolved")) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool TryDispatchStartWavesOnGameThread() {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto retry_not_before =
        g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < retry_not_before) {
        return false;
    }

    if (!TryStartWavesOnGameThread()) {
        g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(
            now_ms + kWaveStartRetryDelayMs,
            std::memory_order_release);
        return false;
    }

    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);
    return true;
}

void PumpQueuedGameplayActions() {
    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto wizard_bot_sync_not_before_ms =
        g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.load(std::memory_order_acquire);

    auto pending =
        g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.load(std::memory_order_acquire);
    while (pending > 0) {
        if (!g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.compare_exchange_weak(
                pending,
                pending - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        if (!TryDispatchHubStartTestrunOnGameThread()) {
            g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.fetch_add(
                1,
                std::memory_order_acq_rel);
        }
        break;
    }

    pending = g_gameplay_keyboard_injection.pending_start_waves_requests.load(std::memory_order_acquire);
    while (pending > 0) {
        if (!g_gameplay_keyboard_injection.pending_start_waves_requests.compare_exchange_weak(
                pending,
                pending - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        if (!TryDispatchStartWavesOnGameThread()) {
            g_gameplay_keyboard_injection.pending_start_waves_requests.fetch_add(
                1,
                std::memory_order_acq_rel);
        }
        break;
    }

    PendingRewardSpawnRequest reward_request;
    bool have_reward_request = false;
    PendingEnemySpawnRequest enemy_request;
    bool have_enemy_request = false;
    PendingWizardBotSyncRequest wizard_bot_request;
    bool have_wizard_bot_request = false;
    PendingGameplayRegionSwitchRequest region_switch_request;
    bool have_region_switch_request = false;
    std::vector<std::uint64_t> destroy_requests;
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        if (wizard_bot_sync_not_before_ms <= now_ms &&
            !g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.empty()) {
            const auto pending_sync_count =
                g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.size();
            for (std::size_t index = 0; index < pending_sync_count; ++index) {
                auto pending_request = g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.front();
                g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.pop_front();
                if (!have_wizard_bot_request && pending_request.next_attempt_ms <= now_ms) {
                    wizard_bot_request = pending_request;
                    have_wizard_bot_request = true;
                    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                        now_ms + kWizardBotSyncDispatchSpacingMs,
                        std::memory_order_release);
                    continue;
                }

                g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.push_back(pending_request);
            }
        }
        const auto region_switch_not_before_ms =
            g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.load(std::memory_order_acquire);
        if (region_switch_not_before_ms <= now_ms &&
            !g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.empty()) {
            const auto pending_region_switch_count =
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size();
            for (std::size_t index = 0; index < pending_region_switch_count; ++index) {
                auto pending_request = g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.front();
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.pop_front();
                if (!have_region_switch_request && pending_request.next_attempt_ms <= now_ms) {
                    region_switch_request = pending_request;
                    have_region_switch_request = true;
                    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(
                        now_ms + kGameplayRegionSwitchDispatchSpacingMs,
                        std::memory_order_release);
                    continue;
                }

                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(pending_request);
            }
        }
        while (!g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.empty()) {
            destroy_requests.push_back(g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.front());
            g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.pop_front();
        }
        if (!g_gameplay_keyboard_injection.pending_reward_spawn_requests.empty()) {
            reward_request = std::move(g_gameplay_keyboard_injection.pending_reward_spawn_requests.front());
            g_gameplay_keyboard_injection.pending_reward_spawn_requests.pop_front();
            have_reward_request = true;
        }
        if (!g_gameplay_keyboard_injection.pending_enemy_spawn_requests.empty()) {
            enemy_request = g_gameplay_keyboard_injection.pending_enemy_spawn_requests.front();
            g_gameplay_keyboard_injection.pending_enemy_spawn_requests.pop_front();
            have_enemy_request = true;
        }
    }

    for (const auto bot_id : destroy_requests) {
        DestroyWizardBotEntityNow(bot_id);
    }

    if (have_region_switch_request) {
        std::string error_message;
        if (!TryDispatchGameplaySwitchRegionOnGameThread(region_switch_request.region_index, &error_message)) {
            region_switch_request.next_attempt_ms = now_ms + kGameplayRegionSwitchRetryDelayMs;
            g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(
                region_switch_request.next_attempt_ms,
                std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(region_switch_request);
            }
            Log(
                "gameplay.switch_region: queued request deferred. region=" +
                std::to_string(region_switch_request.region_index) +
                " retry_in_ms=" + std::to_string(kGameplayRegionSwitchRetryDelayMs) +
                " error=" + error_message);
        }
    }

    if (have_wizard_bot_request) {
        Log(
            "[bots] pump sync bot_id=" + std::to_string(wizard_bot_request.bot_id) +
            " wizard_id=" + std::to_string(wizard_bot_request.wizard_id) +
            " has_transform=" + std::to_string(wizard_bot_request.has_transform ? 1 : 0) +
            " x=" + std::to_string(wizard_bot_request.x) +
            " y=" + std::to_string(wizard_bot_request.y) +
            " heading=" + std::to_string(wizard_bot_request.heading));
        std::string error_message;
        if (!ExecuteWizardBotSyncNow(wizard_bot_request, &error_message)) {
            wizard_bot_request.next_attempt_ms = now_ms + kWizardBotSyncRetryDelayMs;
            g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                wizard_bot_request.next_attempt_ms,
                std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
                UpsertPendingWizardBotSyncRequest(wizard_bot_request);
            }
            Log(
                "[bots] queued sync deferred. bot_id=" + std::to_string(wizard_bot_request.bot_id) +
                " wizard_id=" + std::to_string(wizard_bot_request.wizard_id) +
                " has_transform=" + std::to_string(wizard_bot_request.has_transform ? 1 : 0) +
                " x=" + std::to_string(wizard_bot_request.x) +
                " y=" + std::to_string(wizard_bot_request.y) +
                " heading=" + std::to_string(wizard_bot_request.heading) +
                " retry_in_ms=" + std::to_string(kWizardBotSyncRetryDelayMs) +
                " error=" + error_message);
        } else {
            g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                now_ms + kWizardBotSyncDispatchSpacingMs,
                std::memory_order_release);
        }
    }

    if (have_reward_request) {
        std::string error_message;
        if (!ExecuteSpawnRewardNow(
                reward_request.kind,
                reward_request.amount,
                reward_request.x,
                reward_request.y,
                &error_message)) {
            Log(
                "spawn_reward: queued request failed. kind=" + reward_request.kind +
                " amount=" + std::to_string(reward_request.amount) +
                " x=" + std::to_string(reward_request.x) +
                " y=" + std::to_string(reward_request.y) +
                " error=" + error_message);
        }
    }

    if (have_enemy_request) {
        std::string error_message;
        if (!ExecuteSpawnEnemyNow(enemy_request.type_id, enemy_request.x, enemy_request.y, nullptr, &error_message)) {
            Log(
                "spawn_enemy: queued request failed. type_id=" + std::to_string(enemy_request.type_id) +
                " x=" + std::to_string(enemy_request.x) +
                " y=" + std::to_string(enemy_request.y) +
                " error=" + error_message);
        }
    }
}

void __fastcall HookGameplayMouseRefresh(void* self, void* unused_edx) {
    const auto original =
        GetX86HookTrampoline<GameplayMouseRefreshFn>(g_gameplay_keyboard_injection.mouse_refresh_hook);
    if (original != nullptr) {
        original(self, unused_edx);
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    if (self_address == 0) {
        return;
    }

    const auto live_buffer_index =
        ProcessMemory::Instance().ReadFieldOr<int>(self_address, kGameplayInputBufferIndexOffset, -1);
    if (live_buffer_index >= 0) {
        const auto live_mouse_button_offset = static_cast<std::size_t>(
            live_buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
        const bool is_pressed =
            ProcessMemory::Instance().ReadFieldOr<std::uint8_t>(self_address, live_mouse_button_offset, 0) != 0;
        const bool was_pressed =
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.exchange(is_pressed, std::memory_order_acq_rel);
        if (is_pressed && !was_pressed) {
            RecordGameplayMouseLeftEdge();
        }
    }

    auto& pending = g_gameplay_keyboard_injection.pending_mouse_left_frames;
    auto available = pending.load(std::memory_order_acquire);
    while (available > 0) {
        if (!pending.compare_exchange_weak(
                available,
                available - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        const auto buffer_index =
            ProcessMemory::Instance().ReadFieldOr<int>(self_address, kGameplayInputBufferIndexOffset, -1);
        if (buffer_index < 0) {
            return;
        }

        const auto mouse_button_offset = static_cast<std::size_t>(
            buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
        const std::uint8_t pressed = 1;
        const bool wrote_mouse_button =
            ProcessMemory::Instance().TryWriteField(self_address, mouse_button_offset, pressed);

        uintptr_t gameplay_address = 0;
        const bool have_gameplay_address =
            TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
        const bool wrote_cast_intent =
            have_gameplay_address &&
            ProcessMemory::Instance().TryWriteField(gameplay_address, kGameplayCastIntentOffset, pressed);

        if (wrote_mouse_button || wrote_cast_intent) {
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(true, std::memory_order_release);
            auto& pending_edge_events = g_gameplay_keyboard_injection.pending_mouse_left_edge_events;
            auto available_edge_events = pending_edge_events.load(std::memory_order_acquire);
            while (available_edge_events > 0) {
                if (!pending_edge_events.compare_exchange_weak(
                        available_edge_events,
                        available_edge_events - 1,
                        std::memory_order_acq_rel,
                        std::memory_order_acquire)) {
                    continue;
                }
                RecordGameplayMouseLeftEdge();
                break;
            }
            Log(
                "Injected gameplay mouse-left click. input_state=" + HexString(self_address) +
                " buffer_index=" + std::to_string(buffer_index) +
                " gameplay=" + (have_gameplay_address ? HexString(gameplay_address) : std::string("0x00000000")) +
                " cast_intent=" + std::to_string(wrote_cast_intent ? 1 : 0));
        }
        TickWizardBotMovementControllersIfActive();
        return;
    }

    TickWizardBotMovementControllersIfActive();
}

void __fastcall HookPlayerActorTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorTickFn>(g_gameplay_keyboard_injection.player_actor_tick_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    bool standalone_puppet_actor = false;
    bool standalone_actor_moving = false;
    uintptr_t standalone_actor_world = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        if (const auto* binding = FindBotEntityForActor(actor_address);
            binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
            standalone_puppet_actor = true;
            standalone_actor_moving = binding->movement_active;
            standalone_actor_world = binding->materialized_world_address;
        }
    }

    auto& memory = ProcessMemory::Instance();
    if (standalone_puppet_actor) {
        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            standalone_actor_world,
            "player_tick",
            nullptr);
        ApplyStandaloneWizardPuppetDriveState(actor_address, standalone_actor_moving);
        original(self);
        return;
    }

    original(self);
    LogLocalPlayerAnimationProbe();
}

std::uint8_t __fastcall HookGameplayKeyboardEdge(void* self, void* /*unused_edx*/, std::uint32_t scancode) {
    if (scancode < g_gameplay_keyboard_injection.pending_scancodes.size()) {
        auto& pending = g_gameplay_keyboard_injection.pending_scancodes[scancode];
        auto available = pending.load(std::memory_order_acquire);
        while (available > 0) {
            if (pending.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return 1;
            }
        }
    }

    const auto original =
        GetX86HookTrampoline<GameplayKeyboardEdgeFn>(g_gameplay_keyboard_injection.edge_hook);
    return original != nullptr ? original(self, scancode) : 0;
}

}  // namespace

bool InitializeGameplayKeyboardInjection(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_gameplay_keyboard_injection.initialized) {
        return true;
    }

    const auto mouse_helper = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayMouseRefreshHelper);
    const auto helper = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplayKeyboardEdgeHelper);
    const auto player_actor_tick = ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorTick);
    if (mouse_helper == 0 || helper == 0 || player_actor_tick == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve gameplay input or player tick helpers.";
        }
        return false;
    }

    std::string hook_error;
    if (!InstallX86Hook(
            reinterpret_cast<void*>(mouse_helper),
            reinterpret_cast<void*>(&HookGameplayMouseRefresh),
            kGameplayMouseRefreshHookPatchSize,
            &g_gameplay_keyboard_injection.mouse_refresh_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay mouse refresh hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(helper),
            reinterpret_cast<void*>(&HookGameplayKeyboardEdge),
            kGameplayKeyboardEdgeHookPatchSize,
            &g_gameplay_keyboard_injection.edge_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install gameplay keyboard edge hook: " + hook_error;
        }
        return false;
    }

    if (!InstallX86Hook(
            reinterpret_cast<void*>(player_actor_tick),
            reinterpret_cast<void*>(&HookPlayerActorTick),
            kPlayerActorTickHookPatchSize,
            &g_gameplay_keyboard_injection.player_actor_tick_hook,
            &hook_error)) {
        RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
        RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
        if (error_message != nullptr) {
            *error_message = "Failed to install player actor tick hook: " + hook_error;
        }
        return false;
    }

    g_gameplay_keyboard_injection.initialized = true;
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.clear();
    }
    g_bot_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_wizard_bot_gameplay_snapshots.clear();
    }
    SetD3d9FrameActionPump(&PumpQueuedGameplayActions);
    Log(
        "Gameplay input injection hooks installed. mouse_refresh=" + HexString(mouse_helper) +
        " keyboard_edge=" + HexString(helper) +
        " player_tick=" + HexString(player_actor_tick));
    return true;
}

void ShutdownGameplayKeyboardInjection() {
    SetD3d9FrameActionPump(nullptr);
    RemoveX86Hook(&g_gameplay_keyboard_injection.mouse_refresh_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.edge_hook);
    RemoveX86Hook(&g_gameplay_keyboard_injection.player_actor_tick_hook);
    for (auto& pending : g_gameplay_keyboard_injection.pending_scancodes) {
        pending.store(0, std::memory_order_release);
    }
    g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(false, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_serial.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_mouse_left_frames.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.pending_start_waves_requests.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(0, std::memory_order_release);
    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(0, std::memory_order_release);
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        g_gameplay_keyboard_injection.pending_enemy_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_reward_spawn_requests.clear();
        g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.clear();
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.clear();
    }
    g_bot_entities.clear();
    {
        std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
        g_wizard_bot_gameplay_snapshots.clear();
    }
    g_gameplay_keyboard_injection.initialized = false;
}

bool IsGameplayKeyboardInjectionInitialized() {
    return g_gameplay_keyboard_injection.initialized;
}

std::uint64_t GetGameplayMouseLeftEdgeSerial() {
    return g_gameplay_keyboard_injection.mouse_left_edge_serial.load(std::memory_order_acquire);
}

std::uint64_t GetGameplayMouseLeftEdgeTickMs() {
    return g_gameplay_keyboard_injection.mouse_left_edge_tick_ms.load(std::memory_order_acquire);
}

bool QueueGameplayMouseLeftClick(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay input injection is not initialized.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_mouse_left_frames.fetch_add(
        kInjectedGameplayMouseClickFrames,
        std::memory_order_acq_rel);
    g_gameplay_keyboard_injection.pending_mouse_left_edge_events.fetch_add(1, std::memory_order_acq_rel);
    Log("Queued gameplay mouse-left click. gameplay=" + HexString(scene_address));
    return true;
}

bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay keyboard injection is not initialized.";
        }
        return false;
    }
    if (scancode > 0xFF) {
        if (error_message != nullptr) {
            *error_message = "Scancode must be in the range 0..255.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_scancodes[scancode].fetch_add(1, std::memory_order_acq_rel);
    return true;
}

bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t absolute_global = 0;
    if (!TryResolveInjectedBindingGlobal(binding_name, &absolute_global)) {
        if (error_message != nullptr) {
            *error_message =
                "Unknown gameplay key binding. Use menu, inventory, skills, or belt_slot_1..belt_slot_8.";
        }
        return false;
    }

    std::uint32_t raw_binding_code = 0;
    if (!TryReadInjectedBindingCode(absolute_global, &raw_binding_code)) {
        if (error_message != nullptr) {
            *error_message = "Failed to read the live gameplay key binding.";
        }
        return false;
    }

    if (raw_binding_code > 0xFF) {
        if (error_message != nullptr) {
            *error_message =
                "The live gameplay binding is mouse-backed. Use sd.input.click_normalized for mouse-bound actions.";
        }
        return false;
    }

    return QueueGameplayScancodePress(raw_binding_code, error_message);
}

bool QueueHubStartTestrun(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena state is not active.";
        }
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.exchange(1, std::memory_order_acq_rel);
    std::uint8_t testrun_mode_flag = 0;
    uintptr_t arena_vtable = 0;
    const bool have_testrun_mode_flag =
        ProcessMemory::Instance().TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    const bool have_arena_vtable = ProcessMemory::Instance().TryReadValue(arena_address, &arena_vtable);
    Log(
        "Queued hub testrun request. arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(kGameplaySwitchRegion) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" + HexString(kArenaStartRunDispatch) +
        " create=" + HexString(kArenaCreate) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool QueueGameplaySwitchRegion(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }
    if (region_index < 0 || region_index > kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message = "Region index is out of range.";
        }
        return false;
    }

    PendingGameplayRegionSwitchRequest request;
    request.region_index = region_index;
    request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The gameplay region switch queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(request);
    Log("gameplay.switch_region: queued region=" + std::to_string(region_index));
    return true;
}

bool QueueGameplayStartWaves(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_start_waves_requests.exchange(1, std::memory_order_acq_rel);
    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);

    ArenaWaveStartState arena_state;
    const bool have_arena_state = TryReadArenaWaveStartState(arena_address, &arena_state);
    Log(
        "Queued gameplay start_waves request. scene=" + HexString(scene_address) +
        " arena=" + HexString(arena_address) +
        " start_waves=" + HexString(kArenaStartWaves) +
        " state=" + (have_arena_state ? DescribeArenaWaveStartState(arena_state) : std::string("unreadable")));
    return true;
}

bool QueueWizardBotEntitySync(
    std::uint64_t bot_id,
    std::int32_t wizard_id,
    bool has_transform,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message) {
    PendingWizardBotSyncRequest request;
    request.bot_id = bot_id;
    request.wizard_id = wizard_id;
    request.has_transform = has_transform;
    request.x = position_x;
    request.y = position_y;
    request.heading = heading;

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (g_gameplay_keyboard_injection.initialized) {
        return QueueWizardBotSyncRequest(request, error_message);
    }

    return ExecuteWizardBotSyncNow(request, error_message);
}

bool QueueWizardBotDestroy(std::uint64_t bot_id, std::string* error_message) {
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    if (g_gameplay_keyboard_injection.initialized) {
        return QueueWizardBotDestroyRequest(bot_id, error_message);
    }

    DestroyWizardBotEntityNow(bot_id);
    return true;
}

bool TryGetWizardBotGameplayState(std::uint64_t bot_id, SDModBotGameplayState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModBotGameplayState{};
    std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
    const auto it = std::find_if(
        g_wizard_bot_gameplay_snapshots.begin(),
        g_wizard_bot_gameplay_snapshots.end(),
        [&](const WizardBotGameplaySnapshot& snapshot) {
            return snapshot.bot_id == bot_id;
        });
    if (it == g_wizard_bot_gameplay_snapshots.end()) {
        return false;
    }

    state->available = true;
    state->entity_materialized = it->entity_materialized;
    state->moving = it->moving;
    state->bot_id = it->bot_id;
    state->wizard_id = it->wizard_id;
    state->actor_address = it->actor_address;
    state->world_address = it->world_address;
    state->animation_state_ptr = it->animation_state_ptr;
    state->render_frame_table = it->render_frame_table;
    state->hub_visual_attachment_ptr = it->hub_visual_attachment_ptr;
    state->hub_visual_source_profile_address = it->hub_visual_source_profile_address;
    state->hub_visual_descriptor_signature = it->hub_visual_descriptor_signature;
    state->hub_visual_proxy_address = it->hub_visual_proxy_address;
    state->progression_handle_address = it->progression_handle_address;
    state->equip_handle_address = it->equip_handle_address;
    state->progression_runtime_state_address = it->progression_runtime_state_address;
    state->equip_runtime_state_address = it->equip_runtime_state_address;
    state->gameplay_slot = it->gameplay_slot;
    state->actor_slot = it->actor_slot;
    state->slot_anim_state_index = it->slot_anim_state_index;
    state->resolved_animation_state_id = it->resolved_animation_state_id;
    state->hub_visual_source_kind = it->hub_visual_source_kind;
    state->render_drive_flags = it->render_drive_flags;
    state->anim_drive_state = it->anim_drive_state;
    state->render_variant_primary = it->render_variant_primary;
    state->render_variant_secondary = it->render_variant_secondary;
    state->render_weapon_type = it->render_weapon_type;
    state->render_selection_byte = it->render_selection_byte;
    state->render_variant_tertiary = it->render_variant_tertiary;
    state->x = it->x;
    state->y = it->y;
    state->heading = it->heading;
    state->hp = it->hp;
    state->max_hp = it->max_hp;
    state->mp = it->mp;
    state->max_mp = it->max_mp;
    state->walk_cycle_primary = it->walk_cycle_primary;
    state->walk_cycle_secondary = it->walk_cycle_secondary;
    state->render_drive_stride = it->render_drive_stride;
    state->render_advance_rate = it->render_advance_rate;
    state->render_advance_phase = it->render_advance_phase;
    state->render_drive_overlay_alpha = it->render_drive_overlay_alpha;
    state->render_drive_move_blend = it->render_drive_move_blend;
    state->gameplay_attach_applied = it->gameplay_attach_applied;
    return true;
}

bool TryGetPlayerState(SDModPlayerState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModPlayerState{};
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    uintptr_t world_address = 0;
    const bool resolved_gameplay_address =
        TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
    if (resolved_gameplay_address) {
        (void)TryResolveLocalPlayerWorldContext(
            gameplay_address,
            &actor_address,
            &progression_address,
            &world_address);
    }

    if (actor_address == 0 || progression_address == 0 || world_address == 0) {
        (void)TryReadResolvedGamePointerAbsolute(kLocalPlayerActorGlobal, &actor_address);
        if (actor_address == 0) {
            return false;
        }

        auto& memory = ProcessMemory::Instance();
        world_address = memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
        if (world_address == 0 || !TryResolveActorProgressionRuntime(actor_address, &progression_address)) {
            return false;
        }
    }

    auto& memory = ProcessMemory::Instance();
    state->valid = true;
    state->hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
    state->max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
    state->mp = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
    state->max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    state->xp = ReadRoundedXpOrUnknown(progression_address);
    state->level = memory.ReadFieldOr<int>(progression_address, kProgressionLevelOffset, 0);
    state->x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    state->y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    state->gold = ReadResolvedGlobalIntOr(kGoldGlobal);
    state->actor_address = actor_address;
    state->render_subject_address = actor_address;
    state->world_address = world_address;
    state->progression_address = progression_address;
    state->animation_state_ptr = memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    state->render_frame_table = memory.ReadFieldOr<uintptr_t>(actor_address, kActorRenderFrameTableOffset, 0);
    state->hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualAttachmentPtrOffset, 0);
    state->hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorHubVisualSourceProfileOffset, 0);
    state->hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        actor_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    state->progression_handle_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    state->equip_handle_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
    state->equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    state->actor_slot = static_cast<int>(memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, -1));
    state->resolved_animation_state_id = ResolveActorAnimationStateId(actor_address);
    state->hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(actor_address, kActorHubVisualSourceKindOffset, 0);
    state->render_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(actor_address, kActorRenderDriveFlagsOffset, 0);
    state->anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    state->render_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantPrimaryOffset, 0);
    state->render_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantSecondaryOffset, 0);
    state->render_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderWeaponTypeOffset, 0);
    state->render_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderSelectionByteOffset, 0);
    state->render_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorRenderVariantTertiaryOffset, 0);
    state->walk_cycle_primary = memory.ReadFieldOr<float>(actor_address, kActorWalkCyclePrimaryOffset, 0.0f);
    state->walk_cycle_secondary = memory.ReadFieldOr<float>(actor_address, kActorWalkCycleSecondaryOffset, 0.0f);
    state->render_drive_stride =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    state->render_advance_rate = memory.ReadFieldOr<float>(actor_address, kActorRenderAdvanceRateOffset, 0.0f);
    state->render_advance_phase = memory.ReadFieldOr<float>(actor_address, kActorRenderAdvancePhaseOffset, 0.0f);
    state->render_drive_overlay_alpha =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveOverlayAlphaOffset, 0.0f);
    state->render_drive_move_blend =
        memory.ReadFieldOr<float>(actor_address, kActorRenderDriveMoveBlendOffset, 0.0f);

    const auto render_subject_address = state->render_subject_address;
    state->render_subject_animation_state_ptr =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorAnimationSelectionStateOffset, 0);
    state->render_subject_frame_table =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorRenderFrameTableOffset, 0);
    state->render_subject_hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorHubVisualAttachmentPtrOffset, 0);
    state->render_subject_hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(render_subject_address, kActorHubVisualSourceProfileOffset, 0);
    state->render_subject_hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_subject_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    state->render_subject_hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(render_subject_address, kActorHubVisualSourceKindOffset, 0);
    state->render_subject_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(render_subject_address, kActorRenderDriveFlagsOffset, 0);
    state->render_subject_anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorAnimationDriveStateByteOffset, 0);
    state->render_subject_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantPrimaryOffset, 0);
    state->render_subject_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantSecondaryOffset, 0);
    state->render_subject_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderWeaponTypeOffset, 0);
    state->render_subject_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderSelectionByteOffset, 0);
    state->render_subject_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(render_subject_address, kActorRenderVariantTertiaryOffset, 0);
    state->gameplay_attach_applied = true;
    return true;
}

bool TryGetWorldState(SDModWorldState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModWorldState{};
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    state->valid = true;
    state->wave = GetRunLifecycleCurrentWave();
    if (state->wave <= 0) {
        state->wave = ProcessMemory::Instance().ReadFieldOr<int>(arena_address, kArenaCombatWaveIndexOffset, 0);
    }
    state->enemy_count = ReadResolvedGlobalIntOr(kEnemyCountGlobal);
    state->time_elapsed_ms = GetRunLifecycleElapsedMilliseconds();
    return true;
}

bool TryGetSceneState(SDModSceneState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModSceneState{};

    uintptr_t gameplay_scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_scene_address) || gameplay_scene_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    (void)TryBuildSceneContextSnapshot(gameplay_scene_address, &scene_context);
    state->valid = true;
    state->kind = DescribeSceneKind(scene_context);
    state->name = DescribeSceneName(scene_context);
    state->gameplay_scene_address = gameplay_scene_address;
    state->world_address = scene_context.world_address;
    state->arena_address = scene_context.arena_address;
    state->region_state_address = scene_context.region_state_address;
    state->current_region_index = scene_context.current_region_index;
    state->region_type_id = scene_context.region_type_id;
    state->pending_level_kind = ReadResolvedGlobalIntOr(kPendingLevelKindGlobal);
    state->transition_target_a = ReadResolvedGlobalIntOr(kTransitionTargetAGlobal);
    state->transition_target_b = ReadResolvedGlobalIntOr(kTransitionTargetBGlobal);
    return true;
}

bool SpawnEnemyByType(int type_id, float x, float y, std::string* error_message) {
    if (g_gameplay_keyboard_injection.initialized) {
        PendingEnemySpawnRequest request;
        request.type_id = type_id;
        request.x = x;
        request.y = y;
        return QueueEnemySpawnRequest(request, error_message);
    }

    return ExecuteSpawnEnemyNow(type_id, x, y, nullptr, error_message);
}

bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (g_gameplay_keyboard_injection.initialized) {
        PendingRewardSpawnRequest request;
        request.kind = std::string(kind);
        request.amount = amount;
        request.x = x;
        request.y = y;
        return QueueRewardSpawnRequest(request, error_message);
    }

    return ExecuteSpawnRewardNow(kind, amount, x, y, error_message);
}

}  // namespace sdmod
