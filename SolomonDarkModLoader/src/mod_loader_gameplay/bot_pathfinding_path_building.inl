void SimplifyBotPathWaypoints(
    const GameplayPathGridSnapshot& snapshot,
    ParticipantEntityBinding* binding,
    std::vector<BotPathWaypoint>* waypoints) {
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
        if (previous_dx == next_dx && previous_dy == next_dy &&
            binding != nullptr &&
            IsGameplayPathSegmentTraversable(
                snapshot,
                binding,
                previous.x,
                previous.y,
                next.x,
                next.y,
                nullptr)) {
            continue;
        }
        simplified.push_back(current);
    }
    simplified.push_back(waypoints->back());
    *waypoints = std::move(simplified);
}

bool TryBuildBotPath(
    ParticipantEntityBinding* binding,
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
    auto start_anchor_x = current_x;
    auto start_anchor_y = current_y;
    auto path_target_x = binding->target_x;
    auto path_target_y = binding->target_y;
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
    if (!TryResolveGameplayPathCell(grid_snapshot, path_target_x, path_target_y, &goal_grid_x, &goal_grid_y)) {
        const auto resolved_goal_grid_x = static_cast<int>(std::floor(path_target_y / grid_snapshot.cell_height));
        const auto resolved_goal_grid_y = static_cast<int>(std::floor(path_target_x / grid_snapshot.cell_width));
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
    bool start_relocated =
        start_grid_x != original_start_grid_x ||
        start_grid_y != original_start_grid_y;
    {
        float resolved_start_anchor_x = 0.0f;
        float resolved_start_anchor_y = 0.0f;
        if (TryFindGameplayPathCellSample(
                grid_snapshot,
                binding,
                start_grid_x,
                start_grid_y,
                current_x,
                current_y,
                false,
                true,
                current_x,
                current_y,
                &resolved_start_anchor_x,
                &resolved_start_anchor_y,
                nullptr)) {
            start_anchor_x = resolved_start_anchor_x;
            start_anchor_y = resolved_start_anchor_y;
            const auto start_anchor_delta_x = start_anchor_x - current_x;
            const auto start_anchor_delta_y = start_anchor_y - current_y;
            const auto start_anchor_delta =
                std::sqrt(start_anchor_delta_x * start_anchor_delta_x + start_anchor_delta_y * start_anchor_delta_y);
            if (start_anchor_delta > 0.5f) {
                start_relocated = true;
            }
        }
    }
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

    if (start_grid_x == goal_grid_x && start_grid_y == goal_grid_y) {
        float resolved_target_x = 0.0f;
        float resolved_target_y = 0.0f;
        if (TryResolveNearestTraversablePlacement(
                binding->materialized_world_address,
                binding->actor_address,
                path_target_x,
                path_target_y,
                &resolved_target_x,
                &resolved_target_y,
                nullptr)) {
            path_target_x = resolved_target_x;
            path_target_y = resolved_target_y;
            if (!TryResolveGameplayPathCell(grid_snapshot, path_target_x, path_target_y, &goal_grid_x, &goal_grid_y)) {
                const auto resolved_goal_grid_x = static_cast<int>(std::floor(path_target_y / grid_snapshot.cell_height));
                const auto resolved_goal_grid_y = static_cast<int>(std::floor(path_target_x / grid_snapshot.cell_width));
                goal_grid_x =
                    resolved_goal_grid_x < 0 ? 0
                                             : (resolved_goal_grid_x >= grid_snapshot.width ? grid_snapshot.width - 1 : resolved_goal_grid_x);
                goal_grid_y =
                    resolved_goal_grid_y < 0 ? 0
                                             : (resolved_goal_grid_y >= grid_snapshot.height ? grid_snapshot.height - 1 : resolved_goal_grid_y);
            }
        }
    }

    const auto node_count = static_cast<std::size_t>(grid_snapshot.width * grid_snapshot.height);
    const auto start_index = GameplayPathCellIndex(grid_snapshot, start_grid_x, start_grid_y);
    const auto goal_index = GameplayPathCellIndex(grid_snapshot, goal_grid_x, goal_grid_y);

    if (start_index == goal_index) {
        float direct_goal_x = 0.0f;
        float direct_goal_y = 0.0f;
        if (!TryFindGameplayPathCellSample(
                grid_snapshot,
                binding,
                goal_grid_x,
                goal_grid_y,
                path_target_x,
                path_target_y,
                true,
                false,
                start_anchor_x,
                start_anchor_y,
                &direct_goal_x,
                &direct_goal_y,
                error_message)) {
            return false;
        }

        binding->path_waypoints.clear();
        const auto actor_to_direct_goal_x = direct_goal_x - current_x;
        const auto actor_to_direct_goal_y = direct_goal_y - current_y;
        const auto actor_to_direct_goal_gap =
            std::sqrt(actor_to_direct_goal_x * actor_to_direct_goal_x + actor_to_direct_goal_y * actor_to_direct_goal_y);
        const auto delta_x = direct_goal_x - start_anchor_x;
        const auto delta_y = direct_goal_y - start_anchor_y;
        const auto direct_gap = std::sqrt(delta_x * delta_x + delta_y * delta_y);
        if (start_relocated && actor_to_direct_goal_gap > kWizardBotPathFinalArrivalThreshold) {
            binding->path_waypoints.push_back(BotPathWaypoint{
                goal_grid_x,
                goal_grid_y,
                direct_goal_x,
                direct_goal_y,
            });
        } else if (direct_gap > kWizardBotPathFinalArrivalThreshold) {
            binding->path_waypoints.push_back(BotPathWaypoint{
                goal_grid_x,
                goal_grid_y,
                direct_goal_x,
                direct_goal_y,
            });
        } else {
            const auto raw_target_dx = path_target_x - current_x;
            const auto raw_target_dy = path_target_y - current_y;
            const auto raw_target_gap =
                std::sqrt(raw_target_dx * raw_target_dx + raw_target_dy * raw_target_dy);
            // The sampler may settle on the current anchor when the exact target
            // is inside the cell but not actually safe to walk to. Falling back
            // to the raw target in that case defeats the narrow-lane fix and can
            // feed stock movement an unsafe final point.
            if (raw_target_gap > kWizardBotPathFinalArrivalThreshold &&
                IsGameplayPathPlacementTraversable(
                    grid_snapshot,
                    binding,
                    path_target_x,
                    path_target_y,
                    nullptr) &&
                IsGameplayPathSegmentTraversable(
                    grid_snapshot,
                    binding,
                    start_anchor_x,
                    start_anchor_y,
                    path_target_x,
                    path_target_y,
                    nullptr)) {
                binding->path_waypoints.push_back(BotPathWaypoint{
                    goal_grid_x,
                    goal_grid_y,
                    path_target_x,
                    path_target_y,
                });
            }
        }

        binding->path_waypoint_index = 0;
        binding->path_active = !binding->path_waypoints.empty();
        binding->path_failed = false;
        binding->active_path_revision = binding->movement_intent_revision;
        binding->next_path_retry_not_before_ms = 0;
        binding->current_waypoint_x = direct_goal_x;
        binding->current_waypoint_y = direct_goal_y;

        Log(
            "[bots] built path. bot_id=" + std::to_string(binding->bot_id) +
            " revision=" + std::to_string(binding->movement_intent_revision) +
            " start=(" + std::to_string(start_grid_x) + ", " + std::to_string(start_grid_y) + ")" +
            " goal=(" + std::to_string(goal_grid_x) + ", " + std::to_string(goal_grid_y) + ")" +
            " waypoint_count=" + std::to_string(binding->path_waypoints.size()) +
            (binding->path_waypoints.empty()
                 ? std::string()
                 : " first_waypoint=(" + std::to_string(binding->path_waypoints.front().x) + ", " +
                       std::to_string(binding->path_waypoints.front().y) + ")" +
                       " last_waypoint=(" + std::to_string(binding->path_waypoints.back().x) + ", " +
                       std::to_string(binding->path_waypoints.back().y) + ")") +
            " target=(" + std::to_string(binding->target_x) + ", " + std::to_string(binding->target_y) + ")" +
            " resolved_target=(" + std::to_string(path_target_x) + ", " + std::to_string(path_target_y) + ")" +
            " built_at_ms=" + std::to_string(now_ms));
        return true;
    }

    std::vector<float> g_score(node_count, FLT_MAX);
    std::vector<float> f_score(node_count, FLT_MAX);
    std::vector<int> parent(node_count, -1);
    std::vector<std::uint8_t> state(node_count, 0);
    std::vector<float> node_point_x(node_count, 0.0f);
    std::vector<float> node_point_y(node_count, 0.0f);
    std::vector<std::uint8_t> node_point_valid(node_count, 0);
    std::vector<int> open_set;
    open_set.reserve(node_count);
    auto best_reachable_index = start_index;
    auto best_reachable_heuristic =
        EstimateGameplayPathHeuristic(start_grid_x, start_grid_y, goal_grid_x, goal_grid_y);
    g_score[static_cast<std::size_t>(start_index)] = 0.0f;
    f_score[static_cast<std::size_t>(start_index)] =
        EstimateGameplayPathHeuristic(start_grid_x, start_grid_y, goal_grid_x, goal_grid_y);
    state[static_cast<std::size_t>(start_index)] = 1;
    node_point_x[static_cast<std::size_t>(start_index)] = current_x;
    node_point_y[static_cast<std::size_t>(start_index)] = current_y;
    node_point_valid[static_cast<std::size_t>(start_index)] = 1;
    node_point_x[static_cast<std::size_t>(start_index)] = start_anchor_x;
    node_point_y[static_cast<std::size_t>(start_index)] = start_anchor_y;
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
            node_point_valid[static_cast<std::size_t>(current_index)] != 0
                ? node_point_x[static_cast<std::size_t>(current_index)]
                : (current_index == start_index && !start_relocated
                       ? current_x
                       : GameplayPathCellCenterX(grid_snapshot, current_grid_y));
        const auto current_point_y =
            node_point_valid[static_cast<std::size_t>(current_index)] != 0
                ? node_point_y[static_cast<std::size_t>(current_index)]
                : (current_index == start_index && !start_relocated
                       ? current_y
                       : GameplayPathCellCenterY(grid_snapshot, current_grid_x));
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

            float candidate_point_x = 0.0f;
            float candidate_point_y = 0.0f;
            if (!TryFindGameplayPathCellSample(
                    grid_snapshot,
                    binding,
                    next_grid_x,
                    next_grid_y,
                    GameplayPathCellCenterX(grid_snapshot, next_grid_y),
                    GameplayPathCellCenterY(grid_snapshot, next_grid_x),
                    true,
                    true,
                    current_point_x,
                    current_point_y,
                    &candidate_point_x,
                    &candidate_point_y,
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
            node_point_x[static_cast<std::size_t>(next_index)] = candidate_point_x;
            node_point_y[static_cast<std::size_t>(next_index)] = candidate_point_y;
            node_point_valid[static_cast<std::size_t>(next_index)] = 1;
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
            const auto actor_to_start_anchor_x = start_anchor_x - current_x;
            const auto actor_to_start_anchor_y = start_anchor_y - current_y;
            const auto actor_to_start_anchor_gap =
                std::sqrt(actor_to_start_anchor_x * actor_to_start_anchor_x + actor_to_start_anchor_y * actor_to_start_anchor_y);
            if (start_relocated && actor_to_start_anchor_gap > kWizardBotPathFinalArrivalThreshold) {
                binding->path_waypoints.clear();
                binding->path_waypoints.push_back(BotPathWaypoint{
                    start_grid_x,
                    start_grid_y,
                    start_anchor_x,
                    start_anchor_y,
                });
                binding->path_waypoint_index = 0;
                binding->path_active = true;
                binding->path_failed = false;
                binding->active_path_revision = binding->movement_intent_revision;
                binding->next_path_retry_not_before_ms = 0;
                binding->current_waypoint_x = start_anchor_x;
                binding->current_waypoint_y = start_anchor_y;
                Log(
                    "[bots] path fallback start-anchor. bot_id=" + std::to_string(binding->bot_id) +
                    " revision=" + std::to_string(binding->movement_intent_revision) +
                    " start=(" + std::to_string(start_grid_x) + ", " + std::to_string(start_grid_y) + ")" +
                    " anchor=(" + std::to_string(start_anchor_x) + ", " + std::to_string(start_anchor_y) + ")" +
                    " actor=(" + std::to_string(current_x) + ", " + std::to_string(current_y) + ")");
                return true;
            }
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
            node_point_valid[static_cast<std::size_t>(index)] != 0
                ? node_point_x[static_cast<std::size_t>(index)]
                : GameplayPathCellCenterX(grid_snapshot, grid_y),
            node_point_valid[static_cast<std::size_t>(index)] != 0
                ? node_point_y[static_cast<std::size_t>(index)]
                : GameplayPathCellCenterY(grid_snapshot, grid_x),
        });
    }

    if (!start_relocated &&
        !waypoints.empty() &&
        waypoints.front().grid_x == start_grid_x &&
        waypoints.front().grid_y == start_grid_y) {
        waypoints.erase(waypoints.begin());
    }
    SimplifyBotPathWaypoints(grid_snapshot, binding, &waypoints);

    // Keep the path on cell centers by default. Replacing the final cell-center
    // waypoint with the exact destination looked attractive, but in live runs it
    // caused the final step to collide/slide while the route itself remained
    // valid. The cleaner approach is to stay on the proven grid path first and
    // only allow the exact target to replace the last waypoint when it is already
    // effectively inside that same waypoint.
    if (!waypoints.empty()) {
        const auto final_cell_dx = waypoints.back().x - path_target_x;
        const auto final_cell_dy = waypoints.back().y - path_target_y;
        const auto final_cell_gap = std::sqrt(final_cell_dx * final_cell_dx + final_cell_dy * final_cell_dy);
        if (final_cell_gap <= kWizardBotPathFinalArrivalThreshold &&
            IsGameplayPathPlacementTraversable(grid_snapshot, binding, path_target_x, path_target_y, nullptr)) {
            waypoints.back().x = path_target_x;
            waypoints.back().y = path_target_y;
        }
    } else if (IsGameplayPathPlacementTraversable(grid_snapshot, binding, path_target_x, path_target_y, nullptr)) {
        waypoints.push_back(BotPathWaypoint{
            resolved_goal_grid_x,
            resolved_goal_grid_y,
            path_target_x,
            path_target_y,
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
        binding->current_waypoint_x = path_target_x;
        binding->current_waypoint_y = path_target_y;
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
        " resolved_target=(" + std::to_string(path_target_x) + ", " + std::to_string(path_target_y) + ")" +
        " built_at_ms=" + std::to_string(now_ms));
    return true;
}
