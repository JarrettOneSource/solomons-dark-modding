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
    const SDModLuaEnemySpawnConfig& lua_config,
    int type_id,
    float x,
    float y,
    std::string* error_message,
    std::uint64_t* request_id);
bool QueueRunLifecycleLuaEnemySpawn(
    const SDModLuaEnemySpawnConfig& config,
    int type_id,
    float x,
    float y,
    std::string* error_message,
    std::uint64_t* request_id);
void CancelQueuedRunLifecycleReplicatedEnemyCatchupSpawn(std::uint64_t network_actor_id);
bool TryGetRunLifecycleLuaEnemySpawnConfig(
    uintptr_t enemy_address,
    SDModLuaEnemySpawnConfig* config);
bool SetLuaEnemyAiTargetOverride(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    SDModLuaEnemyAiTargetMode target_mode,
    std::uint64_t target_participant_id,
    std::string* error_message);
bool SetLuaEnemyAiMoveGoal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    std::uint64_t content_id,
    std::uint32_t spawn_serial,
    uintptr_t actor_address,
    float x,
    float y,
    float stop_distance,
    std::string* error_message);
bool StopLuaEnemyAiMoveGoal(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id);
bool ClearLuaEnemyAiOverrides(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id);
bool TryGetLuaEnemyAiCommandState(
    std::string_view owner_mod_id,
    std::uint64_t network_actor_id,
    SDModLuaEnemyAiCommandState* state);
void ClearLuaEnemyAiOverridesForMod(std::string_view owner_mod_id);
void ResetLuaEnemyAiOverrides();
void ForgetRunLifecycleEnemyTracking(uintptr_t enemy_address);
bool PumpRunLifecycleManualEnemySpawnRequest(std::string* error_message = nullptr);
bool TryGetRunLifecycleManualEnemySpawnResult(
    SDModManualRunEnemySpawnResult* result,
    std::uint64_t request_id = 0);
bool TryGetRunLifecycleManualEnemyFreezePosition(uintptr_t actor_address, float* x, float* y);
bool RestoreRunLifecycleFrozenManualEnemyPosition(uintptr_t actor_address);
void PinRunLifecycleFrozenManualEnemies();
void ClearRunLifecycleManualEnemyFreeze(uintptr_t actor_address = 0);
bool TryGetPlayerState(SDModPlayerState* state);
bool RestoreLocalPlayerMana(
    float* resulting_mana,
    std::string* error_message);
bool ResetLocalPlayerManaDeltaObservation();
bool TakeLocalPlayerManaDeltaObservation(
    SDModLocalManaDeltaObservation* observation);
bool TryGetPlayerInventoryState(SDModInventoryState* state);
bool QueuePlayerInventoryItemEquip(
    std::uint32_t recipe_uid,
    std::string* error_message);
bool TryResolveNativeItemRecipeByName(
    std::string_view recipe_name,
    std::uint32_t expected_item_type_id,
    std::uint32_t* recipe_uid,
    std::string* error_message);
bool QueueLuaItemGrantToLocalInventory(
    std::uint64_t authority_participant_id,
    std::uint64_t request_id,
    std::uint64_t content_id,
    const std::array<std::uint8_t, multiplayer::kParticipantVisualLinkColorBlockBytes>&
        color_state,
    bool color_state_valid,
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
bool TryTestGameplayNavSegment(
    float from_x,
    float from_y,
    float to_x,
    float to_y,
    bool* traversable,
    std::string* error_message);
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
bool QueueLuaConsumableDrop(
    std::int32_t native_subtype,
    float x,
    float y,
    std::string* error_message);
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
bool QueueAcceptedReplicatedGoldPickupFeedback(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t amount,
    std::int32_t resulting_gold,
    std::uint64_t accepted_ms,
    std::string* error_message);
bool QueueAcceptedReplicatedOrbPickupFeedback(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t resource_kind,
    float resource_delta,
    float resulting_life_current,
    float resulting_life_max,
    float resulting_mana_current,
    float resulting_mana_max,
    std::uint64_t accepted_ms,
    std::string* error_message);
bool QueueAcceptedReplicatedPowerupPickupFeedback(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    std::uint32_t request_sequence,
    std::int32_t powerup_kind,
    std::int32_t powerup_skill_entry_index,
    std::uint16_t powerup_skill_resulting_active,
    std::int32_t damage_x4_remaining_ticks,
    std::uint64_t accepted_ms,
    std::string* error_message);
bool IsApplyingAcceptedReplicatedGoldPickupFeedback();
void CancelReplicatedLootPickupFeedback(std::uint64_t network_drop_id);
void CancelReplicatedGoldPickupFeedback(std::uint64_t network_drop_id);
bool TryGetLastReplicatedLootPickupFeedbackState(
    SDModReplicatedLootPickupFeedbackState* state);
bool TryGetLastReplicatedGoldPickupFeedbackState(
    SDModReplicatedGoldPickupFeedbackState* state);
void SuppressClientLocalLootActors(const char* reason);
bool HasReplicatedRunEnemyDeathPresentation(std::uint64_t network_actor_id);
void MarkReplicatedRunEnemyDeathPresented(std::uint64_t network_actor_id);
void ClearReplicatedRunEnemyDeathPresentation(std::uint64_t network_actor_id);

}  // namespace sdmod
