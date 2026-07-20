std::unordered_map<uintptr_t, SDModSceneActorState> BuildSceneActorMapByAddress() {
    std::vector<SDModSceneActorState> actors;
    std::unordered_map<uintptr_t, SDModSceneActorState> by_address;
    if (!TryListSceneActors(&actors)) {
        return by_address;
    }

    by_address.reserve(actors.size());
    for (const auto& actor : actors) {
        if (actor.actor_address != 0) {
            by_address[actor.actor_address] = actor;
        }
    }
    return by_address;
}
void ObserveReplicatedRunEnemyDamageInternal(
    std::uint64_t network_actor_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional) {
    if (!IsLocalTransportClient() ||
        network_actor_id == 0 ||
        !HasReplicatedRunEnemyDamageBaseline(network_actor_id) ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(local_hp) ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f ||
        !std::isfinite(target_position_x) ||
        !std::isfinite(target_position_y)) {
        return;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto active = g_local_transport.active_local_cast_input;
    const bool active_cast = active.active && active.skill_id >= 0;
    const bool recent_cast =
        g_local_transport.recent_local_cast_sequence != 0 &&
        g_local_transport.recent_local_cast_skill_id >= 0 &&
        now_ms >= g_local_transport.recent_local_cast_ms &&
        now_ms - g_local_transport.recent_local_cast_ms <=
            kRecentLocalCastAssociationWindowMs;
    const auto associated_skill_id =
        active_cast
            ? active.skill_id
            : (recent_cast ? g_local_transport.recent_local_cast_skill_id : -1);
    bool local_cast_associated = associated_skill_id >= 0;
    if (associated_skill_id == kAirPrimarySkillId) {
        local_cast_associated =
            (active_cast && active.target_network_actor_id == network_actor_id) ||
            (recent_cast &&
             g_local_transport.recent_local_cast_target_network_actor_id ==
                 network_actor_id);
        const auto chain_target =
            g_local_transport.recent_local_air_chain_target_until_ms.find(
                network_actor_id);
        if (chain_target !=
                g_local_transport.recent_local_air_chain_target_until_ms.end() &&
            chain_target->second >= now_ms) {
            local_cast_associated = true;
        }
    }
    if (!local_cast_associated) {
        return;
    }

    authoritative_hp = ClampEnemyHp(authoritative_hp, max_hp);
    local_hp = ClampEnemyHp(local_hp, max_hp);
    auto existing =
        g_local_transport.observed_enemy_damage_by_network_id.find(network_actor_id);
    if (existing != g_local_transport.observed_enemy_damage_by_network_id.end()) {
        auto& observed = existing->second;
        if (observed.in_flight_claim_sequence != 0 &&
            authoritative_hp <=
                observed.in_flight_after_hp + kEnemyDamageClaimHpEpsilon) {
            observed.in_flight_claim_sequence = 0;
            observed.in_flight_sent_ms = 0;
            observed.in_flight_before_hp = 0.0f;
            observed.in_flight_after_hp = 0.0f;
        }
        if (observed.reference_hp_valid &&
            authoritative_hp <= observed.reference_hp + kEnemyDamageClaimHpEpsilon) {
            observed.reference_hp_valid = false;
            observed.reference_hp = 0.0f;
        }
    }

    float observation_baseline_hp = authoritative_hp;
    if (existing != g_local_transport.observed_enemy_damage_by_network_id.end() &&
        existing->second.reference_hp_valid &&
        existing->second.reference_hp + kEnemyDamageClaimHpEpsilon < authoritative_hp &&
        local_hp <= existing->second.reference_hp + kEnemyDamageObservationEpsilon) {
        // An accepted claim correction can arrive before the corresponding
        // world snapshot.  Treat only damage below that correction as new;
        // otherwise the stale snapshot would count the accepted claim twice.
        observation_baseline_hp = existing->second.reference_hp;
    }

    const float observed_damage = observation_baseline_hp - local_hp;
    if (!std::isfinite(observed_damage) ||
        observed_damage <= kEnemyDamageObservationEpsilon) {
        if (existing != g_local_transport.observed_enemy_damage_by_network_id.end()) {
            existing->second.latest_authoritative_hp = authoritative_hp;
            existing->second.max_hp = max_hp;
            existing->second.target_position_x = target_position_x;
            existing->second.target_position_y = target_position_y;
            existing->second.target_position_optional = target_position_optional;
        }
        return;
    }

    auto& observed =
        g_local_transport.observed_enemy_damage_by_network_id[network_actor_id];
    const bool was_claimable =
        observed.pending_damage > kEnemyDamageClaimHpEpsilon;
    const float damage_cap =
        (std::min)(kEnemyDamageClaimAbsoluteCap, max_hp * kEnemyDamageClaimMaxHpFactor);
    observed.pending_damage =
        (std::min)(damage_cap, observed.pending_damage + observed_damage);
    observed.latest_authoritative_hp = authoritative_hp;
    observed.max_hp = max_hp;
    observed.target_position_x = target_position_x;
    observed.target_position_y = target_position_y;
    observed.target_position_optional = target_position_optional;
    if (!was_claimable &&
        observed.pending_damage > kEnemyDamageClaimHpEpsilon) {
        Log(
            "Multiplayer observed enemy damage reached claim threshold. "
            "target_network_actor_id=" + std::to_string(network_actor_id) +
            " accumulated_damage=" + std::to_string(observed.pending_damage));
    }
}

bool SendLocalEnemyDamageClaim(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    std::uint64_t network_actor_id,
    std::int32_t skill_id,
    float authoritative_hp,
    float local_hp,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional,
    bool baseline_prevalidated,
    bool force_resend) {
    const auto endpoints = BuildKnownSendEndpoints();
    if (endpoints.empty()) {
        return false;
    }
    if (network_actor_id == 0 ||
        !std::isfinite(authoritative_hp) ||
        !std::isfinite(local_hp) ||
        !std::isfinite(max_hp) ||
        max_hp <= 0.0f ||
        !std::isfinite(target_position_x) ||
        !std::isfinite(target_position_y)) {
        return false;
    }

    authoritative_hp = ClampEnemyHp(authoritative_hp, max_hp);
    local_hp = ClampEnemyHp(local_hp, max_hp);
    if (IsLocalTransportClient() &&
        !baseline_prevalidated &&
        !HasReplicatedRunEnemyDamageBaseline(network_actor_id)) {
        if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
            MarkReplicatedRunEnemyDamageBaseline(network_actor_id, authoritative_hp);
        }
        Log(
            "Multiplayer enemy damage claim suppressed until first authoritative HP baseline. "
            "target_network_actor_id=" + std::to_string(network_actor_id) +
            " authoritative_hp=" + std::to_string(authoritative_hp) +
            " local_hp=" + std::to_string(local_hp));
        return false;
    }
    if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
        g_local_transport.last_enemy_claimed_hp_by_network_id.erase(network_actor_id);
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(network_actor_id);
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(network_actor_id);
        return false;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto retry_suppressed_it =
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.find(network_actor_id);
    if (retry_suppressed_it !=
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.end()) {
        if (retry_suppressed_it->second > now_ms) {
            return false;
        }
        g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(
            retry_suppressed_it);
    }

    const auto last_claim_it =
        g_local_transport.last_enemy_claimed_hp_by_network_id.find(network_actor_id);
    if (!force_resend &&
        last_claim_it != g_local_transport.last_enemy_claimed_hp_by_network_id.end() &&
        std::fabs(last_claim_it->second - local_hp) <= kEnemyDamageClaimHpEpsilon) {
        return false;
    }

    EnemyDamageClaimPacket packet{};
    packet.header = MakePacketHeader(PacketKind::EnemyDamageClaim, g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    packet.claim_sequence = g_local_transport.next_enemy_damage_claim_sequence++;
    packet.run_nonce = local.runtime.run_nonce != 0
                           ? local.runtime.run_nonce
                           : runtime_state.world_snapshot.run_nonce;
    packet.target_network_actor_id = network_actor_id;
    packet.skill_id = skill_id;
    packet.claimed_damage = authoritative_hp - local_hp;
    packet.client_before_hp = authoritative_hp;
    packet.client_after_hp = local_hp;
    packet.caster_position_x = local.runtime.position_x;
    packet.caster_position_y = local.runtime.position_y;
    packet.target_position_x = target_position_x;
    packet.target_position_y = target_position_y;
    packet.lethal = local_hp <= kEnemyDamageClaimHpEpsilon ? 1 : 0;
    packet.claim_flags = target_position_optional
                             ? kEnemyDamageClaimFlagTargetPositionOptional
                             : 0;
    if (!force_resend) {
        std::int32_t associated_skill_id =
            skill_id > 0 ? skill_id : -1;
        if (associated_skill_id < 0 &&
            g_local_transport.active_local_cast_input.active &&
            g_local_transport.active_local_cast_input.skill_id >= 0) {
            associated_skill_id =
                g_local_transport.active_local_cast_input.skill_id;
        }
        if (associated_skill_id < 0 &&
            g_local_transport.recent_local_cast_skill_id >= 0 &&
            now_ms >= g_local_transport.recent_local_cast_ms &&
            now_ms - g_local_transport.recent_local_cast_ms <=
                kRecentLocalCastAssociationWindowMs) {
            associated_skill_id =
                g_local_transport.recent_local_cast_skill_id;
        }
        RecordLocalEnemyDamageClaimObservationInternal(
            network_actor_id,
            packet.claimed_damage,
            associated_skill_id);
    }
    if (packet.lethal != 0) {
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms[network_actor_id] =
            now_ms + kEnemyDamageLethalClaimPendingSuppressMs;
    }

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
    std::uint32_t local_death_exception_code = 0;
    bool local_death_called = false;
    if (packet.lethal != 0) {
        const auto local_actor_address = FindReplicatedLocalActorAddress(network_actor_id);
        if (local_actor_address != 0) {
            local_death_called =
                sdmod::TryTriggerRunEnemyDeath(local_actor_address, &local_death_exception_code);
            sdmod::ClearManualRunEnemyFreeze(local_actor_address);
            if (local_death_called) {
                sdmod::MarkReplicatedRunEnemyDeathPresented(network_actor_id);
                sdmod::SuppressClientLocalLootActors("client_local_enemy_death_claim");
            }
        }
    }
    g_local_transport.last_enemy_claimed_hp_by_network_id[network_actor_id] = local_hp;
    Log(
        "Multiplayer enemy damage claim sent. target_network_actor_id=" +
        std::to_string(network_actor_id) +
        " sequence=" + std::to_string(packet.claim_sequence) +
        " damage=" + std::to_string(packet.claimed_damage) +
        " after_hp=" + std::to_string(packet.client_after_hp) +
        " baseline_prevalidated=" + std::to_string(baseline_prevalidated ? 1 : 0) +
        " force_resend=" + std::to_string(force_resend ? 1 : 0) +
        " local_death_called=" + std::to_string(local_death_called ? 1 : 0) +
        " local_death_seh=" + HexString(static_cast<uintptr_t>(local_death_exception_code)));
    return true;
}

void SendObservedLocalEnemyDamageClaims(
    const RuntimeState& runtime_state,
    const ParticipantInfo& local,
    std::uint64_t now_ms) {
    for (auto& [network_actor_id, observed] :
         g_local_transport.observed_enemy_damage_by_network_id) {
        if (observed.in_flight_claim_sequence != 0) {
            if (now_ms < observed.in_flight_sent_ms + kEnemyDamageClaimResultRetryMs) {
                continue;
            }
            const auto retry_sequence =
                g_local_transport.next_enemy_damage_claim_sequence;
            if (SendLocalEnemyDamageClaim(
                    runtime_state,
                    local,
                    network_actor_id,
                    0,
                    observed.in_flight_before_hp,
                    observed.in_flight_after_hp,
                    observed.max_hp,
                    observed.target_position_x,
                    observed.target_position_y,
                    observed.target_position_optional,
                    true,
                    true)) {
                observed.in_flight_claim_sequence = retry_sequence;
                observed.in_flight_sent_ms = now_ms;
                Log(
                    "Multiplayer observed enemy damage claim retried. "
                    "target_network_actor_id=" + std::to_string(network_actor_id) +
                    " sequence=" + std::to_string(retry_sequence));
            }
            continue;
        }
        if (observed.pending_damage <= kEnemyDamageClaimHpEpsilon ||
            !std::isfinite(observed.latest_authoritative_hp) ||
            !std::isfinite(observed.max_hp) ||
            observed.max_hp <= 0.0f) {
            continue;
        }

        float claim_before_hp =
            ClampEnemyHp(observed.latest_authoritative_hp, observed.max_hp);
        if (observed.reference_hp_valid) {
            claim_before_hp =
                (std::min)(claim_before_hp, observed.reference_hp);
        }
        if (claim_before_hp <= kEnemyDamageClaimHpEpsilon) {
            continue;
        }
        const float claim_damage =
            (std::min)(observed.pending_damage, claim_before_hp);
        const float claim_after_hp =
            ClampEnemyHp(claim_before_hp - claim_damage, observed.max_hp);
        if (claim_after_hp + kEnemyDamageClaimHpEpsilon >= claim_before_hp) {
            continue;
        }

        const auto claim_sequence =
            g_local_transport.next_enemy_damage_claim_sequence;
        if (!SendLocalEnemyDamageClaim(
                runtime_state,
                local,
                network_actor_id,
                0,
                claim_before_hp,
                claim_after_hp,
                observed.max_hp,
                observed.target_position_x,
                observed.target_position_y,
                observed.target_position_optional,
                true)) {
            continue;
        }

        observed.pending_damage =
            (std::max)(0.0f, observed.pending_damage - claim_damage);
        observed.reference_hp_valid = true;
        observed.reference_hp = claim_after_hp;
        observed.in_flight_claim_sequence = claim_sequence;
        observed.in_flight_sent_ms = now_ms;
        observed.in_flight_before_hp = claim_before_hp;
        observed.in_flight_after_hp = claim_after_hp;
        Log(
            "Multiplayer observed enemy damage claim sent. "
            "target_network_actor_id=" + std::to_string(network_actor_id) +
            " sequence=" + std::to_string(claim_sequence) +
            " accumulated_damage=" + std::to_string(claim_damage) +
            " pending_damage=" + std::to_string(observed.pending_damage));
    }
}

bool HasLocalPendingLethalEnemyDamageClaimInternal(
    std::uint64_t network_actor_id,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() || network_actor_id == 0) {
        return false;
    }
    if (now_ms == 0) {
        now_ms = static_cast<std::uint64_t>(GetTickCount64());
    }
    const auto pending_it =
        g_local_transport.pending_lethal_enemy_damage_claim_until_ms.find(network_actor_id);
    if (pending_it == g_local_transport.pending_lethal_enemy_damage_claim_until_ms.end()) {
        return false;
    }
    if (pending_it->second > now_ms) {
        return true;
    }
    g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(pending_it);
    return false;
}

std::vector<QueuedLocalEnemyDamageClaim> TakeQueuedLocalEnemyDamageClaims() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedLocalEnemyDamageClaim> claims;
    claims.swap(g_queued_local_enemy_damage_claims);
    return claims;
}

void SendLocalEnemyDamageClaims() {
    if (!IsLocalTransportClient()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run ||
        !runtime_state.world_snapshot.valid ||
        runtime_state.world_snapshot.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return;
    }
    if (runtime_state.world_snapshot.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        runtime_state.world_snapshot.run_nonce != local->runtime.run_nonce) {
        return;
    }

    for (const auto& claim : TakeQueuedLocalEnemyDamageClaims()) {
        (void)SendLocalEnemyDamageClaim(
            runtime_state,
            *local,
            claim.network_actor_id,
            claim.skill_id,
            claim.authoritative_hp,
            claim.local_hp,
            claim.max_hp,
            claim.target_position_x,
            claim.target_position_y,
            claim.target_position_optional,
            claim.baseline_prevalidated);
    }

    SendObservedLocalEnemyDamageClaims(
        runtime_state,
        *local,
        static_cast<std::uint64_t>(GetTickCount64()));

    const auto local_scene_actors = BuildSceneActorMapByAddress();
    if (local_scene_actors.empty()) {
        return;
    }

    for (const auto& binding : runtime_state.world_snapshot_apply.actor_bindings) {
        if (binding.network_actor_id == 0 ||
            binding.local_actor_address == 0 ||
            !binding.matched ||
            binding.parked ||
            binding.removed) {
            if (binding.network_actor_id != 0 && (binding.parked || binding.removed)) {
                ClearReplicatedRunEnemyDamageBaseline(binding.network_actor_id);
            }
            continue;
        }

        const auto* authoritative_actor = FindSnapshotActorByNetworkId(
            runtime_state.world_snapshot,
            binding.network_actor_id);
        if (authoritative_actor == nullptr ||
            !authoritative_actor->tracked_enemy ||
            authoritative_actor->run_static ||
            !std::isfinite(authoritative_actor->hp) ||
            !std::isfinite(authoritative_actor->max_hp) ||
            authoritative_actor->max_hp <= 0.0f ||
            authoritative_actor->hp <= kEnemyDamageClaimHpEpsilon) {
            ClearReplicatedRunEnemyDamageBaseline(binding.network_actor_id);
            continue;
        }

        const auto local_it = local_scene_actors.find(binding.local_actor_address);
        if (local_it == local_scene_actors.end()) {
            continue;
        }
        const auto& local_actor = local_it->second;
        if (!local_actor.tracked_enemy ||
            !std::isfinite(local_actor.hp) ||
            !std::isfinite(local_actor.max_hp) ||
            local_actor.max_hp <= 0.0f) {
            continue;
        }

        const float local_hp = ClampEnemyHp(local_actor.hp, local_actor.max_hp);
        const float authoritative_max_hp = authoritative_actor->max_hp;
        if (std::fabs(local_actor.max_hp - authoritative_max_hp) > kEnemyDamageClaimHpEpsilon) {
            ClearReplicatedRunEnemyDamageBaseline(binding.network_actor_id);
            continue;
        }
        const float authoritative_hp =
            ClampEnemyHp(authoritative_actor->hp, authoritative_max_hp);
        if (!HasReplicatedRunEnemyDamageBaseline(binding.network_actor_id)) {
            if (local_hp + kEnemyDamageClaimHpEpsilon >= authoritative_hp) {
                MarkReplicatedRunEnemyDamageBaseline(binding.network_actor_id, authoritative_hp);
            }
            continue;
        }
        if (local_hp + kEnemyDamageObservationEpsilon >= authoritative_hp) {
            g_local_transport.last_enemy_claimed_hp_by_network_id.erase(binding.network_actor_id);
            continue;
        }
        if (local_hp + kEnemyDamageClaimHpEpsilon < authoritative_hp) {
            (void)SendLocalEnemyDamageClaim(
                runtime_state,
                *local,
                binding.network_actor_id,
                0,
                authoritative_hp,
                local_hp,
                authoritative_actor->max_hp,
                local_actor.x,
                local_actor.y,
                true);
        } else {
            ObserveReplicatedRunEnemyDamageInternal(
                binding.network_actor_id,
                authoritative_hp,
                local_hp,
                authoritative_actor->max_hp,
                local_actor.x,
                local_actor.y,
                true);
        }
    }
}
