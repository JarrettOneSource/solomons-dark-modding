bool IsHostLootDropDeactivationKind(multiplayer::LootDropKind drop_kind) {
    return drop_kind == multiplayer::LootDropKind::Gold ||
           drop_kind == multiplayer::LootDropKind::Orb ||
           drop_kind == multiplayer::LootDropKind::Item ||
           drop_kind == multiplayer::LootDropKind::Potion ||
           drop_kind == multiplayer::LootDropKind::Powerup;
}

bool ExecuteHostLootDropDeactivationNow(
    const PendingHostLootDropDeactivation& request,
    SDModHostLootDropDeactivationResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = {};
    result->run_nonce = request.run_nonce;
    result->network_drop_id = request.network_drop_id;
    result->actor_address = request.actor_address;
    result->drop_kind = request.drop_kind;

    if (!multiplayer::IsLocalTransportHost() ||
        request.run_nonce == 0 ||
        request.network_drop_id == 0 ||
        request.actor_address == 0 ||
        !IsHostLootDropDeactivationKind(request.drop_kind)) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local_participant = multiplayer::FindLocalParticipant(runtime_state);
    if (local_participant == nullptr ||
        !local_participant->runtime.valid ||
        !local_participant->runtime.in_run ||
        (local_participant->runtime.run_nonce != 0 &&
         local_participant->runtime.run_nonce != request.run_nonce)) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) ||
        !scene_state.valid ||
        (scene_state.kind != "arena" && scene_state.name != "testrun") ||
        !IsSceneActorAddressPresent(request.actor_address)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    bool neutralized = true;
    if (request.drop_kind == multiplayer::LootDropKind::Gold) {
        const std::uint8_t inactive = 0;
        const std::uint32_t zero = 0;
        neutralized =
            memory.TryWriteField(
                request.actor_address,
                kReplicatedGoldActiveOffset,
                inactive) &&
            memory.TryWriteField(
                request.actor_address,
                kReplicatedGoldAmountOffset,
                zero) &&
            memory.TryWriteField(
                request.actor_address,
                kReplicatedGoldLifetimeOffset,
                zero);
    } else if (request.drop_kind == multiplayer::LootDropKind::Orb) {
        const float zero_value = 0.0f;
        const float settled_motion = 0.0f;
        const std::uint32_t expired_lifetime = 0;
        neutralized =
            memory.TryWriteField(
                request.actor_address,
                kReplicatedOrbValueOffset,
                zero_value) &&
            memory.TryWriteField(
                request.actor_address,
                kReplicatedOrbLifetimeOffset,
                expired_lifetime) &&
            memory.TryWriteField(
                request.actor_address,
                kReplicatedOrbMotionOffset,
                settled_motion);
    } else if (request.drop_kind == multiplayer::LootDropKind::Powerup) {
        const std::uint32_t expired_lifetime = 0;
        neutralized = memory.TryWriteField(
            request.actor_address,
            kReplicatedPowerupLifetimeOffset,
            expired_lifetime);
    }
    if (!neutralized) {
        return false;
    }

    DWORD exception_code = 0;
    // Gold::Tick (0x005E66B0), Orb::Tick (0x005E62E0),
    // Sack::Tick (0x005E6B50), and Bonus::Tick (0x006039C0) all retire
    // collected actors through vtable+0x18. The shared stock implementation
    // (0x00401FD0) marks actor+0x05 terminal; the world removes it only after
    // every current-frame reader has drained.
    result->deactivated = CallActorRequestRetirementSafe(
        request.actor_address,
        &exception_code);
    result->exception_code = static_cast<std::uint32_t>(exception_code);
    return result->deactivated;
}

bool QueueHostLootDropDeactivationInternal(
    std::uint32_t run_nonce,
    std::uint64_t network_drop_id,
    uintptr_t actor_address,
    multiplayer::LootDropKind drop_kind,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    const auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    if (!g_gameplay_keyboard_injection.initialized) {
        return fail("Gameplay action pump is not initialized.");
    }
    if (!multiplayer::IsLocalTransportHost()) {
        return fail("Host loot deactivation is host-only.");
    }
    if (run_nonce == 0 ||
        network_drop_id == 0 ||
        actor_address == 0 ||
        !IsHostLootDropDeactivationKind(drop_kind)) {
        return fail("Host loot deactivation metadata is invalid.");
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& state = g_gameplay_keyboard_injection;
    if (state.host_loot_drop_deactivation_run_nonce != 0 &&
        state.host_loot_drop_deactivation_run_nonce != run_nonce) {
        state.pending_host_loot_drop_deactivations.clear();
        state.pending_host_loot_drop_deactivation_ids.clear();
        state.completed_host_loot_drop_deactivations.clear();
    }
    state.host_loot_drop_deactivation_run_nonce = run_nonce;

    if (state.pending_host_loot_drop_deactivation_ids.find(network_drop_id) !=
        state.pending_host_loot_drop_deactivation_ids.end()) {
        return true;
    }
    if (state.pending_host_loot_drop_deactivations.size() >=
        kQueuedGameplayWorldActionLimit) {
        return fail("Host loot deactivation queue is full.");
    }

    PendingHostLootDropDeactivation request;
    request.run_nonce = run_nonce;
    request.network_drop_id = network_drop_id;
    request.actor_address = actor_address;
    request.drop_kind = drop_kind;
    state.pending_host_loot_drop_deactivations.push_back(request);
    state.pending_host_loot_drop_deactivation_ids.insert(network_drop_id);
    return true;
}

bool TryTakeHostLootDropDeactivationResultInternal(
    SDModHostLootDropDeactivationResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = {};
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& completed =
        g_gameplay_keyboard_injection.completed_host_loot_drop_deactivations;
    if (completed.empty()) {
        return false;
    }
    *result = completed.front();
    completed.pop_front();
    return true;
}

void ClearHostLootDropDeactivationStateInternal() {
    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& state = g_gameplay_keyboard_injection;
    state.pending_host_loot_drop_deactivations.clear();
    state.pending_host_loot_drop_deactivation_ids.clear();
    state.completed_host_loot_drop_deactivations.clear();
    state.host_loot_drop_deactivation_run_nonce = 0;
}

void PumpHostLootDropDeactivation() {
    PendingHostLootDropDeactivation request;
    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        auto& pending =
            g_gameplay_keyboard_injection.pending_host_loot_drop_deactivations;
        if (pending.empty()) {
            return;
        }
        request = pending.front();
        pending.pop_front();
    }

    SDModHostLootDropDeactivationResult result;
    (void)ExecuteHostLootDropDeactivationNow(request, &result);

    {
        std::lock_guard<std::mutex> lock(
            g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        auto& state = g_gameplay_keyboard_injection;
        state.pending_host_loot_drop_deactivation_ids.erase(
            request.network_drop_id);
        if (state.host_loot_drop_deactivation_run_nonce == request.run_nonce) {
            if (state.completed_host_loot_drop_deactivations.size() >=
                kQueuedGameplayWorldActionLimit) {
                state.completed_host_loot_drop_deactivations.pop_front();
            }
            state.completed_host_loot_drop_deactivations.push_back(result);
        }
    }

    Log(
        "native_loot: stock deferred-retirement request completed at the post-stock "
        "AppMainTick boundary. "
        "network_drop_id=" + std::to_string(request.network_drop_id) +
        " kind=" + multiplayer::LootDropKindLabel(request.drop_kind) +
        " actor=" + HexString(request.actor_address) +
        " deactivated=" + std::to_string(result.deactivated ? 1 : 0) +
        " seh=" + HexString(static_cast<uintptr_t>(result.exception_code)));
}
