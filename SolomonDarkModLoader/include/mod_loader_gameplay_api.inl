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
void PinRunLifecycleFrozenManualEnemies();
void ClearRunLifecycleManualEnemyFreeze(uintptr_t actor_address = 0);
bool TryGetPlayerState(SDModPlayerState* state);
bool TryGetPlayerInventoryState(SDModInventoryState* state);
bool TryGetPlayerProgressionBookState(SDModProgressionBookState* state);
bool TryGetWorldState(SDModWorldState* state);
bool TryGetGameplayCombatState(SDModGameplayCombatState* state);
bool IsArenaCombatActorType(std::uint32_t object_type_id);
bool TryGetSceneState(SDModSceneState* state);
bool TryListSceneActors(std::vector<SDModSceneActorState>* actors);
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
    std::uint64_t* participant_id = nullptr);
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
bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message);
bool QueueReplicatedLootSnapshot(
    const multiplayer::LootSnapshotRuntimeInfo& snapshot,
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
