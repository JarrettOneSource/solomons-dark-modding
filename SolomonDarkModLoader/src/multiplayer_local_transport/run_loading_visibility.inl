const ParticipantInfo* FindRunLoadingParticipant(
    const RuntimeState& runtime_state,
    std::uint64_t participant_id) {
    const auto participant = std::find_if(
        runtime_state.participants.begin(),
        runtime_state.participants.end(),
        [&](const ParticipantInfo& participant) {
            return participant.participant_id ==
                    participant_id ||
                participant.steam_id == participant_id;
        });
    return participant != runtime_state.participants.end()
        ? &*participant
        : nullptr;
}

bool IsLocalRunActorMaterialized(
    const ParticipantInfo* local,
    std::uint32_t run_nonce) {
    if (local == nullptr ||
        !local->ready ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce != run_nonce) {
        return false;
    }
    SDModPlayerState player;
    return TryGetPlayerState(&player) &&
           player.valid &&
           player.actor_address != 0;
}

bool IsRemoteRunActorMaterialized(
    const ParticipantInfo* participant,
    std::uint64_t participant_id,
    std::uint32_t run_nonce) {
    if (participant == nullptr ||
        !participant->ready ||
        !participant->transport_connected ||
        !IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.run_nonce != run_nonce) {
        return false;
    }
    SDModParticipantGameplayState gameplay;
    return TryGetParticipantGameplayState(
               participant_id,
               &gameplay) &&
           gameplay.entity_materialized &&
           gameplay.actor_address != 0;
}

std::unordered_set<std::uint64_t>
BuildLocallyVisibleRunParticipantIds(
    const RuntimeState& runtime_state,
    std::uint32_t run_nonce) {
    const auto* local =
        FindLocalParticipant(runtime_state);
    if (!IsLocalRunActorMaterialized(local, run_nonce)) {
        return {};
    }

    std::unordered_set<std::uint64_t> visible_ids;
    visible_ids.insert(g_local_transport.local_peer_id);
    for (const auto& participant :
         runtime_state.participants) {
        if (!IsRemoteParticipant(participant) ||
            participant.participant_id == 0 ||
            !IsRemoteRunActorMaterialized(
                &participant,
                participant.participant_id,
                run_nonce)) {
            continue;
        }
        visible_ids.insert(participant.participant_id);
    }
    return visible_ids;
}

std::unordered_set<std::uint64_t>
BuildHostRunLoadingExpectedParticipantIds(
    const RuntimeState& runtime_state) {
    std::unordered_set<std::uint64_t> participant_ids;
    participant_ids.insert(g_local_transport.local_peer_id);
    const auto* local = FindLocalParticipant(runtime_state);
    const auto loadout_generation = local == nullptr
        ? 0
        : local->loadout_pick_generation;
    for (const auto& participant :
         runtime_state.participants) {
        if (!IsRemoteParticipant(participant) ||
            !IsNativeControlledParticipant(participant) ||
            !participant.ready ||
            !participant.transport_connected ||
            loadout_generation == 0 ||
            participant.loadout_pick_generation !=
                loadout_generation ||
            participant.loadout_pick_state !=
                LoadoutPickState::WorldReady ||
            participant.participant_id == 0) {
            continue;
        }
        participant_ids.insert(
            participant.participant_id);
    }
    return participant_ids;
}

bool HostHasLocalMutualRunVisibility(
    const RuntimeState& runtime_state,
    std::uint32_t run_nonce) {
    for (const auto participant_id :
         g_run_loading_barrier.expected_participant_ids) {
        if (participant_id ==
            g_local_transport.local_peer_id) {
            if (!IsLocalRunActorMaterialized(
                    FindLocalParticipant(runtime_state),
                    run_nonce)) {
                return false;
            }
            continue;
        }
        if (!IsRemoteRunActorMaterialized(
                FindRunLoadingParticipant(
                    runtime_state,
                    participant_id),
                participant_id,
                run_nonce)) {
            return false;
        }
    }
    return !g_run_loading_barrier
                .expected_participant_ids.empty();
}
