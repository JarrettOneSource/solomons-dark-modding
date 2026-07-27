constexpr std::uint64_t kRunLoadingBarrierTimeoutMs = 25000;
constexpr std::uint64_t kRunLoadingMaterializationStableMs = 250;

struct RunLoadingBarrierState {
    bool active = false;
    bool local_mutual_visibility = false;
    bool released = false;
    std::uint32_t run_nonce = 0;
    std::uint32_t local_ack_nonce = 0;
    std::uint32_t release_nonce = 0;
    std::uint64_t started_ms = 0;
    std::uint64_t deadline_ms = 0;
    std::uint64_t local_visibility_stable_since_ms = 0;
    std::uint64_t visible_participant_set_hash = 0;
    std::uint64_t authoritative_expected_participant_set_hash = 0;
    std::uint16_t visible_participant_count = 0;
    std::uint16_t authoritative_expected_participant_count = 0;
    std::uint16_t authoritative_ready_participant_count = 0;
    RunLoadingReleaseReason release_reason =
        RunLoadingReleaseReason::None;
    std::unordered_set<std::uint64_t> expected_participant_ids;
    std::unordered_set<std::uint64_t> ready_participant_ids;
};

RunLoadingBarrierState g_run_loading_barrier;

std::vector<std::uint64_t> SortedRunLoadingParticipantIds(
    const std::unordered_set<std::uint64_t>& participant_ids) {
    std::vector<std::uint64_t> sorted(
        participant_ids.begin(),
        participant_ids.end());
    std::sort(sorted.begin(), sorted.end());
    return sorted;
}

std::uint64_t RunLoadingParticipantSetHash(
    const std::unordered_set<std::uint64_t>& participant_ids) {
    constexpr std::uint64_t kFnvOffsetBasis =
        14695981039346656037ull;
    constexpr std::uint64_t kFnvPrime =
        1099511628211ull;
    auto hash = kFnvOffsetBasis;
    for (const auto participant_id :
         SortedRunLoadingParticipantIds(participant_ids)) {
        for (std::uint32_t shift = 0; shift < 64; shift += 8) {
            hash ^= (participant_id >> shift) & 0xFFull;
            hash *= kFnvPrime;
        }
    }
    return hash;
}

std::string RunLoadingParticipantIdsText(
    const std::vector<std::uint64_t>& participant_ids) {
    std::ostringstream stream;
    for (std::size_t index = 0;
         index < participant_ids.size();
         ++index) {
        if (index != 0) {
            stream << ',';
        }
        stream << participant_ids[index];
    }
    return stream.str();
}

std::uint16_t SaturatingRunLoadingParticipantCount(
    std::size_t count) {
    return static_cast<std::uint16_t>(
        (std::min)(
            count,
            static_cast<std::size_t>(
                (std::numeric_limits<std::uint16_t>::max)())));
}

std::uint32_t RunLoadingDeadlineRemainingMs(
    std::uint64_t now_ms) {
    if (!g_run_loading_barrier.active ||
        g_run_loading_barrier.released ||
        g_run_loading_barrier.deadline_ms <= now_ms) {
        return 0;
    }
    return static_cast<std::uint32_t>(
        (std::min)(
            g_run_loading_barrier.deadline_ms - now_ms,
            static_cast<std::uint64_t>(
                (std::numeric_limits<std::uint32_t>::max)())));
}

RunLoadingBarrierRuntimeInfo BuildRunLoadingBarrierRuntimeInfo(
    std::uint64_t now_ms) {
    RunLoadingBarrierRuntimeInfo info;
    info.active = g_run_loading_barrier.active;
    info.local_mutual_visibility =
        g_run_loading_barrier.local_mutual_visibility;
    info.released = g_run_loading_barrier.released;
    info.timed_out =
        g_run_loading_barrier.release_reason ==
        RunLoadingReleaseReason::Timeout;
    info.run_nonce = g_run_loading_barrier.run_nonce;
    info.local_ack_nonce =
        g_run_loading_barrier.local_ack_nonce;
    info.release_nonce =
        g_run_loading_barrier.release_nonce;
    info.deadline_remaining_ms =
        RunLoadingDeadlineRemainingMs(now_ms);
    info.visible_participant_set_hash =
        g_run_loading_barrier
            .visible_participant_set_hash;
    info.expected_participant_set_hash =
        g_run_loading_barrier
            .authoritative_expected_participant_set_hash;
    info.visible_participant_count =
        g_run_loading_barrier.visible_participant_count;
    info.release_reason =
        g_run_loading_barrier.release_reason;
    info.expected_participant_ids =
        SortedRunLoadingParticipantIds(
            g_run_loading_barrier.expected_participant_ids);
    info.ready_participant_ids =
        SortedRunLoadingParticipantIds(
            g_run_loading_barrier.ready_participant_ids);
    info.expected_participant_count =
        !info.expected_participant_ids.empty()
            ? SaturatingRunLoadingParticipantCount(
                  info.expected_participant_ids.size())
            : g_run_loading_barrier
                  .authoritative_expected_participant_count;
    info.ready_participant_count =
        !info.ready_participant_ids.empty()
            ? SaturatingRunLoadingParticipantCount(
                  info.ready_participant_ids.size())
            : g_run_loading_barrier
                  .authoritative_ready_participant_count;
    for (const auto participant_id :
         info.expected_participant_ids) {
        if (g_run_loading_barrier.ready_participant_ids.find(
                participant_id) ==
            g_run_loading_barrier.ready_participant_ids.end()) {
            info.waiting_participant_ids.push_back(
                participant_id);
        }
    }
    return info;
}

void PublishRunLoadingBarrierRuntime(std::uint64_t now_ms) {
    const auto current =
        BuildRunLoadingBarrierRuntimeInfo(now_ms);
    UpdateRuntimeState([&](RuntimeState& state) {
        state.run_loading_barrier = current;
    });
}

void ResetRunLoadingBarrierState(std::string_view reason) {
    const bool was_active =
        g_run_loading_barrier.active ||
        g_run_loading_barrier.run_nonce != 0 ||
        g_run_loading_barrier.release_nonce != 0;
    g_run_loading_barrier = RunLoadingBarrierState{};
    PublishRunLoadingBarrierRuntime(
        static_cast<std::uint64_t>(GetTickCount64()));
    if (was_active) {
        CancelLoadingScreen();
        Log(
            "Multiplayer run-loading barrier retired. reason=" +
            std::string(reason));
    }
}

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
    for (const auto& peer : g_local_transport.peers) {
        if (peer.participant_id != 0) {
            participant_ids.insert(peer.participant_id);
        }
    }
    for (const auto& participant :
         runtime_state.participants) {
        if (!IsRemoteParticipant(participant) ||
            !IsNativeControlledParticipant(participant) ||
            !participant.ready ||
            !participant.transport_connected ||
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

void BeginRunLoadingBarrier(
    const RuntimeState& runtime_state,
    std::uint32_t run_nonce,
    std::uint64_t now_ms,
    std::uint16_t authoritative_expected_count = 0,
    std::uint64_t authoritative_expected_set_hash = 0) {
    g_run_loading_barrier =
        RunLoadingBarrierState{};
    g_run_loading_barrier.active = true;
    g_run_loading_barrier.run_nonce = run_nonce;
    g_run_loading_barrier.started_ms = now_ms;
    g_run_loading_barrier.deadline_ms =
        now_ms + kRunLoadingBarrierTimeoutMs;
    if (g_local_transport.is_host) {
        g_run_loading_barrier.expected_participant_ids =
            BuildHostRunLoadingExpectedParticipantIds(
                runtime_state);
        g_run_loading_barrier
            .authoritative_expected_participant_count =
            SaturatingRunLoadingParticipantCount(
                g_run_loading_barrier
                    .expected_participant_ids.size());
        g_run_loading_barrier
            .authoritative_expected_participant_set_hash =
            RunLoadingParticipantSetHash(
                g_run_loading_barrier
                    .expected_participant_ids);
    } else {
        g_run_loading_barrier
            .authoritative_expected_participant_count =
            authoritative_expected_count;
        g_run_loading_barrier
            .authoritative_expected_participant_set_hash =
            authoritative_expected_set_hash;
    }
    Log(
        "Multiplayer run-loading barrier started. role=" +
        std::string(
            g_local_transport.is_host ? "host" : "client") +
        " run_nonce=" + std::to_string(run_nonce) +
        " expected_participants=" +
        std::to_string(
            g_run_loading_barrier
                .authoritative_expected_participant_count) +
        " timeout_ms=" +
        std::to_string(kRunLoadingBarrierTimeoutMs));
    BeginLoadingScreen(
        g_local_transport.is_host
            ? LoadingScreenFlow::MultiplayerHost
            : LoadingScreenFlow::MultiplayerJoin,
        LoadingScreenStage::WaitingForParticipants);
}

void ReleaseRunLoadingBarrier(
    RunLoadingReleaseReason reason,
    std::uint64_t now_ms,
    std::string_view source) {
    if (!g_run_loading_barrier.active ||
        g_run_loading_barrier.released ||
        g_run_loading_barrier.run_nonce == 0 ||
        reason == RunLoadingReleaseReason::None) {
        return;
    }
    g_run_loading_barrier.released = true;
    g_run_loading_barrier.release_nonce =
        g_run_loading_barrier.run_nonce;
    g_run_loading_barrier.release_reason = reason;
    const auto runtime =
        BuildRunLoadingBarrierRuntimeInfo(now_ms);
    Log(
        "Multiplayer run-loading barrier released. source=" +
        std::string(source) +
        " role=" +
        std::string(
            g_local_transport.is_host ? "host" : "client") +
        " run_nonce=" +
        std::to_string(g_run_loading_barrier.run_nonce) +
        " reason=" +
        RunLoadingReleaseReasonLabel(reason) +
        " ready=" +
        std::to_string(
            runtime.ready_participant_count) +
        "/" +
        std::to_string(
            runtime.expected_participant_count) +
        " waiting_participant_ids=" +
        RunLoadingParticipantIdsText(
            runtime.waiting_participant_ids));
    AdvanceLoadingScreen(LoadingScreenStage::GameplayReady);
    CompleteLoadingScreen();
}

bool HostRunLoadingReadyByEveryParticipant() {
    if (!g_local_transport.is_host ||
        !g_run_loading_barrier.local_mutual_visibility ||
        g_run_loading_barrier
            .expected_participant_ids.empty()) {
        return false;
    }
    for (const auto participant_id :
         g_run_loading_barrier
             .expected_participant_ids) {
        if (g_run_loading_barrier.ready_participant_ids.find(
                participant_id) ==
            g_run_loading_barrier
                .ready_participant_ids.end()) {
            return false;
        }
    }
    return true;
}

void ServiceRunLoadingBarrier(std::uint64_t now_ms) {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local =
        FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce == 0 ||
        runtime_state.lobby_session_state !=
            LobbySessionState::InBoneyard) {
        PublishRunLoadingBarrierRuntime(now_ms);
        return;
    }

    const auto run_nonce = local->runtime.run_nonce;
    if (!g_run_loading_barrier.active ||
        g_run_loading_barrier.run_nonce != run_nonce) {
        BeginRunLoadingBarrier(
            runtime_state,
            run_nonce,
            now_ms);
    }
    if (g_run_loading_barrier.released) {
        PublishRunLoadingBarrierRuntime(now_ms);
        return;
    }

    const auto visible_participant_ids =
        BuildLocallyVisibleRunParticipantIds(
            runtime_state,
            run_nonce);
    g_run_loading_barrier.visible_participant_count =
        SaturatingRunLoadingParticipantCount(
            visible_participant_ids.size());
    g_run_loading_barrier.visible_participant_set_hash =
        RunLoadingParticipantSetHash(
            visible_participant_ids);
    bool raw_local_mutual_visibility = false;
    if (g_local_transport.is_host) {
        raw_local_mutual_visibility =
            HostHasLocalMutualRunVisibility(
                runtime_state,
                run_nonce);
    } else {
        const auto expected =
            g_run_loading_barrier
                .authoritative_expected_participant_count;
        raw_local_mutual_visibility =
            expected != 0 &&
            g_run_loading_barrier
                    .visible_participant_count ==
                expected &&
            g_run_loading_barrier
                    .visible_participant_set_hash ==
                g_run_loading_barrier
                    .authoritative_expected_participant_set_hash;
    }
    if (!raw_local_mutual_visibility) {
        g_run_loading_barrier.local_visibility_stable_since_ms = 0;
        g_run_loading_barrier.local_mutual_visibility = false;
    } else {
        if (g_run_loading_barrier.local_visibility_stable_since_ms == 0) {
            g_run_loading_barrier.local_visibility_stable_since_ms =
                now_ms;
        }
        g_run_loading_barrier.local_mutual_visibility =
            now_ms -
                    g_run_loading_barrier
                        .local_visibility_stable_since_ms >=
                kRunLoadingMaterializationStableMs;
    }

    if (g_run_loading_barrier
            .local_mutual_visibility) {
        AdvanceLoadingScreen(
            LoadingScreenStage::ConfirmingParticipants);
        g_run_loading_barrier.local_ack_nonce =
            run_nonce;
        if (g_local_transport.is_host) {
            g_run_loading_barrier
                .ready_participant_ids.insert(
                    g_local_transport.local_peer_id);
        }
    }

    if (g_local_transport.is_host &&
        HostRunLoadingReadyByEveryParticipant()) {
        ReleaseRunLoadingBarrier(
            RunLoadingReleaseReason::
                AllParticipantsReady,
            now_ms,
            "host_all_peer_acks");
    } else if (
        now_ms >=
        g_run_loading_barrier.deadline_ms) {
        ReleaseRunLoadingBarrier(
            RunLoadingReleaseReason::Timeout,
            now_ms,
            g_local_transport.is_host
                ? "host_deadline"
                : "client_fallback_deadline");
    }
    PublishRunLoadingBarrierRuntime(now_ms);
}

template <typename Packet>
void PopulateRunLoadingBarrierPacketFields(
    Packet* packet) {
    if (packet == nullptr ||
        !g_run_loading_barrier.active) {
        return;
    }
    packet->run_loading_ack_nonce =
        g_run_loading_barrier.local_ack_nonce;
    packet->run_loading_visible_participant_count =
        g_run_loading_barrier
            .visible_participant_count;
    packet->run_loading_release_nonce =
        g_run_loading_barrier.release_nonce;
    packet->run_loading_deadline_remaining_ms =
        RunLoadingDeadlineRemainingMs(
            static_cast<std::uint64_t>(
                GetTickCount64()));
    packet->run_loading_visible_participant_set_hash =
        g_run_loading_barrier
            .visible_participant_set_hash;
    packet->run_loading_expected_participant_set_hash =
        g_run_loading_barrier
            .authoritative_expected_participant_set_hash;
    packet->run_loading_expected_participant_count =
        !g_run_loading_barrier
             .expected_participant_ids.empty()
            ? SaturatingRunLoadingParticipantCount(
                  g_run_loading_barrier
                      .expected_participant_ids.size())
            : g_run_loading_barrier
                  .authoritative_expected_participant_count;
    packet->run_loading_ready_participant_count =
        SaturatingRunLoadingParticipantCount(
            g_run_loading_barrier
                .ready_participant_ids.size());
    packet->run_loading_release_reason =
        static_cast<std::uint8_t>(
            g_run_loading_barrier.release_reason);
}

template <typename Packet>
bool HasRunLoadingBarrierPacketWork(
    const Packet& packet) {
    return packet.run_loading_ack_nonce != 0 ||
           packet.run_loading_release_nonce != 0 ||
           packet.run_loading_expected_participant_count !=
               0 ||
           packet.run_loading_expected_participant_set_hash !=
               0;
}

template <typename Packet>
void ApplyRunLoadingBarrierPacket(
    const Packet& packet,
    bool packet_from_configured_authority,
    std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.run_nonce == 0) {
        return;
    }

    if (g_local_transport.is_host) {
        if (!g_run_loading_barrier.active ||
            g_run_loading_barrier.released ||
            packet.run_nonce !=
                g_run_loading_barrier.run_nonce ||
            packet.run_loading_ack_nonce !=
                g_run_loading_barrier.run_nonce ||
            packet.run_loading_visible_participant_count !=
                SaturatingRunLoadingParticipantCount(
                    g_run_loading_barrier
                        .expected_participant_ids.size()) ||
            packet.run_loading_expected_participant_set_hash !=
                g_run_loading_barrier
                    .authoritative_expected_participant_set_hash ||
            packet.run_loading_visible_participant_set_hash !=
                g_run_loading_barrier
                    .authoritative_expected_participant_set_hash ||
            g_run_loading_barrier
                    .expected_participant_ids.find(
                        packet.participant_id) ==
                g_run_loading_barrier
                    .expected_participant_ids.end()) {
            return;
        }
        if (g_run_loading_barrier
                .ready_participant_ids.insert(
                    packet.participant_id)
                .second) {
            Log(
                "Multiplayer run-loading peer ack accepted. "
                "participant_id=" +
                std::to_string(packet.participant_id) +
                " run_nonce=" +
                std::to_string(packet.run_nonce) +
                " visible_participants=" +
                std::to_string(
                    packet
                        .run_loading_visible_participant_count));
        }
        return;
    }

    if (!packet_from_configured_authority ||
        packet.authority_participant_id == 0 ||
        packet.participant_id !=
            packet.authority_participant_id ||
        packet.run_loading_expected_participant_count ==
            0 ||
        packet.run_loading_expected_participant_set_hash ==
            0) {
        return;
    }

    if (!g_run_loading_barrier.active ||
        g_run_loading_barrier.run_nonce !=
            packet.run_nonce) {
        BeginRunLoadingBarrier(
            SnapshotRuntimeState(),
            packet.run_nonce,
            now_ms,
            packet
                .run_loading_expected_participant_count,
            packet
                .run_loading_expected_participant_set_hash);
    } else {
        g_run_loading_barrier
            .authoritative_expected_participant_count =
            packet
                .run_loading_expected_participant_count;
        g_run_loading_barrier
            .authoritative_expected_participant_set_hash =
            packet
                .run_loading_expected_participant_set_hash;
    }
    g_run_loading_barrier
        .authoritative_ready_participant_count =
        packet.run_loading_ready_participant_count;
    if (packet.run_loading_deadline_remaining_ms != 0) {
        const auto authority_deadline =
            now_ms +
            packet
                .run_loading_deadline_remaining_ms;
        g_run_loading_barrier.deadline_ms =
            (std::min)(
                g_run_loading_barrier.deadline_ms,
                authority_deadline);
    }

    const auto reason =
        static_cast<RunLoadingReleaseReason>(
            packet.run_loading_release_reason);
    if (packet.run_loading_release_nonce ==
            packet.run_nonce &&
        (reason ==
             RunLoadingReleaseReason::
                 AllParticipantsReady ||
         reason ==
             RunLoadingReleaseReason::Timeout)) {
        ReleaseRunLoadingBarrier(
            reason,
            now_ms,
            "authenticated_host_release");
        g_run_loading_barrier
            .authoritative_expected_participant_count =
            packet
                .run_loading_expected_participant_count;
        g_run_loading_barrier
            .authoritative_ready_participant_count =
            packet
                .run_loading_ready_participant_count;
    }
    PublishRunLoadingBarrierRuntime(now_ms);
}
