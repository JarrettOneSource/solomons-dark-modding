// Host-authoritative offer issuance, native picker presentation, and choice resolution.

enum class HostLevelUpOfferPublishResult {
    Sent,
    AlreadyIssued,
    PendingMaterialization,
    Failed,
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

void IssueHostLevelUpOfferForParticipant(
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    std::vector<BotSkillChoiceOption> options,
    bool suppress_native_picker = false) {
    if (target_participant_id == 0 || options.empty()) {
        return;
    }
    if (options.size() > kLevelUpOfferMaxOptions) {
        options.resize(kLevelUpOfferMaxOptions);
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
    g_local_transport.issued_level_up_offers_by_id[offer_id] = issued_offer;

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
    if (!SyncParticipantProgressionToSharedLevelUpAndRollChoices(
            participant.participant_id,
            level,
            experience,
            source_progression_address,
            &options,
            &error_message)) {
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

    IssueHostLevelUpOfferForParticipant(
        participant.participant_id,
        run_nonce,
        level,
        experience,
        std::move(options));
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
        g_local_transport.suppress_local_level_up_fanout_for_debug ||
        level <= 0 ||
        experience < 0) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());

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
    g_local_transport.issued_level_up_offers_by_id[offer_id] = issued_offer;

    std::vector<LevelUpChoiceOptionState> offer_options;
    offer_options.reserve(options.size());
    for (const auto& option : options) {
        LevelUpChoiceOptionState option_state;
        option_state.option_id = option.option_id;
        option_state.apply_count = option.apply_count;
        offer_options.push_back(option_state);
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
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
    (void)source_progression_address;
    if (!IsLocalTransportHost() ||
        g_local_transport.suppress_local_level_up_fanout_for_debug ||
        level <= 0 ||
        experience < 0) {
        return;
    }
    const auto local_peer_id = g_local_transport.local_peer_id;
    if (local_peer_id == 0 ||
        HasUnresolvedIssuedLevelUpOfferForParticipant(local_peer_id)) {
        return;
    }

    // The host is its own level-up authority. Mirror the client offer/choice
    // flow for the host's own level-up so selection is routed through the
    // loader's controlled, non-modal picker path instead of the native modal
    // picker that monopolizes the gameplay thread.
    std::vector<BotSkillChoiceOption> options;
    std::string error_message;
    if (!SyncLocalPlayerProgressionToSharedLevelUpAndRollChoices(
            level,
            experience,
            &options,
            &error_message)) {
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

bool DebugPublishHostLevelUpOffer(
    std::uint64_t target_participant_id,
    std::int32_t level,
    std::int32_t experience,
    std::int32_t option_id,
    std::int32_t apply_count,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (!IsLocalTransportHost()) {
        return fail("deterministic level-up offer requires the local transport host");
    }
    if (target_participant_id == 0) {
        return fail("deterministic level-up offer requires a target participant id");
    }
    if (level <= 0 || experience < 0) {
        return fail("deterministic level-up offer requires valid progression values");
    }
    if (option_id < 0 || apply_count <= 0 || apply_count > 2) {
        return fail("deterministic level-up offer requires a valid option and apply_count 1..2");
    }
    if (HasUnresolvedIssuedLevelUpOfferForParticipant(target_participant_id)) {
        return fail("target participant already has an unresolved level-up offer");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const bool target_self = target_participant_id == g_local_transport.local_peer_id;
    const auto* participant = target_self
        ? FindLocalParticipant(runtime_state)
        : FindParticipant(runtime_state, target_participant_id);
    if (participant == nullptr) {
        return fail("deterministic level-up offer target participant is unavailable");
    }
    if (!participant->transport_connected) {
        return fail("deterministic level-up offer target transport is disconnected");
    }
    if (!participant->owned_progression.initialized) {
        return fail("deterministic level-up offer target progression is uninitialized");
    }
    if (participant->owned_progression.progression_book_truncated) {
        return fail("deterministic level-up offer target progression book is truncated");
    }
    if (!target_self &&
        (!IsRemoteParticipant(*participant) ||
         !IsNativeControlledParticipant(*participant))) {
        return fail("deterministic level-up offer target is not a native remote participant");
    }

    const auto* entry = FindProgressionBookEntryById(
        participant->owned_progression,
        option_id);
    if (entry == nullptr) {
        return fail("deterministic level-up offer option is outside the native progression book");
    }
    if (entry->statbook_max_level > 0 &&
        static_cast<std::int32_t>(entry->active) + apply_count >
            entry->statbook_max_level) {
        return fail("deterministic level-up offer option would exceed its native max level");
    }

    std::string sync_error;
    if (target_self) {
        const bool previous_suppression =
            g_local_transport.suppress_local_level_up_fanout_for_debug;
        g_local_transport.suppress_local_level_up_fanout_for_debug = true;
        const bool synchronized = SyncLocalPlayerProgressionToSharedLevelUp(
                level,
                experience,
                &sync_error);
        g_local_transport.suppress_local_level_up_fanout_for_debug =
            previous_suppression;
        if (!synchronized) {
            return fail("deterministic host-self progression sync failed: " + sync_error);
        }
    } else if (!SyncParticipantProgressionToSharedLevelUp(
                   target_participant_id,
                   level,
                   experience,
                   0,
                   &sync_error)) {
        return fail("deterministic remote progression sync failed: " + sync_error);
    }

    BotSkillChoiceOption option;
    option.option_id = option_id;
    option.apply_count = apply_count;
    std::vector<BotSkillChoiceOption> options = {option};
    if (target_self) {
        return IssueLocalHostSelfLevelUpOffer(
            level,
            experience,
            std::move(options),
            true,
            error_message);
    }

    const auto* local = FindLocalParticipant(runtime_state);
    const std::uint32_t run_nonce =
        local != nullptr && local->runtime.valid ? local->runtime.run_nonce : 0;
    IssueHostLevelUpOfferForParticipant(
        target_participant_id,
        run_nonce,
        level,
        experience,
        std::move(options),
        true);
    Log(
        "Multiplayer deterministic level-up offer issued. target_participant_id=" +
        std::to_string(target_participant_id) +
        " level=" + std::to_string(level) +
        " xp=" + std::to_string(experience) +
        " option_id=" + std::to_string(option_id) +
        " apply_count=" + std::to_string(apply_count));
    return true;
}

bool ShouldSuppressLocalLevelUpFanoutForDebug() {
    return g_local_transport.suppress_local_level_up_fanout_for_debug;
}

bool CallLevelUpScreenCloseSafe(uintptr_t screen_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (screen_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable_address = 0;
    uintptr_t close_address = 0;
    if (!memory.TryReadValue(screen_address, &vtable_address) ||
        vtable_address == 0 ||
        !memory.TryReadValue(vtable_address + kLevelUpScreenCloseVtableOffset, &close_address) ||
        close_address == 0) {
        return false;
    }

    auto* close_screen = reinterpret_cast<NativeLevelUpScreenCloseFn>(close_address);
    __try {
        close_screen(reinterpret_cast<void*>(screen_address));
        return true;
    } __except (CaptureLocalTransportSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

#include "level_up_choice_and_picker.inl"
