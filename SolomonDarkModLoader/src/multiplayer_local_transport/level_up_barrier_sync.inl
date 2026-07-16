// Host-owned synchronized level-up round state and client reconciliation.

constexpr std::uint64_t kHostLevelUpBarrierTimeoutMs = 60'000;
constexpr std::uint64_t kHostLevelUpBarrierBroadcastIntervalMs = 250;
constexpr std::uint64_t kHostLevelUpBarrierResumeBroadcastMs = 3'000;

void AdvanceHostLevelUpBarrierRevision() {
    auto& barrier = g_local_transport.host_level_up_barrier;
    barrier.revision += 1;
    if (barrier.revision == 0) {
        barrier.revision = 1;
    }
}

HostLevelUpBarrierParticipant* FindHostLevelUpBarrierParticipant(
    std::uint64_t participant_id) {
    auto& participants = g_local_transport.host_level_up_barrier.participants;
    const auto it = std::find_if(
        participants.begin(),
        participants.end(),
        [&](const HostLevelUpBarrierParticipant& participant) {
            return participant.participant_id == participant_id;
        });
    return it == participants.end() ? nullptr : &*it;
}

const HostLevelUpBarrierParticipant* FindHostLevelUpBarrierParticipant(
    std::uint64_t participant_id,
    const HostLevelUpBarrierState& barrier) {
    const auto it = std::find_if(
        barrier.participants.begin(),
        barrier.participants.end(),
        [&](const HostLevelUpBarrierParticipant& participant) {
            return participant.participant_id == participant_id;
        });
    return it == barrier.participants.end() ? nullptr : &*it;
}

std::uint32_t HostLevelUpBarrierDeadlineRemainingMs(std::uint64_t now_ms) {
    const auto& barrier = g_local_transport.host_level_up_barrier;
    if (!barrier.active || barrier.deadline_ms <= now_ms) {
        return 0;
    }
    return static_cast<std::uint32_t>(
        (std::min)(
            barrier.deadline_ms - now_ms,
            static_cast<std::uint64_t>(
                (std::numeric_limits<std::uint32_t>::max)())));
}

std::vector<std::uint64_t> CollectHostLevelUpBarrierWaitingParticipantIds() {
    std::vector<std::uint64_t> participant_ids;
    const auto& barrier = g_local_transport.host_level_up_barrier;
    if (!barrier.active) {
        return participant_ids;
    }
    participant_ids.reserve(barrier.participants.size());
    for (const auto& participant : barrier.participants) {
        if (!participant.resolved && !participant.disconnected &&
            participant.participant_id != 0) {
            participant_ids.push_back(participant.participant_id);
        }
    }
    std::sort(participant_ids.begin(), participant_ids.end());
    return participant_ids;
}

LevelUpWaitStatusRuntimeInfo BuildHostLevelUpWaitStatusRuntimeInfo(
    std::uint64_t now_ms) {
    LevelUpWaitStatusRuntimeInfo status;
    const auto& barrier = g_local_transport.host_level_up_barrier;
    status.valid = barrier.barrier_id != 0;
    status.pause_active = barrier.active;
    status.timed_out = barrier.timed_out;
    status.authority_participant_id = g_local_transport.local_peer_id;
    status.barrier_id = barrier.barrier_id;
    status.revision = barrier.revision;
    status.deadline_remaining_ms = HostLevelUpBarrierDeadlineRemainingMs(now_ms);
    status.received_ms = now_ms;
    status.waiting_participant_ids =
        CollectHostLevelUpBarrierWaitingParticipantIds();
    return status;
}

LevelUpBarrierPacket BuildHostLevelUpBarrierPacket(std::uint64_t now_ms) {
    const auto& barrier = g_local_transport.host_level_up_barrier;
    LevelUpBarrierPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::LevelUpBarrier,
        g_local_transport.next_sequence++);
    packet.authority_participant_id = g_local_transport.local_peer_id;
    packet.barrier_id = barrier.barrier_id;
    packet.run_nonce = barrier.run_nonce;
    packet.revision = barrier.revision;
    packet.deadline_remaining_ms = HostLevelUpBarrierDeadlineRemainingMs(now_ms);
    packet.level = barrier.level;
    packet.experience = barrier.experience;
    packet.flags =
        (barrier.active ? kLevelUpBarrierFlagActive : 0) |
        (barrier.timed_out ? kLevelUpBarrierFlagTimedOut : 0);
    const auto participant_count =
        (std::min)(
            barrier.participants.size(),
            static_cast<std::size_t>(kLevelUpWaitStatusMaxParticipants));
    packet.participant_count = static_cast<std::uint8_t>(participant_count);
    for (std::size_t index = 0; index < participant_count; ++index) {
        const auto& participant = barrier.participants[index];
        auto& packet_participant = packet.participants[index];
        packet_participant.participant_id = participant.participant_id;
        packet_participant.offer_id = participant.offer_id;
        packet_participant.option_index = participant.option_index;
        packet_participant.option_id = participant.option_id;
        packet_participant.apply_count = participant.apply_count;
        packet_participant.resulting_active = participant.resulting_active;
        packet_participant.flags =
            (participant.resolved
                 ? kLevelUpBarrierParticipantFlagResolved
                 : 0) |
            (participant.auto_picked
                 ? kLevelUpBarrierParticipantFlagAutoPicked
                 : 0) |
            (participant.disconnected
                 ? kLevelUpBarrierParticipantFlagDisconnected
                 : 0);
    }
    return packet;
}

void BroadcastHostLevelUpBarrierState(std::uint64_t now_ms, bool force) {
    if (!IsLocalTransportHost()) {
        return;
    }
    auto& barrier = g_local_transport.host_level_up_barrier;
    if (barrier.barrier_id == 0 ||
        (!barrier.active && now_ms > barrier.resume_broadcast_until_ms)) {
        return;
    }
    if (!force &&
        now_ms - barrier.last_broadcast_ms <
            kHostLevelUpBarrierBroadcastIntervalMs) {
        return;
    }

    barrier.last_broadcast_ms = now_ms;
    const auto packet = BuildHostLevelUpBarrierPacket(now_ms);
    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

bool BeginOrExtendHostLevelUpBarrier(
    std::vector<std::uint64_t> participant_ids,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address,
    std::uint64_t now_ms) {
    if (!IsLocalTransportHost() || participant_ids.empty() ||
        level <= 0 || experience < 0) {
        return false;
    }

    participant_ids.erase(
        std::remove(participant_ids.begin(), participant_ids.end(), 0),
        participant_ids.end());
    std::sort(participant_ids.begin(), participant_ids.end());
    participant_ids.erase(
        std::unique(participant_ids.begin(), participant_ids.end()),
        participant_ids.end());
    if (participant_ids.empty()) {
        return false;
    }
    if (participant_ids.size() > kLevelUpWaitStatusMaxParticipants) {
        participant_ids.resize(kLevelUpWaitStatusMaxParticipants);
    }

    auto& barrier = g_local_transport.host_level_up_barrier;
    if (barrier.active &&
        (barrier.run_nonce != run_nonce || barrier.level != level ||
         barrier.experience != experience)) {
        Log(
            "Multiplayer level-up barrier start rejected while another round is active. "
            "active_barrier_id=" + std::to_string(barrier.barrier_id) +
            " active_level=" + std::to_string(barrier.level) +
            " requested_level=" + std::to_string(level));
        return false;
    }

    if (!barrier.active) {
        barrier = HostLevelUpBarrierState{};
        barrier.active = true;
        barrier.barrier_id = g_local_transport.next_level_up_barrier_id++;
        if (g_local_transport.next_level_up_barrier_id == 0) {
            g_local_transport.next_level_up_barrier_id = 1;
        }
        barrier.run_nonce = run_nonce;
        barrier.revision = 1;
        barrier.level = level;
        barrier.experience = experience;
        barrier.source_progression_address = source_progression_address;
        barrier.started_ms = now_ms;
        barrier.deadline_ms = now_ms + kHostLevelUpBarrierTimeoutMs;
        barrier.participants.reserve(participant_ids.size());
        for (const auto participant_id : participant_ids) {
            HostLevelUpBarrierParticipant participant;
            participant.participant_id = participant_id;
            participant.last_offer_attempt_ms = now_ms;
            barrier.participants.push_back(participant);
        }
        BroadcastHostLevelUpBarrierState(now_ms, true);
        Log(
            "Multiplayer level-up barrier started. barrier_id=" +
            std::to_string(barrier.barrier_id) +
            " participant_count=" +
            std::to_string(barrier.participants.size()) +
            " timeout_ms=" +
            std::to_string(kHostLevelUpBarrierTimeoutMs));
        return true;
    }

    bool changed = false;
    for (const auto participant_id : participant_ids) {
        if (FindHostLevelUpBarrierParticipant(participant_id) != nullptr) {
            continue;
        }
        HostLevelUpBarrierParticipant participant;
        participant.participant_id = participant_id;
        participant.last_offer_attempt_ms = now_ms;
        barrier.participants.push_back(participant);
        changed = true;
    }
    if (changed) {
        std::sort(
            barrier.participants.begin(),
            barrier.participants.end(),
            [](const HostLevelUpBarrierParticipant& left,
               const HostLevelUpBarrierParticipant& right) {
                return left.participant_id < right.participant_id;
            });
        AdvanceHostLevelUpBarrierRevision();
        BroadcastHostLevelUpBarrierState(now_ms, true);
    }
    return true;
}

void AttachHostLevelUpOfferToBarrier(
    std::uint64_t participant_id,
    std::uint64_t offer_id,
    std::uint64_t now_ms) {
    auto& barrier = g_local_transport.host_level_up_barrier;
    if (!barrier.active || offer_id == 0) {
        return;
    }
    auto* participant = FindHostLevelUpBarrierParticipant(participant_id);
    if (participant == nullptr || participant->resolved ||
        participant->offer_id == offer_id) {
        return;
    }
    participant->offer_id = offer_id;
    AdvanceHostLevelUpBarrierRevision();
    BroadcastHostLevelUpBarrierState(now_ms, true);
}

void CompleteHostLevelUpBarrierIfReady(std::uint64_t now_ms) {
    auto& barrier = g_local_transport.host_level_up_barrier;
    if (!barrier.active) {
        return;
    }
    const bool all_resolved = std::all_of(
        barrier.participants.begin(),
        barrier.participants.end(),
        [](const HostLevelUpBarrierParticipant& participant) {
            return participant.resolved || participant.disconnected;
        });
    if (!all_resolved) {
        return;
    }
    barrier.active = false;
    barrier.resume_broadcast_until_ms =
        now_ms + kHostLevelUpBarrierResumeBroadcastMs;
    BroadcastHostLevelUpBarrierState(now_ms, true);
    Log(
        "Multiplayer level-up barrier completed; resume broadcast. barrier_id=" +
        std::to_string(barrier.barrier_id) +
        " revision=" + std::to_string(barrier.revision) +
        " timed_out=" + std::to_string(barrier.timed_out ? 1 : 0));
}

void MarkHostLevelUpBarrierParticipantResolved(
    const LevelUpChoiceResultPacket& result,
    bool auto_picked,
    std::uint64_t now_ms) {
    auto& barrier = g_local_transport.host_level_up_barrier;
    if (!barrier.active ||
        result.result_code !=
            static_cast<std::uint8_t>(LevelUpChoiceResultCode::Accepted)) {
        return;
    }
    auto* participant =
        FindHostLevelUpBarrierParticipant(result.target_participant_id);
    if (participant == nullptr || participant->resolved) {
        return;
    }
    participant->offer_id = result.offer_id;
    participant->option_index = result.option_index;
    participant->option_id = result.option_id;
    participant->apply_count = result.apply_count;
    participant->resulting_active = result.resulting_active;
    participant->resolved = true;
    participant->auto_picked = auto_picked;
    AdvanceHostLevelUpBarrierRevision();
    CompleteHostLevelUpBarrierIfReady(now_ms);
    if (barrier.active) {
        BroadcastHostLevelUpBarrierState(now_ms, true);
    }
}

void MarkHostLevelUpBarrierParticipantDisconnected(
    std::uint64_t participant_id,
    std::uint64_t now_ms) {
    if (!IsLocalTransportHost()) {
        return;
    }
    auto* participant = FindHostLevelUpBarrierParticipant(participant_id);
    if (participant == nullptr || participant->resolved || participant->disconnected) {
        return;
    }
    participant->disconnected = true;
    participant->resolved = true;
    AdvanceHostLevelUpBarrierRevision();
    CompleteHostLevelUpBarrierIfReady(now_ms);
    if (g_local_transport.host_level_up_barrier.active) {
        BroadcastHostLevelUpBarrierState(now_ms, true);
    }
}

void PopulateHostLevelUpBarrierStatePacket(
    StatePacket* packet,
    std::uint64_t now_ms) {
    if (packet == nullptr || !IsLocalTransportHost()) {
        return;
    }
    const auto& barrier = g_local_transport.host_level_up_barrier;
    packet->level_up_barrier_id = barrier.barrier_id;
    packet->level_up_barrier_revision = barrier.revision;
    packet->level_up_deadline_remaining_ms =
        HostLevelUpBarrierDeadlineRemainingMs(now_ms);
    packet->level_up_pause_active = barrier.active ? 1 : 0;
    packet->level_up_barrier_flags =
        (barrier.active ? kLevelUpBarrierFlagActive : 0) |
        (barrier.timed_out ? kLevelUpBarrierFlagTimedOut : 0);
    const auto waiting_participant_ids =
        CollectHostLevelUpBarrierWaitingParticipantIds();
    const auto waiting_count =
        (std::min)(
            waiting_participant_ids.size(),
            static_cast<std::size_t>(kLevelUpWaitStatusMaxParticipants));
    packet->level_up_waiting_count = static_cast<std::uint8_t>(waiting_count);
    for (std::size_t index = 0; index < waiting_count; ++index) {
        packet->level_up_waiting_participant_ids[index] =
            waiting_participant_ids[index];
    }
}

bool ApplyAuthoritativeLevelUpWaitStatus(
    std::uint64_t authority_participant_id,
    std::uint64_t barrier_id,
    std::uint32_t revision,
    std::uint32_t deadline_remaining_ms,
    bool pause_active,
    bool timed_out,
    std::vector<std::uint64_t> waiting_participant_ids,
    std::uint64_t now_ms) {
    bool applied = false;
    UpdateRuntimeState([&](RuntimeState& state) {
        const auto& current = state.level_up_wait_status;
        if (current.valid &&
            current.authority_participant_id == authority_participant_id &&
            (barrier_id < current.barrier_id ||
             (barrier_id == current.barrier_id &&
              revision < current.revision))) {
            return;
        }
        std::sort(
            waiting_participant_ids.begin(),
            waiting_participant_ids.end());
        waiting_participant_ids.erase(
            std::unique(
                waiting_participant_ids.begin(),
                waiting_participant_ids.end()),
            waiting_participant_ids.end());
        LevelUpWaitStatusRuntimeInfo status;
        status.valid = barrier_id != 0;
        status.pause_active = pause_active;
        status.timed_out = timed_out;
        status.authority_participant_id = authority_participant_id;
        status.barrier_id = barrier_id;
        status.revision = revision;
        status.deadline_remaining_ms = deadline_remaining_ms;
        status.received_ms = now_ms;
        status.waiting_participant_ids = std::move(waiting_participant_ids);
        state.level_up_wait_status = std::move(status);
        applied = true;
    });
    return applied;
}

void ApplyLevelUpBarrierPacket(
    const LevelUpBarrierPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() || packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.barrier_id == 0 || packet.revision == 0 ||
        packet.participant_count == 0 ||
        packet.participant_count > kLevelUpWaitStatusMaxParticipants ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto& current = runtime_state.level_up_wait_status;
    if (current.valid &&
        current.authority_participant_id == packet.authority_participant_id &&
        (packet.barrier_id < current.barrier_id ||
         (packet.barrier_id == current.barrier_id &&
          packet.revision < current.revision))) {
        return;
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    std::vector<std::uint64_t> waiting_participant_ids;
    waiting_participant_ids.reserve(packet.participant_count);
    for (std::size_t index = 0; index < packet.participant_count; ++index) {
        const auto& participant = packet.participants[index];
        if (participant.participant_id == 0) {
            return;
        }
        const bool resolved =
            (participant.flags &
             kLevelUpBarrierParticipantFlagResolved) != 0;
        const bool disconnected =
            (participant.flags &
             kLevelUpBarrierParticipantFlagDisconnected) != 0;
        if (!resolved && !disconnected) {
            waiting_participant_ids.push_back(participant.participant_id);
            continue;
        }
        if (disconnected || participant.offer_id == 0 ||
            participant.option_index <= 0 || participant.option_id < 0 ||
            participant.apply_count <= 0) {
            continue;
        }

        LevelUpChoiceResultPacket result{};
        result.header = MakePacketHeader(
            PacketKind::LevelUpChoiceResult,
            packet.header.sequence);
        result.authority_participant_id = packet.authority_participant_id;
        result.target_participant_id = participant.participant_id;
        result.offer_id = participant.offer_id;
        result.run_nonce = packet.run_nonce;
        result.level = packet.level;
        result.experience = packet.experience;
        result.option_index = participant.option_index;
        result.option_id = participant.option_id;
        result.apply_count = participant.apply_count;
        result.result_code =
            static_cast<std::uint8_t>(LevelUpChoiceResultCode::Accepted);
        result.flags =
            (participant.flags &
             kLevelUpBarrierParticipantFlagAutoPicked) != 0
                ? kLevelUpChoiceResultFlagAutoPicked
                : 0;
        result.resulting_active = participant.resulting_active;
        ApplyLevelUpChoiceResultPacket(result, from, now_ms);
    }

    const bool pause_active =
        (packet.flags & kLevelUpBarrierFlagActive) != 0;
    const bool timed_out =
        (packet.flags & kLevelUpBarrierFlagTimedOut) != 0;
    (void)ApplyAuthoritativeLevelUpWaitStatus(
        packet.authority_participant_id,
        packet.barrier_id,
        packet.revision,
        packet.deadline_remaining_ms,
        pause_active,
        timed_out,
        std::move(waiting_participant_ids),
        now_ms);
}
