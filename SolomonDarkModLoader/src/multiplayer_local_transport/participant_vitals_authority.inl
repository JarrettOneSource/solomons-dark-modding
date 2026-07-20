constexpr std::uint64_t kParticipantVitalsCorrectionResendMs = 100;
constexpr std::uint64_t kParticipantVitalsCorrectionSendIntervalMs = 50;
constexpr float kParticipantVitalsCorrectionEpsilon = 0.05f;

void QueueHostParticipantVitalsCorrectionInternal(
    std::uint64_t target_participant_id,
    float life_current,
    float life_max,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick) {
    if (!g_local_transport.initialized ||
        !g_local_transport.is_host ||
        target_participant_id == 0 ||
        target_participant_id == g_local_transport.local_peer_id ||
        !std::isfinite(life_current) ||
        !std::isfinite(life_max) ||
        life_max <= 0.0f) {
        return;
    }

    QueuedHostParticipantVitalsCorrection queued;
    queued.target_participant_id = target_participant_id;
    queued.life_current = (std::clamp)(life_current, 0.0f, life_max);
    queued.life_max = life_max;
    queued.transient_status_flags = static_cast<std::uint8_t>(
        transient_status_flags & ParticipantTransientStatusFlagPoisoned);
    queued.poison_remaining_ticks =
        (queued.transient_status_flags & ParticipantTransientStatusFlagPoisoned) != 0
            ? (std::clamp)(
                  poison_remaining_ticks,
                  std::int32_t{1},
                  kParticipantPoisonMaxDurationTicks)
            : 0;
    queued.poison_damage_per_tick =
        queued.poison_remaining_ticks > 0 &&
                std::isfinite(poison_damage_per_tick) &&
                poison_damage_per_tick >= 0.0f &&
                poison_damage_per_tick <= 10000.0f
            ? poison_damage_per_tick
            : 0.0f;

    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    g_queued_host_participant_vitals_corrections.push_back(queued);
}

std::vector<QueuedHostParticipantVitalsCorrection>
TakeQueuedHostParticipantVitalsCorrections() {
    std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
    std::vector<QueuedHostParticipantVitalsCorrection> queued;
    queued.swap(g_queued_host_participant_vitals_corrections);
    return queued;
}

void SendQueuedHostParticipantVitalsCorrections(std::uint64_t now_ms) {
    if (!g_local_transport.is_host) {
        (void)TakeQueuedHostParticipantVitalsCorrections();
        return;
    }

    const auto queued = TakeQueuedHostParticipantVitalsCorrections();
    std::unordered_map<std::uint64_t, QueuedHostParticipantVitalsCorrection>
        strongest_by_participant;
    for (const auto& correction : queued) {
        auto [it, inserted] = strongest_by_participant.emplace(
            correction.target_participant_id,
            correction);
        if (!inserted) {
            it->second.life_current =
                (std::min)(it->second.life_current, correction.life_current);
            const bool correction_poisoned =
                (correction.transient_status_flags &
                 ParticipantTransientStatusFlagPoisoned) != 0;
            if (correction_poisoned) {
                it->second.transient_status_flags |=
                    ParticipantTransientStatusFlagPoisoned;
                it->second.poison_remaining_ticks =
                    (std::max)(
                        it->second.poison_remaining_ticks,
                        correction.poison_remaining_ticks);
                it->second.poison_damage_per_tick =
                    (std::max)(
                        it->second.poison_damage_per_tick,
                        correction.poison_damage_per_tick);
            }
        }
    }
    for (const auto& [target_participant_id, correction] :
         strongest_by_participant) {
        (void)target_participant_id;
        const auto runtime_state = SnapshotRuntimeState();
        const auto* participant =
            FindParticipant(runtime_state, correction.target_participant_id);
        if (participant == nullptr ||
            !IsRemoteParticipant(*participant) ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            (participant->runtime.life_max > 0.0f &&
             std::fabs(participant->runtime.life_max - correction.life_max) >
                 (std::max)(1.0f, participant->runtime.life_max * 0.1f))) {
            continue;
        }

        auto pending_it =
            g_local_transport.pending_participant_vitals_corrections_by_participant.find(
                correction.target_participant_id);
        const bool poison_active =
            (correction.transient_status_flags &
             ParticipantTransientStatusFlagPoisoned) != 0;
        const bool have_stronger_correction =
            pending_it ==
                g_local_transport.pending_participant_vitals_corrections_by_participant.end() ||
            correction.life_current + kParticipantVitalsCorrectionEpsilon <
                pending_it->second.packet.life_current ||
            (poison_active &&
             (pending_it->second.packet.transient_status_flags &
              ParticipantTransientStatusFlagPoisoned) == 0);
        if (!have_stronger_correction) {
            continue;
        }

        PendingParticipantVitalsCorrection pending;
        pending.packet.header = MakePacketHeader(
            PacketKind::ParticipantVitalsCorrection,
            g_local_transport.next_sequence++);
        pending.packet.authority_participant_id = g_local_transport.local_peer_id;
        pending.packet.target_participant_id = correction.target_participant_id;
        pending.packet.correction_sequence =
            g_local_transport.next_participant_vitals_correction_sequence++;
        if (g_local_transport.next_participant_vitals_correction_sequence == 0) {
            g_local_transport.next_participant_vitals_correction_sequence = 1;
        }
        pending.packet.run_nonce = participant->runtime.run_nonce;
        pending.packet.life_current = correction.life_current;
        pending.packet.life_max = correction.life_max;
        pending.packet.transient_status_flags = static_cast<std::uint8_t>(
            ParticipantTransientStatusFlagSnapshotValid |
            correction.transient_status_flags);
        pending.packet.poison_remaining_ticks =
            correction.poison_remaining_ticks;
        pending.packet.poison_damage_per_tick =
            correction.poison_damage_per_tick;
        pending.last_sent_ms = 0;
        g_local_transport.pending_participant_vitals_corrections_by_participant[
            correction.target_participant_id] = pending;

        UpdateRuntimeState([&](RuntimeState& state) {
            auto* mutable_participant =
                FindParticipant(state, correction.target_participant_id);
            if (mutable_participant == nullptr) {
                return;
            }
            mutable_participant->runtime.life_current =
                (std::min)(
                    mutable_participant->runtime.life_current,
                    correction.life_current);
            if (poison_active) {
                mutable_participant->runtime.transient_status_flags =
                    pending.packet.transient_status_flags;
                mutable_participant->runtime.poison_remaining_ticks =
                    pending.packet.poison_remaining_ticks;
            }
        });

        Log(
            "Multiplayer host captured remote participant damage. target_participant_id=" +
            std::to_string(correction.target_participant_id) +
            " correction_sequence=" +
            std::to_string(pending.packet.correction_sequence) +
            " life=" + std::to_string(correction.life_current) + "/" +
            std::to_string(correction.life_max) +
            " transient_flags=" +
            std::to_string(pending.packet.transient_status_flags) +
            " poison_ticks=" +
            std::to_string(pending.packet.poison_remaining_ticks) +
            " poison_damage=" +
            std::to_string(pending.packet.poison_damage_per_tick));
    }

    for (auto& [participant_id, pending] :
         g_local_transport.pending_participant_vitals_corrections_by_participant) {
        const auto last_send_it =
            g_local_transport.last_participant_vitals_correction_send_ms_by_participant.find(
                participant_id);
        if (last_send_it !=
                g_local_transport.last_participant_vitals_correction_send_ms_by_participant.end() &&
            now_ms - last_send_it->second <
                kParticipantVitalsCorrectionSendIntervalMs) {
            continue;
        }
        if (pending.last_sent_ms != 0 &&
            now_ms - pending.last_sent_ms <
                kParticipantVitalsCorrectionResendMs) {
            continue;
        }
        pending.packet.header.sequence = g_local_transport.next_sequence++;
        SendPacketToParticipantOrPeers(pending.packet, participant_id);
        pending.last_sent_ms = now_ms;
        g_local_transport.last_participant_vitals_correction_send_ms_by_participant[
            participant_id] = now_ms;
    }
}

void ApplyParticipantVitalsCorrectionPacket(
    const ParticipantVitalsCorrectionPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    const auto allowed_transient_flags = static_cast<std::uint8_t>(
        kParticipantTransientStatusValueMask |
        ParticipantTransientStatusFlagSnapshotValid);
    const bool transient_snapshot_valid =
        (packet.transient_status_flags &
         ParticipantTransientStatusFlagSnapshotValid) != 0;
    const bool poison_active =
        (packet.transient_status_flags &
         ParticipantTransientStatusFlagPoisoned) != 0;
    const bool poison_payload_valid = poison_active
        ? packet.poison_remaining_ticks > 0 &&
              packet.poison_remaining_ticks <=
                  kParticipantPoisonMaxDurationTicks &&
              std::isfinite(packet.poison_damage_per_tick) &&
              packet.poison_damage_per_tick >= 0.0f &&
              packet.poison_damage_per_tick <= 10000.0f
        : packet.poison_remaining_ticks == 0 &&
              packet.poison_damage_per_tick == 0.0f;
    if (!IsLocalTransportClient() ||
        !IsConfiguredRemoteAuthorityEndpoint(from) ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.target_participant_id != g_local_transport.local_peer_id ||
        packet.correction_sequence == 0 ||
        !std::isfinite(packet.life_current) ||
        !std::isfinite(packet.life_max) ||
        packet.life_max <= 0.0f ||
        packet.life_current < 0.0f ||
        packet.life_current > packet.life_max ||
        !transient_snapshot_valid ||
        (packet.transient_status_flags & ~allowed_transient_flags) != 0 ||
        !poison_payload_valid) {
        return;
    }

    const auto last_it =
        g_local_transport.last_participant_vitals_correction_sequence_by_authority.find(
            packet.authority_participant_id);
    if (last_it !=
            g_local_transport.last_participant_vitals_correction_sequence_by_authority.end() &&
        !IsPacketSequenceNewer(packet.correction_sequence, last_it->second)) {
        return;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        !std::isfinite(player_state.hp) ||
        !std::isfinite(player_state.max_hp) ||
        player_state.max_hp <= 0.0f ||
        std::fabs(player_state.max_hp - packet.life_max) >
            (std::max)(1.0f, player_state.max_hp * 0.1f)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr ||
        (packet.run_nonce != 0 &&
         local->runtime.run_nonce != 0 &&
         packet.run_nonce != local->runtime.run_nonce)) {
        return;
    }

    const float corrected_life =
        (std::min)(player_state.hp, packet.life_current);
    const bool wrote = TryWriteLocalPlayerOrbResource(
        static_cast<std::int32_t>(LootOrbResourceKind::Health),
        corrected_life,
        player_state.max_hp,
        player_state.mp,
        player_state.max_mp);
    if (!wrote) {
        return;
    }

    if (poison_active) {
        std::string poison_error;
        if (!QueueLocalPlayerPoisonCorrection(
                packet.correction_sequence,
                packet.poison_remaining_ticks,
                packet.poison_damage_per_tick,
                &poison_error)) {
            Log(
                "Multiplayer participant poison correction queue failed. "
                "authority_participant_id=" +
                std::to_string(packet.authority_participant_id) +
                " target_participant_id=" +
                std::to_string(packet.target_participant_id) +
                " correction_sequence=" +
                std::to_string(packet.correction_sequence) +
                " error=" + poison_error);
            return;
        }
    }

    g_local_transport.last_participant_vitals_correction_sequence_by_authority[
        packet.authority_participant_id] = packet.correction_sequence;
    if (!poison_active) {
        g_local_transport.last_applied_participant_vitals_correction_sequence =
            packet.correction_sequence;
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* mutable_local = FindLocalParticipant(state);
        if (mutable_local == nullptr) {
            return;
        }
        mutable_local->runtime.life_current = corrected_life;
        mutable_local->runtime.life_max = player_state.max_hp;
        if (poison_active) {
            mutable_local->runtime.transient_status_flags =
                packet.transient_status_flags;
            mutable_local->runtime.poison_remaining_ticks =
                packet.poison_remaining_ticks;
        }
    });
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    Log(
        "Multiplayer participant damage correction applied. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " target_participant_id=" +
        std::to_string(packet.target_participant_id) +
        " correction_sequence=" +
        std::to_string(packet.correction_sequence) +
        " life=" + std::to_string(corrected_life) + "/" +
        std::to_string(player_state.max_hp) +
        " transient_flags=" +
        std::to_string(packet.transient_status_flags) +
        " poison_ticks=" +
        std::to_string(packet.poison_remaining_ticks) +
        " poison_damage=" +
        std::to_string(packet.poison_damage_per_tick));
}
