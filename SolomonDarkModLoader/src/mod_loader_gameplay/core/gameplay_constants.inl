constexpr std::size_t kGameplayMouseRefreshHookPatchSize = 8;
constexpr std::size_t kGameplayKeyboardEdgeHookPatchSize = 9;
constexpr std::size_t kPlayerActorTickHookPatchSize = 6;
constexpr std::size_t kPlayerActorEnsureProgressionHandleHookPatchSize = 7;
constexpr std::size_t kPlayerActorApplyManaDeltaHookPatchSize = 5;
constexpr std::size_t kPlayerActorDtorHookPatchSize = 12;
constexpr bool kEnablePlayerActorDtorHook = false;
constexpr std::size_t kPlayerActorVtable28HookPatchSize = 6;
constexpr std::size_t kPlayerActorSecondarySpellCastHookMinimumPatchSize = 5;
// SecondaryCursorWorldProjection starts with a three-byte stack reservation
// followed by a six-byte world-origin load. The safe hook keeps both whole.
constexpr std::size_t kSecondaryCursorWorldProjectionHookMinimumPatchSize = 5;
constexpr std::size_t kPlayerActorMagicDamageHookMinimumPatchSize = 5;
// Badguy::Contact starts with sub esp,8; push ebx; push esi (five bytes).
constexpr std::size_t kBadguyDamageHookMinimumPatchSize = 5;
// Mod_Poisoned::Tick begins with one whole five-byte absolute load.
constexpr std::size_t kPoisonedModifierTickHookMinimumPatchSize = 5;
// Mod_Webbed::Tick starts with `push ecx` followed by the six-byte absolute
// load of the active actor. Seven bytes preserve whole instructions.
constexpr std::size_t kWebbedModifierTickHookMinimumPatchSize = 7;
constexpr std::size_t kPlayerActorPurePrimaryGateHookMinimumPatchSize = 5;
constexpr std::size_t kPlayerControlBrainUpdateHookMinimumPatchSize = 5;
constexpr std::size_t kPurePrimarySpellStartHookMinimumPatchSize = 5;
constexpr std::size_t kPurePrimaryAttackDispatchHookMinimumPatchSize = 5;
constexpr std::size_t kFireEmberCtorHookMinimumPatchSize = 5;
constexpr std::size_t kSpellCastDispatcherHookMinimumPatchSize = 5;
// 0x0044F5F0 starts with two whole instructions:
//   push -1           (2 bytes)
//   push 0x76559b     (5 bytes)
// A 5-byte hook splits the second instruction and makes the trampoline invalid.
constexpr std::size_t kSpellActionBuilderHookMinimumPatchSize = 7;
constexpr std::size_t kSpellBuilderResetHookMinimumPatchSize = 5;
constexpr std::size_t kSpellBuilderFinalizeHookMinimumPatchSize = 5;
constexpr std::size_t kGameplayHudRenderDispatchHookPatchSize = 6;
// Glyph_Draw begins with push ebp; mov ebp,esp; and esp,0xfffffff8 (6 bytes).
constexpr std::size_t kGameplayUiGlyphDrawHookPatchSize = 6;
constexpr std::size_t kGameplayUiCenteredGlyphDrawHookPatchSize = 6;
constexpr std::size_t kPuppetManagerDeletePuppetHookPatchSize = 6;
// 0x004024C0 starts with 5 bytes of whole instructions:
//   push ebp; mov ebp, esp; push ebx; push esi
// Using 6 bytes splits the following `mov esi, [ebp+0x8]` and corrupts the
// trampoline. Keep this hook boundary at 5 unless the function prologue is
// re-audited.
constexpr std::size_t kPointerListDeleteBatchHookPatchSize = 5;
// Object_Delete at 0x004024A0 treats each batch entry as a managed callback
// wrapper. Byte +0x06 requests a call through the callback cell at +0x00.
constexpr std::size_t kManagedPointerReleaseCallbackCellOffset = 0x00;
constexpr std::size_t kManagedPointerReleaseCallbackEnabledOffset = 0x06;
constexpr std::size_t kManagedPointerReleaseOwnerVtableOffset = 0x28;
constexpr int kManagedPointerReleasePreflightMaxCount = 4096;
constexpr std::size_t kActorWorldUnregisterHookPatchSize = 6;
constexpr std::size_t kGameplaySwitchRegionHookMinimumPatchSize = 5;
constexpr int kWizardSourceActorFactoryTypeId = 0x1397;
// 0x0054BA80 is PlayerActor vtable +0x1c in the current binary. It begins with
// one 8-byte instruction followed by a 7-byte instruction, so the detour must
// stop exactly at the 8-byte boundary.
constexpr std::size_t kActorAnimationAdvanceHookPatchSize = 8;
constexpr std::size_t kMonsterPathfindingRefreshTargetHookMinimumPatchSize = 5;
constexpr std::size_t kBadguyMoveStepHookMinimumPatchSize = 5;
constexpr std::size_t kGoldPickupHookMinimumPatchSize = 5;
constexpr std::size_t kOrbPickupHookMinimumPatchSize = 5;
constexpr std::size_t kItemDropPickupHookMinimumPatchSize = 5;
constexpr std::size_t kPowerupPickupHookMinimumPatchSize = 5;
constexpr int kArenaRegionIndex = 5;
constexpr std::size_t kStandaloneWizardVisualRuntimeSize = 0x8E4;
// PlayerActor::CastSecondary toggles these three persistent profile bytes for
// Firewalker (row 0x17), Mindstar (0x4E), and Regenerate (0x4F).
constexpr std::size_t kWizardProfileFirewalkerActiveOffset = 0x8DC;
constexpr std::size_t kWizardProfileMindstarActiveOffset = 0x8DD;
constexpr std::size_t kWizardProfileRegenerateActiveOffset = 0x8DE;
// PlayerActor owns a PointerList<SmartPointer<Mod>> at +0x104. Its count and
// storage lanes expose active stock modifiers without inventing parallel
// status state. These IDs come from the stock modifier constructors.
constexpr std::size_t kActorModifierListOffset = 0x104;
constexpr std::size_t kActorModifierListCountOffset = 0x10C;
constexpr std::size_t kActorModifierListStorageOffset = 0x118;
constexpr std::size_t kPointerListRemoveValueVtableOffset = 0x1C;
constexpr std::size_t kNativeModifierTypeIdOffset = 0x08;
constexpr std::size_t kNativeModifierDurationTicksOffset = 0x14;
constexpr std::size_t kNativePoisonDamagePerTickOffset = 0x1C;
constexpr std::size_t kNativePoisonSourceSlotOffset = 0x20;
constexpr std::size_t kNativeWebbedStrengthOffset = 0x1C;
constexpr std::size_t kNativeWebbedRequestedStrengthOffset = 0x20;
constexpr std::uint32_t kNativeStoneskinModifierTypeId = 0x1B71;
constexpr std::uint32_t kNativePoisonModifierTypeId = 0x1B72;
constexpr std::uint32_t kNativePrismaticModifierTypeId = 0x1B76;
constexpr std::uint32_t kNativeWebbedModifierTypeId = 0x1B79;
constexpr std::uint32_t kNativeRingIceModifierTypeId = 0x1B6F;
constexpr std::size_t kStandaloneWizardVisualLinkSize = 0xA8;
constexpr std::size_t kStandaloneWizardVisualLinkColorBlockOffset = 0x88;
constexpr std::size_t kStandaloneWizardVisualLinkResetStateOffset = 0x1C;
constexpr std::size_t kStandaloneWizardVisualLinkActiveFlagOffset = 0x58;
constexpr std::uint32_t kStandaloneWizardHatVisualTypeId = 0x1B5D;
constexpr std::uint32_t kStandaloneWizardRobeVisualTypeId = 0x1B5E;
// Stock inventory lists use base Item objects as empty grid placeholders.
// They are implementation detail, not participant-owned inventory rows.
constexpr std::uint32_t kInventoryPlaceholderItemTypeId = 0x1B58;
constexpr std::uint32_t kInventoryPotionItemTypeId = 0x1B59;
constexpr std::uint32_t kInventorySackItemTypeId = 0x1B60;
constexpr std::uint32_t kInventoryMiscItemTypeId = 0x1B64;
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
constexpr std::size_t kStandaloneWizardAttachmentStaffVisualStateOffset = 0x84;
constexpr std::uint32_t kStandaloneWizardStaffItemTypeId = 0x1B5C;
constexpr std::uint32_t kStandaloneWizardWandItemTypeId = 0x1B63;
constexpr std::uint32_t kStandaloneWizardRingItemTypeId = 0x1B5A;
constexpr std::uint32_t kStandaloneWizardAmuletItemTypeId = 0x1B5B;
// Object_Ctor treats +0x04..+0x07 as object-header state, not an actor-owned
// render-context pointer. Keep the raw word available for dumps and probes, but
// do not treat it as a transferable render node.
constexpr std::size_t kActorAnimationConfigBlockSize = 0x0C;
constexpr std::size_t kGameplayIndexStateActorSelectionBaseIndex = 0x0C;
// Concentrate has two related stock representations. Progression refresh reads
// the slot-0 entries at 16 and 20, so refreshing a remote native participant
// must swap those two values transactionally. Runtime behaviors (for example
// Fortunate Flailing at 0x00537AA0) instead read 16+actor_slot and
// 20+actor_slot, so every materialized participant also needs persistent
// per-gameplay-slot lanes.
constexpr std::size_t kGameplayIndexStateConcentrationAIndex = 0x10;
constexpr std::size_t kGameplayIndexStateConcentrationBIndex = 0x14;
// Skills_Wizard row 0x43 is Rush. Its ranked mValue remains dynamic and is
// intentionally not baked into progression+0x90 by the stock stat refresh.
constexpr int kRushProgressionEntryIndex = 0x43;
// Stock symbol note: +0x22C is a packed discrete frame offset/countdown field, not a pointer.
constexpr std::size_t kActorHubVisualDescriptorBlockSize = 0x20;
constexpr int kActorAnimationStateSlotBias = 0x0C;
constexpr int kUnknownAnimationStateId = -1;
constexpr std::uint8_t kDeadWizardBotCorpseDriveState = 1;
constexpr float kWizardHeadingRadiansToDegrees = 57.2957795130823208767981548141051703f;
constexpr int kGameplayInputBufferCount = 2;
constexpr std::size_t kGameplayInputBufferStride = 0x203;
constexpr std::uint64_t kWaveStartRetryDelayMs = 250;
constexpr std::uint64_t kWizardBotSyncRetryDelayMs = 250;
constexpr std::uint64_t kWizardBotSyncDispatchSpacingMs = 500;
constexpr std::uint64_t kWizardBotSceneBindingTickIntervalMs = 50;
constexpr bool kEnableWizardBotHotPathDiagnostics = false;
constexpr bool kEnableLocalPlayerCastProbeDiagnostics = false;
constexpr float kWizardBotPathWaypointArrivalThreshold = 12.0f;
constexpr float kWizardBotPathFinalArrivalThreshold = 8.0f;
constexpr std::uint64_t kWizardBotPathRetryDelayMs = 500;
constexpr std::uint64_t kGameplayRegionSwitchRetryDelayMs = 250;
constexpr std::uint64_t kGameplayRegionSwitchDispatchSpacingMs = 500;
// Native region switches can expose a nonzero world before the stock actor
// containers are safe for remote participant materialization. The local
// multiplayer pair can hit this during create->hub startup; keep the churn
// window long enough to defer clone/rematerialization work past that native
// teardown/rebind window.
constexpr std::uint64_t kGameplaySceneChurnDelayMs = 3000;
constexpr std::uint64_t kRemoteParticipantSpawnSceneStableDelayMs = 1500;
// Initial hub construction can keep retiring stock UI/puppet allocations after
// its world pointer and slot-0 vitals already look valid. Two additional peers
// make that window long enough for a gameplay-slot actor to collide with stock
// heap cleanup. Run transitions also carry kGameplaySceneChurnDelayMs, but the
// create->hub path does not, so give shared-hub materialization its own gate.
constexpr std::uint64_t kRemoteParticipantSpawnHubSceneStableDelayMs = 4500;
constexpr DWORD kHubStartTestrunDispatchCooldownMs = 5000;
constexpr std::uint32_t kInjectedGameplayMouseClickFrames = 2;
// FUN_0052C910 arms the stock control-brain action cooldown at +0x10 from
// native random windows such as 50..150 ticks. Bot casts use the same
// actor-owned field after native completion so Lua readiness follows the
// control-brain rearm path instead of owning an element timer.
constexpr std::int32_t kBotNativeActionRearmMinTicks = 50;
constexpr std::int32_t kBotNativeActionRearmMaxTicks = 150;
constexpr std::int32_t kBotNativeActionRearmTicks =
    (kBotNativeActionRearmMinTicks + kBotNativeActionRearmMaxTicks) / 2;
constexpr std::uint64_t kBotManaReserveRecoveryIntervalMs = 250;
constexpr float kBotManaReserveRecoveryRatioPerSecond = 0.10f;

constexpr std::uint8_t kHagathaCuringSelector = 11;
constexpr std::uint8_t kHagathaGlassCannonSelector = 16;
constexpr std::uint8_t kHagathaCurseBossesSelector = 22;
constexpr float kHagathaCurseBossesDamageMultiplier = 3.0f;
constexpr std::uint32_t kEtherPrimaryDamageSourceNativeTypeId = 0x7D3;
constexpr std::uint32_t kFireballDamageSourceNativeTypeId = 0x7D4;
constexpr std::uint32_t kWaterPrimaryDamageSourceNativeTypeId = 0x7D5;
constexpr std::uint32_t kFireEmberDamageSourceNativeTypeId = 0x7D6;
constexpr std::uint32_t kFirewalkerDamageSourceNativeTypeId = 0x7EE;
constexpr std::uint32_t kMagicStormDamageSourceNativeTypeId = 0x7F0;
constexpr std::uint32_t kMagicTrapDamageSourceNativeTypeId = 0x7F5;

bool IsHagathaCurseBossesNativeType(std::uint32_t object_type_id) {
    return IsStockBossEnemyNativeType(
        static_cast<std::int32_t>(object_type_id));
}

bool IsPlayerAuthoredDamageSourceNativeType(std::uint32_t object_type_id) {
    return object_type_id == kEtherPrimaryDamageSourceNativeTypeId ||
           object_type_id == kFireballDamageSourceNativeTypeId ||
           object_type_id == kWaterPrimaryDamageSourceNativeTypeId ||
           object_type_id == kFireEmberDamageSourceNativeTypeId ||
           object_type_id == kFirewalkerDamageSourceNativeTypeId ||
           object_type_id == kMagicStormDamageSourceNativeTypeId ||
           object_type_id == kMagicTrapDamageSourceNativeTypeId;
}

bool IsArenaCombatActorTypeInternal(std::uint32_t object_type_id) {
    // WaveData_Parse and FUN_0062D920 identify the stock arena enemy classes.
    // Most use the original 1001..1013 family. Spider and Imp Portal are
    // direct wave entries, while Green Imp and Maggot are hostile children
    // created by those native classes.
    constexpr std::uint32_t kFirstArenaCombatActorType = 1001;
    constexpr std::uint32_t kLastArenaCombatActorType = 1013;
    constexpr std::uint32_t kGreenImpArenaCombatActorType = 0x7FC;
    constexpr std::uint32_t kMaggotArenaCombatActorType = 0x7FD;
    constexpr std::uint32_t kSpiderArenaCombatActorType = 0x809;
    constexpr std::uint32_t kImpPortalArenaCombatActorType = 0x139D;
    return (object_type_id >= kFirstArenaCombatActorType &&
            object_type_id <= kLastArenaCombatActorType) ||
           object_type_id == kGreenImpArenaCombatActorType ||
           object_type_id == kMaggotArenaCombatActorType ||
           object_type_id == kSpiderArenaCombatActorType ||
           object_type_id == kImpPortalArenaCombatActorType;
}
constexpr std::size_t kQueuedGameplayWorldActionLimit = 64;
constexpr std::uint64_t kNativeInventoryCreditRetryDelayMs = 100;
constexpr std::uint64_t kNativeInventoryCreditExpiryMs = 15000;
constexpr std::uint32_t kNativeInventoryCreditMaxAttempts = 100;
constexpr std::uint64_t kLuaItemGrantRetryDelayMs = 100;
constexpr std::uint64_t kLuaItemGrantExpiryMs = 15000;
constexpr std::uint32_t kLuaItemGrantMaxAttempts = 100;
constexpr int kSpawnRewardDefaultLifetime = 0;
constexpr int kUnknownXpSentinel = -1;
constexpr int kFirstWizardBotSlot = 1;
constexpr int kHubRegionIndex = 0;
constexpr std::uint8_t kTargetHandleGroupSentinel = 0xFF;
constexpr std::uint16_t kTargetHandleSlotSentinel = 0xFFFF;
constexpr int kPrimaryComboDispatcherSelectionState = 0x34;
constexpr std::size_t kHostileTargetBucketDeltaOffset = 0x164;
constexpr std::size_t kSceneActorBucketScanCount = 0x2000;
constexpr int kSceneTypeHub = 0xFA1;
constexpr int kSceneTypeMemorator = 0xFA2;
constexpr int kSceneTypeDowser = 0xFA3;
constexpr int kSceneTypeLibrarian = 0xFA4;
constexpr int kSceneTypePolisherArch = 0xFA5;
constexpr int kSceneTypeArena = 0xFA6;

// ---- Wizard clone-source actor contract ----
// FUN_0061AA00 accepts stock-prepared source actors whose actor+0x174 kind is 3.
// The loader fills a transient source profile only from native Skills_Wizard
// color output, then lets FUN_005E3080 build the stock descriptor window.
constexpr std::int32_t kWizardCloneSourceActorKind = 3;
constexpr std::size_t kNativeDerivedSourceProfileSize = 0x100;
