// Level-up offer, choice, and accepted-result packet handling.

void PublishLevelUpChoiceResultRuntimeInfo(
    const LevelUpChoiceResultPacket& packet,
    std::uint64_t now_ms) {
    UpdateRuntimeState([&](RuntimeState& state) {
        LevelUpChoiceResultRuntimeInfo result;
        result.valid = true;
        result.authority_participant_id = packet.authority_participant_id;
        result.target_participant_id = packet.target_participant_id;
        result.offer_id = packet.offer_id;
        result.run_nonce = packet.run_nonce;
        result.received_ms = now_ms;
        result.level = packet.level;
        result.experience = packet.experience;
        result.option_index = packet.option_index;
        result.option_id = packet.option_id;
        result.apply_count = packet.apply_count;
        result.resulting_active = packet.resulting_active;
        result.auto_picked =
            (packet.flags & kLevelUpChoiceResultFlagAutoPicked) != 0;
        result.result_code = LevelUpChoiceResultCodeFromPacketValue(packet.result_code);
        state.last_level_up_choice_result = result;

        if (state.active_level_up_offer.valid &&
            state.active_level_up_offer.offer_id == packet.offer_id &&
            state.active_level_up_offer.target_participant_id == packet.target_participant_id) {
            state.active_level_up_offer.selected_option_index = packet.option_index;
            state.active_level_up_offer.selected_option_id = packet.option_id;
            if (result.result_code == LevelUpChoiceResultCode::Accepted ||
                result.result_code == LevelUpChoiceResultCode::StaleOffer) {
                state.active_level_up_offer.selection_submitted = true;
                state.active_level_up_offer.valid = false;
            } else {
                state.active_level_up_offer.selection_submitted = false;
            }
        }

        if (result.result_code != LevelUpChoiceResultCode::Accepted) {
            return;
        }

        ParticipantInfo* participant = nullptr;
        if (packet.target_participant_id == g_local_transport.local_peer_id) {
            participant = FindLocalParticipant(state);
        } else {
            participant = FindParticipant(state, packet.target_participant_id);
        }
        if (participant == nullptr) {
            return;
        }
        participant->character_profile.level = packet.level;
        participant->character_profile.experience = packet.experience;
        participant->runtime.level = packet.level;
        participant->runtime.experience_current = packet.experience;
        participant->owned_progression.initialized = true;
    });
}

bool ClearLocalLevelUpPickerAfterProgrammaticChoice(
    std::uint64_t offer_id,
    std::int32_t option_index,
    std::int32_t option_id,
    bool write_screen_selection) {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0 ||
        kProgressionLocalSkillPickerScreenOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t screen_address = 0;
    (void)memory.TryReadField(
        player_state.progression_address,
        kProgressionLocalSkillPickerScreenOffset,
        &screen_address);

    bool wrote = true;
    if (write_screen_selection && screen_address != 0 && option_index > 0) {
        const std::int32_t zero_based_selected_index = option_index - 1;
        wrote = memory.TryWriteField(
            screen_address,
            kLevelUpScreenSelectedOptionIndexOffset,
            zero_based_selected_index) && wrote;
    }

    const std::int32_t no_pending_choices = 0;
    const std::int32_t no_incoming_choices = 0;
    const std::uint8_t picker_ui_flag_cleared = 0;
    const std::uint32_t no_temporary_picker_state = 0;
    const uintptr_t no_screen = 0;
    wrote = memory.TryWriteField(
        player_state.progression_address,
        kProgressionLevelUpPendingChoiceCountOffset,
        no_pending_choices) && wrote;
    wrote = memory.TryWriteField(
        player_state.progression_address,
        kProgressionLevelUpIncomingChoiceCountOffset,
        no_incoming_choices) && wrote;
    wrote = memory.TryWriteField(
        player_state.progression_address,
        kProgressionLevelUpPickerUiFlagOffset,
        picker_ui_flag_cleared) && wrote;
    wrote = memory.TryWriteField(
        player_state.progression_address,
        kProgressionLevelUpTemporaryPickerObjectOffset,
        no_temporary_picker_state) && wrote;
    wrote = memory.TryWriteField(
        player_state.progression_address,
        kProgressionLevelUpTemporaryPickerValueOffset,
        no_temporary_picker_state) && wrote;
    wrote = memory.TryWriteField(
        player_state.progression_address,
        kProgressionLocalSkillPickerScreenOffset,
        no_screen) && wrote;

    Log(
        "Multiplayer level-up native picker cleared after programmatic accepted choice. offer_id=" +
        std::to_string(offer_id) +
        " option_index=" + std::to_string(option_index) +
        " option_id=" + std::to_string(option_id) +
        " progression=" + HexString(player_state.progression_address) +
        " screen=" + HexString(screen_address) +
        " wrote=" + std::to_string(wrote ? 1 : 0));
    return wrote;
}

bool TryReadParticipantProgressionEntryActive(
    std::uint64_t participant_id,
    std::int32_t entry_index,
    std::uint16_t* active) {
    if (active == nullptr || participant_id == 0 || entry_index < 0) {
        return false;
    }
    *active = 0;

    if (participant_id == g_local_transport.local_peer_id) {
        SDModProgressionBookState book_state;
        if (!TryGetPlayerProgressionBookState(&book_state) || !book_state.valid) {
            return false;
        }
        for (const auto& entry : book_state.entries) {
            if (entry.valid && entry.entry_index == entry_index) {
                *active = entry.active;
                return true;
            }
        }
        return false;
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t table_address = 0;
    std::int32_t entry_count = 0;
    if (!memory.TryReadField(
            gameplay_state.progression_runtime_state_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &table_address) ||
        !memory.TryReadField(
            gameplay_state.progression_runtime_state_address,
            kStandaloneWizardProgressionTableCountOffset,
            &entry_count) ||
        table_address == 0 ||
        entry_index >= entry_count) {
        return false;
    }
    const uintptr_t entry_address =
        table_address +
        static_cast<std::size_t>(entry_index) * kStandaloneWizardProgressionEntryStride;
    return memory.TryReadField(
        entry_address,
        kStandaloneWizardProgressionActiveFlagOffset,
        active);
}

LevelUpChoiceResultPacket BuildLevelUpChoiceResultPacket(
    std::uint64_t offer_id,
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    std::int32_t option_index,
    const BotSkillChoiceOption& option,
    LevelUpChoiceResultCode result_code,
    std::uint16_t resulting_active,
    bool auto_picked = false) {
    LevelUpChoiceResultPacket result{};
    result.header = MakePacketHeader(PacketKind::LevelUpChoiceResult, g_local_transport.next_sequence++);
    result.authority_participant_id = g_local_transport.local_peer_id;
    result.target_participant_id = target_participant_id;
    result.offer_id = offer_id;
    result.run_nonce = run_nonce;
    result.level = level;
    result.experience = experience;
    result.option_index = option_index;
    result.option_id = option.option_id;
    result.apply_count = option.apply_count;
    result.result_code = static_cast<std::uint8_t>(result_code);
    result.flags = auto_picked ? kLevelUpChoiceResultFlagAutoPicked : 0;
    result.resulting_active = resulting_active;
    return result;
}

LevelUpChoiceResultPacket SendLevelUpChoiceResult(
    const LevelUpChoicePacket& request,
    std::uint64_t target_participant_id,
    std::uint32_t run_nonce,
    std::int32_t level,
    std::int32_t experience,
    std::int32_t option_index,
    const BotSkillChoiceOption& option,
    LevelUpChoiceResultCode result_code,
    const TransportPeerEndpoint& endpoint) {
    std::uint16_t resulting_active = 0;
    if (result_code == LevelUpChoiceResultCode::Accepted) {
        (void)TryReadParticipantProgressionEntryActive(
            target_participant_id,
            option.option_id,
            &resulting_active);
    }
    const auto result = BuildLevelUpChoiceResultPacket(
        request.offer_id,
        target_participant_id,
        run_nonce,
        level,
        experience,
        option_index,
        option,
        result_code,
        resulting_active);

    SendPacketToEndpoint(result, endpoint);
    RelayPacketToPeers(result, endpoint);
    PublishLevelUpChoiceResultRuntimeInfo(
        result,
        static_cast<std::uint64_t>(GetTickCount64()));
    return result;
}

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
            result_code = LevelUpChoiceResultCode::StaleOffer;
        } else if (!TryResolveIssuedLevelUpOption(
                       offer,
                       packet.option_index,
                       packet.option_id,
                       &selected_option)) {
            result_code = LevelUpChoiceResultCode::InvalidOption;
            offer.result_code = result_code;
        } else if (!ApplyParticipantSkillChoiceOption(
                       packet.participant_id,
                       selected_option,
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
        from);
    if (result_code == LevelUpChoiceResultCode::Accepted) {
        MarkHostLevelUpBarrierParticipantResolved(result, false, now_ms);
    }

    Log(
        "Multiplayer level-up choice " +
        std::string(result_code == LevelUpChoiceResultCode::Accepted ? "accepted" : "rejected") +
        ". participant_id=" + std::to_string(packet.participant_id) +
        " offer_id=" + std::to_string(packet.offer_id) +
        " run_nonce=" + std::to_string(run_nonce) +
        " option_index=" + std::to_string(selected_index) +
        " option_id=" + std::to_string(selected_option.option_id) +
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

    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);
    const auto result_code = LevelUpChoiceResultCodeFromPacketValue(packet.result_code);
    if (result_code == LevelUpChoiceResultCode::Accepted) {
        BotSkillChoiceOption option;
        option.option_id = packet.option_id;
        option.apply_count = packet.apply_count;
        const bool duplicate_result =
            g_local_transport.native_applied_level_up_result_offer_ids.find(
                packet.offer_id) !=
            g_local_transport.native_applied_level_up_result_offer_ids.end();
        std::uint16_t native_active_before = 0;
        const bool have_native_active_before =
            TryReadParticipantProgressionEntryActive(
                packet.target_participant_id,
                packet.option_id,
                &native_active_before);
        const bool already_at_authoritative_result =
            packet.resulting_active > 0 &&
            have_native_active_before &&
            native_active_before >= packet.resulting_active;
        bool native_apply_complete = duplicate_result || already_at_authoritative_result;

        if (duplicate_result || already_at_authoritative_result) {
            Log(
                "Multiplayer level-up choice result native apply skipped as idempotent. authority_participant_id=" +
                std::to_string(packet.authority_participant_id) +
                " target_participant_id=" + std::to_string(packet.target_participant_id) +
                " offer_id=" + std::to_string(packet.offer_id) +
                " option_id=" + std::to_string(packet.option_id) +
                " native_active=" +
                    (have_native_active_before
                         ? std::to_string(native_active_before)
                         : std::string("unavailable")) +
                " resulting_active=" + std::to_string(packet.resulting_active));
        } else if (packet.target_participant_id == g_local_transport.local_peer_id) {
            const auto runtime_state = SnapshotRuntimeState();
            const bool native_picker_already_applied =
                runtime_state.active_level_up_offer.valid &&
                runtime_state.active_level_up_offer.offer_id == packet.offer_id &&
                runtime_state.active_level_up_offer.target_participant_id == packet.target_participant_id &&
                runtime_state.active_level_up_offer.native_picker_local_apply_observed;
            if (!native_picker_already_applied) {
                std::string error_message;
                if (!ApplyLocalPlayerSkillChoiceOption(option, &error_message)) {
                    Log(
                        "Multiplayer level-up choice result accepted but local apply failed. authority_participant_id=" +
                        std::to_string(packet.authority_participant_id) +
                        " offer_id=" + std::to_string(packet.offer_id) +
                        " option_id=" + std::to_string(packet.option_id) +
                        " error=" + error_message);
                } else {
                    native_apply_complete = true;
                    if (!ClearLocalLevelUpPickerAfterProgrammaticChoice(
                            packet.offer_id,
                            packet.option_index,
                            packet.option_id,
                            true)) {
                        Log(
                            "Multiplayer level-up choice result accepted but native picker cleanup failed. authority_participant_id=" +
                            std::to_string(packet.authority_participant_id) +
                            " offer_id=" + std::to_string(packet.offer_id) +
                            " option_id=" + std::to_string(packet.option_id));
                    }
                }
            } else {
                native_apply_complete = true;
                Log(
                    "Multiplayer level-up choice result accepted; native picker had already applied locally. authority_participant_id=" +
                    std::to_string(packet.authority_participant_id) +
                    " offer_id=" + std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id));
            }
        } else {
            std::string error_message;
            if (!ApplyParticipantSkillChoiceOption(
                    packet.target_participant_id,
                    option,
                    &error_message)) {
                Log(
                    "Multiplayer level-up choice result accepted but remote participant apply failed. authority_participant_id=" +
                    std::to_string(packet.authority_participant_id) +
                    " target_participant_id=" + std::to_string(packet.target_participant_id) +
                    " offer_id=" + std::to_string(packet.offer_id) +
                    " option_id=" + std::to_string(packet.option_id) +
                    " error=" + error_message);
            } else {
                std::uint16_t native_active_after = 0;
                native_apply_complete =
                    packet.resulting_active == 0 ||
                    (TryReadParticipantProgressionEntryActive(
                         packet.target_participant_id,
                         packet.option_id,
                         &native_active_after) &&
                     native_active_after >= packet.resulting_active);
                Log(
                    "Multiplayer level-up choice result accepted; remote participant progression applied. authority_participant_id=" +
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
