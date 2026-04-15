#include <cfloat>

struct GameplayPathGridSnapshot {
    uintptr_t controller_address = 0;
    uintptr_t cells_address = 0;
    int width = 0;
    int height = 0;
    float cell_width = 0.0f;
    float cell_height = 0.0f;
};

float NormalizeGameplayHeadingDegrees(float heading_degrees) {
    if (!std::isfinite(heading_degrees)) {
        return 0.0f;
    }

    while (heading_degrees < 0.0f) {
        heading_degrees += 360.0f;
    }
    while (heading_degrees >= 360.0f) {
        heading_degrees -= 360.0f;
    }
    return heading_degrees;
}

bool CallMovementCollisionTestCirclePlacementSafe(
    uintptr_t placement_test_address,
    uintptr_t movement_controller_address,
    float x,
    float y,
    float radius,
    std::uint32_t mask,
    std::uint32_t* blocked_result,
    DWORD* exception_code) {
    if (blocked_result != nullptr) {
        *blocked_result = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (placement_test_address == 0 || movement_controller_address == 0) {
        return false;
    }

    auto* placement_test = reinterpret_cast<MovementCollisionTestCirclePlacementFn>(placement_test_address);
    __try {
        const auto blocked = placement_test(
            reinterpret_cast<void*>(movement_controller_address),
            x,
            y,
            radius,
            mask);
        if (blocked_result != nullptr) {
            *blocked_result = blocked;
        }
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryBuildGameplayPathGridSnapshot(
    uintptr_t world_address,
    GameplayPathGridSnapshot* snapshot,
    std::string* error_message) {
    if (snapshot == nullptr || world_address == 0 || kActorOwnerMovementControllerOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "Path grid snapshot requires a live world address and movement-controller offset.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto controller_address = world_address + kActorOwnerMovementControllerOffset;
    const auto cells_address = memory.ReadFieldOr<uintptr_t>(controller_address, 0xB4, 0);
    const auto grid_height = static_cast<int>(memory.ReadFieldOr<std::uint32_t>(controller_address, 0xD8, 0));
    const auto grid_width = static_cast<int>(memory.ReadFieldOr<std::uint32_t>(controller_address, 0xDC, 0));
    const auto cell_width = memory.ReadFieldOr<float>(controller_address, 0xE0, 0.0f);
    const auto cell_height = memory.ReadFieldOr<float>(controller_address, 0xE4, 0.0f);
    if (cells_address == 0 || grid_width <= 0 || grid_height <= 0 || cell_width <= 0.0f || cell_height <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "Movement controller grid snapshot was incomplete. controller=" + HexString(controller_address) +
                " cells=" + HexString(cells_address) +
                " width=" + std::to_string(grid_width) +
                " height=" + std::to_string(grid_height) +
                " cell=(" + std::to_string(cell_width) + ", " + std::to_string(cell_height) + ")";
        }
        return false;
    }

    snapshot->controller_address = controller_address;
    snapshot->cells_address = cells_address;
    snapshot->width = grid_width;
    snapshot->height = grid_height;
    snapshot->cell_width = cell_width;
    snapshot->cell_height = cell_height;
    return true;
}

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

bool IsGameplayPathPlacementTraversable(
    const GameplayPathGridSnapshot& snapshot,
    BotEntityBinding* binding,
    float world_x,
    float world_y,
    std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Path placement query requires a materialized actor.";
        }
        return false;
    }
    if (kMovementCollisionTestCirclePlacement == 0 || kActorCollisionRadiusOffset == 0 || kActorPrimaryFlagMaskOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "Path placement query seams are not loaded.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto radius = memory.ReadFieldOr<float>(binding->actor_address, kActorCollisionRadiusOffset, 0.0f);
    const auto mask = memory.ReadFieldOr<std::uint32_t>(binding->actor_address, kActorPrimaryFlagMaskOffset, 0);
    if (radius <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "Bot actor has no collision radius for path placement queries.";
        }
        return false;
    }

    std::uint32_t blocked = 0;
    DWORD exception_code = 0;
    if (!CallMovementCollisionTestCirclePlacementSafe(
            ProcessMemory::Instance().ResolveGameAddressOrZero(kMovementCollisionTestCirclePlacement),
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
    BotEntityBinding* binding,
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
    BotEntityBinding* binding,
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

    const auto traversable = IsGameplayPathPlacementTraversable(
        snapshot,
        binding,
        GameplayPathCellCenterX(snapshot, grid_y),
        GameplayPathCellCenterY(snapshot, grid_x),
        error_message);

    if (traversable_cache != nullptr && index >= 0 && static_cast<std::size_t>(index) < traversable_cache->size()) {
        (*traversable_cache)[static_cast<std::size_t>(index)] = traversable ? 1 : 0;
    }
    return traversable;
}

bool TryFindNearestTraversableGoalCell(
    const GameplayPathGridSnapshot& snapshot,
    BotEntityBinding* binding,
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

float EstimateGameplayPathHeuristic(int grid_x, int grid_y, int goal_grid_x, int goal_grid_y) {
    const auto dx = static_cast<float>(std::abs(goal_grid_x - grid_x));
    const auto dy = static_cast<float>(std::abs(goal_grid_y - grid_y));
    const auto diagonal = dx < dy ? dx : dy;
    const auto straight = (dx > dy ? dx : dy) - diagonal;
    return diagonal * 1.41421356237f + straight;
}

void ResetBotPathState(BotEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->path_active = false;
    binding->path_failed = false;
    binding->active_path_revision = 0;
    binding->path_waypoint_index = 0;
    binding->current_waypoint_x = 0.0f;
    binding->current_waypoint_y = 0.0f;
    binding->path_waypoints.clear();
}

void StopBotPathMotion(BotEntityBinding* binding, bool preserve_path) {
    if (binding == nullptr) {
        return;
    }

    binding->movement_active = false;
    binding->direction_x = 0.0f;
    binding->direction_y = 0.0f;
    binding->current_waypoint_x = 0.0f;
    binding->current_waypoint_y = 0.0f;
    if (!preserve_path) {
        ResetBotPathState(binding);
    }
}

void SimplifyBotPathWaypoints(std::vector<BotPathWaypoint>* waypoints) {
    if (waypoints == nullptr || waypoints->size() < 3) {
        return;
    }

    std::vector<BotPathWaypoint> simplified;
    simplified.reserve(waypoints->size());
    simplified.push_back((*waypoints)[0]);
    for (std::size_t index = 1; index + 1 < waypoints->size(); ++index) {
        const auto& previous = simplified.back();
        const auto& current = (*waypoints)[index];
        const auto& next = (*waypoints)[index + 1];
        const auto previous_dx = current.grid_x - previous.grid_x;
        const auto previous_dy = current.grid_y - previous.grid_y;
        const auto next_dx = next.grid_x - current.grid_x;
        const auto next_dy = next.grid_y - current.grid_y;
        if (previous_dx == next_dx && previous_dy == next_dy) {
            continue;
        }
        simplified.push_back(current);
    }
    simplified.push_back(waypoints->back());
    *waypoints = std::move(simplified);
}

bool TryBuildBotPath(
    BotEntityBinding* binding,
    std::uint64_t now_ms,
    std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0 || binding->materialized_world_address == 0 || !binding->has_target) {
        if (error_message != nullptr) {
            *error_message = "Bot path build requires a live actor, live world, and destination.";
        }
        return false;
    }

    GameplayPathGridSnapshot grid_snapshot;
    if (!TryBuildGameplayPathGridSnapshot(binding->materialized_world_address, &grid_snapshot, error_message)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto current_x = memory.ReadFieldOr<float>(binding->actor_address, kActorPositionXOffset, 0.0f);
    const auto current_y = memory.ReadFieldOr<float>(binding->actor_address, kActorPositionYOffset, 0.0f);
    int start_grid_x = 0;
    int start_grid_y = 0;
    int goal_grid_x = 0;
    int goal_grid_y = 0;
    if (!TryResolveGameplayPathCell(grid_snapshot, current_x, current_y, &start_grid_x, &start_grid_y)) {
        if (error_message != nullptr) {
            *error_message = "Current actor position is outside the gameplay path grid.";
        }
        return false;
    }
    if (!TryResolveGameplayPathCell(grid_snapshot, binding->target_x, binding->target_y, &goal_grid_x, &goal_grid_y)) {
        const auto resolved_goal_grid_x = static_cast<int>(std::floor(binding->target_y / grid_snapshot.cell_height));
        const auto resolved_goal_grid_y = static_cast<int>(std::floor(binding->target_x / grid_snapshot.cell_width));
        goal_grid_x = resolved_goal_grid_x < 0 ? 0 : (resolved_goal_grid_x >= grid_snapshot.width ? grid_snapshot.width - 1 : resolved_goal_grid_x);
        goal_grid_y = resolved_goal_grid_y < 0 ? 0 : (resolved_goal_grid_y >= grid_snapshot.height ? grid_snapshot.height - 1 : resolved_goal_grid_y);
    }

    const auto original_start_grid_x = start_grid_x;
    const auto original_start_grid_y = start_grid_y;
    std::vector<std::int8_t> traversable_cache(static_cast<std::size_t>(grid_snapshot.width * grid_snapshot.height), -1);
    int effective_start_grid_x = start_grid_x;
    int effective_start_grid_y = start_grid_y;
    if (!TryFindNearestTraversableGoalCell(
            grid_snapshot,
            binding,
            goal_grid_x,
            goal_grid_y,
            &effective_start_grid_x,
            &effective_start_grid_y,
            &traversable_cache,
            nullptr)) {
        if (error_message != nullptr) {
            *error_message =
                "No traversable start cell near actor grid=(" +
                std::to_string(start_grid_x) + ", " + std::to_string(start_grid_y) + ").";
        }
        return false;
    }
    start_grid_x = effective_start_grid_x;
    start_grid_y = effective_start_grid_y;
    const auto start_relocated =
        start_grid_x != original_start_grid_x ||
        start_grid_y != original_start_grid_y;
    if (!TryFindNearestTraversableGoalCell(
            grid_snapshot,
            binding,
            start_grid_x,
            start_grid_y,
            &goal_grid_x,
            &goal_grid_y,
            &traversable_cache,
            error_message)) {
        return false;
    }

    const auto node_count = static_cast<std::size_t>(grid_snapshot.width * grid_snapshot.height);
    const auto start_index = GameplayPathCellIndex(grid_snapshot, start_grid_x, start_grid_y);
    const auto goal_index = GameplayPathCellIndex(grid_snapshot, goal_grid_x, goal_grid_y);
    std::vector<float> g_score(node_count, FLT_MAX);
    std::vector<float> f_score(node_count, FLT_MAX);
    std::vector<int> parent(node_count, -1);
    std::vector<std::uint8_t> state(node_count, 0);
    std::vector<int> open_set;
    open_set.reserve(node_count);
    auto best_reachable_index = start_index;
    auto best_reachable_heuristic =
        EstimateGameplayPathHeuristic(start_grid_x, start_grid_y, goal_grid_x, goal_grid_y);
    g_score[static_cast<std::size_t>(start_index)] = 0.0f;
    f_score[static_cast<std::size_t>(start_index)] =
        EstimateGameplayPathHeuristic(start_grid_x, start_grid_y, goal_grid_x, goal_grid_y);
    state[static_cast<std::size_t>(start_index)] = 1;
    open_set.push_back(start_index);

    const int neighbor_offsets[8][2] = {
        { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 },
        { 1, 1 }, { 1, -1 }, { -1, 1 }, { -1, -1 },
    };

    bool found_path = false;
    while (!open_set.empty()) {
        auto best_it = open_set.begin();
        for (auto it = open_set.begin() + 1; it != open_set.end(); ++it) {
            if (f_score[static_cast<std::size_t>(*it)] < f_score[static_cast<std::size_t>(*best_it)]) {
                best_it = it;
            }
        }
        const auto current_index = *best_it;
        open_set.erase(best_it);
        state[static_cast<std::size_t>(current_index)] = 2;
        if (current_index == goal_index) {
            found_path = true;
            break;
        }

        const auto current_grid_x = current_index / grid_snapshot.height;
        const auto current_grid_y = current_index % grid_snapshot.height;
        const auto current_heuristic =
            EstimateGameplayPathHeuristic(current_grid_x, current_grid_y, goal_grid_x, goal_grid_y);
        if (current_heuristic < best_reachable_heuristic) {
            best_reachable_heuristic = current_heuristic;
            best_reachable_index = current_index;
        }
        const auto current_point_x =
            current_index == start_index && !start_relocated
                ? current_x
                : GameplayPathCellCenterX(grid_snapshot, current_grid_y);
        const auto current_point_y =
            current_index == start_index && !start_relocated
                ? current_y
                : GameplayPathCellCenterY(grid_snapshot, current_grid_x);
        for (const auto& offset : neighbor_offsets) {
            const auto next_grid_x = current_grid_x + offset[0];
            const auto next_grid_y = current_grid_y + offset[1];
            if (!IsGameplayPathCellInBounds(grid_snapshot, next_grid_x, next_grid_y)) {
                continue;
            }

            if (offset[0] != 0 && offset[1] != 0) {
                if (!IsGameplayPathCellTraversable(
                        grid_snapshot,
                        binding,
                        current_grid_x + offset[0],
                        current_grid_y,
                        &traversable_cache,
                        error_message) ||
                    !IsGameplayPathCellTraversable(
                        grid_snapshot,
                        binding,
                        current_grid_x,
                        current_grid_y + offset[1],
                        &traversable_cache,
                        error_message)) {
                    continue;
                }
            }

            if (!IsGameplayPathCellTraversable(
                    grid_snapshot,
                    binding,
                    next_grid_x,
                    next_grid_y,
                    &traversable_cache,
                    error_message)) {
                continue;
            }

            if (!IsGameplayPathSegmentTraversable(
                    grid_snapshot,
                    binding,
                    current_point_x,
                    current_point_y,
                    GameplayPathCellCenterX(grid_snapshot, next_grid_y),
                    GameplayPathCellCenterY(grid_snapshot, next_grid_x),
                    error_message)) {
                continue;
            }

            const auto next_index = GameplayPathCellIndex(grid_snapshot, next_grid_x, next_grid_y);
            if (state[static_cast<std::size_t>(next_index)] == 2) {
                continue;
            }

            const auto step_cost = (offset[0] != 0 && offset[1] != 0) ? 1.41421356237f : 1.0f;
            const auto tentative_g = g_score[static_cast<std::size_t>(current_index)] + step_cost;
            if (tentative_g >= g_score[static_cast<std::size_t>(next_index)]) {
                continue;
            }

            parent[static_cast<std::size_t>(next_index)] = current_index;
            g_score[static_cast<std::size_t>(next_index)] = tentative_g;
            f_score[static_cast<std::size_t>(next_index)] =
                tentative_g + EstimateGameplayPathHeuristic(next_grid_x, next_grid_y, goal_grid_x, goal_grid_y);
            if (state[static_cast<std::size_t>(next_index)] != 1) {
                state[static_cast<std::size_t>(next_index)] = 1;
                open_set.push_back(next_index);
            }
        }
    }

    auto resolved_goal_index = goal_index;
    auto resolved_goal_grid_x = goal_grid_x;
    auto resolved_goal_grid_y = goal_grid_y;
    if (!found_path) {
        if (best_reachable_index == start_index) {
            if (error_message != nullptr && error_message->empty()) {
                *error_message =
                    "A* search found no path. start=(" + std::to_string(start_grid_x) + ", " + std::to_string(start_grid_y) +
                    ") goal=(" + std::to_string(goal_grid_x) + ", " + std::to_string(goal_grid_y) + ")";
            }
            return false;
        }

        resolved_goal_index = best_reachable_index;
        resolved_goal_grid_x = resolved_goal_index / grid_snapshot.height;
        resolved_goal_grid_y = resolved_goal_index % grid_snapshot.height;
        Log(
            "[bots] path fallback reachable-goal. bot_id=" + std::to_string(binding->bot_id) +
            " revision=" + std::to_string(binding->movement_intent_revision) +
            " requested_goal=(" + std::to_string(goal_grid_x) + ", " + std::to_string(goal_grid_y) + ")" +
            " fallback_goal=(" + std::to_string(resolved_goal_grid_x) + ", " + std::to_string(resolved_goal_grid_y) + ")" +
            " heuristic=" + std::to_string(best_reachable_heuristic));
    }

    std::vector<int> reversed_indices;
    for (int cursor = resolved_goal_index; cursor != -1; cursor = parent[static_cast<std::size_t>(cursor)]) {
        reversed_indices.push_back(cursor);
        if (cursor == start_index) {
            break;
        }
    }
    if (reversed_indices.empty() || reversed_indices.back() != start_index) {
        if (error_message != nullptr) {
            *error_message = "A* reconstruction failed to reach the start node.";
        }
        return false;
    }

    std::vector<BotPathWaypoint> waypoints;
    waypoints.reserve(reversed_indices.size());
    for (auto it = reversed_indices.rbegin(); it != reversed_indices.rend(); ++it) {
        const auto index = *it;
        const auto grid_x = index / grid_snapshot.height;
        const auto grid_y = index % grid_snapshot.height;
        waypoints.push_back(BotPathWaypoint{
            grid_x,
            grid_y,
            GameplayPathCellCenterX(grid_snapshot, grid_y),
            GameplayPathCellCenterY(grid_snapshot, grid_x),
        });
    }

    if (!start_relocated &&
        !waypoints.empty() &&
        waypoints.front().grid_x == start_grid_x &&
        waypoints.front().grid_y == start_grid_y) {
        waypoints.erase(waypoints.begin());
    }
    SimplifyBotPathWaypoints(&waypoints);

    // Keep the path on cell centers by default. Replacing the final cell-center
    // waypoint with the exact destination looked attractive, but in live runs it
    // caused the final step to collide/slide while the route itself remained
    // valid. The cleaner approach is to stay on the proven grid path first and
    // only allow the exact target to replace the last waypoint when it is already
    // effectively inside that same waypoint.
    if (!waypoints.empty()) {
        const auto final_cell_dx = waypoints.back().x - binding->target_x;
        const auto final_cell_dy = waypoints.back().y - binding->target_y;
        const auto final_cell_gap = std::sqrt(final_cell_dx * final_cell_dx + final_cell_dy * final_cell_dy);
        if (final_cell_gap <= kWizardBotPathFinalArrivalThreshold &&
            IsGameplayPathPlacementTraversable(grid_snapshot, binding, binding->target_x, binding->target_y, nullptr)) {
            waypoints.back().x = binding->target_x;
            waypoints.back().y = binding->target_y;
        }
    } else if (IsGameplayPathPlacementTraversable(grid_snapshot, binding, binding->target_x, binding->target_y, nullptr)) {
        waypoints.push_back(BotPathWaypoint{
            resolved_goal_grid_x,
            resolved_goal_grid_y,
            binding->target_x,
            binding->target_y,
        });
    }

    binding->path_waypoints = std::move(waypoints);
    binding->path_waypoint_index = 0;
    binding->path_active = !binding->path_waypoints.empty();
    binding->path_failed = false;
    binding->active_path_revision = binding->movement_intent_revision;
    binding->next_path_retry_not_before_ms = 0;
    if (!binding->path_waypoints.empty()) {
        binding->current_waypoint_x = binding->path_waypoints.front().x;
        binding->current_waypoint_y = binding->path_waypoints.front().y;
    } else {
        binding->current_waypoint_x = binding->target_x;
        binding->current_waypoint_y = binding->target_y;
    }

    Log(
        "[bots] built path. bot_id=" + std::to_string(binding->bot_id) +
        " revision=" + std::to_string(binding->movement_intent_revision) +
        " start=(" + std::to_string(start_grid_x) + ", " + std::to_string(start_grid_y) + ")" +
        " goal=(" + std::to_string(resolved_goal_grid_x) + ", " + std::to_string(resolved_goal_grid_y) + ")" +
        " waypoint_count=" + std::to_string(binding->path_waypoints.size()) +
        (binding->path_waypoints.empty()
             ? std::string()
             : " first_waypoint=(" + std::to_string(binding->path_waypoints.front().x) + ", " +
                   std::to_string(binding->path_waypoints.front().y) + ")" +
                   " last_waypoint=(" + std::to_string(binding->path_waypoints.back().x) + ", " +
                   std::to_string(binding->path_waypoints.back().y) + ")") +
        " target=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")" +
        " built_at_ms=" + std::to_string(now_ms));
    return true;
}

bool UpdateWizardBotPathMotion(BotEntityBinding* binding, std::uint64_t now_ms, std::string* error_message) {
    if (binding == nullptr) {
        return false;
    }

    if (binding->controller_state != multiplayer::BotControllerState::Moving || !binding->has_target) {
        StopBotPathMotion(binding, false);
        return true;
    }

    const auto revision_changed = binding->active_path_revision != binding->movement_intent_revision;
    if (binding->path_failed && !revision_changed && now_ms < binding->next_path_retry_not_before_ms) {
        binding->movement_active = false;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        return true;
    }

    const auto rebuild_due =
        revision_changed ||
        (!binding->path_failed && (!binding->path_active || binding->path_waypoints.empty())) ||
        (binding->path_failed && now_ms >= binding->next_path_retry_not_before_ms);
    if (rebuild_due) {
        if (!TryBuildBotPath(binding, now_ms, error_message)) {
            binding->path_failed = true;
            binding->path_active = false;
            binding->active_path_revision = binding->movement_intent_revision;
            binding->next_path_retry_not_before_ms = now_ms + kWizardBotPathRetryDelayMs;
            binding->movement_active = false;
            binding->direction_x = 0.0f;
            binding->direction_y = 0.0f;
            return false;
        }
    }

    if (!binding->path_active || binding->path_waypoints.empty()) {
        binding->movement_active = false;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        if (now_ms - binding->last_path_debug_log_ms >= 1000) {
            binding->last_path_debug_log_ms = now_ms;
            Log(
                "[bots] path inactive. bot_id=" + std::to_string(binding->bot_id) +
                " revision=" + std::to_string(binding->movement_intent_revision) +
                " path_active=" + std::to_string(binding->path_active ? 1 : 0) +
                " waypoint_count=" + std::to_string(binding->path_waypoints.size()));
        }
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_x = memory.ReadFieldOr<float>(binding->actor_address, kActorPositionXOffset, 0.0f);
    const auto actor_y = memory.ReadFieldOr<float>(binding->actor_address, kActorPositionYOffset, 0.0f);
    while (binding->path_waypoint_index < binding->path_waypoints.size()) {
        const auto& waypoint = binding->path_waypoints[binding->path_waypoint_index];
        const auto delta_x = waypoint.x - actor_x;
        const auto delta_y = waypoint.y - actor_y;
        const auto distance = std::sqrt(delta_x * delta_x + delta_y * delta_y);
        const auto final_waypoint =
            binding->path_waypoint_index + 1 >= binding->path_waypoints.size();
        const auto arrival_threshold =
            final_waypoint ? kWizardBotPathFinalArrivalThreshold : kWizardBotPathWaypointArrivalThreshold;
        if (distance > arrival_threshold) {
            break;
        }
        ++binding->path_waypoint_index;
    }

    if (binding->path_waypoint_index >= binding->path_waypoints.size()) {
        binding->path_active = false;
        binding->movement_active = false;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        binding->current_waypoint_x = 0.0f;
        binding->current_waypoint_y = 0.0f;
        (void)multiplayer::StopBot(binding->bot_id);
        if (now_ms - binding->last_path_debug_log_ms >= 1000) {
            binding->last_path_debug_log_ms = now_ms;
            Log(
                "[bots] path complete. bot_id=" + std::to_string(binding->bot_id) +
                " revision=" + std::to_string(binding->movement_intent_revision) +
                " actor=(" + std::to_string(actor_x) + ", " + std::to_string(actor_y) + ")" +
                " destination=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")");
        }
        return true;
    }

    const auto& waypoint = binding->path_waypoints[binding->path_waypoint_index];
    const auto delta_x = waypoint.x - actor_x;
    const auto delta_y = waypoint.y - actor_y;
    const auto distance = std::sqrt(delta_x * delta_x + delta_y * delta_y);
    if (distance <= 0.0001f) {
        binding->movement_active = false;
        binding->direction_x = 0.0f;
        binding->direction_y = 0.0f;
        return true;
    }

    binding->movement_active = true;
    binding->direction_x = delta_x / distance;
    binding->direction_y = delta_y / distance;
    binding->desired_heading_valid = true;
    binding->desired_heading = NormalizeGameplayHeadingDegrees(
        static_cast<float>(std::atan2(binding->direction_y, binding->direction_x) * (180.0 / 3.14159265358979323846) + 90.0));
    binding->current_waypoint_x = waypoint.x;
    binding->current_waypoint_y = waypoint.y;
    if (now_ms - binding->last_path_debug_log_ms >= 1000) {
        binding->last_path_debug_log_ms = now_ms;
        Log(
            "[bots] path follow tick. bot_id=" + std::to_string(binding->bot_id) +
            " revision=" + std::to_string(binding->movement_intent_revision) +
            " actor=(" + std::to_string(actor_x) + ", " + std::to_string(actor_y) + ")" +
            " waypoint_index=" + std::to_string(binding->path_waypoint_index) +
            "/" + std::to_string(binding->path_waypoints.size()) +
            " waypoint=(" + std::to_string(binding->current_waypoint_x) + ", " + std::to_string(binding->current_waypoint_y) + ")" +
            " dir=(" + std::to_string(binding->direction_x) + ", " + std::to_string(binding->direction_y) + ")" +
            " distance=" + std::to_string(distance));
    }
    return true;
}
