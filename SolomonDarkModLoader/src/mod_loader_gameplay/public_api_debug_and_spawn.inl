bool TryGetGameplaySelectionDebugState(SDModGameplaySelectionDebugState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModGameplaySelectionDebugState{};
    uintptr_t table_address = 0;
    int entry_count = 0;
    if (!TryResolveGameplayIndexState(&table_address, &entry_count) || table_address == 0 || entry_count <= 0) {
        return false;
    }

    state->valid = true;
    state->table_address = table_address;
    state->entry_count = entry_count;
    for (int slot_index = 0; slot_index < static_cast<int>(kGameplayPlayerSlotCount); ++slot_index) {
        const auto table_index = static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex) + slot_index;
        int value = 0;
        if (table_index >= 0 && table_index < entry_count) {
            (void)TryReadGameplayIndexStateValue(table_index, &value);
        }
        state->slot_selection_entries[slot_index] = static_cast<std::int32_t>(value);
    }

    state->player_selection_state_0 =
        static_cast<std::int32_t>(ReadResolvedGlobalIntOr(kPlayerSelectionState0Global, 0));
    state->player_selection_state_1 =
        static_cast<std::int32_t>(ReadResolvedGlobalIntOr(kPlayerSelectionState1Global, 0));
    return true;
}

bool TryGetGameplayNavGridState(SDModGameplayNavGridState* state, int subdivisions) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModGameplayNavGridState{};

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid ||
        player_state.actor_address == 0 || player_state.world_address == 0) {
        return false;
    }

    GameplayPathGridSnapshot snapshot;
    std::string error_message;
    if (!TryBuildGameplayPathGridSnapshot(player_state.world_address, &snapshot, &error_message)) {
        return false;
    }

    state->valid = true;
    state->world_address = player_state.world_address;
    state->controller_address = snapshot.controller_address;
    state->cells_address = snapshot.cells_address;
    state->probe_actor_address = player_state.actor_address;
    state->width = snapshot.width;
    state->height = snapshot.height;
    state->cell_width = snapshot.cell_width;
    state->cell_height = snapshot.cell_height;
    state->probe_x = player_state.x;
    state->probe_y = player_state.y;
    state->subdivisions = subdivisions > 0 ? subdivisions : 1;
    state->cells.reserve(static_cast<std::size_t>(snapshot.width * snapshot.height));

    ParticipantEntityBinding probe_binding{};
    probe_binding.actor_address = player_state.actor_address;
    probe_binding.materialized_world_address = player_state.world_address;
    std::vector<std::int8_t> traversable_cache(static_cast<std::size_t>(snapshot.width * snapshot.height), -1);
    for (int grid_x = 0; grid_x < snapshot.width; ++grid_x) {
        for (int grid_y = 0; grid_y < snapshot.height; ++grid_y) {
            SDModGameplayNavCellState cell_state;
            cell_state.grid_x = grid_x;
            cell_state.grid_y = grid_y;
            cell_state.center_x = GameplayPathCellCenterX(snapshot, grid_y);
            cell_state.center_y = GameplayPathCellCenterY(snapshot, grid_x);
            cell_state.traversable =
                IsGameplayPathPlacementTraversable(
                    snapshot,
                    &probe_binding,
                    cell_state.center_x,
                    cell_state.center_y,
                    nullptr);
            cell_state.path_traversable =
                IsGameplayPathCellTraversable(
                    snapshot,
                    &probe_binding,
                    grid_x,
                    grid_y,
                    &traversable_cache,
                    nullptr);
            cell_state.samples.reserve(static_cast<std::size_t>(state->subdivisions * state->subdivisions));
            for (int sample_x = 0; sample_x < state->subdivisions; ++sample_x) {
                for (int sample_y = 0; sample_y < state->subdivisions; ++sample_y) {
                    SDModGameplayNavCellState::Sample sample_state;
                    sample_state.sample_x = sample_x;
                    sample_state.sample_y = sample_y;
                    sample_state.world_x =
                        static_cast<float>(grid_y) * snapshot.cell_width +
                        ((static_cast<float>(sample_y) + 0.5f) / static_cast<float>(state->subdivisions)) * snapshot.cell_width;
                    sample_state.world_y =
                        static_cast<float>(grid_x) * snapshot.cell_height +
                        ((static_cast<float>(sample_x) + 0.5f) / static_cast<float>(state->subdivisions)) * snapshot.cell_height;
                    sample_state.traversable =
                        IsGameplayPathPlacementTraversable(
                            snapshot,
                            &probe_binding,
                            sample_state.world_x,
                            sample_state.world_y,
                            nullptr);
                    cell_state.samples.push_back(sample_state);
                }
            }
            state->cells.push_back(std::move(cell_state));
        }
    }

    return true;
}

bool SpawnEnemyByType(
    int type_id,
    float x,
    float y,
    std::string* error_message,
    std::uint64_t* request_id) {
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "spawn enemy: gameplay action pump is not initialized.";
        }
        return false;
    }

    PendingEnemySpawnRequest request;
    request.request_id = g_gameplay_keyboard_injection.next_enemy_spawn_request_id.fetch_add(
        1,
        std::memory_order_acq_rel);
    request.type_id = type_id;
    request.x = x;
    request.y = y;
    if (request_id != nullptr) {
        *request_id = request.request_id;
    }
    return QueueEnemySpawnRequest(request, error_message);
}

bool TryGetLastEnemySpawnResult(SDModEnemySpawnResult* result, std::uint64_t request_id) {
    if (result == nullptr) {
        return false;
    }

    std::lock_guard<std::mutex> result_lock(g_last_enemy_spawn_result_mutex);
    if (!g_last_enemy_spawn_result.valid ||
        (request_id != 0 && g_last_enemy_spawn_result.request_id != request_id)) {
        *result = SDModEnemySpawnResult{};
        return false;
    }

    *result = g_last_enemy_spawn_result;
    return true;
}

bool RebindSceneActorCell(uintptr_t actor_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    DWORD exception_code = 0;
    if (TryRebindActorToOwnerWorld(actor_address, 0, &exception_code)) {
        return true;
    }
    if (error_message != nullptr) {
        *error_message =
            "WorldCellGrid_RebindActor failed for actor=" + HexString(actor_address) +
            " exception=" + HexString(exception_code);
    }
    return false;
}

bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "spawn reward: gameplay action pump is not initialized.";
        }
        return false;
    }

    PendingRewardSpawnRequest request;
    request.kind = std::string(kind);
    request.amount = amount;
    request.x = x;
    request.y = y;
    return QueueRewardSpawnRequest(request, error_message);
}
