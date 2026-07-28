std::uint32_t NextParticipantHitFeedbackSequence(
    std::uint32_t sequence) {
    sequence += 1;
    return sequence == 0 ? 1 : sequence;
}

void ResetParticipantHitFeedbackState() {
    {
        std::lock_guard<std::mutex> lock(
            g_local_transport_event_mutex);
        g_queued_host_participant_hit_feedback.clear();
    }
    g_local_transport
        .next_hit_feedback_event_sequence_by_participant.clear();
    g_local_transport.hit_feedback_run_nonce_by_participant.clear();
    g_local_transport
        .pending_hit_feedback_events_by_participant.clear();
    g_local_transport.local_hit_feedback_ack_sequence = 0;
    g_local_transport.received_hit_feedback_run_nonce = 0;
    g_local_transport
        .received_hit_feedback_events_by_sequence.clear();
}

bool QueueHostParticipantHitFeedbackInternal(
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    float health_before,
    float health_after,
    float health_maximum,
    const ParticipantHitReactionState& hit_reaction,
    bool ouch_eligible) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        target_participant_id == 0 ||
        target_participant_id == g_local_transport.local_peer_id ||
        run_nonce == 0 ||
        !std::isfinite(health_before) ||
        !std::isfinite(health_after) ||
        !std::isfinite(health_maximum) ||
        health_maximum <= 0.0f ||
        health_before <= health_after ||
        health_after <= 0.0f ||
        health_before > health_maximum) {
        return false;
    }
    if (!IsValidParticipantHitReactionState(hit_reaction)) {
        return false;
    }

    QueuedHostParticipantHitFeedback queued;
    queued.target_participant_id = target_participant_id;
    queued.run_nonce = run_nonce;
    queued.health_before = health_before;
    queued.health_after = health_after;
    queued.health_maximum = health_maximum;
    queued.hit_reaction = hit_reaction;
    queued.feedback_flags = ouch_eligible
        ? ParticipantHitFeedbackFlagOuchEligible
        : 0;

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    const auto queued_for_target = std::count_if(
        g_queued_host_participant_hit_feedback.begin(),
        g_queued_host_participant_hit_feedback.end(),
        [&](const QueuedHostParticipantHitFeedback& existing) {
            return existing.target_participant_id ==
                target_participant_id;
        });
    if (queued_for_target >=
        kParticipantHitFeedbackMaximumPendingEvents) {
        return false;
    }
    g_queued_host_participant_hit_feedback.push_back(queued);
    return true;
}

std::vector<QueuedHostParticipantHitFeedback>
TakeQueuedHostParticipantHitFeedback() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedHostParticipantHitFeedback> queued;
    queued.swap(g_queued_host_participant_hit_feedback);
    return queued;
}

void SendQueuedHostParticipantHitFeedback(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        (void)TakeQueuedHostParticipantHitFeedback();
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    for (const auto& queued : TakeQueuedHostParticipantHitFeedback()) {
        const auto* participant =
            FindParticipant(runtime_state, queued.target_participant_id);
        if (participant == nullptr ||
            !IsRemoteParticipant(*participant) ||
            !IsNativeControlledParticipant(*participant) ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            participant->runtime.run_nonce != queued.run_nonce) {
            continue;
        }

        auto& retained =
            g_local_transport
                .pending_hit_feedback_events_by_participant[
                    queued.target_participant_id];
        auto& retained_run_nonce =
            g_local_transport.hit_feedback_run_nonce_by_participant[
                queued.target_participant_id];
        auto& next_sequence =
            g_local_transport
                .next_hit_feedback_event_sequence_by_participant[
                    queued.target_participant_id];
        if (retained_run_nonce != queued.run_nonce) {
            retained.clear();
            retained_run_nonce = queued.run_nonce;
            next_sequence = 1;
        }
        if (next_sequence == 0) {
            next_sequence = 1;
        }
        if (retained.size() >=
            kParticipantHitFeedbackMaximumPendingEvents) {
            Log(
                "[hit-feedback] event=authority_queue_full "
                "target_participant_id=" +
                std::to_string(queued.target_participant_id) +
                " run_nonce=" +
                std::to_string(queued.run_nonce));
            continue;
        }

        PendingParticipantHitFeedback pending;
        auto& event = pending.packet;
        event.header = MakePacketHeader(
            PacketKind::ParticipantHitFeedback,
            g_local_transport.next_sequence++);
        event.authority_participant_id =
            g_local_transport.local_peer_id;
        event.target_participant_id =
            queued.target_participant_id;
        event.event_sequence = next_sequence;
        event.run_nonce = queued.run_nonce;
        event.health_before = queued.health_before;
        event.health_after = queued.health_after;
        event.health_maximum = queued.health_maximum;
        event.hit_reaction = queued.hit_reaction;
        event.feedback_flags = queued.feedback_flags;
        pending.last_sent_ms = 0;
        retained.push_back(pending);
        next_sequence =
            NextParticipantHitFeedbackSequence(next_sequence);

        Log(
            "[hit-feedback] event=authority_capture "
            "authority_participant_id=" +
            std::to_string(event.authority_participant_id) +
            " target_participant_id=" +
            std::to_string(event.target_participant_id) +
            " run_nonce=" + std::to_string(event.run_nonce) +
            " event_sequence=" +
            std::to_string(event.event_sequence) +
            " health_before=" +
            std::to_string(event.health_before) +
            " health_after=" +
            std::to_string(event.health_after) +
            " health_maximum=" +
            std::to_string(event.health_maximum) +
            " hit_primary_alpha=" +
            std::to_string(event.hit_reaction.primary_alpha) +
            " hit_intensity=" +
            std::to_string(event.hit_reaction.intensity) +
            " hit_secondary_alpha=" +
            std::to_string(event.hit_reaction.secondary_alpha) +
            " hit_color_red=" +
            std::to_string(event.hit_reaction.color_red) +
            " hit_color_green=" +
            std::to_string(event.hit_reaction.color_green) +
            " hit_color_blue=" +
            std::to_string(event.hit_reaction.color_blue) +
            " hit_color_alpha=" +
            std::to_string(event.hit_reaction.color_alpha) +
            " ouch_eligible=" +
            std::to_string(
                (event.feedback_flags &
                 ParticipantHitFeedbackFlagOuchEligible) != 0
                    ? 1
                    : 0));
    }

    for (auto& [participant_id, pending_events] :
         g_local_transport
             .pending_hit_feedback_events_by_participant) {
        for (auto& pending : pending_events) {
            if (pending.last_sent_ms != 0 &&
                now_ms - pending.last_sent_ms <
                    kParticipantHitFeedbackResendMs) {
                continue;
            }
            pending.packet.header.sequence =
                g_local_transport.next_sequence++;
            SendPacketToParticipantOrPeers(
                pending.packet,
                participant_id);
            pending.last_sent_ms = now_ms;
        }
    }
}

void ResetLocalHitFeedbackAcknowledgementForRun(
    std::uint32_t run_nonce) {
    if (g_local_transport.is_host ||
        g_local_transport.received_hit_feedback_run_nonce ==
            run_nonce) {
        return;
    }
    g_local_transport.received_hit_feedback_events_by_sequence.clear();
    g_local_transport.local_hit_feedback_ack_sequence = 0;
    g_local_transport.received_hit_feedback_run_nonce = run_nonce;
}

void RetireAcknowledgedParticipantHitFeedbackEvents(
    std::uint64_t participant_id,
    std::uint32_t run_nonce,
    std::uint32_t ack_sequence) {
    if (!g_local_transport.is_host ||
        participant_id == 0 ||
        run_nonce == 0 ||
        ack_sequence == 0) {
        return;
    }

    const auto pending_it =
        g_local_transport
            .pending_hit_feedback_events_by_participant.find(
                participant_id);
    if (pending_it ==
            g_local_transport
                .pending_hit_feedback_events_by_participant.end() ||
        pending_it->second.empty() ||
        pending_it->second.front().packet.run_nonce != run_nonce) {
        return;
    }

    auto& pending = pending_it->second;
    const auto acknowledged = std::find_if(
        pending.begin(),
        pending.end(),
        [&](const PendingParticipantHitFeedback& event) {
            return event.packet.event_sequence == ack_sequence &&
                   event.packet.run_nonce == run_nonce;
        });
    if (acknowledged == pending.end()) {
        return;
    }
    pending.erase(pending.begin(), std::next(acknowledged));
    if (pending.empty()) {
        g_local_transport
            .pending_hit_feedback_events_by_participant.erase(
                pending_it);
    }
}

void ApplyParticipantHitFeedbackPacket(
    const ParticipantHitFeedbackPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id ==
            g_local_transport.local_peer_id ||
        packet.target_participant_id !=
            g_local_transport.local_peer_id ||
        packet.run_nonce == 0 ||
        packet.event_sequence == 0 ||
        !std::isfinite(packet.health_before) ||
        !std::isfinite(packet.health_after) ||
        !std::isfinite(packet.health_maximum) ||
        packet.health_maximum <= 0.0f ||
        packet.health_before <= packet.health_after ||
        packet.health_after <= 0.0f ||
        packet.health_before > packet.health_maximum ||
        !IsValidParticipantHitReactionState(packet.hit_reaction) ||
        (packet.feedback_flags &
         ~kParticipantHitFeedbackKnownFlags) != 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        !local->runtime.valid ||
        !local->runtime.in_run ||
        local->runtime.run_nonce != packet.run_nonce) {
        return;
    }

    ResetLocalHitFeedbackAcknowledgementForRun(packet.run_nonce);
    const auto acknowledged =
        g_local_transport.local_hit_feedback_ack_sequence;
    if (acknowledged != 0 &&
        (packet.event_sequence == acknowledged ||
         !IsPacketSequenceNewer(
             packet.event_sequence,
             acknowledged))) {
        return;
    }

    auto& received =
        g_local_transport.received_hit_feedback_events_by_sequence;
    if (received.size() >=
            kParticipantHitFeedbackMaximumPendingEvents &&
        received.find(packet.event_sequence) == received.end()) {
        return;
    }
    received.emplace(packet.event_sequence, packet);

    auto expected_sequence = acknowledged == 0
        ? 1
        : NextParticipantHitFeedbackSequence(acknowledged);
    while (true) {
        const auto expected = received.find(expected_sequence);
        if (expected == received.end()) {
            break;
        }

        std::string queue_error;
        const auto& event = expected->second;
        if (!QueueLocalPlayerHitFeedback(
                event.authority_participant_id,
                event.target_participant_id,
                event.run_nonce,
                event.event_sequence,
                event.health_before,
                event.health_after,
                event.health_maximum,
                event.hit_reaction,
                event.feedback_flags,
                &queue_error)) {
            Log(
                "[hit-feedback] event=owner_queue_pending "
                "event_sequence=" +
                std::to_string(event.event_sequence) +
                " error=" + queue_error);
            break;
        }

        received.erase(expected);
        g_local_transport.local_hit_feedback_ack_sequence =
            expected_sequence;
        UpsertPeerEndpoint(
            from,
            event.authority_participant_id,
            now_ms);
        expected_sequence =
            NextParticipantHitFeedbackSequence(expected_sequence);
    }
}

bool TryDispatchParticipantHitFeedbackPacket(
    PacketKind kind,
    const void* data,
    int received,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (kind != PacketKind::ParticipantHitFeedback) {
        return false;
    }
    if (data == nullptr ||
        received !=
            static_cast<int>(sizeof(ParticipantHitFeedbackPacket))) {
        return true;
    }

    ParticipantHitFeedbackPacket packet{};
    std::memcpy(&packet, data, sizeof(packet));
    if (!IsValidHeader(
            packet.header,
            PacketKind::ParticipantHitFeedback)) {
        return true;
    }
    g_local_transport.packets_received += 1;
    ApplyParticipantHitFeedbackPacket(packet, from, now_ms);
    return true;
}
