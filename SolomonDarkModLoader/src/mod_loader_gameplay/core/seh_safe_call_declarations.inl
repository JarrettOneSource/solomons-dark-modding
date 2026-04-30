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
