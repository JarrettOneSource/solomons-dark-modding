bool ResolveParticipantSpawnTransform(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    float* out_x,
    float* out_y,
    float* out_heading) {
    if (out_x == nullptr || out_y == nullptr || out_heading == nullptr) {
        return false;
    }

    float x = request.x;
    float y = request.y;
    float heading = request.heading;
    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) || local_actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address =
        memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorOwnerOffset, 0);
    if (world_address == 0) {
        return false;
    }

    bool allow_local_anchor_fallback = false;
    if (request.bot_id != 0) {
        const auto runtime_state = multiplayer::SnapshotRuntimeState();
        if (const auto* participant = multiplayer::FindParticipant(runtime_state, request.bot_id);
            participant != nullptr && multiplayer::IsLuaControlledParticipant(*participant)) {
            allow_local_anchor_fallback = true;
        }
    }

    if (!request.has_transform) {
        if (!allow_local_anchor_fallback) {
            return false;
        }
        x = memory.ReadFieldOr<float>(local_actor_address, kActorPositionXOffset, 0.0f) + kDefaultWizardBotOffsetX;
        y = memory.ReadFieldOr<float>(local_actor_address, kActorPositionYOffset, 0.0f) + kDefaultWizardBotOffsetY;
        heading = memory.ReadFieldOr<float>(local_actor_address, kActorHeadingOffset, 0.0f);
    } else if (!request.has_heading) {
        uintptr_t existing_actor_address = 0;
        if (request.bot_id != 0) {
            if (const auto* binding = FindParticipantEntity(request.bot_id); binding != nullptr) {
                existing_actor_address = binding->actor_address;
            }
        }

        if (existing_actor_address != 0) {
            heading = memory.ReadFieldOr<float>(existing_actor_address, kActorHeadingOffset, 0.0f);
        } else {
            heading = memory.ReadFieldOr<float>(local_actor_address, kActorHeadingOffset, 0.0f);
        }
    }

    uintptr_t placement_probe_actor_address = local_actor_address;
    if (request.bot_id != 0) {
        if (const auto* binding = FindParticipantEntity(request.bot_id);
            binding != nullptr && binding->actor_address != 0) {
            placement_probe_actor_address = binding->actor_address;
        }
    }

    std::string placement_error;
    float resolved_x = x;
    float resolved_y = y;
    if (!TryResolveNearestTraversablePlacement(
            world_address,
            placement_probe_actor_address,
            x,
            y,
            &resolved_x,
            &resolved_y,
            &placement_error)) {
        Log(
            "[bots] resolve transform rejected non-traversable placement. bot_id=" +
            std::to_string(request.bot_id) +
            " requested=(" + std::to_string(x) + ", " + std::to_string(y) + ")" +
            " placement_error=" + placement_error);
        return false;
    }

    *out_x = resolved_x;
    *out_y = resolved_y;
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

