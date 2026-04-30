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
    std::uint32_t primary_entry_arg,
    std::uint32_t combo_entry_arg,
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
bool PreparePendingWizardBotCast(ParticipantEntityBinding* binding, std::string* error_message);
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
