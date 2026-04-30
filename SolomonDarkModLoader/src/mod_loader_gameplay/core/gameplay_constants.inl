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
// 0x0054BA80 is PlayerActor vtable +0x1c in the current binary. It begins with
// one 8-byte instruction followed by a 7-byte instruction, so the detour must
// stop exactly at the 8-byte boundary.
constexpr std::size_t kActorAnimationAdvanceHookPatchSize = 8;
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
constexpr bool kEnableWizardBotHotPathDiagnostics = false;
constexpr bool kEnableLocalPlayerCastProbeDiagnostics = false;
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
constexpr std::uint8_t kTargetHandleGroupSentinel = 0xFF;
constexpr std::uint16_t kTargetHandleSlotSentinel = 0xFFFF;
constexpr std::size_t kActorSpellTargetGroupByteOffset = 0x164;
constexpr std::size_t kActorSpellTargetSlotShortOffset = 0x166;
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
