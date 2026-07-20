// Public local cast, damage, death, loot-pickup, and inventory queue APIs.

std::uint64_t QueueLocalCastEventInternal(
    CastKind cast_kind,
    std::int32_t secondary_slot,
    std::int32_t skill_id,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    std::uint32_t hold_frames,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y,
    const std::int32_t* live_secondary_entry_indices,
    std::size_t live_secondary_entry_count) {
    if (skill_id < 0 ||
        (cast_kind != CastKind::Primary && cast_kind != CastKind::Secondary) ||
        (cast_kind == CastKind::Primary && secondary_slot != -1) ||
        (cast_kind == CastKind::Secondary &&
         (secondary_slot < 0 ||
          secondary_slot >=
              static_cast<std::int32_t>(kSecondaryLoadoutSlotCount))) ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(direction_x) ||
        !std::isfinite(direction_y)) {
        return 0;
    }
    if (has_aim_target &&
        !IsUsableLocalCastAimTarget(position_x, position_y, aim_target_x, aim_target_y)) {
        has_aim_target = false;
        aim_target_x = 0.0f;
        aim_target_y = 0.0f;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalCastEvents = 16;
    if (g_queued_local_cast_events.size() >= kMaxQueuedLocalCastEvents) {
        g_queued_local_cast_events.erase(g_queued_local_cast_events.begin());
    }
    QueuedLocalCastEvent event;
    event.native_queue_id = g_next_local_cast_event_id++;
    if (g_next_local_cast_event_id == 0) {
        g_next_local_cast_event_id = 1;
    }
    event.cast_kind = cast_kind;
    event.secondary_slot = secondary_slot;
    event.skill_id = skill_id;
    if (cast_kind == CastKind::Secondary &&
        live_secondary_entry_indices != nullptr &&
        live_secondary_entry_count == event.live_secondary_entry_indices.size()) {
        std::copy_n(
            live_secondary_entry_indices,
            live_secondary_entry_count,
            event.live_secondary_entry_indices.begin());
        event.has_live_secondary_loadout =
            event.live_secondary_entry_indices[
                static_cast<std::size_t>(secondary_slot)] == skill_id;
    }
    event.target_network_actor_id = target_network_actor_id;
    event.target_actor_address = target_actor_address;
    if (hold_frames > 0) {
        constexpr std::uint64_t kApproximateFrameMs = 16;
        event.minimum_hold_until_ms =
            static_cast<std::uint64_t>(GetTickCount64()) +
            static_cast<std::uint64_t>(hold_frames) * kApproximateFrameMs;
    }
    event.position_x = position_x;
    event.position_y = position_y;
    event.direction_x = direction_x;
    event.direction_y = direction_y;
    event.has_aim_target = has_aim_target;
    event.aim_target_x = aim_target_x;
    event.aim_target_y = aim_target_y;
    g_queued_local_cast_events.push_back(event);
    return event.native_queue_id;
}

std::uint64_t QueueLocalSpellCastEvent(
    std::int32_t skill_id,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    std::uint32_t hold_frames,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y) {
    return QueueLocalCastEventInternal(
        CastKind::Primary,
        -1,
        skill_id,
        position_x,
        position_y,
        direction_x,
        direction_y,
        target_network_actor_id,
        target_actor_address,
        hold_frames,
        has_aim_target,
        aim_target_x,
        aim_target_y,
        nullptr,
        0);
}

std::uint64_t QueueLocalSecondarySpellCastEvent(
    std::int32_t skill_id,
    std::int32_t secondary_slot,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    std::uint64_t target_network_actor_id,
    uintptr_t target_actor_address,
    bool has_aim_target,
    float aim_target_x,
    float aim_target_y,
    const std::int32_t* live_secondary_entry_indices,
    std::size_t live_secondary_entry_count) {
    return QueueLocalCastEventInternal(
        CastKind::Secondary,
        secondary_slot,
        skill_id,
        position_x,
        position_y,
        direction_x,
        direction_y,
        target_network_actor_id,
        target_actor_address,
        0,
        has_aim_target,
        aim_target_x,
        aim_target_y,
        live_secondary_entry_indices,
        live_secondary_entry_count);
}

void QueueLocalEnemyDamageClaim(
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional) {
    if (network_actor_id == 0 ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(local_hp) ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f ||
        !std::isfinite(target_position_x) ||
        !std::isfinite(target_position_y) ||
        local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        return;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    constexpr std::size_t kMaxQueuedLocalEnemyDamageClaims = 32;
    if (g_queued_local_enemy_damage_claims.size() >= kMaxQueuedLocalEnemyDamageClaims) {
        g_queued_local_enemy_damage_claims.erase(g_queued_local_enemy_damage_claims.begin());
    }
    QueuedLocalEnemyDamageClaim claim;
    claim.network_actor_id = network_actor_id;
    claim.skill_id = skill_id;
    claim.authoritative_hp = authoritative_hp;
    claim.local_hp = local_hp;
    claim.max_hp = max_hp;
    claim.target_position_x = target_position_x;
    claim.target_position_y = target_position_y;
    claim.target_position_optional = target_position_optional;
    claim.baseline_prevalidated =
        !IsLocalTransportClient() ||
        HasReplicatedRunEnemyDamageBaseline(network_actor_id);
    g_queued_local_enemy_damage_claims.push_back(claim);
    if (local_hp <= kEnemyDamageClaimHpEpsilon && IsLocalTransportClient()) {
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms[network_actor_id] =
            static_cast<std::uint64_t>(GetTickCount64()) +
            kEnemyDamageLethalClaimPendingSuppressMs;
    }
}

void NotifyLocalRunEnemyDeath(uintptr_t actor_address) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        actor_address == 0) {
        return;
    }

    SDModSceneActorState actor;
    if (!TryGetRunEnemyActorForDeathSnapshotByAddress(actor_address, &actor)) {
        return;
    }

    const auto network_actor_id = ResolveLocalRunEnemyNetworkActorId(actor);
    if (network_actor_id == 0) {
        return;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    RecordRecentRunEnemyDeathSnapshot(network_actor_id, actor, now_ms);
    Log(
        "world_snapshot: recorded host run enemy death snapshot from native hook. actor=" +
        HexString(actor.actor_address) +
        " network_actor_id=" + std::to_string(network_actor_id) +
        " type=" + HexString(static_cast<uintptr_t>(actor.object_type_id)) +
        " enemy_type=" + std::to_string(actor.enemy_type) +
        " hp=" + std::to_string(actor.hp) +
        " max_hp=" + std::to_string(actor.max_hp));
}

bool QueueLocalLootPickupRequest(
    std::uint64_t network_drop_id,
    std::uint32_t* request_sequence,
    std::string* error_message,
    const LootPickupRequestCapture* capture) {
    if (request_sequence != nullptr) {
        *request_sequence = 0;
    }
    auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    if (!IsLocalTransportEnabled()) {
        return fail("local transport is not enabled");
    }
    if (!IsLocalTransportClient()) {
        return fail("loot pickup requests are currently client-to-host only");
    }
    if (network_drop_id == 0) {
        return fail("network_drop_id must be non-zero");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return fail("local participant is not in a run");
    }
    const LootDropSnapshot* queued_drop =
        runtime_state.loot_snapshot.valid &&
                runtime_state.loot_snapshot.scene_intent.kind == ParticipantSceneIntentKind::Run
            ? FindLootDropSnapshotByNetworkId(runtime_state.loot_snapshot, network_drop_id)
            : nullptr;
    const bool present_in_loot_snapshot = queued_drop != nullptr;
    const bool matches_recent_pickup_result =
        runtime_state.last_loot_pickup_result.valid &&
        runtime_state.last_loot_pickup_result.network_drop_id == network_drop_id;
    if (!present_in_loot_snapshot && !matches_recent_pickup_result) {
        return fail("network_drop_id is not present in the replicated loot snapshot");
    }

    LootPickupRequestCapture resolved_capture{};
    if (capture != nullptr && capture->valid) {
        resolved_capture = *capture;
    } else if (present_in_loot_snapshot) {
        SDModPlayerState player_state;
        if (TryGetPlayerState(&player_state) && player_state.valid) {
            resolved_capture.valid = true;
            resolved_capture.requester_position_x = player_state.x;
            resolved_capture.requester_position_y = player_state.y;
            resolved_capture.drop_position_x = queued_drop->position_x;
            resolved_capture.drop_position_y = queued_drop->position_y;
        }
    }
    const bool resolved_capture_valid =
        resolved_capture.valid &&
        std::isfinite(resolved_capture.requester_position_x) &&
        std::isfinite(resolved_capture.requester_position_y) &&
        std::isfinite(resolved_capture.drop_position_x) &&
        std::isfinite(resolved_capture.drop_position_y);

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    const auto queued_request_it = std::find_if(
        g_queued_local_loot_pickup_requests.begin(),
        g_queued_local_loot_pickup_requests.end(),
        [&](const QueuedLocalLootPickupRequest& queued_request) {
            return queued_request.network_drop_id == network_drop_id;
        });
    if (queued_request_it != g_queued_local_loot_pickup_requests.end()) {
        if (resolved_capture_valid) {
            queued_request_it->has_pickup_positions = true;
            queued_request_it->requester_position_x =
                resolved_capture.requester_position_x;
            queued_request_it->requester_position_y =
                resolved_capture.requester_position_y;
            queued_request_it->drop_position_x =
                resolved_capture.drop_position_x;
            queued_request_it->drop_position_y =
                resolved_capture.drop_position_y;
        }
        if (request_sequence != nullptr) {
            *request_sequence = queued_request_it->request_sequence;
        }
        return true;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto in_flight_it =
        g_in_flight_local_loot_pickup_requests_by_drop_id.find(
            network_drop_id);
    if (in_flight_it !=
        g_in_flight_local_loot_pickup_requests_by_drop_id.end()) {
        if (now_ms - in_flight_it->second.sent_ms <
            kLocalLootPickupRequestRetryMs) {
            if (request_sequence != nullptr) {
                *request_sequence = in_flight_it->second.request_sequence;
            }
            return true;
        }
        g_in_flight_local_loot_pickup_requests_by_drop_id.erase(
            in_flight_it);
    }

    constexpr std::size_t kMaxQueuedLocalLootPickupRequests = 32;
    if (g_queued_local_loot_pickup_requests.size() >= kMaxQueuedLocalLootPickupRequests) {
        g_queued_local_loot_pickup_requests.erase(g_queued_local_loot_pickup_requests.begin());
    }

    QueuedLocalLootPickupRequest request;
    request.network_drop_id = network_drop_id;
    request.request_sequence = g_next_local_loot_pickup_request_sequence++;
    request.automatic_proximity_request = capture != nullptr && capture->valid;
    if (g_next_local_loot_pickup_request_sequence == 0) {
        g_next_local_loot_pickup_request_sequence = 1;
    }
    if (resolved_capture_valid) {
        request.has_pickup_positions = true;
        request.requester_position_x = resolved_capture.requester_position_x;
        request.requester_position_y = resolved_capture.requester_position_y;
        request.drop_position_x = resolved_capture.drop_position_x;
        request.drop_position_y = resolved_capture.drop_position_y;
    }
    if (request_sequence != nullptr) {
        *request_sequence = request.request_sequence;
    }
    g_queued_local_loot_pickup_requests.push_back(request);
    return true;
}

bool QueueLocalHostPowerupPickup(
    uintptr_t actor_address,
    const LootPickupRequestCapture* capture) {
    if (!IsLocalTransportHost() || actor_address == 0) {
        return false;
    }

    LootPickupRequestCapture resolved_capture;
    if (capture != nullptr &&
        capture->valid &&
        std::isfinite(capture->requester_position_x) &&
        std::isfinite(capture->requester_position_y) &&
        std::isfinite(capture->drop_position_x) &&
        std::isfinite(capture->drop_position_y)) {
        resolved_capture = *capture;
    }

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    const auto existing = std::find_if(
        g_queued_local_host_powerup_pickups.begin(),
        g_queued_local_host_powerup_pickups.end(),
        [&](const QueuedLocalHostPowerupPickup& pickup) {
            return pickup.actor_address == actor_address;
        });
    if (existing != g_queued_local_host_powerup_pickups.end()) {
        if (resolved_capture.valid) {
            existing->capture = resolved_capture;
        }
        return true;
    }
    constexpr std::size_t kMaxQueuedLocalHostPowerupPickups = 16;
    if (g_queued_local_host_powerup_pickups.size() >=
        kMaxQueuedLocalHostPowerupPickups) {
        g_queued_local_host_powerup_pickups.erase(
            g_queued_local_host_powerup_pickups.begin());
    }
    QueuedLocalHostPowerupPickup pickup;
    pickup.actor_address = actor_address;
    pickup.capture = resolved_capture;
    g_queued_local_host_powerup_pickups.push_back(pickup);
    return true;
}

bool MarkLocalInventoryNativeConverged(std::uint32_t inventory_revision) {
    if (inventory_revision == 0) {
        return false;
    }

    bool converged = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = FindLocalParticipant(state);
        if (local == nullptr ||
            local->owned_progression.inventory_revision != inventory_revision) {
            return;
        }
        local->owned_progression.inventory_host_authoritative = false;
        converged = true;
    });
    return converged;
}
