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
    uintptr_t world_address = 0;
    if (!memory.TryReadField(local_actor_address, kActorOwnerOffset, &world_address)) {
        return false;
    }
    if (world_address == 0) {
        return false;
    }

    if (!request.has_transform || !request.has_heading) {
        return false;
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
