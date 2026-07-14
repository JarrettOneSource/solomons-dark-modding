bool TryFindHostRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (network_actor_id == 0 || !g_local_transport.is_host) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind) ||
            !actor.tracked_enemy) {
            continue;
        }

        std::uint64_t candidate_id = 0;
        std::uint32_t spawn_serial = 0;
        if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
            candidate_id = BuildRunWorldActorNetworkId(spawn_serial);
        } else {
            const auto existing =
                g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
            candidate_id = existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()
                               ? existing->second
                               : AllocateRunHostLocalWorldActorNetworkId(actor);
        }

        if (candidate_id == network_actor_id) {
            if (actor_out != nullptr) {
                *actor_out = actor;
            }
            return true;
        }
    }
    return false;
}
const WorldActorSnapshot* FindSnapshotActorByNetworkId(
    const WorldSnapshotRuntimeInfo& snapshot,
    std::uint64_t network_actor_id) {
    for (const auto& actor : snapshot.actors) {
        if (actor.network_actor_id == network_actor_id) {
            return &actor;
        }
    }
    return nullptr;
}

uintptr_t FindReplicatedLocalActorAddress(std::uint64_t network_actor_id) {
    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& binding : runtime_state.world_snapshot_apply.actor_bindings) {
        if (binding.network_actor_id == network_actor_id &&
            binding.local_actor_address != 0 &&
            binding.matched &&
            !binding.parked &&
            !binding.removed) {
            return binding.local_actor_address;
        }
    }
    return 0;
}

std::uint64_t FindReplicatedLocalNetworkActorId(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }

    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& binding : runtime_state.world_snapshot_apply.actor_bindings) {
        if (binding.local_actor_address == actor_address &&
            binding.network_actor_id != 0 &&
            binding.matched &&
            !binding.parked &&
            !binding.removed) {
            return binding.network_actor_id;
        }
    }
    return 0;
}

bool TryGetLiveRunEnemyActorByAddress(
    uintptr_t actor_address,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (actor_address == 0) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (actor.actor_address == actor_address &&
            ShouldReplicateWorldActor(actor, scene_intent.kind) &&
            actor.tracked_enemy) {
            if (actor_out != nullptr) {
                *actor_out = actor;
            }
            return true;
        }
    }
    return false;
}

bool TryGetRunEnemyActorForDeathSnapshotByAddress(
    uintptr_t actor_address,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (actor_address == 0) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    for (const auto& actor : actors) {
        if (actor.actor_address == actor_address &&
            actor.valid &&
            actor.owner_address != 0 &&
            actor.object_type_id != 0 &&
            actor.object_type_id != 1 &&
            actor.tracked_enemy &&
            std::isfinite(actor.x) &&
            std::isfinite(actor.y) &&
            std::isfinite(actor.radius) &&
            actor.radius >= 0.0f &&
            std::isfinite(actor.max_hp) &&
            actor.max_hp > 0.0f) {
            if (actor_out != nullptr) {
                *actor_out = actor;
            }
            return true;
        }
    }
    return false;
}

std::uint64_t ResolveLocalRunEnemyNetworkActorId(const SDModSceneActorState& actor) {
    if (!actor.tracked_enemy || actor.actor_address == 0) {
        return 0;
    }

    if (g_local_transport.is_host) {
        std::uint32_t spawn_serial = 0;
        if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
            return BuildRunWorldActorNetworkId(spawn_serial);
        }

        const auto existing =
            g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
        return existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()
                   ? existing->second
                   : AllocateRunHostLocalWorldActorNetworkId(actor);
    }

    return FindReplicatedLocalNetworkActorId(actor.actor_address);
}

std::uint64_t ResolveLocalRunEnemyNetworkActorId(uintptr_t actor_address) {
    SDModSceneActorState actor;
    if (!TryGetLiveRunEnemyActorByAddress(actor_address, &actor)) {
        return 0;
    }
    return ResolveLocalRunEnemyNetworkActorId(actor);
}

bool TryFindLocalRunEnemyByNetworkIdInternal(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (network_actor_id == 0) {
        return false;
    }

    if (g_local_transport.is_host) {
        return TryFindHostRunEnemyByNetworkId(network_actor_id, actor_out);
    }

    return TryGetLiveRunEnemyActorByAddress(
        FindReplicatedLocalActorAddress(network_actor_id),
        actor_out);
}

bool TryNormalizeCastDirection(
    float direction_x,
    float direction_y,
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y,
    float* normalized_x,
    float* normalized_y,
    float* aim_distance) {
    if (normalized_x == nullptr || normalized_y == nullptr || aim_distance == nullptr) {
        return false;
    }

    float dx = direction_x;
    float dy = direction_y;
    float length = std::sqrt((dx * dx) + (dy * dy));
    if (!std::isfinite(length) || length <= 0.0001f) {
        dx = aim_target_x - position_x;
        dy = aim_target_y - position_y;
        length = std::sqrt((dx * dx) + (dy * dy));
    }
    if (!std::isfinite(length) || length <= 0.0001f) {
        return false;
    }

    *normalized_x = dx / length;
    *normalized_y = dy / length;
    const float aim_dx = aim_target_x - position_x;
    const float aim_dy = aim_target_y - position_y;
    const float raw_aim_distance = std::sqrt((aim_dx * aim_dx) + (aim_dy * aim_dy));
    *aim_distance =
        std::isfinite(raw_aim_distance) && raw_aim_distance > 0.0001f
            ? raw_aim_distance
            : length;
    return std::isfinite(*normalized_x) &&
           std::isfinite(*normalized_y) &&
           std::isfinite(*aim_distance);
}

bool IsUsableLocalCastAimTarget(
    float position_x,
    float position_y,
    float aim_target_x,
    float aim_target_y) {
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }
    if (std::abs(aim_target_x) < 0.001f && std::abs(aim_target_y) < 0.001f) {
        return false;
    }

    const auto dx = aim_target_x - position_x;
    const auto dy = aim_target_y - position_y;
    const auto distance = std::sqrt((dx * dx) + (dy * dy));
    constexpr float kMinCastAimDistance = 1.0f;
    constexpr float kMaxCastAimDistance = 4096.0f;
    constexpr float kMaxCastAimCoordinateMagnitude = 20000.0f;
    return std::isfinite(distance) &&
           distance >= kMinCastAimDistance &&
           distance <= kMaxCastAimDistance &&
           std::abs(aim_target_x) <= kMaxCastAimCoordinateMagnitude &&
           std::abs(aim_target_y) <= kMaxCastAimCoordinateMagnitude;
}

bool TryFindLocalRunEnemyForCastAim(
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    float aim_target_x,
    float aim_target_y,
    SDModSceneActorState* actor_out) {
    if (actor_out != nullptr) {
        *actor_out = {};
    }
    if (!std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    float normalized_x = 0.0f;
    float normalized_y = 0.0f;
    float aim_distance = 0.0f;
    if (!TryNormalizeCastDirection(
            direction_x,
            direction_y,
            position_x,
            position_y,
            aim_target_x,
            aim_target_y,
            &normalized_x,
            &normalized_y,
            &aim_distance)) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    constexpr float kCastAimBackwardTolerance = 96.0f;
    constexpr float kCastAimForwardTolerance = 512.0f;
    constexpr float kCastAimMaxPerpendicular = 256.0f;
    float best_score = (std::numeric_limits<float>::max)();
    SDModSceneActorState best_actor{};
    bool have_best = false;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind) ||
            !actor.tracked_enemy) {
            continue;
        }

        const float dx = actor.x - position_x;
        const float dy = actor.y - position_y;
        const float forward = (dx * normalized_x) + (dy * normalized_y);
        const float max_forward = (std::max)(aim_distance + kCastAimForwardTolerance, 768.0f);
        if (!std::isfinite(forward) ||
            forward < -kCastAimBackwardTolerance ||
            forward > max_forward) {
            continue;
        }

        const float distance_sq = (dx * dx) + (dy * dy);
        const float perpendicular_sq = (std::max)(0.0f, distance_sq - (forward * forward));
        const float max_perpendicular =
            (std::max)(kCastAimMaxPerpendicular, actor.radius + 192.0f);
        if (!std::isfinite(perpendicular_sq) ||
            perpendicular_sq > max_perpendicular * max_perpendicular) {
            continue;
        }

        const float aim_delta = forward - aim_distance;
        const float score = perpendicular_sq + (aim_delta * aim_delta * 0.05f);
        if (score < best_score) {
            best_score = score;
            best_actor = actor;
            have_best = true;
        }
    }

    if (!have_best) {
        return false;
    }
    if (actor_out != nullptr) {
        *actor_out = best_actor;
    }
    return true;
}

bool IsRunEnemyAlignedWithPlayerCastAim(
    const SDModSceneActorState& actor,
    float position_x,
    float position_y,
    float direction_x,
    float direction_y,
    float aim_target_x,
    float aim_target_y) {
    if (!actor.tracked_enemy ||
        actor.dead ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        !std::isfinite(aim_target_x) ||
        !std::isfinite(aim_target_y)) {
        return false;
    }

    float normalized_x = 0.0f;
    float normalized_y = 0.0f;
    float aim_distance = 0.0f;
    if (!TryNormalizeCastDirection(
            direction_x,
            direction_y,
            position_x,
            position_y,
            aim_target_x,
            aim_target_y,
            &normalized_x,
            &normalized_y,
            &aim_distance)) {
        return false;
    }

    const float dx = actor.x - position_x;
    const float dy = actor.y - position_y;
    const float forward = (dx * normalized_x) + (dy * normalized_y);
    if (!std::isfinite(forward) || forward < -16.0f) {
        return false;
    }

    const float distance_sq = (dx * dx) + (dy * dy);
    const float perpendicular_sq = (std::max)(0.0f, distance_sq - (forward * forward));
    const float max_perpendicular = (std::max)(actor.radius + 72.0f, 96.0f);
    if (!std::isfinite(perpendicular_sq) ||
        perpendicular_sq > max_perpendicular * max_perpendicular) {
        return false;
    }

    const float max_forward = (std::max)(aim_distance + 160.0f, 640.0f);
    return std::isfinite(max_forward) && forward <= max_forward;
}

bool IsSaneExplicitCastTarget(
    const SDModSceneActorState& actor,
    float position_x,
    float position_y) {
    if (!actor.tracked_enemy ||
        actor.dead ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.hp) ||
        !std::isfinite(actor.max_hp) ||
        !std::isfinite(position_x) ||
        !std::isfinite(position_y) ||
        actor.max_hp <= 0.0f ||
        actor.hp <= kEnemyDamageClaimHpEpsilon) {
        return false;
    }

    constexpr float kMaxExplicitCastTargetDistance = 4096.0f;
    const auto dx = actor.x - position_x;
    const auto dy = actor.y - position_y;
    const auto distance = std::sqrt((dx * dx) + (dy * dy));
    return std::isfinite(distance) && distance <= kMaxExplicitCastTargetDistance;
}

bool TryResolveExplicitCastTargetNetworkActorId(
    uintptr_t target_actor_address,
    float position_x,
    float position_y,
    std::uint64_t* network_actor_id_out) {
    if (network_actor_id_out != nullptr) {
        *network_actor_id_out = 0;
    }

    SDModSceneActorState actor;
    if (!TryGetLiveRunEnemyActorByAddress(target_actor_address, &actor) ||
        !IsSaneExplicitCastTarget(actor, position_x, position_y)) {
        return false;
    }

    const auto network_actor_id = ResolveLocalRunEnemyNetworkActorId(actor);
    if (network_actor_id == 0) {
        return false;
    }
    if (network_actor_id_out != nullptr) {
        *network_actor_id_out = network_actor_id;
    }
    return true;
}

void ApplyEnemyDamageCorrection(const EnemyDamageResultPacket& packet) {
    if (!IsLocalTransportClient() ||
        packet.claimant_participant_id != g_local_transport.local_peer_id ||
        packet.target_network_actor_id == 0 ||
        !std::isfinite(packet.authoritative_hp) ||
        !std::isfinite(packet.authoritative_max_hp) ||
        packet.authoritative_max_hp <= 0.0f) {
        return;
    }

    const bool accepted =
        packet.result_code == static_cast<std::uint8_t>(EnemyDamageResultCode::Accepted);
    const bool dead =
        packet.dead != 0 || packet.authoritative_hp <= kEnemyDamageClaimHpEpsilon;
    const auto observed_it =
        g_local_transport.observed_enemy_damage_by_network_id.find(
            packet.target_network_actor_id);
    if (observed_it !=
        g_local_transport.observed_enemy_damage_by_network_id.end()) {
        auto& observed = observed_it->second;
        const bool matches_in_flight =
            observed.in_flight_claim_sequence != 0 &&
            (packet.claim_sequence == observed.in_flight_claim_sequence ||
             (accepted &&
              packet.authoritative_hp <=
                  observed.in_flight_after_hp + kEnemyDamageClaimHpEpsilon));
        if (matches_in_flight) {
            observed.in_flight_claim_sequence = 0;
            observed.in_flight_sent_ms = 0;
            observed.in_flight_before_hp = 0.0f;
            observed.in_flight_after_hp = 0.0f;
            observed.latest_authoritative_hp = packet.authoritative_hp;
            observed.max_hp = packet.authoritative_max_hp;
            observed.reference_hp_valid = accepted && !dead;
            observed.reference_hp = accepted && !dead
                                        ? packet.authoritative_hp
                                        : 0.0f;
        }
    }

    const auto actor_address = FindReplicatedLocalActorAddress(packet.target_network_actor_id);
    if (actor_address == 0) {
        return;
    }

    if (TryWriteRunEnemyHealth(
            actor_address,
            packet.authoritative_hp,
            packet.authoritative_max_hp)) {
        std::uint32_t death_exception_code = 0;
        bool death_called = false;
        if (accepted && dead) {
            const bool death_already_presented =
                sdmod::HasReplicatedRunEnemyDeathPresentation(packet.target_network_actor_id);
            if (!death_already_presented) {
                death_called = sdmod::TryTriggerRunEnemyDeath(actor_address, &death_exception_code);
            }
            sdmod::ClearManualRunEnemyFreeze(actor_address);
            sdmod::MarkReplicatedRunEnemyDeathPresented(packet.target_network_actor_id);
            if (death_called) {
                sdmod::SuppressClientLocalLootActors("client_enemy_damage_correction_death");
            }
        } else {
            sdmod::ClearReplicatedRunEnemyDeathPresentation(packet.target_network_actor_id);
        }
        if (packet.result_code == static_cast<std::uint8_t>(EnemyDamageResultCode::Accepted)) {
            if (dead) {
                ClearReplicatedRunEnemyDamageBaseline(packet.target_network_actor_id);
            } else {
                MarkReplicatedRunEnemyDamageBaseline(
                    packet.target_network_actor_id,
                    packet.authoritative_hp);
                g_local_transport.last_enemy_claimed_hp_by_network_id[packet.target_network_actor_id] =
                    packet.authoritative_hp;
            }
            g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(
                packet.target_network_actor_id);
            g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(
                packet.target_network_actor_id);
        } else {
            MarkReplicatedRunEnemyDamageBaseline(
                packet.target_network_actor_id,
                packet.authoritative_hp);
            g_local_transport.last_enemy_claimed_hp_by_network_id.erase(packet.target_network_actor_id);
            g_local_transport.pending_lethal_enemy_damage_claim_until_ms.erase(
                packet.target_network_actor_id);
            g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms[packet.target_network_actor_id] =
                static_cast<std::uint64_t>(GetTickCount64()) +
                kEnemyDamageRejectedRetrySuppressMs;
        }
        Log(
            "Multiplayer enemy damage correction applied. target_network_actor_id=" +
            std::to_string(packet.target_network_actor_id) +
            " result=" + std::to_string(static_cast<int>(packet.result_code)) +
            " claim_sequence=" + std::to_string(packet.claim_sequence) +
            " hp=" + std::to_string(packet.authoritative_hp) +
            " max_hp=" + std::to_string(packet.authoritative_max_hp) +
            " death_called=" + std::to_string(death_called ? 1 : 0) +
            " death_seh=" + HexString(static_cast<uintptr_t>(death_exception_code)));
    }
}
