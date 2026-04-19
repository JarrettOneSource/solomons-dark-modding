bool IsGameplayPathCellInBounds(const GameplayPathGridSnapshot& snapshot, int grid_x, int grid_y) {
    return
        0 <= grid_x && grid_x < snapshot.width &&
        0 <= grid_y && grid_y < snapshot.height;
}

int GameplayPathCellIndex(const GameplayPathGridSnapshot& snapshot, int grid_x, int grid_y) {
    return snapshot.height * grid_x + grid_y;
}

float GameplayPathCellCenterX(const GameplayPathGridSnapshot& snapshot, int grid_x) {
    return (static_cast<float>(grid_x) + 0.5f) * snapshot.cell_width;
}

float GameplayPathCellCenterY(const GameplayPathGridSnapshot& snapshot, int grid_y) {
    return (static_cast<float>(grid_y) + 0.5f) * snapshot.cell_height;
}

bool GameplayPathCellContainsWorldPoint(
    const GameplayPathGridSnapshot& snapshot,
    int grid_x,
    int grid_y,
    float world_x,
    float world_y) {
    if (!std::isfinite(world_x) || !std::isfinite(world_y) ||
        !IsGameplayPathCellInBounds(snapshot, grid_x, grid_y)) {
        return false;
    }

    const auto cell_min_x = static_cast<float>(grid_y) * snapshot.cell_width;
    const auto cell_max_x = cell_min_x + snapshot.cell_width;
    const auto cell_min_y = static_cast<float>(grid_x) * snapshot.cell_height;
    const auto cell_max_y = cell_min_y + snapshot.cell_height;
    return
        world_x >= cell_min_x && world_x < cell_max_x &&
        world_y >= cell_min_y && world_y < cell_max_y;
}

bool IsGameplayPathPlacementTraversable(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    float world_x,
    float world_y,
    std::string* error_message);

bool IsGameplayPathSegmentTraversable(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    float from_x,
    float from_y,
    float to_x,
    float to_y,
    std::string* error_message);

bool TryResolveGameplayPathCell(
    const GameplayPathGridSnapshot& snapshot,
    float world_x,
    float world_y,
    int* grid_x,
    int* grid_y) {
    if (grid_x == nullptr || grid_y == nullptr || snapshot.cell_width <= 0.0f || snapshot.cell_height <= 0.0f) {
        return false;
    }

    const auto resolved_grid_x = static_cast<int>(std::floor(world_y / snapshot.cell_height));
    const auto resolved_grid_y = static_cast<int>(std::floor(world_x / snapshot.cell_width));
    if (!IsGameplayPathCellInBounds(snapshot, resolved_grid_x, resolved_grid_y)) {
        return false;
    }

    *grid_x = resolved_grid_x;
    *grid_y = resolved_grid_y;
    return true;
}

bool TryFindGameplayPathCellSample(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    int grid_x,
    int grid_y,
    float preferred_x,
    float preferred_y,
    bool require_direct_reachability,
    bool allow_anchor_fallback,
    float anchor_x,
    float anchor_y,
    float* resolved_x,
    float* resolved_y,
    std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0 || resolved_x == nullptr || resolved_y == nullptr) {
        return false;
    }
    if (!IsGameplayPathCellInBounds(snapshot, grid_x, grid_y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto radius = memory.ReadFieldOr<float>(binding->actor_address, kActorCollisionRadiusOffset, 0.0f);
    const auto preferred_margin = radius > 8.0f ? radius : 8.0f;
    const auto cell_min_x = static_cast<float>(grid_y) * snapshot.cell_width;
    const auto cell_max_x = cell_min_x + snapshot.cell_width;
    const auto cell_min_y = static_cast<float>(grid_x) * snapshot.cell_height;
    const auto cell_max_y = cell_min_y + snapshot.cell_height;
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

    const auto clamped_preferred_x = clamp_with_margin(
        preferred_x,
        cell_min_x + margin_x,
        cell_max_x - margin_x);
    const auto clamped_preferred_y = clamp_with_margin(
        preferred_y,
        cell_min_y + margin_y,
        cell_max_y - margin_y);
    const auto preferred_in_cell =
        GameplayPathCellContainsWorldPoint(snapshot, grid_x, grid_y, preferred_x, preferred_y);
    const auto anchor_in_cell =
        GameplayPathCellContainsWorldPoint(snapshot, grid_x, grid_y, anchor_x, anchor_y);
    const auto preferred_reference_x = preferred_in_cell ? preferred_x : clamped_preferred_x;
    const auto preferred_reference_y = preferred_in_cell ? preferred_y : clamped_preferred_y;

    bool have_candidate = false;
    float best_distance_sq = FLT_MAX;
    float best_x = 0.0f;
    float best_y = 0.0f;
    const auto accept_sample_without_query = [&](float sample_x, float sample_y) {
        const auto dx = sample_x - preferred_reference_x;
        const auto dy = sample_y - preferred_reference_y;
        const auto distance_sq = dx * dx + dy * dy;
        if (!have_candidate || distance_sq < best_distance_sq) {
            have_candidate = true;
            best_distance_sq = distance_sq;
            best_x = sample_x;
            best_y = sample_y;
        }
    };
    const auto consider_sample = [&](float sample_x, float sample_y) {
        if (!IsGameplayPathPlacementTraversable(snapshot, binding, sample_x, sample_y, nullptr)) {
            return;
        }
        if (require_direct_reachability &&
            !IsGameplayPathSegmentTraversable(snapshot, binding, anchor_x, anchor_y, sample_x, sample_y, nullptr)) {
            return;
        }

        const auto dx = sample_x - preferred_reference_x;
        const auto dy = sample_y - preferred_reference_y;
        const auto distance_sq = dx * dx + dy * dy;
        if (!have_candidate || distance_sq < best_distance_sq) {
            have_candidate = true;
            best_distance_sq = distance_sq;
            best_x = sample_x;
            best_y = sample_y;
        }
    };

    if (allow_anchor_fallback && anchor_in_cell) {
        // The actor is already occupying this point. Native placement queries
        // can reject that sample because the actor overlaps itself, but for the
        // path planner the current anchor is a valid start sample by definition.
        // Goal sampling must be able to suppress this fallback, otherwise a
        // same-cell destination can degenerate into "stay where you already are"
        // and the caller loops forever on an empty path.
        accept_sample_without_query(anchor_x, anchor_y);
    }

    if (preferred_in_cell) {
        consider_sample(preferred_x, preferred_y);
    }
    consider_sample(clamped_preferred_x, clamped_preferred_y);
    consider_sample(
        GameplayPathCellCenterX(snapshot, grid_y),
        GameplayPathCellCenterY(snapshot, grid_x));

    if (require_direct_reachability) {
        constexpr int kGameplayPathCellLineSampleResolution = 12;
        const auto line_target_x = preferred_in_cell ? preferred_x : clamped_preferred_x;
        const auto line_target_y = preferred_in_cell ? preferred_y : clamped_preferred_y;
        for (int sample_index = 0; sample_index < kGameplayPathCellLineSampleResolution; ++sample_index) {
            const auto t =
                static_cast<float>(sample_index + 1) /
                static_cast<float>(kGameplayPathCellLineSampleResolution + 1);
            const auto sample_x = anchor_x + (line_target_x - anchor_x) * t;
            const auto sample_y = anchor_y + (line_target_y - anchor_y) * t;
            if (!GameplayPathCellContainsWorldPoint(snapshot, grid_x, grid_y, sample_x, sample_y)) {
                continue;
            }
            consider_sample(sample_x, sample_y);
        }
    }

    const auto usable_width = (cell_max_x - margin_x) - (cell_min_x + margin_x);
    const auto usable_height = (cell_max_y - margin_y) - (cell_min_y + margin_y);
    for (int sample_index_x = 0; sample_index_x < kGameplayPathCellPlacementSampleResolution; ++sample_index_x) {
        const auto t_x =
            (static_cast<float>(sample_index_x) + 0.5f) /
            static_cast<float>(kGameplayPathCellPlacementSampleResolution);
        const auto sample_x =
            (usable_width <= 0.0f)
                ? (cell_min_x + margin_x)
                : (cell_min_x + margin_x + usable_width * t_x);
        for (int sample_index_y = 0; sample_index_y < kGameplayPathCellPlacementSampleResolution; ++sample_index_y) {
            const auto t_y =
                (static_cast<float>(sample_index_y) + 0.5f) /
                static_cast<float>(kGameplayPathCellPlacementSampleResolution);
            const auto sample_y =
                (usable_height <= 0.0f)
                    ? (cell_min_y + margin_y)
                    : (cell_min_y + margin_y + usable_height * t_y);
            consider_sample(sample_x, sample_y);
        }
    }

    if (!have_candidate) {
        if (error_message != nullptr && error_message->empty()) {
            *error_message =
                "No traversable sample in grid cell=(" +
                std::to_string(grid_x) + ", " + std::to_string(grid_y) + ").";
        }
        return false;
    }

    *resolved_x = best_x;
    *resolved_y = best_y;
    return true;
}
