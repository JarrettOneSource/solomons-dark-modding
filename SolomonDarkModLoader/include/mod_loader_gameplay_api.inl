bool IsRunLifecycleActive();
bool EndRunLifecycleFromExternal(std::string_view reason);
int GetRunLifecycleCurrentWave();
std::uint64_t GetRunLifecycleElapsedMilliseconds();
void SetRunLifecycleCombatPreludeOnlySuppression(bool enabled);
void SetRunLifecycleWaveStartEnemyTracking(bool enabled);
void SetRunLifecycleManualEnemySpawnerTestMode(bool enabled);
bool IsRunLifecycleManualEnemySpawnerTestModeEnabled();
void GetRunLifecycleTrackedEnemies(std::vector<SDModTrackedEnemyState>* enemies);
bool TryGetRunLifecycleEnemySpawnSerial(uintptr_t enemy_address, std::uint32_t* spawn_serial);
bool TryAccelerateRunLifecycleEnemyPoolForSnapshot(int enemy_type, std::uint32_t missing_enemy_count);
uintptr_t GetRunLifecycleLastWaveSpawnerAddress();
bool IsRunLifecycleManualEnemySpawnerReady();

bool QueueRunLifecycleManualEnemySpawn(
    int type_id,
    float x,
    float y,
    bool freeze_on_spawn,
    std::string* error_message,
    std::uint64_t* request_id);
bool QueueRunLifecycleReplicatedEnemyCatchupSpawn(
    std::uint64_t network_actor_id,
    int type_id,
    float x,
    float y,
    std::string* error_message,
    std::uint64_t* request_id);
void CancelQueuedRunLifecycleReplicatedEnemyCatchupSpawn(std::uint64_t network_actor_id);
bool PumpRunLifecycleManualEnemySpawnRequest(std::string* error_message = nullptr);
bool TryGetRunLifecycleManualEnemySpawnResult(
    SDModManualRunEnemySpawnResult* result,
    std::uint64_t request_id = 0);
bool TryGetRunLifecycleManualEnemyFreezePosition(uintptr_t actor_address, float* x, float* y);
bool RestoreRunLifecycleFrozenManualEnemyPosition(uintptr_t actor_address);
void PinRunLifecycleFrozenManualEnemies();
void ClearRunLifecycleManualEnemyFreeze(uintptr_t actor_address = 0);
bool TryGetPlayerState(SDModPlayerState* state);
bool ResetLocalPlayerManaDeltaObservation();
bool TakeLocalPlayerManaDeltaObservation(
    SDModLocalManaDeltaObservation* observation);
bool TryGetPlayerInventoryState(SDModInventoryState* state);
bool QueuePlayerInventoryItemEquip(
    std::uint32_t recipe_uid,
    std::string* error_message);
bool QueueNestedSackInventoryFixture(
    std::int32_t potion_slot,
    std::int32_t stack_count,
    std::string* error_message);
bool TryGetPlayerProgressionBookState(SDModProgressionBookState* state);
bool TryGetWorldState(SDModWorldState* state);
bool TryGetGameplayCombatState(SDModGameplayCombatState* state);
bool IsArenaCombatActorType(std::uint32_t object_type_id);
bool TryGetSceneState(SDModSceneState* state);
bool TryListSceneActors(std::vector<SDModSceneActorState>* actors);
bool TryListNativeActorModifiers(
    uintptr_t actor_address,
    std::vector<SDModNativeModifierState>* modifiers);
bool TryListRecentNativeSpellEffectActors(
    std::vector<SDModNativeSpellEffectActorState>* actors);
bool TryGetGameplaySelectionDebugState(SDModGameplaySelectionDebugState* state);
bool RunWithParticipantConcentrationContext(
    std::uint64_t participant_id,
    const std::function<bool()>& operation,
    std::string* error_message);
bool TryApplyParticipantConcentrationSelections(
    std::uint64_t participant_id,
    std::int32_t entry_a,
    std::int32_t entry_b,
    std::string* error_message);
bool TryReconcileParticipantConcentrationRuntimeSelections(
    std::uint64_t participant_id,
    std::int32_t entry_a,
    std::int32_t entry_b,
    std::string* error_message);
bool TryGetGameplayNavGridState(SDModGameplayNavGridState* state, int subdivisions = 1);
void RequestNavGridSnapshotRebuild(int subdivisions);
std::shared_ptr<const SDModGameplayNavGridState> GetLastNavGridSnapshotShared();
void RebuildNavGridSnapshotIfRequested_GameplayThread();
void FlushNavGridSnapshotOnSceneUnload();
bool TryGetParticipantGameplayState(
    std::uint64_t participant_id,
    SDModParticipantGameplayState* state);
bool TryRefreshParticipantGameplayState(
    std::uint64_t participant_id,
    SDModParticipantGameplayState* state);
bool TryGetGameplayHudParticipantDisplayNameForActor(
    uintptr_t actor_address,
    std::string* display_name,
    std::uint64_t* participant_id = nullptr,
    float* health_ratio = nullptr);
bool RebindSceneActorCell(uintptr_t actor_address, std::string* error_message);
bool QueueManualRunEnemySpawn(
    int type_id,
    float x,
    float y,
    bool freeze_on_spawn,
    std::string* error_message,
    std::uint64_t* request_id = nullptr);
bool TryGetLastManualRunEnemySpawnResult(
    SDModManualRunEnemySpawnResult* result,
    std::uint64_t request_id = 0);
void ClearManualRunEnemyFreeze(uintptr_t actor_address = 0);
bool RetireTestRunPlayerCreatedActors(
    std::uint32_t native_type_id,
    std::uint32_t* requested_count,
    std::string* error_message);
bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message);
bool QueueReplicatedLootSnapshot(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
    std::string* error_message);
bool QueueHostLootDropDeactivation(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    multiplayer::LootDropKind drop_kind,
    std::string* error_message);
bool TryTakeHostLootDropDeactivationResult(
    SDModHostLootDropDeactivationResult* result);
void ClearHostLootDropDeactivationState();
bool QueueNativeInventoryCredit(
    std::uint64_t authority_participant_id,
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t item_type_id,
    std::uint32_t item_recipe_uid,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        item_color_state,
    bool item_color_state_valid,
    std::int32_t item_slot,
    std::int32_t stack_count,
    std::uint32_t inventory_revision,
    std::string* error_message);
bool IsReplicatedLootPresentationActor(uintptr_t actor_address);
bool TryGetReplicatedLootPresentationState(
    std::uint64_t network_drop_id,
    SDModReplicatedLootPresentationState* state);
void GetReplicatedLootPresentationStates(std::vector<SDModReplicatedLootPresentationState>* states);
void SuppressClientLocalLootActors(const char* reason);
bool HasReplicatedRunEnemyDeathPresentation(std::uint64_t network_actor_id);
void MarkReplicatedRunEnemyDeathPresented(std::uint64_t network_actor_id);
void ClearReplicatedRunEnemyDeathPresentation(std::uint64_t network_actor_id);

}  // namespace sdmod
