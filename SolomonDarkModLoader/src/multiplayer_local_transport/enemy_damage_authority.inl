// Host-authoritative enemy damage, death correction, and Fireball Explode splash handling.

bool IsEnemyDamageClaimSequenceDuplicate(const EnemyDamageClaimPacket& packet) {
    const auto it = g_local_transport.last_enemy_claim_sequence_by_participant.find(packet.participant_id);
    if (it == g_local_transport.last_enemy_claim_sequence_by_participant.end() ||
        packet.claim_sequence == 0) {
        return false;
    }
    return !IsPacketSequenceNewer(packet.claim_sequence, it->second);
}

void RememberEnemyDamageClaimSequence(const EnemyDamageClaimPacket& packet) {
    if (packet.claim_sequence != 0) {
        g_local_transport.last_enemy_claim_sequence_by_participant[packet.participant_id] =
            packet.claim_sequence;
    }
}

void SendEnemyDamageResult(
    const EnemyDamageClaimPacket& claim,
    const TransportPeerEndpoint& endpoint,
    EnemyDamageResultCode result_code,
    float authoritative_hp,
    float authoritative_max_hp,
    bool dead) {
    EnemyDamageResultPacket result{};
    result.header = MakePacketHeader(PacketKind::EnemyDamageResult, g_local_transport.next_sequence++);
    result.authority_participant_id = g_local_transport.local_peer_id;
    result.claimant_participant_id = claim.participant_id;
    result.claim_sequence = claim.claim_sequence;
    result.run_nonce = claim.run_nonce;
    result.target_network_actor_id = claim.target_network_actor_id;
    result.result_code = static_cast<std::uint8_t>(result_code);
    result.dead = dead ? 1 : 0;
    result.authoritative_hp = authoritative_hp;
    result.authoritative_max_hp = authoritative_max_hp;
    SendPacketToEndpoint(result, endpoint);
}

bool ValidateEnemyDamageClaim(
    const EnemyDamageClaimPacket& packet,
    const ParticipantInfo* participant,
    const SDModSceneActorState& target_actor,
    std::string* reject_reason) {
    auto reject = [&](const char* reason) {
        if (reject_reason != nullptr) {
            *reject_reason = reason;
        }
        return false;
    };

    if (participant == nullptr ||
        !IsRemoteParticipant(*participant) ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("participant_not_active_run");
    }
    if (packet.run_nonce != 0 &&
        participant->runtime.run_nonce != 0 &&
        packet.run_nonce != participant->runtime.run_nonce) {
        return reject("participant_run_nonce_mismatch");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return reject("host_not_active_run");
    }
    if (packet.run_nonce != 0 &&
        local->runtime.run_nonce != 0 &&
        packet.run_nonce != local->runtime.run_nonce) {
        return reject("host_run_nonce_mismatch");
    }
    if ((packet.claim_flags & ~kEnemyDamageClaimKnownFlags) != 0) {
        return reject("unknown_claim_flags");
    }
    if (!target_actor.tracked_enemy ||
        target_actor.dead ||
        !std::isfinite(target_actor.hp) ||
        !std::isfinite(target_actor.max_hp) ||
        target_actor.max_hp <= 0.0f ||
        target_actor.hp <= kEnemyDamageClaimHpEpsilon) {
        return reject("target_not_live_enemy");
    }
    if (!std::isfinite(packet.claimed_damage) ||
        !std::isfinite(packet.client_before_hp) ||
        !std::isfinite(packet.client_after_hp) ||
        packet.claimed_damage <= kEnemyDamageClaimHpEpsilon ||
        packet.client_after_hp < -kEnemyDamageClaimHpEpsilon ||
        packet.client_before_hp <= packet.client_after_hp + kEnemyDamageClaimHpEpsilon) {
        return reject("invalid_damage_numbers");
    }

    const float damage_cap =
        (std::min)(kEnemyDamageClaimAbsoluteCap, target_actor.max_hp * kEnemyDamageClaimMaxHpFactor);
    if (packet.claimed_damage > damage_cap) {
        return reject("damage_cap");
    }

    if (!std::isfinite(packet.caster_position_x) ||
        !std::isfinite(packet.caster_position_y) ||
        !std::isfinite(packet.target_position_x) ||
        !std::isfinite(packet.target_position_y)) {
        return reject("invalid_positions");
    }
    const float distance_limit_sq = kEnemyDamageClaimMaxDistance * kEnemyDamageClaimMaxDistance;
    if (DistanceSquared(
            packet.caster_position_x,
            packet.caster_position_y,
            target_actor.x,
            target_actor.y) > distance_limit_sq &&
        DistanceSquared(
            participant->runtime.position_x,
            participant->runtime.position_y,
            target_actor.x,
            target_actor.y) > distance_limit_sq) {
        return reject("distance_sanity");
    }
    const float target_drift_limit_sq =
        kEnemyDamageClaimMaxTargetDrift * kEnemyDamageClaimMaxTargetDrift;
    const bool target_position_optional =
        (packet.claim_flags & kEnemyDamageClaimFlagTargetPositionOptional) != 0;
    if (!target_position_optional &&
        DistanceSquared(
            packet.target_position_x,
            packet.target_position_y,
            target_actor.x,
            target_actor.y) > target_drift_limit_sq) {
        return reject("target_position_drift");
    }

    return true;
}

#include "enemy_damage_target_position.inl"

int ResolveParticipantPrimaryEntryForTransport(const ParticipantInfo& participant) {
    SDModParticipantGameplayState gameplay_state;
    if (TryGetParticipantGameplayState(participant.participant_id, &gameplay_state) &&
        gameplay_state.available) {
        const int gameplay_primary_entry =
            gameplay_state.character_profile.loadout.primary_entry_index >= 0
                ? gameplay_state.character_profile.loadout.primary_entry_index
                : ResolveNativePrimaryEntryForElement(
                      gameplay_state.character_profile.element_id);
        if (gameplay_primary_entry >= 0) {
            return gameplay_primary_entry;
        }
    }

    if (participant.runtime.primary_entry_index >= 0) {
        return participant.runtime.primary_entry_index;
    }
    if (participant.character_profile.loadout.primary_entry_index >= 0) {
        return participant.character_profile.loadout.primary_entry_index;
    }
    return ResolveNativePrimaryEntryForElement(
        participant.character_profile.element_id);
}

void CaptureHostLocalFireballExplodeBaseline(
    const ParticipantInfo& local,
    const CastPacket& packet,
    std::uint64_t now_ms) {
    g_local_transport.host_local_explode_cast_baseline = {};

    const int fire_primary_entry = ResolveNativePrimaryEntryForElement(0);
    if (!g_local_transport.is_host ||
        fire_primary_entry < 0 ||
        ResolveParticipantPrimaryEntryForTransport(local) != fire_primary_entry ||
        static_cast<CastKind>(packet.cast_kind) != CastKind::Primary ||
        static_cast<CastInputPhase>(packet.input_phase) != CastInputPhase::Pressed ||
        packet.target_network_actor_id == 0 ||
        packet.element_id != 0 ||
        packet.primary_entry_index != fire_primary_entry) {
        return;
    }

    float splash_damage = 0.0f;
    float splash_radius_world = 0.0f;
    if (!TryResolveFireballExplodeSplashTuning(
            local.owned_progression,
            &splash_damage,
            &splash_radius_world)) {
        return;
    }

    SDModSceneActorState primary_target;
    if (!TryFindHostRunEnemyByNetworkId(
            packet.target_network_actor_id,
            &primary_target) ||
        !primary_target.valid ||
        primary_target.dead ||
        !std::isfinite(primary_target.hp) ||
        !std::isfinite(primary_target.max_hp) ||
        primary_target.max_hp <= 0.0f ||
        primary_target.hp <= kEnemyDamageClaimHpEpsilon ||
        !std::isfinite(primary_target.x) ||
        !std::isfinite(primary_target.y)) {
        return;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return;
    }

    HostLocalExplodeCastBaseline baseline;
    baseline.valid = true;
    baseline.cast_sequence = packet.cast_sequence;
    baseline.run_nonce = packet.run_nonce;
    baseline.target_network_actor_id = packet.target_network_actor_id;
    baseline.captured_ms = now_ms;
    baseline.primary_hp =
        ClampEnemyHp(primary_target.hp, primary_target.max_hp);
    baseline.primary_x = primary_target.x;
    baseline.primary_y = primary_target.y;
    baseline.splash_damage = splash_damage;
    baseline.splash_radius_world = splash_radius_world;
    baseline.targets.reserve(
        (std::min)(actors.size(), static_cast<std::size_t>(kWorldSnapshotMaxActors)));

    const auto scene_intent = SceneIntentFromLocalScene();
    for (const auto& actor : actors) {
        if (baseline.targets.size() >= kWorldSnapshotMaxActors ||
            !ShouldReplicateWorldActor(actor, scene_intent.kind) ||
            !actor.tracked_enemy ||
            actor.dead ||
            actor.actor_address == primary_target.actor_address ||
            !std::isfinite(actor.hp) ||
            !std::isfinite(actor.max_hp) ||
            actor.max_hp <= 0.0f ||
            actor.hp <= kEnemyDamageClaimHpEpsilon) {
            continue;
        }

        const auto network_actor_id = ResolveLocalRunEnemyNetworkActorId(actor);
        if (network_actor_id == 0 ||
            network_actor_id == packet.target_network_actor_id) {
            continue;
        }

        HostLocalExplodeTargetBaseline target;
        target.network_actor_id = network_actor_id;
        target.hp = ClampEnemyHp(actor.hp, actor.max_hp);
        target.max_hp = actor.max_hp;
        baseline.targets.push_back(target);
    }

    g_local_transport.host_local_explode_cast_baseline = std::move(baseline);
    Log(
        "Multiplayer host-local explode cast baseline captured. participant_id=" +
        std::to_string(local.participant_id) +
        " cast_sequence=" + std::to_string(packet.cast_sequence) +
        " primary_target_network_actor_id=" +
        std::to_string(packet.target_network_actor_id) +
        " primary_hp=" + std::to_string(primary_target.hp) +
        " splash_damage=" + std::to_string(splash_damage) +
        " radius_world=" + std::to_string(splash_radius_world) +
        " target_count=" +
        std::to_string(
            g_local_transport.host_local_explode_cast_baseline.targets.size()));
}

int ApplyHostAcceptedFireballExplodeSplash(
    const EnemyDamageClaimPacket& packet,
    const ParticipantInfo* participant,
    std::uint64_t now_ms,
    const SDModSceneActorState& primary_target) {
    const int fire_primary_entry = ResolveNativePrimaryEntryForElement(0);
    if (!g_local_transport.is_host ||
        participant == nullptr ||
        fire_primary_entry < 0 ||
        ResolveParticipantPrimaryEntryForTransport(*participant) != fire_primary_entry ||
        packet.target_network_actor_id == 0 ||
        !std::isfinite(primary_target.x) ||
        !std::isfinite(primary_target.y)) {
        return -1;
    }

    float splash_damage = 0.0f;
    float splash_radius_world = 0.0f;
    if (!TryResolveFireballExplodeSplashTuning(
            participant->owned_progression,
            &splash_damage,
            &splash_radius_world)) {
        return -1;
    }

    const auto runtime_state = SnapshotRuntimeState();
    if (!runtime_state.world_snapshot.valid) {
        return -1;
    }

    int eligible_target_count = 0;
    for (const auto& snapshot_actor : runtime_state.world_snapshot.actors) {
        if (snapshot_actor.network_actor_id == 0 ||
            snapshot_actor.network_actor_id == packet.target_network_actor_id ||
            !snapshot_actor.tracked_enemy ||
            snapshot_actor.dead ||
            snapshot_actor.run_static ||
            !std::isfinite(snapshot_actor.position_x) ||
            !std::isfinite(snapshot_actor.position_y) ||
            !std::isfinite(snapshot_actor.hp) ||
            !std::isfinite(snapshot_actor.max_hp) ||
            snapshot_actor.max_hp <= 0.0f) {
            continue;
        }

        SDModSceneActorState actor;
        if (!TryFindHostRunEnemyByNetworkId(snapshot_actor.network_actor_id, &actor) ||
            actor.actor_address == 0 ||
            !actor.valid ||
            actor.dead ||
            !std::isfinite(actor.x) ||
            !std::isfinite(actor.y)) {
            continue;
        }

        const float dx = snapshot_actor.position_x - primary_target.x;
        const float dy = snapshot_actor.position_y - primary_target.y;
        if (!std::isfinite(dx) || !std::isfinite(dy) ||
            (dx * dx) + (dy * dy) > splash_radius_world * splash_radius_world) {
            continue;
        }
        ++eligible_target_count;

        const float baseline_hp =
            ClampEnemyHp(snapshot_actor.hp, snapshot_actor.max_hp);
        const float live_hp =
            ClampEnemyHp(actor.hp, snapshot_actor.max_hp);
        const float desired_hp =
            ClampEnemyHp(baseline_hp - splash_damage, snapshot_actor.max_hp);
        // Native splash may already have reached this target. Converge to the
        // lower of the live value and the authoritative baseline-minus-splash
        // value so reconciliation is idempotent and can never heal or double
        // damage an actor.
        const float new_hp = (std::min)(live_hp, desired_hp);
        if (new_hp + kEnemyDamageClaimHpEpsilon >= live_hp) {
            continue;
        }

        const bool wrote =
            TryWriteRunEnemyHealth(actor.actor_address, new_hp, snapshot_actor.max_hp);
        std::uint32_t death_exception_code = 0;
        bool death_called = false;
        if (wrote && new_hp <= kEnemyDamageClaimHpEpsilon) {
            death_called =
                sdmod::TryTriggerRunEnemyDeath(actor.actor_address, &death_exception_code);
            sdmod::ClearManualRunEnemyFreeze(actor.actor_address);
            if (death_called) {
                RecordRecentRunEnemyDeathSnapshot(
                    snapshot_actor.network_actor_id,
                    actor,
                    now_ms);
            }
        }

        Log(
            "Multiplayer host explode splash applied. participant_id=" +
            std::to_string(packet.participant_id) +
            " primary_target_network_actor_id=" +
            std::to_string(packet.target_network_actor_id) +
            " splash_target_network_actor_id=" +
            std::to_string(snapshot_actor.network_actor_id) +
            " damage=" + std::to_string(splash_damage) +
            " radius_world=" + std::to_string(splash_radius_world) +
            " baseline_hp=" + std::to_string(baseline_hp) +
            " live_before_hp=" + std::to_string(live_hp) +
            " after_hp=" + std::to_string(wrote ? new_hp : live_hp) +
            " wrote=" + std::to_string(wrote ? 1 : 0) +
            " death_called=" + std::to_string(death_called ? 1 : 0) +
            " death_seh=" + HexString(static_cast<uintptr_t>(death_exception_code)));
    }
    return eligible_target_count;
}

void ReconcileHostLocalFireballExplodeSplash(std::uint64_t now_ms) {
    auto& baseline = g_local_transport.host_local_explode_cast_baseline;
    const bool association_expired =
        baseline.captured_ms == 0 ||
        now_ms < baseline.captured_ms ||
        now_ms - baseline.captured_ms >
            kRecentLocalCastAssociationWindowMs;
    if (!g_local_transport.is_host ||
        !baseline.valid ||
        baseline.cast_sequence == 0 ||
        baseline.target_network_actor_id == 0 ||
        baseline.cast_sequence ==
            g_local_transport.last_local_explode_splash_cast_sequence ||
        association_expired) {
        if (association_expired) {
            baseline = {};
        }
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        (baseline.run_nonce != 0 &&
         local->runtime.run_nonce != 0 &&
         baseline.run_nonce != local->runtime.run_nonce)) {
        baseline = {};
        return;
    }

    SDModSceneActorState primary_target;
    const bool have_live_primary =
        TryFindHostRunEnemyByNetworkId(
            baseline.target_network_actor_id,
            &primary_target) &&
        primary_target.valid &&
        std::isfinite(primary_target.hp);
    bool impact_observed =
        have_live_primary &&
        (primary_target.dead ||
         primary_target.hp + kEnemyDamageClaimHpEpsilon < baseline.primary_hp);
    float impact_x = baseline.primary_x;
    float impact_y = baseline.primary_y;
    if (have_live_primary &&
        std::isfinite(primary_target.x) &&
        std::isfinite(primary_target.y)) {
        impact_x = primary_target.x;
        impact_y = primary_target.y;
    } else {
        const auto death_it =
            g_local_transport.recent_run_enemy_deaths_by_network_id.find(
                baseline.target_network_actor_id);
        if (death_it !=
            g_local_transport.recent_run_enemy_deaths_by_network_id.end()) {
            impact_observed = true;
            impact_x = death_it->second.position_x;
            impact_y = death_it->second.position_y;
        }
    }
    if (!impact_observed ||
        !std::isfinite(impact_x) ||
        !std::isfinite(impact_y)) {
        return;
    }

    int eligible_target_count = 0;
    int written_target_count = 0;
    const float radius_squared =
        baseline.splash_radius_world * baseline.splash_radius_world;
    for (const auto& target_baseline : baseline.targets) {
        SDModSceneActorState actor;
        if (!TryFindHostRunEnemyByNetworkId(
                target_baseline.network_actor_id,
                &actor) ||
            !actor.valid ||
            !std::isfinite(actor.x) ||
            !std::isfinite(actor.y) ||
            !std::isfinite(actor.hp) ||
            !std::isfinite(target_baseline.hp) ||
            !std::isfinite(target_baseline.max_hp) ||
            target_baseline.max_hp <= 0.0f) {
            continue;
        }

        const float distance_squared =
            DistanceSquared(actor.x, actor.y, impact_x, impact_y);
        if (!std::isfinite(distance_squared) ||
            distance_squared > radius_squared) {
            continue;
        }
        ++eligible_target_count;

        const float live_hp =
            ClampEnemyHp(actor.hp, target_baseline.max_hp);
        const float desired_hp =
            ClampEnemyHp(
                target_baseline.hp - baseline.splash_damage,
                target_baseline.max_hp);
        // Stock splash may have already applied. Converging to the lower
        // value makes this pass idempotent and prevents healing or a second
        // splash application when native behavior worked on its own.
        const float new_hp = (std::min)(live_hp, desired_hp);
        if (actor.dead ||
            new_hp + kEnemyDamageClaimHpEpsilon >= live_hp) {
            continue;
        }

        const bool wrote = TryWriteRunEnemyHealth(
            actor.actor_address,
            new_hp,
            target_baseline.max_hp);
        std::uint32_t death_exception_code = 0;
        bool death_called = false;
        if (wrote) {
            ++written_target_count;
        }
        if (wrote && new_hp <= kEnemyDamageClaimHpEpsilon) {
            death_called =
                sdmod::TryTriggerRunEnemyDeath(
                    actor.actor_address,
                    &death_exception_code);
            sdmod::ClearManualRunEnemyFreeze(actor.actor_address);
            if (death_called) {
                RecordRecentRunEnemyDeathSnapshot(
                    target_baseline.network_actor_id,
                    actor,
                    now_ms);
            }
        }

        Log(
            "Multiplayer host-local explode splash converged. participant_id=" +
            std::to_string(g_local_transport.local_peer_id) +
            " cast_sequence=" + std::to_string(baseline.cast_sequence) +
            " primary_target_network_actor_id=" +
            std::to_string(baseline.target_network_actor_id) +
            " splash_target_network_actor_id=" +
            std::to_string(target_baseline.network_actor_id) +
            " damage=" + std::to_string(baseline.splash_damage) +
            " radius_world=" + std::to_string(baseline.splash_radius_world) +
            " baseline_hp=" + std::to_string(target_baseline.hp) +
            " live_before_hp=" + std::to_string(live_hp) +
            " after_hp=" + std::to_string(wrote ? new_hp : live_hp) +
            " wrote=" + std::to_string(wrote ? 1 : 0) +
            " death_called=" + std::to_string(death_called ? 1 : 0) +
            " death_seh=" +
            HexString(static_cast<uintptr_t>(death_exception_code)));
    }

    const auto completed_cast_sequence = baseline.cast_sequence;
    const auto primary_target_network_actor_id =
        baseline.target_network_actor_id;
    const auto primary_before_hp = baseline.primary_hp;
    const auto primary_after_hp =
        have_live_primary && std::isfinite(primary_target.hp)
            ? primary_target.hp
            : 0.0f;
    g_local_transport.last_local_explode_splash_cast_sequence =
        completed_cast_sequence;
    baseline = {};
    Log(
        "Multiplayer host-local explode impact reconciled. participant_id=" +
        std::to_string(g_local_transport.local_peer_id) +
        " cast_sequence=" + std::to_string(completed_cast_sequence) +
        " primary_target_network_actor_id=" +
        std::to_string(primary_target_network_actor_id) +
        " eligible_target_count=" + std::to_string(eligible_target_count) +
        " written_target_count=" + std::to_string(written_target_count) +
        " before_hp=" + std::to_string(primary_before_hp) +
        " after_hp=" + std::to_string(primary_after_hp));
}

void ApplyEnemyDamageClaimPacket(
    const EnemyDamageClaimPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.target_network_actor_id == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    if (IsEnemyDamageClaimSequenceDuplicate(packet)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* participant = FindParticipant(runtime_state, packet.participant_id);

    SDModSceneActorState target_actor;
    if (!TryFindHostRunEnemyByNetworkId(packet.target_network_actor_id, &target_actor)) {
        SendEnemyDamageResult(packet, from, EnemyDamageResultCode::Rejected, 0.0f, 0.0f, true);
        RememberEnemyDamageClaimSequence(packet);
        Log(
            "Multiplayer enemy damage claim rejected. reason=target_not_found participant_id=" +
            std::to_string(packet.participant_id) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id));
        return;
    }

    std::string reject_reason;
    if (!ValidateEnemyDamageClaim(packet, participant, target_actor, &reject_reason)) {
        SendEnemyDamageResult(
            packet,
            from,
            EnemyDamageResultCode::Rejected,
            ClampEnemyHp(target_actor.hp, target_actor.max_hp),
            target_actor.max_hp,
            target_actor.dead);
        RememberEnemyDamageClaimSequence(packet);
        Log(
            "Multiplayer enemy damage claim rejected. reason=" + reject_reason +
            " participant_id=" + std::to_string(packet.participant_id) +
            " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
            " damage=" + std::to_string(packet.claimed_damage) +
            " host_hp=" + std::to_string(target_actor.hp) +
            " client_after_hp=" + std::to_string(packet.client_after_hp) +
            " host_position=(" + std::to_string(target_actor.x) + "," +
            std::to_string(target_actor.y) + ")" +
            " claimed_position=(" + std::to_string(packet.target_position_x) + "," +
            std::to_string(packet.target_position_y) + ")" +
            " caster_position=(" + std::to_string(packet.caster_position_x) + "," +
            std::to_string(packet.caster_position_y) + ")" +
            " participant_position=(" +
            std::to_string(participant != nullptr ? participant->runtime.position_x : 0.0f) +
            "," +
            std::to_string(participant != nullptr ? participant->runtime.position_y : 0.0f) +
            ")");
        return;
    }

    const float current_hp = ClampEnemyHp(target_actor.hp, target_actor.max_hp);
    const float claimed_after_hp = ClampEnemyHp(packet.client_after_hp, target_actor.max_hp);
    const float accepted_hp = (std::min)(current_hp, claimed_after_hp);
    const bool accepted_new_damage =
        accepted_hp + kEnemyDamageClaimHpEpsilon < current_hp;
    const bool wrote = TryWriteRunEnemyHealth(
        target_actor.actor_address,
        accepted_hp,
        target_actor.max_hp);
    const bool position_applied =
        wrote &&
        accepted_new_damage &&
        accepted_hp > kEnemyDamageClaimHpEpsilon &&
        TryApplyAcceptedEnemyDamageTargetPosition(packet, target_actor);
    std::uint32_t death_exception_code = 0;
    bool death_called = false;
    if (wrote && accepted_hp <= kEnemyDamageClaimHpEpsilon) {
        death_called = sdmod::TryTriggerRunEnemyDeath(target_actor.actor_address, &death_exception_code);
        sdmod::ClearManualRunEnemyFreeze(target_actor.actor_address);
        if (death_called) {
            RecordRecentRunEnemyDeathSnapshot(
                packet.target_network_actor_id,
                target_actor,
                now_ms);
        }
    }
    if (wrote) {
        ApplyHostAcceptedFireballExplodeSplash(packet, participant, now_ms, target_actor);
    }

    RememberEnemyDamageClaimSequence(packet);
    SendEnemyDamageResult(
        packet,
        from,
        wrote ? EnemyDamageResultCode::Accepted : EnemyDamageResultCode::Rejected,
        wrote ? accepted_hp : current_hp,
        target_actor.max_hp,
        wrote ? accepted_hp <= kEnemyDamageClaimHpEpsilon : target_actor.dead);

    Log(
        "Multiplayer enemy damage claim " + std::string(wrote ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(packet.participant_id) +
        " target_network_actor_id=" + std::to_string(packet.target_network_actor_id) +
        " damage=" + std::to_string(packet.claimed_damage) +
        " before_hp=" + std::to_string(current_hp) +
        " after_hp=" + std::to_string(wrote ? accepted_hp : current_hp) +
        " position_applied=" + std::to_string(position_applied ? 1 : 0) +
        " claimed_position=(" + std::to_string(packet.target_position_x) + "," +
        std::to_string(packet.target_position_y) + ")" +
        " lethal=" + std::to_string(accepted_hp <= kEnemyDamageClaimHpEpsilon ? 1 : 0) +
        " death_called=" + std::to_string(death_called ? 1 : 0) +
        " death_seh=" + HexString(static_cast<uintptr_t>(death_exception_code)));
}
