bool ResolveParticipantSpawnTransform(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    bool validate_placement,
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

    bool allow_local_spawn_anchor = false;
    if (request.bot_id != 0) {
        const auto runtime_state = multiplayer::SnapshotRuntimeState();
        if (const auto* participant = multiplayer::FindParticipant(runtime_state, request.bot_id);
            participant != nullptr && multiplayer::IsLuaControlledParticipant(*participant)) {
            allow_local_spawn_anchor = true;
        }
    }

    if (!request.has_transform) {
        if (!allow_local_spawn_anchor) {
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

    if (request.has_transform && !validate_placement) {
        *out_x = x;
        *out_y = y;
        *out_heading = heading;
        return true;
    }

    // Transform updates are scene/teleport syncs, not path requests. Use the
    // local player as the placement probe so a far-away bot does not force the
    // native placement resolver to pick a point reachable from its stale cell.
    uintptr_t placement_probe_actor_address = local_actor_address;

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
