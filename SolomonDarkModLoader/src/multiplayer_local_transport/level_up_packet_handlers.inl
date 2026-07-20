void ApplyLevelUpOfferPacket(
    const LevelUpOfferPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.target_participant_id != g_local_transport.local_peer_id ||
        packet.offer_id == 0 ||
        packet.level <= 0 ||
        packet.experience < 0 ||
        packet.option_count == 0 ||
        packet.option_count > kLevelUpOfferMaxOptions ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }

    std::lock_guard<std::recursive_mutex> picker_lock(
        g_local_level_up_picker_mutex);
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);

    std::vector<LevelUpChoiceOptionState> options;
    options.reserve(packet.option_count);
    for (std::size_t index = 0; index < packet.option_count; ++index) {
        const auto& packet_option = packet.options[index];
        if (packet_option.option_id < 0 || packet_option.apply_count <= 0) {
            continue;
        }
        LevelUpChoiceOptionState option;
        option.option_id = packet_option.option_id;
        option.apply_count = packet_option.apply_count;
        options.push_back(option);
    }
    if (options.empty()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr &&
        local->runtime.run_nonce != 0 &&
        packet.run_nonce != 0 &&
        local->runtime.run_nonce != packet.run_nonce) {
        Log(
            "Multiplayer level-up offer ignored; run nonce mismatch. authority_participant_id=" +
            std::to_string(packet.authority_participant_id) +
            " offer_id=" + std::to_string(packet.offer_id) +
            " local_run_nonce=" + std::to_string(local->runtime.run_nonce) +
            " packet_run_nonce=" + std::to_string(packet.run_nonce));
        return;
    }

    std::string sync_error;
    if (!SyncLocalPlayerProgressionToSharedLevelUp(packet.level, packet.experience, &sync_error)) {
        Log(
            "Multiplayer level-up offer rejected; local progression sync failed. authority_participant_id=" +
            std::to_string(packet.authority_participant_id) +
            " offer_id=" + std::to_string(packet.offer_id) +
            " level=" + std::to_string(packet.level) +
            " xp=" + std::to_string(packet.experience) +
            " error=" + sync_error);
        return;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        LevelUpOfferRuntimeInfo offer;
        offer.valid = true;
        offer.selection_submitted = false;
        offer.suppress_native_picker =
            (packet.flags & LevelUpOfferFlagSuppressNativePicker) != 0;
        offer.authority_participant_id = packet.authority_participant_id;
        offer.target_participant_id = packet.target_participant_id;
        offer.offer_id = packet.offer_id;
        offer.run_nonce = packet.run_nonce;
        offer.received_ms = now_ms;
        offer.level = packet.level;
        offer.experience = packet.experience;
        offer.options = options;
        state.active_level_up_offer = std::move(offer);
    });

    Log(
        "Multiplayer level-up offer accepted. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " target_participant_id=" + std::to_string(packet.target_participant_id) +
        " offer_id=" + std::to_string(packet.offer_id) +
        " run_nonce=" + std::to_string(packet.run_nonce) +
        " level=" + std::to_string(packet.level) +
        " xp=" + std::to_string(packet.experience) +
        " option_count=" + std::to_string(options.size()));
}

void ApplyLevelUpChoicePacket(
    const LevelUpChoicePacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportHost() ||
        packet.participant_id == 0 ||
        packet.participant_id == g_local_transport.local_peer_id ||
        packet.offer_id == 0) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);

    auto offer_it = g_local_transport.issued_level_up_offers_by_id.find(packet.offer_id);
    BotSkillChoiceOption selected_option{};
    std::int32_t selected_index = packet.option_index;
    std::int32_t level = 0;
    std::int32_t experience = 0;
    std::uint32_t run_nonce = packet.run_nonce;
    LevelUpChoiceResultCode result_code = LevelUpChoiceResultCode::StaleOffer;
    bool auto_pick_confirmation = false;
    std::string error_message;

    if (offer_it != g_local_transport.issued_level_up_offers_by_id.end()) {
        auto& offer = offer_it->second;
        level = offer.level;
        experience = offer.experience;
        run_nonce = offer.run_nonce;
        if (offer.target_participant_id != packet.participant_id ||
            (packet.run_nonce != 0 && offer.run_nonce != 0 && packet.run_nonce != offer.run_nonce)) {
            result_code = LevelUpChoiceResultCode::Rejected;
        } else if (offer.resolved) {
            const auto* resolved_participant =
                FindHostLevelUpBarrierParticipant(packet.participant_id);
            const bool matches_resolved_choice =
                resolved_participant != nullptr &&
                resolved_participant->resolved &&
                resolved_participant->offer_id == packet.offer_id &&
                resolved_participant->option_index > 0 &&
                (packet.option_index <= 0 ||
                 packet.option_index == resolved_participant->option_index) &&
                (packet.option_id < 0 ||
                 packet.option_id == resolved_participant->option_id) &&
                TryResolveIssuedLevelUpOption(
                    offer,
                    resolved_participant->option_index,
                    resolved_participant->option_id,
                    &selected_option);
            if (matches_resolved_choice) {
                selected_index = resolved_participant->option_index;
                result_code = LevelUpChoiceResultCode::Accepted;
                auto_pick_confirmation = resolved_participant->auto_picked;
            } else {
                result_code = LevelUpChoiceResultCode::StaleOffer;
            }
        } else if (!TryResolveIssuedLevelUpOption(
                       offer,
                       packet.option_index,
                       packet.option_id,
                       &selected_option)) {
            result_code = LevelUpChoiceResultCode::InvalidOption;
            offer.result_code = result_code;
        } else if (offer.auto_picked) {
            const auto* barrier_participant =
                FindHostLevelUpBarrierParticipant(packet.participant_id);
            if (barrier_participant == nullptr ||
                !barrier_participant->auto_picked ||
                barrier_participant->offer_id != packet.offer_id ||
                barrier_participant->option_index != packet.option_index ||
                barrier_participant->option_id != selected_option.option_id) {
                result_code = LevelUpChoiceResultCode::InvalidOption;
                offer.result_code = result_code;
            } else {
                // The authority already applied this forced choice to its
                // remote clone. This matching packet is the client's proof
                // that its native picker applied and closed successfully.
                result_code = LevelUpChoiceResultCode::Accepted;
                auto_pick_confirmation = true;
                offer.resolved = true;
                offer.result_code = result_code;
            }
        } else if (!ApplyAuthoritativeRemoteSkillRankDelta(
                       packet.participant_id,
                       selected_option,
                       nullptr,
                       &error_message)) {
            result_code = LevelUpChoiceResultCode::ApplyFailed;
            offer.result_code = result_code;
        } else {
            result_code = LevelUpChoiceResultCode::Accepted;
            offer.resolved = true;
            offer.result_code = result_code;
        }

        if (selected_index <= 0 && selected_option.option_id >= 0) {
            for (std::size_t index = 0; index < offer.options.size(); ++index) {
                if (offer.options[index].option_id == selected_option.option_id) {
                    selected_index = static_cast<std::int32_t>(index + 1);
                    break;
                }
            }
        }
    }

    const auto result = SendLevelUpChoiceResult(
        packet,
        packet.participant_id,
        run_nonce,
        level,
        experience,
        selected_index,
        selected_option,
        result_code,
        auto_pick_confirmation,
        from);
    if (result_code == LevelUpChoiceResultCode::Accepted) {
        MarkHostLevelUpBarrierParticipantResolved(
            result,
            auto_pick_confirmation,
            now_ms);
    }

    Log(
        "Multiplayer level-up choice " +
        std::string(result_code == LevelUpChoiceResultCode::Accepted ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(packet.participant_id) +
        " offer_id=" + std::to_string(packet.offer_id) +
        " run_nonce=" + std::to_string(run_nonce) +
        " option_index=" + std::to_string(selected_index) +
        " option_id=" + std::to_string(selected_option.option_id) +
        " auto_pick_confirmation=" +
            std::to_string(auto_pick_confirmation ? 1 : 0) +
        " result=" + LevelUpChoiceResultCodeLabel(result_code) +
        (error_message.empty() ? "" : " error=" + error_message));
}

void ApplyLevelUpChoiceResultPacket(
    const LevelUpChoiceResultPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id ||
        packet.target_participant_id == 0 ||
        packet.offer_id == 0 ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }

    std::unique_lock<std::recursive_mutex> picker_lock(
        g_local_level_up_picker_mutex,
        std::defer_lock);
    if (packet.target_participant_id == g_local_transport.local_peer_id) {
        picker_lock.lock();
    }

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    const auto result_code = LevelUpChoiceResultCodeFromPacketValue(packet.result_code);
    if (result_code == LevelUpChoiceResultCode::Accepted &&
        (packet.option_id < 0 ||
         packet.apply_count <= 0 ||
         packet.resulting_active == 0)) {
        Log(
            "Multiplayer accepted level-up result rejected; authoritative progression state is invalid. authority_participant_id=" +
            std::to_string(packet.authority_participant_id) +
            " target_participant_id=" +
            std::to_string(packet.target_participant_id) +
            " offer_id=" + std::to_string(packet.offer_id) +
            " option_id=" + std::to_string(packet.option_id) +
            " apply_count=" + std::to_string(packet.apply_count) +
            " resulting_active=" + std::to_string(packet.resulting_active));
        return;
    }
    if (result_code == LevelUpChoiceResultCode::Accepted &&
        g_local_transport.native_applied_level_up_result_offer_ids.find(
            packet.offer_id) !=
        g_local_transport.native_applied_level_up_result_offer_ids.end()) {
        return;
    }
    if (result_code == LevelUpChoiceResultCode::Accepted) {
        BotSkillChoiceOption option;
        option.option_id = packet.option_id;
        option.apply_count = packet.apply_count;
        const bool auto_picked =
            (packet.flags & kLevelUpChoiceResultFlagAutoPicked) != 0;
        std::uint16_t native_active_before = 0;
        const bool have_native_active_before =
            TryReadParticipantProgressionEntryActive(
                packet.target_participant_id,
                packet.option_id,
                &native_active_before);
        const bool already_at_authoritative_result =
            packet.resulting_active > 0 &&
            have_native_active_before &&
            native_active_before == packet.resulting_active;
        bool native_apply_complete = false;

        if (packet.target_participant_id == g_local_transport.local_peer_id) {
            const auto runtime_state = SnapshotRuntimeState();
            const bool native_picker_already_applied =
                runtime_state.active_level_up_offer.valid &&
                runtime_state.active_level_up_offer.offer_id == packet.offer_id &&
                runtime_state.active_level_up_offer.target_participant_id == packet.target_participant_id &&
                runtime_state.active_level_up_offer.native_picker_local_apply_observed;
            bool local_progression_complete =
                already_at_authoritative_result ||
                native_picker_already_applied;
            bool programmatic_apply = false;
            if (!local_progression_complete) {
                std::string error_message;
                if (!ApplyLocalPlayerSkillChoiceOption(option, &error_message)) {
                    Log(
                        "Multiplayer level-up choice result accepted but local apply failed. authority_participant_id=" +
                        std::to_string(packet.authority_participant_id) +
                        " offer_id=" + std::to_string(packet.offer_id) +
                        " option_id=" + std::to_string(packet.option_id) +
                        " error=" + error_message);
                } else {
                    local_progression_complete = true;
                    programmatic_apply = true;
                }
            }

            bool picker_cleanup_complete = true;
            if (local_progression_complete &&
                (auto_picked || programmatic_apply)) {
                picker_cleanup_complete =
                    ClearLocalLevelUpPickerAfterProgrammaticChoice(
                        packet.offer_id,
                        packet.option_index,
                        packet.option_id,
                        true);
            }
            std::uint16_t native_active_after = 0;
            const bool native_rank_verified =
                packet.resulting_active == 0 ||
                (TryReadParticipantProgressionEntryActive(
                     packet.target_participant_id,
                     packet.option_id,
                     &native_active_after) &&
                 native_active_after == packet.resulting_active);
            native_apply_complete =
                local_progression_complete &&
                picker_cleanup_complete &&
                native_rank_verified;
            if (local_progression_complete &&
                picker_cleanup_complete &&
                !native_rank_verified) {
                Log(
                    "Multiplayer auto-pick native rank verification failed; synchronized pause retained. offer_id=" +
                    std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id) +
                    " expected_active=" + std::to_string(packet.resulting_active) +
                    " native_active=" + std::to_string(native_active_after));
            }

            const bool send_auto_pick_confirmation =
                auto_picked &&
                native_apply_complete &&
                g_local_transport.confirmed_auto_pick_level_up_offer_ids.insert(
                    packet.offer_id).second;
            if (send_auto_pick_confirmation) {
                if (g_local_transport.confirmed_auto_pick_level_up_offer_ids.size() > 512) {
                    g_local_transport.confirmed_auto_pick_level_up_offer_ids.clear();
                    g_local_transport.confirmed_auto_pick_level_up_offer_ids.insert(
                        packet.offer_id);
                }
                LevelUpChoicePacket confirmation{};
                confirmation.header = MakePacketHeader(
                    PacketKind::LevelUpChoice,
                    g_local_transport.next_sequence++);
                confirmation.participant_id = g_local_transport.local_peer_id;
                confirmation.offer_id = packet.offer_id;
                confirmation.run_nonce = packet.run_nonce;
                confirmation.option_index = packet.option_index;
                confirmation.option_id = packet.option_id;
                SendPacketToEndpoint(confirmation, from);
                SendPacketToEndpoint(confirmation, from);
                Log(
                    "Multiplayer forced level-up choice applied and native picker closed; confirmation sent. authority_participant_id=" +
                    std::to_string(packet.authority_participant_id) +
                    " offer_id=" + std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id));
            }
        } else {
            if (already_at_authoritative_result) {
                native_apply_complete = true;
                Log(
                    "Multiplayer level-up choice result native apply skipped as idempotent. authority_participant_id=" +
                    std::to_string(packet.authority_participant_id) +
                    " target_participant_id=" + std::to_string(packet.target_participant_id) +
                    " offer_id=" + std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id));
            }
            std::string error_message;
            if (!native_apply_complete &&
                !HydrateAuthoritativeRemoteProgressionEntryState(
                    packet.target_participant_id,
                    packet.option_id,
                    packet.resulting_active,
                    1,
                    &error_message)) {
                Log(
                    "Multiplayer level-up choice result accepted but remote participant hydration failed. authority_participant_id=" +
                    std::to_string(packet.authority_participant_id) +
                    " target_participant_id=" + std::to_string(packet.target_participant_id) +
                    " offer_id=" + std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id) +
                    " error=" + error_message);
            } else if (!native_apply_complete) {
                std::uint16_t native_active_after = 0;
                native_apply_complete =
                    packet.resulting_active == 0 ||
                    (TryReadParticipantProgressionEntryActive(
                     packet.target_participant_id,
                     packet.option_id,
                     &native_active_after) &&
                     native_active_after == packet.resulting_active);
                Log(
                    "Multiplayer level-up choice result accepted; remote participant progression hydrated. authority_participant_id=" +
                    std::to_string(packet.authority_participant_id) +
                    " target_participant_id=" + std::to_string(packet.target_participant_id) +
                    " offer_id=" + std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id) +
                    " resulting_active=" + std::to_string(packet.resulting_active) +
                    " native_apply_complete=" +
                        std::to_string(native_apply_complete ? 1 : 0));
            }
        }
        if (native_apply_complete) {
            g_local_transport.native_applied_level_up_result_offer_ids.insert(
                packet.offer_id);
            if (g_local_transport.native_applied_level_up_result_offer_ids.size() > 512) {
                g_local_transport.native_applied_level_up_result_offer_ids.clear();
                g_local_transport.native_applied_level_up_result_offer_ids.insert(
                    packet.offer_id);
            }
        }
    }

    PublishLevelUpChoiceResultRuntimeInfo(packet, now_ms);
    Log(
        "Multiplayer level-up choice result applied. authority_participant_id=" +
        std::to_string(packet.authority_participant_id) +
        " target_participant_id=" + std::to_string(packet.target_participant_id) +
        " offer_id=" + std::to_string(packet.offer_id) +
        " run_nonce=" + std::to_string(packet.run_nonce) +
        " option_index=" + std::to_string(packet.option_index) +
        " option_id=" + std::to_string(packet.option_id) +
        " resulting_active=" + std::to_string(packet.resulting_active) +
        " auto_picked=" +
            std::to_string(
                (packet.flags & kLevelUpChoiceResultFlagAutoPicked) != 0 ? 1 : 0) +
        " result=" + LevelUpChoiceResultCodeLabel(result_code));
}
