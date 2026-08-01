ScopedLocalNativeSpellDamageDispatch::
ScopedLocalNativeSpellDamageDispatch(
    std::int32_t skill_id) {
    if (!IsLocalTransportClient() || skill_id < 0) {
        return;
    }
    active_ = true;
    previous_skill_id_ =
        g_local_native_spell_damage_dispatch_skill_id;
    g_local_native_spell_damage_dispatch_skill_id = skill_id;
}

ScopedLocalNativeSpellDamageDispatch::
~ScopedLocalNativeSpellDamageDispatch() {
    if (active_) {
        g_local_native_spell_damage_dispatch_skill_id =
            previous_skill_id_;
    }
}

bool TryFindLocalRunEnemyByNetworkId(
    std::uint64_t network_actor_id,
    SDModSceneActorState* actor_out) {
    return TryFindLocalRunEnemyByNetworkIdInternal(network_actor_id, actor_out);
}

bool TryResolveLocalMultiplayerAirPrimaryNativeTarget(
    uintptr_t caster_actor_address,
    std::uint64_t* network_actor_id_out,
    uintptr_t* target_actor_address_out) {
    return TryResolveLocalMultiplayerAirPrimaryNativeTargetInternal(
        caster_actor_address,
        network_actor_id_out,
        target_actor_address_out);
}

std::uint64_t GetLocalRunEnemyNetworkActorId(uintptr_t actor_address) {
    return ResolveLocalRunEnemyNetworkActorId(actor_address);
}

void ResetLocalEnemyDamageClaimObservation(
    std::uint64_t network_actor_id) {
    ResetLocalEnemyDamageClaimObservationInternal(network_actor_id);
}

bool TakeLocalEnemyDamageClaimObservation(
    std::uint64_t network_actor_id,
    LocalEnemyDamageClaimObservation* observation) {
    if (network_actor_id == 0 || observation == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(
        g_local_enemy_damage_claim_observation_mutex);
    const auto existing =
        g_local_enemy_damage_claim_observations.find(network_actor_id);
    if (existing == g_local_enemy_damage_claim_observations.end() ||
        !existing->second.valid) {
        *observation = LocalEnemyDamageClaimObservation{};
        g_local_enemy_damage_claim_observations.erase(network_actor_id);
        return false;
    }
    *observation = existing->second;
    g_local_enemy_damage_claim_observations.erase(existing);
    return true;
}

void PublishLocalAirChainFrame(
    uintptr_t caster_actor_address,
    const AirChainTargetCapture* targets,
    std::size_t target_count,
    std::size_t target_total_count) {
    QueueLocalAirChainFrameInternal(
        caster_actor_address,
        targets,
        target_count,
        target_total_count);
}

uintptr_t ResolveReplicatedAirChainTarget(
    uintptr_t caster_actor_address,
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    uintptr_t fallback_actor_address,
    float source_x,
    float source_y,
    AirChainSourceEndpoint* authoritative_source,
    AirChainTargetEndpoint* authoritative_target) {
    return ResolveReplicatedAirChainTargetInternal(
        caster_actor_address,
        owner_participant_id,
        target_ordinal,
        fallback_actor_address,
        source_x,
        source_y,
        authoritative_source,
        authoritative_target);
}

void RecordReplicatedAirChainSourceOverride(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied) {
    RecordAirChainSourceOverrideInternal(
        owner_participant_id,
        target_ordinal,
        applied);
}

void RecordReplicatedAirChainTargetOverride(
    std::uint64_t owner_participant_id,
    std::uint16_t target_ordinal,
    bool applied) {
    RecordAirChainTargetOverrideInternal(
        owner_participant_id,
        target_ordinal,
        applied);
}

bool ShouldSuppressLocalClientRunEnemyDeathPresentation(
    uintptr_t actor_address,
    float* authoritative_hp_out) {
    if (authoritative_hp_out != nullptr) {
        *authoritative_hp_out = 0.0f;
    }
    if (!IsLocalTransportClient() || actor_address == 0) {
        return false;
    }

    const auto network_actor_id =
        FindReplicatedLocalNetworkActorId(actor_address);
    if (network_actor_id == 0) {
        return false;
    }
    if (sdmod::HasReplicatedRunEnemyDeathPresentation(network_actor_id)) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& actor : runtime_state.world_snapshot.actors) {
        if (actor.network_actor_id != network_actor_id ||
            !actor.tracked_enemy) {
            continue;
        }
        if (authoritative_hp_out != nullptr && std::isfinite(actor.hp)) {
            *authoritative_hp_out = actor.hp;
        }
        return !actor.dead &&
               (!std::isfinite(actor.hp) ||
                actor.hp > kEnemyDamageClaimHpEpsilon);
    }

    // A live replicated binding without a current authoritative death is not
    // permission to run the terminal native presentation.
    return true;
}

bool HasReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id) {
    return IsLocalTransportClient() &&
           network_actor_id != 0 &&
           g_local_transport.last_synced_enemy_hp_by_network_id.find(network_actor_id) !=
               g_local_transport.last_synced_enemy_hp_by_network_id.end();
}

void MarkReplicatedRunEnemyDamageBaseline(
    std::uint64_t network_actor_id,
    float authoritative_hp) {
    if (!IsLocalTransportClient() ||
        network_actor_id == 0 ||
        !std::isfinite(authoritative_hp)) {
        return;
    }
    g_local_transport.last_synced_enemy_hp_by_network_id[network_actor_id] =
        (std::max)(0.0f, authoritative_hp);
}

void ClearReplicatedRunEnemyDamageBaseline(std::uint64_t network_actor_id) {
    if (network_actor_id == 0) {
        return;
    }
    g_local_transport.last_synced_enemy_hp_by_network_id.erase(network_actor_id);
    g_local_transport.last_enemy_claimed_hp_by_network_id.erase(network_actor_id);
    g_local_transport.observed_enemy_damage_by_network_id.erase(network_actor_id);
    g_local_transport.rejected_enemy_damage_retry_suppressed_until_ms.erase(network_actor_id);
}

void ObserveLocalPlayerReplicatedRunEnemyDamageEvent(
    std::uint64_t network_actor_id,
    float damage,
    float max_hp,
    float target_position_x,
    float target_position_y,
    bool target_position_optional) {
    ObserveLocalPlayerReplicatedRunEnemyDamageEventInternal(
        network_actor_id,
        damage,
        max_hp,
        target_position_x,
        target_position_y,
        target_position_optional);
}

bool TrySetRunEnemyHealth(uintptr_t actor_address, float hp, float max_hp) {
    return TryWriteRunEnemyHealth(actor_address, hp, max_hp);
}
