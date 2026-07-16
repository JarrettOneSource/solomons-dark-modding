// Host-authoritative offer issuance, native picker presentation, and choice resolution.

enum class HostLevelUpOfferPublishResult {
    Sent,
    AlreadyIssued,
    PendingMaterialization,
    Failed,
};

class ScopedLocalLevelUpFanoutSuppression final {
public:
    ScopedLocalLevelUpFanoutSuppression()
        : previous_(g_local_transport.suppress_local_level_up_fanout) {
        g_local_transport.suppress_local_level_up_fanout = true;
    }

    ~ScopedLocalLevelUpFanoutSuppression() {
        g_local_transport.suppress_local_level_up_fanout = previous_;
    }

    ScopedLocalLevelUpFanoutSuppression(
        const ScopedLocalLevelUpFanoutSuppression&) = delete;
    ScopedLocalLevelUpFanoutSuppression& operator=(
        const ScopedLocalLevelUpFanoutSuppression&) = delete;

private:
    bool previous_ = false;
};

bool IsLevelUpOfferMaterializationPendingError(const std::string& error_message) {
    return error_message.find("materialized progression") != std::string::npos;
}

void QueuePendingHostLevelUpOfferTarget(
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address,
    std::uint64_t now_ms,
    const std::string& reason) {
    if (target_participant_id == 0 || HasUnresolvedIssuedLevelUpOfferForParticipant(target_participant_id)) {
        return;
    }

    auto [it, inserted] =
        g_local_transport.pending_level_up_offer_targets_by_participant.try_emplace(target_participant_id);
    auto& pending = it->second;
    pending.target_participant_id = target_participant_id;
    pending.run_nonce = run_nonce;
    pending.level = level;
    pending.experience = experience;
    pending.source_progression_address = source_progression_address;
    if (inserted || pending.requested_ms == 0) {
        pending.requested_ms = now_ms;
    }

    if (inserted || now_ms - pending.last_log_ms >= 1000) {
        pending.last_log_ms = now_ms;
        Log(
            "Multiplayer level-up offer deferred; participant progression not materialized. participant_id=" +
            std::to_string(target_participant_id) +
            " run_nonce=" + std::to_string(run_nonce) +
            " level=" + std::to_string(level) +
            " xp=" + std::to_string(experience) +
            " reason=" + reason);
    }
}

bool IssueHostLevelUpOfferForParticipant(
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    std::vector<BotSkillChoiceOption> options,
    bool suppress_native_picker = false) {
    if (target_participant_id == 0 || options.empty()) {
        return false;
    }
    if (HasUnresolvedIssuedLevelUpOfferForParticipant(target_participant_id)) {
        Log(
            "Multiplayer duplicate level-up offer issuance suppressed. participant_id=" +
            std::to_string(target_participant_id));
        return false;
    }
    if (options.size() > kLevelUpOfferMaxOptions) {
        options.resize(kLevelUpOfferMaxOptions);
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!BeginOrExtendHostLevelUpBarrier(
            {target_participant_id},
            run_nonce,
            level,
            experience,
            0,
            now_ms)) {
        return false;
    }

    const auto offer_id = g_local_transport.next_level_up_offer_id++;
    if (g_local_transport.next_level_up_offer_id == 0) {
        g_local_transport.next_level_up_offer_id = 1;
    }

    IssuedLevelUpOffer issued_offer;
    issued_offer.offer_id = offer_id;
    issued_offer.target_participant_id = target_participant_id;
    issued_offer.run_nonce = run_nonce;
    issued_offer.level = level;
    issued_offer.experience = experience;
    issued_offer.options = options;
    issued_offer.barrier_id =
        g_local_transport.host_level_up_barrier.barrier_id;
    issued_offer.issued_ms = now_ms;
    g_local_transport.issued_level_up_offers_by_id[offer_id] = issued_offer;
    AttachHostLevelUpOfferToBarrier(
        target_participant_id,
        offer_id,
        now_ms);

    LevelUpOfferPacket packet{};
    packet.header = MakePacketHeader(PacketKind::LevelUpOffer, g_local_transport.next_sequence++);
    packet.authority_participant_id = g_local_transport.local_peer_id;
    packet.target_participant_id = target_participant_id;
    packet.offer_id = offer_id;
    packet.run_nonce = run_nonce;
    packet.level = level;
    packet.experience = experience;
    packet.option_count = static_cast<std::uint8_t>(options.size());
    packet.flags = suppress_native_picker
        ? LevelUpOfferFlagSuppressNativePicker
        : 0;
    for (std::size_t index = 0; index < options.size(); ++index) {
        packet.options[index].option_id = options[index].option_id;
        packet.options[index].apply_count = options[index].apply_count;
    }

    SendPacketToParticipantOrPeers(packet, target_participant_id);
    Log(
        "Multiplayer level-up offer sent. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " target_participant_id=" + std::to_string(packet.target_participant_id) +
        " offer_id=" + std::to_string(packet.offer_id) +
        " run_nonce=" + std::to_string(packet.run_nonce) +
        " level=" + std::to_string(packet.level) +
        " xp=" + std::to_string(packet.experience) +
        " option_count=" + std::to_string(packet.option_count));
    return true;
}

HostLevelUpOfferPublishResult TryPublishHostLevelUpOfferForParticipant(
    const ParticipantInfo& participant,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address,
    bool queue_on_pending_materialization,
    std::uint64_t now_ms) {
    if (HasUnresolvedIssuedLevelUpOfferForParticipant(participant.participant_id)) {
        return HostLevelUpOfferPublishResult::AlreadyIssued;
    }
    if (participant.runtime.valid &&
        participant.runtime.in_run &&
        run_nonce != 0 &&
        participant.runtime.run_nonce != 0 &&
        participant.runtime.run_nonce != run_nonce) {
        Log(
            "Multiplayer level-up offer skipped; participant run nonce mismatch. participant_id=" +
            std::to_string(participant.participant_id) +
            " host_run_nonce=" + std::to_string(run_nonce) +
            " participant_run_nonce=" + std::to_string(participant.runtime.run_nonce));
        return HostLevelUpOfferPublishResult::Failed;
    }

    std::vector<BotSkillChoiceOption> options;
    std::string error_message;
    bool synchronized = false;
    {
        ScopedLocalLevelUpFanoutSuppression suppress_fanout;
        synchronized = SyncParticipantProgressionToSharedLevelUpAndRollChoices(
            participant.participant_id,
            level,
            experience,
            source_progression_address,
            &options,
            &error_message);
    }
    if (!synchronized) {
        if (IsLevelUpOfferMaterializationPendingError(error_message)) {
            if (queue_on_pending_materialization) {
                QueuePendingHostLevelUpOfferTarget(
                    participant.participant_id,
                    run_nonce,
                    level,
                    experience,
                    source_progression_address,
                    now_ms,
                    error_message);
            }
            return HostLevelUpOfferPublishResult::PendingMaterialization;
        }
        Log(
            "Multiplayer level-up offer skipped; participant roll failed. participant_id=" +
            std::to_string(participant.participant_id) +
            " level=" + std::to_string(level) +
            " xp=" + std::to_string(experience) +
            " error=" + error_message);
        return HostLevelUpOfferPublishResult::Failed;
    }

    if (options.empty()) {
        Log(
            "Multiplayer level-up offer skipped; participant roll returned no options. participant_id=" +
            std::to_string(participant.participant_id));
        return HostLevelUpOfferPublishResult::Failed;
    }

    if (HasUnresolvedIssuedLevelUpOfferForParticipant(participant.participant_id)) {
        return HostLevelUpOfferPublishResult::AlreadyIssued;
    }

    if (!IssueHostLevelUpOfferForParticipant(
        participant.participant_id,
        run_nonce,
        level,
        experience,
        std::move(options))) {
        return HasUnresolvedIssuedLevelUpOfferForParticipant(participant.participant_id)
            ? HostLevelUpOfferPublishResult::AlreadyIssued
            : HostLevelUpOfferPublishResult::Failed;
    }
    return HostLevelUpOfferPublishResult::Sent;
}

void ProcessPendingHostLevelUpOffers(std::uint64_t now_ms) {
    if (!IsLocalTransportHost() ||
        g_local_transport.pending_level_up_offer_targets_by_participant.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    for (auto it = g_local_transport.pending_level_up_offer_targets_by_participant.begin();
         it != g_local_transport.pending_level_up_offer_targets_by_participant.end();) {
        auto pending = it->second;
        const auto* participant = FindParticipant(runtime_state, pending.target_participant_id);
        if (participant == nullptr ||
            !IsRemoteParticipant(*participant) ||
            !IsNativeControlledParticipant(*participant) ||
            !participant->transport_connected) {
            Log(
                "Multiplayer pending level-up offer dropped; target participant unavailable. participant_id=" +
                std::to_string(pending.target_participant_id));
            MarkHostLevelUpBarrierParticipantDisconnected(
                pending.target_participant_id,
                now_ms);
            it = g_local_transport.pending_level_up_offer_targets_by_participant.erase(it);
            continue;
        }

        const auto result = TryPublishHostLevelUpOfferForParticipant(
            *participant,
            pending.run_nonce,
            pending.level,
            pending.experience,
            pending.source_progression_address,
            false,
            now_ms);
        if (result == HostLevelUpOfferPublishResult::Sent ||
            result == HostLevelUpOfferPublishResult::AlreadyIssued ||
            result == HostLevelUpOfferPublishResult::Failed) {
            it = g_local_transport.pending_level_up_offer_targets_by_participant.erase(it);
            continue;
        }

        auto live_pending =
            g_local_transport.pending_level_up_offer_targets_by_participant.find(
                pending.target_participant_id);
        if (live_pending != g_local_transport.pending_level_up_offer_targets_by_participant.end() &&
            now_ms - live_pending->second.last_log_ms >= 1000) {
            live_pending->second.last_log_ms = now_ms;
            Log(
                "Multiplayer pending level-up offer waiting for participant progression. participant_id=" +
                std::to_string(live_pending->second.target_participant_id) +
                " run_nonce=" + std::to_string(live_pending->second.run_nonce) +
                " level=" + std::to_string(live_pending->second.level) +
                " xp=" + std::to_string(live_pending->second.experience));
        }
        ++it;
    }
}

void PublishHostLevelUpOffers(
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address) {
    if (!IsLocalTransportHost() ||
        g_local_transport.suppress_local_level_up_fanout ||
        level <= 0 ||
        experience < 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::vector<std::uint64_t> remote_participant_ids;
    for (const auto& participant : runtime_state.participants) {
        if (IsRemoteParticipant(participant) &&
            IsNativeControlledParticipant(participant) &&
            participant.transport_connected) {
            remote_participant_ids.push_back(participant.participant_id);
        }
    }
    if (!remote_participant_ids.empty() &&
        !BeginOrExtendHostLevelUpBarrier(
            remote_participant_ids,
            run_nonce,
            level,
            experience,
            source_progression_address,
            now_ms)) {
        return;
    }

    for (const auto& participant : runtime_state.participants) {
        if (!IsRemoteParticipant(participant) ||
            !IsNativeControlledParticipant(participant) ||
            !participant.transport_connected) {
            continue;
        }
        const auto result = TryPublishHostLevelUpOfferForParticipant(
            participant,
            run_nonce,
            level,
            experience,
            source_progression_address,
            true,
            now_ms);
        if (result == HostLevelUpOfferPublishResult::Sent ||
            result == HostLevelUpOfferPublishResult::AlreadyIssued ||
            result == HostLevelUpOfferPublishResult::Failed) {
            g_local_transport.pending_level_up_offer_targets_by_participant.erase(
                participant.participant_id);
        }
    }

    if (g_local_transport.issued_level_up_offers_by_id.size() > 64) {
        for (auto it = g_local_transport.issued_level_up_offers_by_id.begin();
             it != g_local_transport.issued_level_up_offers_by_id.end();) {
            if (it->second.resolved) {
                it = g_local_transport.issued_level_up_offers_by_id.erase(it);
            } else {
                ++it;
            }
        }
    }
}

bool IssueLocalHostSelfLevelUpOffer(
    std::int32_t level,
    std::int32_t experience,
    std::vector<BotSkillChoiceOption> options,
    bool suppress_native_picker,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (!IsLocalTransportHost()) {
        return fail("host-self level-up offer requires the local transport host");
    }
    if (level <= 0 || experience < 0) {
        return fail("host-self level-up offer requires valid progression values");
    }
    const auto local_peer_id = g_local_transport.local_peer_id;
    if (local_peer_id == 0) {
        return fail("host-self level-up offer requires a local participant id");
    }
    if (HasUnresolvedIssuedLevelUpOfferForParticipant(local_peer_id)) {
        return fail("host-self participant already has an unresolved level-up offer");
    }
    if (options.empty()) {
        return fail("host-self level-up offer requires at least one option");
    }
    if (options.size() > kLevelUpOfferMaxOptions) {
        options.resize(kLevelUpOfferMaxOptions);
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!BeginOrExtendHostLevelUpBarrier(
            {local_peer_id},
            run_nonce,
            level,
            experience,
            0,
            now_ms)) {
        return fail("host-self level-up barrier could not be started");
    }

    const auto offer_id = g_local_transport.next_level_up_offer_id++;
    if (g_local_transport.next_level_up_offer_id == 0) {
        g_local_transport.next_level_up_offer_id = 1;
    }

    IssuedLevelUpOffer issued_offer;
    issued_offer.offer_id = offer_id;
    issued_offer.target_participant_id = local_peer_id;
    issued_offer.run_nonce = run_nonce;
    issued_offer.level = level;
    issued_offer.experience = experience;
    issued_offer.options = options;
    issued_offer.barrier_id =
        g_local_transport.host_level_up_barrier.barrier_id;
    issued_offer.issued_ms = now_ms;
    g_local_transport.issued_level_up_offers_by_id[offer_id] = issued_offer;
    AttachHostLevelUpOfferToBarrier(local_peer_id, offer_id, now_ms);

    std::vector<LevelUpChoiceOptionState> offer_options;
    offer_options.reserve(options.size());
    for (const auto& option : options) {
        LevelUpChoiceOptionState option_state;
        option_state.option_id = option.option_id;
        option_state.apply_count = option.apply_count;
        offer_options.push_back(option_state);
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        LevelUpOfferRuntimeInfo offer;
        offer.valid = true;
        offer.selection_submitted = false;
        offer.suppress_native_picker = suppress_native_picker;
        offer.authority_participant_id = local_peer_id;
        offer.target_participant_id = local_peer_id;
        offer.offer_id = offer_id;
        offer.run_nonce = run_nonce;
        offer.received_ms = now_ms;
        offer.level = level;
        offer.experience = experience;
        offer.options = std::move(offer_options);
        state.active_level_up_offer = std::move(offer);
    });

    Log(
        "Multiplayer host-self level-up offer issued. authority_participant_id=" +
        std::to_string(local_peer_id) +
        " offer_id=" + std::to_string(offer_id) +
        " run_nonce=" + std::to_string(run_nonce) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " option_count=" + std::to_string(options.size()));
    return true;
}

void PublishLocalHostSelfLevelUpOffer(
    std::int32_t level,
    std::int32_t experience,
    uintptr_t source_progression_address) {
    if (!IsLocalTransportHost() ||
        g_local_transport.suppress_local_level_up_fanout ||
        level <= 0 ||
        experience < 0) {
        return;
    }
    const auto local_peer_id = g_local_transport.local_peer_id;
    if (local_peer_id == 0 ||
        HasUnresolvedIssuedLevelUpOfferForParticipant(local_peer_id)) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (!BeginOrExtendHostLevelUpBarrier(
            {local_peer_id},
            run_nonce,
            level,
            experience,
            source_progression_address,
            now_ms)) {
        return;
    }

    // The host is its own level-up authority. Mirror the client offer/choice
    // flow for the host's own level-up so selection is routed through the
    // loader's controlled, non-modal picker path instead of the native modal
    // picker that monopolizes the gameplay thread.
    std::vector<BotSkillChoiceOption> options;
    std::string error_message;
    bool synchronized = false;
    {
        ScopedLocalLevelUpFanoutSuppression suppress_fanout;
        synchronized = SyncLocalPlayerProgressionToSharedLevelUpAndRollChoices(
            level,
            experience,
            &options,
            &error_message);
    }
    if (!synchronized) {
        Log(
            "Multiplayer host-self level-up offer skipped; local roll failed. level=" +
            std::to_string(level) +
            " xp=" + std::to_string(experience) +
            " error=" + error_message);
        return;
    }
    if (!IssueLocalHostSelfLevelUpOffer(
            level,
            experience,
            std::move(options),
            false,
            &error_message)) {
        Log(
            "Multiplayer host-self level-up offer skipped; issue failed. level=" +
            std::to_string(level) +
            " xp=" + std::to_string(experience) +
            " error=" + error_message);
    }
}
