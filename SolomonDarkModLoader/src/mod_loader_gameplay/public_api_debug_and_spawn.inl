bool TryGetGameplaySelectionDebugState(SDModGameplaySelectionDebugState* state) {
    if (state == nullptr) {
        return false;
    }

    *state = SDModGameplaySelectionDebugState{};
    std::scoped_lock concentration_context_lock(
        g_participant_concentration_context_mutex);
    if (g_participant_concentration_context_depth.load(
            std::memory_order_acquire) != 0) {
        // A native callback may re-enter this getter on the same thread while
        // a remote participant context is installed.  Treat that frame as an
        // unavailable snapshot; the next transport tick will read the restored
        // local lanes.
        return false;
    }
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
        std::int32_t concentration_a = -1;
        std::int32_t concentration_b = -1;
        (void)TryReadGameplayConcentrationStateForSlot(
            slot_index,
            &concentration_a,
            &concentration_b);
        state->concentration_entries_a_by_slot[slot_index] = concentration_a;
        state->concentration_entries_b_by_slot[slot_index] = concentration_b;
    }
    state->concentration_entry_a = state->concentration_entries_a_by_slot[0];
    state->concentration_entry_b = state->concentration_entries_b_by_slot[0];
    state->player_selection_state_0 = state->slot_selection_entries[0];
    state->player_selection_state_1 = state->slot_selection_entries[1];
    return true;
}

bool RunWithParticipantConcentrationContext(
    std::uint64_t participant_id,
    const std::function<bool()>& operation,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (participant_id == 0 || !operation) {
        return fail("Participant Concentrate context requires an operation and participant id.");
    }

    auto* binding = FindParticipantEntity(participant_id);
    if (binding == nullptr ||
        binding->controller_kind != multiplayer::ParticipantControllerKind::Native ||
        !binding->concentration_selection_valid) {
        return fail(
            "Participant Concentrate context requires a materialized native participant selection.");
    }

    ScopedParticipantConcentrationContext context(binding);
    if (!context.active) {
        return fail("Unable to install the participant Concentrate context: " + context.status);
    }

    const bool operation_succeeded = operation();
    context.Restore();
    if (!context.restored) {
        return fail("Unable to restore the local Concentrate context: " + context.status);
    }
    return operation_succeeded;
}

bool TryReconcileParticipantConcentrationRuntimeSelections(
    std::uint64_t participant_id,
    std::int32_t entry_a,
    std::int32_t entry_b,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (participant_id == 0 || entry_a < -1 || entry_b < -1) {
        return fail("Concentrate runtime-lane reconcile received invalid participant state.");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        !gameplay_state.entity_materialized ||
        gameplay_state.gameplay_slot < 0 ||
        gameplay_state.gameplay_slot >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return fail(
            "Concentrate runtime-lane reconcile requires a materialized gameplay-slot participant.");
    }
    if (!TryWriteGameplayConcentrationStateForSlot(
            gameplay_state.gameplay_slot,
            entry_a,
            entry_b,
            error_message)) {
        return false;
    }
    return true;
}

bool TryApplyParticipantConcentrationSelections(
    std::uint64_t participant_id,
    std::int32_t entry_a,
    std::int32_t entry_b,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (participant_id == 0) {
        return fail("Concentration-state apply requires a participant id.");
    }
    if (entry_a < -1 || entry_b < -1) {
        return fail("Concentration entries must be -1 or valid progression rows.");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        !gameplay_state.entity_materialized ||
        gameplay_state.actor_address == 0 ||
        gameplay_state.progression_runtime_state_address == 0 ||
        gameplay_state.gameplay_slot < 0 ||
        gameplay_state.gameplay_slot >= static_cast<int>(kGameplayPlayerSlotCount)) {
        return fail(
            "Concentration-state apply requires a materialized gameplay-slot participant.");
    }

    std::int32_t progression_entry_count = 0;
    if (!ProcessMemory::Instance().TryReadField(
            gameplay_state.progression_runtime_state_address,
            kStandaloneWizardProgressionTableCountOffset,
            &progression_entry_count) ||
        progression_entry_count <= 0 ||
        progression_entry_count > 4096) {
        return fail("Unable to validate Concentrate entries against the participant progression.");
    }
    if (entry_a >= progression_entry_count || entry_b >= progression_entry_count) {
        return fail("A Concentrate entry is outside the participant progression table.");
    }

    const auto concentration_a_index =
        static_cast<int>(kGameplayIndexStateConcentrationAIndex);
    const auto concentration_b_index =
        static_cast<int>(kGameplayIndexStateConcentrationBIndex);
    ScopedParticipantConcentrationSamplingSuppression sampling_suppression;
    int previous_a = -1;
    int previous_b = -1;
    if (!TryReadGameplayIndexStateValue(concentration_a_index, &previous_a) ||
        !TryReadGameplayIndexStateValue(concentration_b_index, &previous_b)) {
        return fail("Unable to snapshot the process Concentrate state.");
    }
    DWORD exception_code = 0;
    bool refresh_ok = false;
    bool restore_ok = false;
    std::string restore_error;
    if (!TryWriteGameplayConcentrationState(entry_a, entry_b, error_message)) {
        return false;
    }

    const auto refresh_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kActorProgressionRefresh);
    refresh_ok =
        refresh_address != 0 &&
        CallActorProgressionRefreshSafe(
            refresh_address,
            gameplay_state.actor_address,
            &exception_code);
    restore_ok = TryWriteGameplayConcentrationState(
        static_cast<std::int32_t>(previous_a),
        static_cast<std::int32_t>(previous_b),
        &restore_error);
    if (!refresh_ok) {
        return fail(
            "Participant progression refresh after Concentrate sync failed with 0x" +
            HexString(exception_code) + ".");
    }
    if (!restore_ok) {
        return fail(
            "Participant progression refresh succeeded but restoring the local "
            "Concentrate context failed: " + restore_error);
    }
    std::string runtime_lane_error;
    if (!TryReconcileParticipantConcentrationRuntimeSelections(
            participant_id,
            entry_a,
            entry_b,
            &runtime_lane_error)) {
        return fail(
            "Participant progression refreshed but its gameplay-slot Concentrate "
            "runtime lanes failed to reconcile: " + runtime_lane_error);
    }
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

bool RebindSceneActorCell(uintptr_t actor_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    DWORD exception_code = 0;
    if (TryRebindActorToOwnerWorld(actor_address, &exception_code)) {
        return true;
    }
    if (error_message != nullptr) {
        *error_message =
            "WorldCellGrid_RebindActor failed for actor=" + HexString(actor_address) +
            " exception=" + HexString(exception_code);
    }
    return false;
}

bool QueueManualRunEnemySpawn(
    int type_id,
    float x,
    float y,
    bool freeze_on_spawn,
    std::string* error_message,
    std::uint64_t* request_id) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn: gameplay action pump is not initialized.";
        }
        return false;
    }
    if (multiplayer::IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message = "manual run enemy spawn is host-authoritative while connected to multiplayer.";
        }
        return false;
    }

    return QueueRunLifecycleManualEnemySpawn(
        type_id,
        x,
        y,
        freeze_on_spawn,
        error_message,
        request_id);
}

bool TryGetLastManualRunEnemySpawnResult(
    SDModManualRunEnemySpawnResult* result,
    std::uint64_t request_id) {
    return TryGetRunLifecycleManualEnemySpawnResult(result, request_id);
}

void ClearManualRunEnemyFreeze(uintptr_t actor_address) {
    ClearRunLifecycleManualEnemyFreeze(actor_address);
}

bool SpawnReward(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "spawn reward: gameplay action pump is not initialized.";
        }
        return false;
    }
    if (multiplayer::IsLocalTransportClient()) {
        if (error_message != nullptr) {
            *error_message = "spawn reward is host-authoritative while connected to multiplayer.";
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
