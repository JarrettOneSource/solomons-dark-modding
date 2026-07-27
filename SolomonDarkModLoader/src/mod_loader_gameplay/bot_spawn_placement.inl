bool ResolveNativeBotSpawnPlacement(
    std::uint64_t bot_id,
    multiplayer::ParticipantSceneIntentKind scene_kind,
    std::string_view phase,
    float anchor_x,
    float anchor_y,
    float* resolved_x,
    float* resolved_y,
    std::string* error_message) {
    if (resolved_x != nullptr) {
        *resolved_x = 0.0f;
    }
    if (resolved_y != nullptr) {
        *resolved_y = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (resolved_x == nullptr ||
        resolved_y == nullptr ||
        !std::isfinite(anchor_x) ||
        !std::isfinite(anchor_y)) {
        if (error_message != nullptr) {
            *error_message = "spawn placement unavailable";
        }
        return false;
    }

    SDModPlayerState local_player;
    if (!TryGetPlayerState(&local_player) ||
        !local_player.valid ||
        local_player.actor_address == 0 ||
        local_player.world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "spawn placement unavailable";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    float collision_radius = 0.0f;
    std::uint32_t primary_collision_mask = 0;
    if (!TryReadFiniteFloatField(
            local_player.actor_address,
            kActorCollisionRadiusOffset,
            &collision_radius) ||
        !memory.TryReadField(
            local_player.actor_address,
            kActorPrimaryFlagMaskOffset,
            &primary_collision_mask) ||
        collision_radius <= 0.0f ||
        primary_collision_mask == 0 ||
        kActorOwnerMovementControllerOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "spawn placement unavailable";
        }
        return false;
    }

    const auto basic_placement_address =
        memory.ResolveGameAddressOrZero(
            kMovementCollisionTestCirclePlacement);
    const auto extended_placement_address =
        memory.ResolveGameAddressOrZero(
            kMovementCollisionTestCirclePlacementExtended);
    const auto movement_controller_address =
        local_player.world_address +
        kActorOwnerMovementControllerOffset;
    if (basic_placement_address == 0 ||
        extended_placement_address == 0 ||
        movement_controller_address == 0) {
        if (error_message != nullptr) {
            *error_message = "spawn placement unavailable";
        }
        return false;
    }

    std::vector<std::pair<float, float>> reserved_bot_placements;
    const auto runtime = multiplayer::SnapshotRuntimeState();
    for (const auto& participant : runtime.participants) {
        if (participant.participant_id == bot_id ||
            !multiplayer::IsLuaControlledParticipant(participant) ||
            !participant.runtime.transform_valid ||
            participant.runtime.scene_intent.kind != scene_kind ||
            !std::isfinite(participant.runtime.position_x) ||
            !std::isfinite(participant.runtime.position_y)) {
            continue;
        }
        reserved_bot_placements.emplace_back(
            participant.runtime.position_x,
            participant.runtime.position_y);
    }

    const std::uint32_t overlap_allow_mask = 0;
    std::uint32_t final_basic_result = 0;
    std::uint32_t final_extended_result = 0;
    DWORD final_exception_code = 0;
    const auto native_probe = [&](float x, float y) {
        final_basic_result = 0;
        final_extended_result = 0;
        final_exception_code = 0;
        if (!CallMovementCollisionTestCirclePlacementSafe(
                basic_placement_address,
                movement_controller_address,
                x,
                y,
                collision_radius,
                overlap_allow_mask,
                &final_basic_result,
                &final_exception_code)) {
            return BotSpawnPlacementProbeResult::Unavailable;
        }
        if (final_basic_result != 0) {
            return BotSpawnPlacementProbeResult::Blocked;
        }
        if (!CallMovementCollisionTestCirclePlacementExtendedSafe(
                extended_placement_address,
                movement_controller_address,
                x,
                y,
                collision_radius,
                primary_collision_mask,
                overlap_allow_mask,
                &final_extended_result,
                &final_exception_code)) {
            return BotSpawnPlacementProbeResult::Unavailable;
        }
        if (final_extended_result != 0) {
            return BotSpawnPlacementProbeResult::Blocked;
        }

        const auto reserved_clearance =
            collision_radius + collision_radius;
        const auto reserved_clearance_squared =
            reserved_clearance * reserved_clearance;
        for (const auto& reserved : reserved_bot_placements) {
            const auto dx = x - reserved.first;
            const auto dy = y - reserved.second;
            const auto reserved_distance_squared =
                dx * dx + dy * dy;
            if (reserved_distance_squared <
                reserved_clearance_squared) {
                return BotSpawnPlacementProbeResult::Blocked;
            }
        }
        return BotSpawnPlacementProbeResult::Clear;
    };

    BotSpawnPlacementResult placement;
    if (!FindNearestClearBotSpawnPlacement(
            anchor_x,
            anchor_y,
            collision_radius,
            native_probe,
            &placement)) {
        const char* error =
            placement.probe_unavailable
                ? "spawn placement unavailable"
                : "no clear spawn position";
        if (error_message != nullptr) {
            *error_message = error;
        }
        Log(
            "[bots] native spawn placement rejected. bot_id=" +
            std::to_string(bot_id) +
            " scene=" +
            multiplayer::ParticipantSceneIntentKindLabel(scene_kind) +
            " phase=" + std::string(phase) +
            " anchor_x=" + std::to_string(anchor_x) +
            " anchor_y=" + std::to_string(anchor_y) +
            " radius=" + std::to_string(collision_radius) +
            " primary_mask=" + HexString(primary_collision_mask) +
            " reservation_count=" +
            std::to_string(reserved_bot_placements.size()) +
            " probe_count=" +
            std::to_string(placement.probe_count) +
            " search_distance=" +
            std::to_string(placement.search_distance) +
            " search_bound=" +
            std::to_string(
                BotSpawnPlacementSearchBound(collision_radius)) +
            " basic_result=" +
            std::to_string(final_basic_result) +
            " extended_result=" +
            std::to_string(final_extended_result) +
            " exception=" + HexString(final_exception_code) +
            " error=" + error);
        return false;
    }

    *resolved_x = placement.x;
    *resolved_y = placement.y;
    Log(
        "[bots] native spawn placement accepted. bot_id=" +
        std::to_string(bot_id) +
        " scene=" +
        multiplayer::ParticipantSceneIntentKindLabel(scene_kind) +
        " phase=" + std::string(phase) +
        " anchor_x=" + std::to_string(anchor_x) +
        " anchor_y=" + std::to_string(anchor_y) +
        " resolved_x=" + std::to_string(placement.x) +
        " resolved_y=" + std::to_string(placement.y) +
        " radius=" + std::to_string(collision_radius) +
        " primary_mask=" + HexString(primary_collision_mask) +
        " reservation_count=" +
        std::to_string(reserved_bot_placements.size()) +
        " probe_count=" + std::to_string(placement.probe_count) +
        " search_distance=" +
        std::to_string(placement.search_distance) +
        " search_bound=" +
        std::to_string(
            BotSpawnPlacementSearchBound(collision_radius)) +
        " basic_result=" + std::to_string(final_basic_result) +
        " extended_result=" +
        std::to_string(final_extended_result));
    return true;
}
