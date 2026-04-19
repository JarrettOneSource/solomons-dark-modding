bool TryFindNearestTraversableGoalCell(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    int start_grid_x,
    int start_grid_y,
    int* goal_grid_x,
    int* goal_grid_y,
    std::vector<std::int8_t>* traversable_cache,
    std::string* error_message) {
    if (goal_grid_x == nullptr || goal_grid_y == nullptr) {
        return false;
    }
    if (IsGameplayPathCellTraversable(snapshot, binding, *goal_grid_x, *goal_grid_y, traversable_cache, error_message)) {
        return true;
    }

    const auto max_radius = snapshot.width > snapshot.height ? snapshot.width : snapshot.height;
    int best_grid_x = -1;
    int best_grid_y = -1;
    float best_distance_sq = FLT_MAX;

    for (int radius = 1; radius < max_radius; ++radius) {
        const auto min_x = (*goal_grid_x - radius) > 0 ? (*goal_grid_x - radius) : 0;
        const auto max_x = (*goal_grid_x + radius) < (snapshot.width - 1) ? (*goal_grid_x + radius) : (snapshot.width - 1);
        const auto min_y = (*goal_grid_y - radius) > 0 ? (*goal_grid_y - radius) : 0;
        const auto max_y = (*goal_grid_y + radius) < (snapshot.height - 1) ? (*goal_grid_y + radius) : (snapshot.height - 1);
        for (int grid_x = min_x; grid_x <= max_x; ++grid_x) {
            for (int grid_y = min_y; grid_y <= max_y; ++grid_y) {
                if (grid_x != min_x && grid_x != max_x && grid_y != min_y && grid_y != max_y) {
                    continue;
                }
                if (!IsGameplayPathCellTraversable(snapshot, binding, grid_x, grid_y, traversable_cache, error_message)) {
                    continue;
                }
                const auto dx = static_cast<float>(grid_x - start_grid_x);
                const auto dy = static_cast<float>(grid_y - start_grid_y);
                const auto distance_sq = dx * dx + dy * dy;
                if (distance_sq < best_distance_sq) {
                    best_distance_sq = distance_sq;
                    best_grid_x = grid_x;
                    best_grid_y = grid_y;
                }
            }
        }
        if (best_grid_x != -1) {
            *goal_grid_x = best_grid_x;
            *goal_grid_y = best_grid_y;
            return true;
        }
    }

    if (error_message != nullptr) {
        *error_message =
            "No traversable goal cell near destination grid=(" +
            std::to_string(*goal_grid_x) + ", " + std::to_string(*goal_grid_y) + ").";
    }
    return false;
}

bool TryResolveNearestTraversablePlacement(
    uintptr_t world_address,
    uintptr_t probe_actor_address,
    float desired_x,
    float desired_y,
    float* resolved_x,
    float* resolved_y,
    std::string* error_message) {
    if (resolved_x == nullptr || resolved_y == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Nearest traversable placement requires output coordinates.";
        }
        return false;
    }
    if (world_address == 0 || probe_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Nearest traversable placement requires a live world and probe actor.";
        }
        return false;
    }

    GameplayPathGridSnapshot snapshot;
    if (!TryBuildGameplayPathGridSnapshot(world_address, &snapshot, error_message)) {
        return false;
    }

    ParticipantEntityBinding probe_binding{};
    probe_binding.actor_address = probe_actor_address;
    probe_binding.materialized_world_address = world_address;
    auto& memory = ProcessMemory::Instance();
    const auto anchor_x = memory.ReadFieldOr<float>(probe_actor_address, kActorPositionXOffset, 0.0f);
    const auto anchor_y = memory.ReadFieldOr<float>(probe_actor_address, kActorPositionYOffset, 0.0f);
    if (IsGameplayPathPlacementTraversable(snapshot, &probe_binding, desired_x, desired_y, error_message) &&
        IsGameplayPathSegmentTraversable(snapshot, &probe_binding, anchor_x, anchor_y, desired_x, desired_y, nullptr)) {
        *resolved_x = desired_x;
        *resolved_y = desired_y;
        return true;
    }

    int goal_grid_x = 0;
    int goal_grid_y = 0;
    if (!TryResolveGameplayPathCell(snapshot, desired_x, desired_y, &goal_grid_x, &goal_grid_y)) {
        const auto resolved_goal_grid_x = static_cast<int>(std::floor(desired_y / snapshot.cell_height));
        const auto resolved_goal_grid_y = static_cast<int>(std::floor(desired_x / snapshot.cell_width));
        goal_grid_x =
            resolved_goal_grid_x < 0 ? 0
                                     : (resolved_goal_grid_x >= snapshot.width ? snapshot.width - 1 : resolved_goal_grid_x);
        goal_grid_y =
            resolved_goal_grid_y < 0 ? 0
                                     : (resolved_goal_grid_y >= snapshot.height ? snapshot.height - 1 : resolved_goal_grid_y);
    }

    const auto radius = memory.ReadFieldOr<float>(probe_actor_address, kActorCollisionRadiusOffset, 0.0f);
    const auto preferred_margin = radius > 8.0f ? radius : 8.0f;
    const auto max_margin_x = snapshot.cell_width * 0.45f;
    const auto max_margin_y = snapshot.cell_height * 0.45f;
    const auto margin_x = preferred_margin < max_margin_x ? preferred_margin : max_margin_x;
    const auto margin_y = preferred_margin < max_margin_y ? preferred_margin : max_margin_y;

    auto clamp_with_margin = [](float value, float min_value, float max_value) {
        if (max_value < min_value) {
            return min_value;
        }
        return std::clamp(value, min_value, max_value);
    };

    bool have_strict_candidate = false;
    float best_strict_distance_sq = FLT_MAX;
    float best_strict_x = 0.0f;
    float best_strict_y = 0.0f;

    bool have_relaxed_candidate = false;
    float best_relaxed_distance_sq = FLT_MAX;
    float best_relaxed_x = 0.0f;
    float best_relaxed_y = 0.0f;

    const auto max_radius = snapshot.width > snapshot.height ? snapshot.width : snapshot.height;
    for (int search_radius = 0; search_radius < max_radius; ++search_radius) {
        const auto min_x = (goal_grid_x - search_radius) > 0 ? (goal_grid_x - search_radius) : 0;
        const auto max_x = (goal_grid_x + search_radius) < (snapshot.width - 1)
            ? (goal_grid_x + search_radius)
            : (snapshot.width - 1);
        const auto min_y = (goal_grid_y - search_radius) > 0 ? (goal_grid_y - search_radius) : 0;
        const auto max_y = (goal_grid_y + search_radius) < (snapshot.height - 1)
            ? (goal_grid_y + search_radius)
            : (snapshot.height - 1);

        for (int grid_x = min_x; grid_x <= max_x; ++grid_x) {
            for (int grid_y = min_y; grid_y <= max_y; ++grid_y) {
                if (search_radius != 0 &&
                    grid_x != min_x && grid_x != max_x &&
                    grid_y != min_y && grid_y != max_y) {
                    continue;
                }

                const auto cell_min_x = static_cast<float>(grid_y) * snapshot.cell_width;
                const auto cell_max_x = cell_min_x + snapshot.cell_width;
                const auto cell_min_y = static_cast<float>(grid_x) * snapshot.cell_height;
                const auto cell_max_y = cell_min_y + snapshot.cell_height;

                const auto preferred_x = clamp_with_margin(
                    desired_x,
                    cell_min_x + margin_x,
                    cell_max_x - margin_x);
                const auto preferred_y = clamp_with_margin(
                    desired_y,
                    cell_min_y + margin_y,
                    cell_max_y - margin_y);

                std::array<std::pair<float, float>, 9> samples = {{
                    { preferred_x, preferred_y },
                    { GameplayPathCellCenterX(snapshot, grid_y), GameplayPathCellCenterY(snapshot, grid_x) },
                    { cell_min_x + margin_x, cell_min_y + margin_y },
                    { cell_max_x - margin_x, cell_min_y + margin_y },
                    { cell_min_x + margin_x, cell_max_y - margin_y },
                    { cell_max_x - margin_x, cell_max_y - margin_y },
                    { preferred_x, cell_min_y + margin_y },
                    { preferred_x, cell_max_y - margin_y },
                    { cell_min_x + margin_x, preferred_y },
                }};

                for (const auto& sample : samples) {
                    const auto sample_x = sample.first;
                    const auto sample_y = sample.second;
                    if (!IsGameplayPathPlacementTraversable(snapshot, &probe_binding, sample_x, sample_y, nullptr)) {
                        continue;
                    }

                    const auto dx = sample_x - desired_x;
                    const auto dy = sample_y - desired_y;
                    const auto distance_sq = dx * dx + dy * dy;
                    const auto direct_reachable =
                        IsGameplayPathSegmentTraversable(
                            snapshot,
                            &probe_binding,
                            anchor_x,
                            anchor_y,
                            sample_x,
                            sample_y,
                            nullptr);

                    if (direct_reachable) {
                        if (!have_strict_candidate || distance_sq < best_strict_distance_sq) {
                            have_strict_candidate = true;
                            best_strict_distance_sq = distance_sq;
                            best_strict_x = sample_x;
                            best_strict_y = sample_y;
                        }
                    } else if (!have_relaxed_candidate || distance_sq < best_relaxed_distance_sq) {
                        have_relaxed_candidate = true;
                        best_relaxed_distance_sq = distance_sq;
                        best_relaxed_x = sample_x;
                        best_relaxed_y = sample_y;
                    }
                }
            }
        }

        if (have_strict_candidate) {
            *resolved_x = best_strict_x;
            *resolved_y = best_strict_y;
            return true;
        }
    }

    if (have_relaxed_candidate) {
        *resolved_x = best_relaxed_x;
        *resolved_y = best_relaxed_y;
        return true;
    }

    if (error_message != nullptr) {
        *error_message =
            "No traversable placement near desired point=(" +
            std::to_string(desired_x) + ", " + std::to_string(desired_y) + ").";
    }
    return false;
}

