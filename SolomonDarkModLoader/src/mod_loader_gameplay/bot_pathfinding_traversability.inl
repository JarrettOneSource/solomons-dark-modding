std::uint32_t ResolveGameplayPathCollisionMask(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->actor_address == 0 || kActorPrimaryFlagMaskOffset == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_mask =
        memory.ReadFieldOr<std::uint32_t>(binding->actor_address, kActorPrimaryFlagMaskOffset, 0);
    if (actor_mask != 0) {
        return actor_mask;
    }

    // Stock only seeds +0x38/+0x3C through the slot-0 actor path, so
    // gameplay-slot bots can legitimately keep zero masks. For path planning we
    // want player-equivalent placement semantics without mutating the bot's live
    // actor identity fields.
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return actor_mask;
    }

    uintptr_t local_player_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_player_actor_address) ||
        local_player_actor_address == 0) {
        return actor_mask;
    }

    const auto player_mask =
        memory.ReadFieldOr<std::uint32_t>(local_player_actor_address, kActorPrimaryFlagMaskOffset, 0);
    return player_mask != 0 ? player_mask : actor_mask;
}

bool DoesGameplayPathCircleOverlapObstacle(
    const std::vector<GameplayPathCircleObstacle>& obstacles,
    float world_x,
    float world_y,
    float radius) {
    for (const auto& obstacle : obstacles) {
        const auto combined_radius = radius + obstacle.radius;
        const auto delta_x = world_x - obstacle.x;
        const auto delta_y = world_y - obstacle.y;
        if ((delta_x * delta_x) + (delta_y * delta_y) <= combined_radius * combined_radius) {
            return true;
        }
    }

    return false;
}

bool IsGameplayPathBlockedByStaticCircleObstacle(
    const GameplayPathGridSnapshot& snapshot,
    float world_x,
    float world_y,
    float radius) {
    return DoesGameplayPathCircleOverlapObstacle(
        snapshot.static_circle_obstacles,
        world_x,
        world_y,
        radius);
}

bool IsGameplayPathOverlappingIgnoredCircleObstacle(
    const GameplayPathGridSnapshot& snapshot,
    float world_x,
    float world_y,
    float radius) {
    return DoesGameplayPathCircleOverlapObstacle(
        snapshot.ignored_circle_obstacles,
        world_x,
        world_y,
        radius);
}

bool IsGameplayPathPlacementTraversable(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    float world_x,
    float world_y,
    std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Path placement query requires a materialized actor.";
        }
        return false;
    }
    if (kMovementCollisionTestCirclePlacement == 0 ||
        kActorCollisionRadiusOffset == 0 ||
        kActorPrimaryFlagMaskOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "Path placement query seams are not loaded.";
        }
        return false;
    }
    if (snapshot.controller_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Path placement query requires a live movement controller.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto radius = memory.ReadFieldOr<float>(binding->actor_address, kActorCollisionRadiusOffset, 0.0f);
    const auto collision_mask = ResolveGameplayPathCollisionMask(binding);
    if (radius <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Bot actor has no collision radius for path placement queries.";
        }
        return false;
    }

    if (IsGameplayPathBlockedByStaticCircleObstacle(snapshot, world_x, world_y, radius)) {
        return false;
    }

    std::uint32_t blocked = 0;
    DWORD exception_code = 0;
    const auto native_circle_block_mask =
        collision_mask &
        ~(kGameplayPathStaticCircleObstacleMask | kGameplayPathPushableCircleObstacleMask);
    const auto native_overlap_allow_mask =
        collision_mask |
        kGameplayPathStaticCircleObstacleMask |
        kGameplayPathPushableCircleObstacleMask;
    const auto extended_placement_address =
        memory.ResolveGameAddressOrZero(kMovementCollisionTestCirclePlacementExtended);
    bool placement_ok = false;
    if (extended_placement_address != 0) {
        placement_ok = CallMovementCollisionTestCirclePlacementExtendedSafe(
            extended_placement_address,
            snapshot.controller_address,
            world_x,
            world_y,
            radius,
            native_circle_block_mask,
            native_overlap_allow_mask,
            &blocked,
            &exception_code);
    } else {
        placement_ok = CallMovementCollisionTestCirclePlacementSafe(
            memory.ResolveGameAddressOrZero(kMovementCollisionTestCirclePlacement),
            snapshot.controller_address,
            world_x,
            world_y,
            radius,
            native_overlap_allow_mask,
            &blocked,
            &exception_code);
    }
    if (!placement_ok) {
        if (error_message != nullptr) {
            *error_message =
                "Native placement query failed. actor=" + HexString(binding->actor_address) +
                " controller=" + HexString(snapshot.controller_address) +
                " collision_mask=" + HexString(collision_mask) +
                " native_circle_block_mask=" + HexString(native_circle_block_mask) +
                " native_overlap_allow_mask=" + HexString(native_overlap_allow_mask) +
                " exception=0x" + HexString(exception_code);
        }
        return false;
    }

    // Native overlap lists can still report the push-through gate as blocked
    // after the raw circle prepass is filtered. The kept static-circle pass
    // above has already rejected trees, gravestones, and holes.
    if (blocked != 0 &&
        IsGameplayPathOverlappingIgnoredCircleObstacle(snapshot, world_x, world_y, radius)) {
        return true;
    }

    return blocked == 0;
}

bool IsGameplayPathSegmentTraversable(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    float from_x,
    float from_y,
    float to_x,
    float to_y,
    std::string* error_message) {
    const auto delta_x = to_x - from_x;
    const auto delta_y = to_y - from_y;
    const auto distance = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    if (distance <= 0.0001f) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto radius = memory.ReadFieldOr<float>(binding->actor_address, kActorCollisionRadiusOffset, 0.0f);
    const auto cell_min = snapshot.cell_width < snapshot.cell_height ? snapshot.cell_width : snapshot.cell_height;
    float step_distance = cell_min * 0.25f;
    if (radius > 0.0f) {
        const auto radius_step = radius * 0.5f;
        if (radius_step < step_distance) {
            step_distance = radius_step;
        }
    }
    if (step_distance < 4.0f) {
        step_distance = 4.0f;
    }
    const auto resolved_samples = static_cast<int>(std::ceil(distance / step_distance));
    const auto samples = resolved_samples > 1 ? resolved_samples : 1;
    const auto start_self_clearance = radius > 0.0f ? ((radius * 2.0f) + 0.5f) : 0.0f;
    const auto start_self_clearance_sq = start_self_clearance * start_self_clearance;
    for (int sample_index = 1; sample_index <= samples; ++sample_index) {
        const auto t = static_cast<float>(sample_index) / static_cast<float>(samples);
        const auto sample_x = from_x + delta_x * t;
        const auto sample_y = from_y + delta_y * t;
        const auto from_sample_x = sample_x - from_x;
        const auto from_sample_y = sample_y - from_y;
        if (start_self_clearance > 0.0f &&
            ((from_sample_x * from_sample_x) + (from_sample_y * from_sample_y)) <= start_self_clearance_sq) {
            continue;
        }
        if (!IsGameplayPathPlacementTraversable(snapshot, binding, sample_x, sample_y, error_message)) {
            return false;
        }
    }
    return true;
}

bool IsGameplayPathCellTraversable(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    int grid_x,
    int grid_y,
    std::vector<std::int8_t>* traversable_cache,
    std::string* error_message) {
    if (!IsGameplayPathCellInBounds(snapshot, grid_x, grid_y)) {
        return false;
    }

    const auto index = GameplayPathCellIndex(snapshot, grid_x, grid_y);
    if (traversable_cache != nullptr && index >= 0 && static_cast<std::size_t>(index) < traversable_cache->size()) {
        const auto cached = (*traversable_cache)[static_cast<std::size_t>(index)];
        if (cached != -1) {
            return cached == 1;
        }
    }

    const auto center_x = GameplayPathCellCenterX(snapshot, grid_y);
    const auto center_y = GameplayPathCellCenterY(snapshot, grid_x);
    float sample_x = 0.0f;
    float sample_y = 0.0f;
    const auto traversable = TryFindGameplayPathCellSample(
        snapshot,
        binding,
        grid_x,
        grid_y,
        center_x,
        center_y,
        false,
        false,
        center_x,
        center_y,
        &sample_x,
        &sample_y,
        error_message);

    if (traversable_cache != nullptr && index >= 0 && static_cast<std::size_t>(index) < traversable_cache->size()) {
        (*traversable_cache)[static_cast<std::size_t>(index)] = traversable ? 1 : 0;
    }
    return traversable;
}
