// Host barrier timeout, auto-pick, and periodic broadcast authority.

bool ShouldSuppressLocalLevelUpFanout() {
    return g_local_transport.suppress_local_level_up_fanout;
}

#include "level_up_choice_and_picker.inl"

bool TryAutoPickHostLevelUpBarrierParticipant(
    std::uint64_t participant_id,
    std::uint64_t now_ms) {
    auto* barrier_participant =
        FindHostLevelUpBarrierParticipant(participant_id);
    if (barrier_participant == nullptr || barrier_participant->resolved ||
        barrier_participant->disconnected ||
        barrier_participant->offer_id == 0) {
        return false;
    }

    const auto offer_it =
        g_local_transport.issued_level_up_offers_by_id.find(
            barrier_participant->offer_id);
    if (offer_it == g_local_transport.issued_level_up_offers_by_id.end() ||
        offer_it->second.resolved || offer_it->second.options.empty()) {
        return false;
    }

    auto& offer = offer_it->second;
    auto send_remote_auto_pick_result = [&]() {
        if (participant_id == g_local_transport.local_peer_id ||
            !barrier_participant->auto_picked ||
            barrier_participant->option_index <= 0 ||
            barrier_participant->option_id < 0 ||
            barrier_participant->apply_count <= 0) {
            return false;
        }
        if (barrier_participant->last_auto_pick_result_ms != 0 &&
            now_ms - barrier_participant->last_auto_pick_result_ms <
                kHostLevelUpBarrierBroadcastIntervalMs) {
            return true;
        }

        BotSkillChoiceOption selected_option;
        selected_option.option_id = barrier_participant->option_id;
        selected_option.apply_count = barrier_participant->apply_count;
        const auto result = BuildLevelUpChoiceResultPacket(
            offer.offer_id,
            participant_id,
            offer.run_nonce,
            offer.level,
            offer.experience,
            barrier_participant->option_index,
            selected_option,
            LevelUpChoiceResultCode::Accepted,
            barrier_participant->resulting_active,
            true);
        SendPacketToParticipantOrPeers(result, participant_id);
        SendPacketToParticipantOrPeers(result, participant_id);
        barrier_participant->last_auto_pick_result_ms = now_ms;
        return true;
    };

    if (offer.auto_picked) {
        return send_remote_auto_pick_result();
    }

    for (std::size_t index = 0; index < offer.options.size(); ++index) {
        const auto& option = offer.options[index];
        const auto option_index = static_cast<std::int32_t>(index + 1);
        if (participant_id == g_local_transport.local_peer_id) {
            LevelUpChoiceOptionState selected_option;
            selected_option.option_id = option.option_id;
            selected_option.apply_count = option.apply_count;
            std::string error_message;
            if (ResolveHostSelfLevelUpChoice(
                    offer.offer_id,
                    option_index,
                    selected_option,
                    &error_message,
                    true)) {
                return true;
            }
            Log(
                "Multiplayer level-up timeout auto-pick host option failed. "
                "barrier_id=" +
                std::to_string(
                    g_local_transport.host_level_up_barrier.barrier_id) +
                " offer_id=" + std::to_string(offer.offer_id) +
                " option_id=" + std::to_string(option.option_id) +
                " error=" + error_message);
            continue;
        }

        std::string error_message;
        if (!ApplyParticipantSkillChoiceOption(
                participant_id,
                option,
                &error_message)) {
            Log(
                "Multiplayer level-up timeout auto-pick remote option failed. "
                "barrier_id=" +
                std::to_string(
                    g_local_transport.host_level_up_barrier.barrier_id) +
                " participant_id=" + std::to_string(participant_id) +
                " offer_id=" + std::to_string(offer.offer_id) +
                " option_id=" + std::to_string(option.option_id) +
                " error=" + error_message);
            continue;
        }

        offer.auto_picked = true;
        offer.result_code = LevelUpChoiceResultCode::Accepted;
        g_local_transport.pending_level_up_offer_targets_by_participant.erase(
            participant_id);
        std::uint16_t resulting_active = 0;
        (void)TryReadParticipantProgressionEntryActive(
            participant_id,
            option.option_id,
            &resulting_active);
        barrier_participant->option_index = option_index;
        barrier_participant->option_id = option.option_id;
        barrier_participant->apply_count = option.apply_count;
        barrier_participant->resulting_active = resulting_active;
        barrier_participant->auto_picked = true;
        AdvanceHostLevelUpBarrierRevision();
        BroadcastHostLevelUpBarrierState(now_ms, true);
        (void)send_remote_auto_pick_result();
        Log(
            "Multiplayer level-up timeout forced remote option; waiting for native picker confirmation. "
            "barrier_id=" +
            std::to_string(
                g_local_transport.host_level_up_barrier.barrier_id) +
            " participant_id=" + std::to_string(participant_id) +
            " offer_id=" + std::to_string(offer.offer_id) +
            " option_index=" + std::to_string(option_index) +
            " option_id=" + std::to_string(option.option_id));
        return true;
    }
    return false;
}

void ProcessHostLevelUpBarrier(std::uint64_t now_ms) {
    if (!IsLocalTransportHost() ||
        !g_local_transport.host_level_up_barrier.active) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    std::vector<std::uint64_t> missing_offer_participant_ids;
    std::vector<std::uint64_t> disconnected_participant_ids;
    for (auto& participant :
         g_local_transport.host_level_up_barrier.participants) {
        if (participant.resolved || participant.disconnected) {
            continue;
        }
        if (participant.participant_id != g_local_transport.local_peer_id) {
            const auto* runtime_participant =
                FindParticipant(runtime_state, participant.participant_id);
            if (runtime_participant == nullptr ||
                !runtime_participant->transport_connected) {
                disconnected_participant_ids.push_back(
                    participant.participant_id);
                continue;
            }
        }
        if (participant.offer_id == 0 &&
            (participant.last_offer_attempt_ms == 0 ||
             now_ms - participant.last_offer_attempt_ms >= 250)) {
            participant.last_offer_attempt_ms = now_ms;
            missing_offer_participant_ids.push_back(
                participant.participant_id);
        }
    }

    for (const auto participant_id : disconnected_participant_ids) {
        MarkHostLevelUpBarrierParticipantDisconnected(participant_id, now_ms);
    }
    if (!g_local_transport.host_level_up_barrier.active) {
        return;
    }

    for (const auto participant_id : missing_offer_participant_ids) {
        if (participant_id == g_local_transport.local_peer_id) {
            PublishLocalHostSelfLevelUpOffer(
                g_local_transport.host_level_up_barrier.level,
                g_local_transport.host_level_up_barrier.experience,
                g_local_transport.host_level_up_barrier
                    .source_progression_address);
            continue;
        }
        const auto* participant = FindParticipant(runtime_state, participant_id);
        if (participant == nullptr) {
            continue;
        }
        const auto result = TryPublishHostLevelUpOfferForParticipant(
            *participant,
            g_local_transport.host_level_up_barrier.run_nonce,
            g_local_transport.host_level_up_barrier.level,
            g_local_transport.host_level_up_barrier.experience,
            g_local_transport.host_level_up_barrier
                .source_progression_address,
            true,
            now_ms);
        if (result == HostLevelUpOfferPublishResult::Sent ||
            result == HostLevelUpOfferPublishResult::AlreadyIssued) {
            g_local_transport.pending_level_up_offer_targets_by_participant.erase(
                participant_id);
        }
    }

    auto& barrier = g_local_transport.host_level_up_barrier;
    if (!barrier.active || now_ms < barrier.deadline_ms) {
        return;
    }
    if (!barrier.timed_out) {
        barrier.timed_out = true;
        AdvanceHostLevelUpBarrierRevision();
        BroadcastHostLevelUpBarrierState(now_ms, true);
        Log(
            "Multiplayer level-up barrier timed out; auto-picking unresolved choices. "
            "barrier_id=" + std::to_string(barrier.barrier_id));
    }

    const auto unresolved_participant_ids =
        CollectHostLevelUpBarrierWaitingParticipantIds();
    for (const auto participant_id : unresolved_participant_ids) {
        (void)TryAutoPickHostLevelUpBarrierParticipant(
            participant_id,
            now_ms);
    }
}
