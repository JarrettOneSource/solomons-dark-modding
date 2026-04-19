std::uint32_t ResolveGameplayPathPlacementMask(ParticipantEntityBinding* binding) {
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
    const auto mask = ResolveGameplayPathPlacementMask(binding);
    if (radius <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Bot actor has no collision radius for path placement queries.";
        }
        return false;
    }

    std::uint32_t blocked = 0;
    DWORD exception_code = 0;
    if (!CallMovementCollisionTestCirclePlacementSafe(
            memory.ResolveGameAddressOrZero(kMovementCollisionTestCirclePlacement),
            snapshot.controller_address,
            world_x,
            world_y,
            radius,
            mask,
            &blocked,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Native placement query failed. actor=" + HexString(binding->actor_address) +
                " controller=" + HexString(snapshot.controller_address) +
                " exception=0x" + HexString(exception_code);
        }
        return false;
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
    for (int sample_index = 1; sample_index <= samples; ++sample_index) {
        const auto t = static_cast<float>(sample_index) / static_cast<float>(samples);
        const auto sample_x = from_x + delta_x * t;
        const auto sample_y = from_y + delta_y * t;
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
