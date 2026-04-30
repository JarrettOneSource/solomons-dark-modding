bool TryReadArenaWaveStartState(uintptr_t arena_address, ArenaWaveStartState* state);
std::string DescribeArenaWaveStartState(const ArenaWaveStartState& candidate);

bool TryRebindActorToOwnerWorld(
    uintptr_t actor_address,
    uintptr_t fallback_world_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto rebind_actor_address = memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
    if (rebind_actor_address == 0) {
        return false;
    }

    const auto world_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, fallback_world_address);
    if (world_address == 0) {
        return false;
    }

    return CallWorldCellGridRebindActorSafe(
        rebind_actor_address,
        world_address,
        actor_address,
        exception_code);
}

bool TryUpdateParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* /*error_message*/) {
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    auto* binding = FindParticipantEntity(request.bot_id);
    if (binding == nullptr || binding->actor_address == 0) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, &x, &y, &heading)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(binding->actor_address, kActorPositionXOffset, x) ||
        !memory.TryWriteField(binding->actor_address, kActorPositionYOffset, y)) {
        DematerializeParticipantEntityNow(request.bot_id, true, "update transform write failed");
        return false;
    }
    DWORD rebind_exception_code = 0;
    if (!TryRebindActorToOwnerWorld(
            binding->actor_address,
            binding->materialized_world_address,
            &rebind_exception_code)) {
        Log(
            "[bots] participant transform rebind failed. bot_id=" +
            std::to_string(request.bot_id) +
            " actor=" + HexString(binding->actor_address) +
            " exception=" + HexString(rebind_exception_code));
    }

    ApplyWizardActorFacingState(binding->actor_address, heading);
    binding->character_profile = request.character_profile;
    binding->scene_intent = request.scene_intent;
    PublishParticipantGameplaySnapshot(*binding);
    return true;
}

bool TrySpawnStandaloneRemoteWizardParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message);

bool TrySpawnRegisteredGameNpcParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message);

bool TrySpawnGameplaySlotBotParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message);

bool TryFindOpenGameplayBotSlot(uintptr_t gameplay_address, int* target_slot) {
    if (target_slot != nullptr) {
        *target_slot = -1;
    }
    if (gameplay_address == 0) {
        return false;
    }

    for (int candidate = kFirstWizardBotSlot;
         candidate < static_cast<int>(kGameplayPlayerSlotCount);
         ++candidate) {
        uintptr_t existing_actor = 0;
        if (!TryResolvePlayerActorForSlot(gameplay_address, candidate, &existing_actor) ||
            existing_actor == 0) {
            if (target_slot != nullptr) {
                *target_slot = candidate;
            }
            return true;
        }
    }

    return false;
}

bool ShouldUseGameplaySlotBotParticipantRail(uintptr_t gameplay_address, const SceneContextSnapshot& scene_context) {
    // Arena scenes expose the gameplay player-slot array (slots 1..3) that the
    // stock hostile pathfinder scans for targets via HookMonsterPathfindingRefreshTarget.
    // Routing arena bots through Gameplay_CreatePlayerSlot + ActorWorld_RegisterGameplaySlotActor
    // places them in slots 1..3 so enemies actually aggro them. The stock scene
    // only has three non-local slots, so overflow arena bots intentionally use
    // the standalone wizard rail and are added to the widened hostile selector.
    return IsArenaSceneContext(scene_context) && TryFindOpenGameplayBotSlot(gameplay_address, nullptr);
}

bool ShouldUseRegisteredGameNpcParticipantRail(const SceneContextSnapshot& scene_context) {
    (void)scene_context;
    // Keep hub bots on the standalone clone rail until a true long-lived
    // GameNpc (0x1397) publication contract is recovered. The clone-handoff
    // path uses WizardCloneFromSourceActor, which returns a player-family actor
    // (PlayerActorCtor writes object_type=0x1). Binding that result as
    // RegisteredGameNpc and driving GameNpc_SetMoveGoal on it corrupted the
    // actor's player-side state and crashed stock PlayerActorTick.
    return false;
}
