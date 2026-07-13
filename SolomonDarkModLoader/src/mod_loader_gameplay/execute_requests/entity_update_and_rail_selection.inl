bool TryReadArenaWaveStartState(uintptr_t arena_address, ArenaWaveStartState* state);
std::string DescribeArenaWaveStartState(const ArenaWaveStartState& candidate);

bool TryRebindActorToOwnerWorld(
    uintptr_t actor_address,
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

    uintptr_t world_address = 0;
    if (!memory.TryReadField(actor_address, kActorOwnerOffset, &world_address)) {
        return false;
    }
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
    const bool validate_transform_placement =
        !request.has_transform ||
        request.scene_intent.kind != multiplayer::ParticipantSceneIntentKind::SharedHub;
    if (!ResolveParticipantSpawnTransform(
            gameplay_address,
            request,
            validate_transform_placement,
            &x,
            &y,
            &heading)) {
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

    auto& memory = ProcessMemory::Instance();
    uintptr_t local_actor_address = 0;
    uintptr_t current_world_address = 0;
    if (TryResolvePlayerActorForSlot(
            gameplay_address,
            0,
            &local_actor_address) &&
        local_actor_address != 0) {
        (void)memory.TryReadField(
            local_actor_address,
            kActorOwnerOffset,
            &current_world_address);
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

        uintptr_t existing_world_address = 0;
        const bool existing_world_readable =
            memory.TryReadField(
                existing_actor,
                kActorOwnerOffset,
                &existing_world_address);
        if (current_world_address != 0 &&
            (!existing_world_readable ||
             existing_world_address == 0 ||
             existing_world_address != current_world_address)) {
            const auto actor_slot_offset =
                kGameplayPlayerActorOffset +
                static_cast<std::size_t>(candidate) *
                    kGameplayPlayerSlotStride;
            const auto progression_slot_offset =
                kGameplayPlayerProgressionHandleOffset +
                static_cast<std::size_t>(candidate) *
                    kGameplayPlayerSlotStride;
            const bool actor_cleared =
                memory.TryWriteField<uintptr_t>(
                    gameplay_address,
                    actor_slot_offset,
                    0);
            const bool progression_cleared =
                memory.TryWriteField<uintptr_t>(
                    gameplay_address,
                    progression_slot_offset,
                    0);
            if (actor_cleared && progression_cleared) {
                Log(
                    "[bots] reclaimed stale gameplay participant slot. slot=" +
                    std::to_string(candidate) +
                    " actor=" + HexString(existing_actor) +
                    " actor_world=" + HexString(existing_world_address) +
                    " current_world=" + HexString(current_world_address));
                if (target_slot != nullptr) {
                    *target_slot = candidate;
                }
                return true;
            }
        }
    }

    return false;
}

bool ShouldUseGameplaySlotBotParticipantRail(uintptr_t gameplay_address, const SceneContextSnapshot& scene_context) {
    (void)gameplay_address;
    // A network participant is a stock player-slot wizard in every shared
    // gameplay scene. Keeping the same ownership/equip/progression shape in the
    // hub and arena avoids the incomplete standalone-clone progression object
    // and makes body/equipment presentation deterministic before run entry.
    // The supported four-player model maps exactly onto slot 0 plus slots 1..3;
    // a full slot array is an explicit materialization failure, not a request to
    // silently downgrade a participant onto a different native object model.
    return IsSharedHubSceneContext(scene_context) ||
           IsArenaSceneContext(scene_context);
}
