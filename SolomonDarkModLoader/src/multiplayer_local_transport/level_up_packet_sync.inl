// Level-up offer, choice, and accepted-result packet handling.

void DisarmLocalLevelUpOptionRollForOffer(std::uint64_t offer_id) {
    if (offer_id == 0) {
        return;
    }
    {
        std::lock_guard<std::mutex> lock(g_local_level_up_option_roll_mutex);
        if (g_armed_local_level_up_option_roll.offer_id == offer_id) {
            g_armed_local_level_up_option_roll = ArmedLocalLevelUpOptionRoll{};
        }
    }
    auto expected_offer_id = offer_id;
    (void)g_last_applied_local_level_up_option_roll_offer_id.compare_exchange_strong(
        expected_offer_id,
        0,
        std::memory_order_acq_rel,
        std::memory_order_acquire);
}

void PublishLevelUpChoiceResultRuntimeInfo(
    const LevelUpChoiceResultPacket& packet,
    std::uint64_t now_ms) {
    const auto incoming_result_code =
        LevelUpChoiceResultCodeFromPacketValue(packet.result_code);
    bool accepted_owned_book_applied =
        incoming_result_code != LevelUpChoiceResultCode::Accepted;
    UpdateRuntimeState([&](RuntimeState& state) {
        const auto& current = state.last_level_up_choice_result;
        if (current.valid &&
            current.authority_participant_id == packet.authority_participant_id &&
            current.target_participant_id == packet.target_participant_id &&
            current.offer_id == packet.offer_id &&
            current.result_code == LevelUpChoiceResultCode::Accepted &&
            incoming_result_code != LevelUpChoiceResultCode::Accepted) {
            return;
        }

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
        result.result_code = incoming_result_code;
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
        if (packet.option_id >= 0 && packet.resulting_active > 0) {
            accepted_owned_book_applied =
                ApplyAuthoritativeProgressionBookEntryState(
                    packet.option_id,
                    packet.resulting_active,
                    1,
                    &participant->owned_progression);
        }
        participant->character_profile.level = packet.level;
        participant->character_profile.experience = packet.experience;
        participant->runtime.level = packet.level;
        participant->runtime.experience_current = packet.experience;
        participant->owned_progression.initialized = true;
    });

    if (!accepted_owned_book_applied) {
        Log(
            "Multiplayer accepted level-up result could not advance the participant-owned progression book. "
            "target_participant_id=" +
            std::to_string(packet.target_participant_id) +
            " offer_id=" + std::to_string(packet.offer_id) +
            " option_id=" + std::to_string(packet.option_id) +
            " resulting_active=" +
            std::to_string(packet.resulting_active));
    }

    if (packet.target_participant_id == g_local_transport.local_peer_id &&
        (incoming_result_code == LevelUpChoiceResultCode::Accepted ||
         incoming_result_code == LevelUpChoiceResultCode::StaleOffer)) {
        DisarmLocalLevelUpOptionRollForOffer(packet.offer_id);
    }
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
    if (!wrote) {
        Log(
            "Multiplayer level-up native picker selection write failed before close. offer_id=" +
            std::to_string(offer_id) +
            " option_index=" + std::to_string(option_index) +
            " option_id=" + std::to_string(option_id) +
            " screen=" + HexString(screen_address));
        return false;
    }

    DWORD close_exception = 0;
    const bool close_ok =
        screen_address == 0 ||
        CallLevelUpScreenCloseSafe(screen_address, &close_exception);
    if (!close_ok) {
        Log(
            "Multiplayer level-up native picker close failed; synchronized pause retained. offer_id=" +
            std::to_string(offer_id) +
            " option_index=" + std::to_string(option_index) +
            " option_id=" + std::to_string(option_id) +
            " screen=" + HexString(screen_address) +
            " close_seh=" +
            HexString(static_cast<uintptr_t>(close_exception)));
        return false;
    }

    DisarmLocalLevelUpOptionRollForOffer(offer_id);

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
        "Multiplayer level-up native picker closed and cleared after programmatic accepted choice. offer_id=" +
        std::to_string(offer_id) +
        " option_index=" + std::to_string(option_index) +
        " option_id=" + std::to_string(option_id) +
        " progression=" + HexString(player_state.progression_address) +
        " screen=" + HexString(screen_address) +
        " close_ok=" + std::to_string(close_ok ? 1 : 0) +
        " close_seh=" + HexString(static_cast<uintptr_t>(close_exception)) +
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
    bool auto_picked,
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
        resulting_active,
        auto_picked);

    SendPacketToEndpoint(result, endpoint);
    RelayPacketToPeers(result, endpoint);
    PublishLevelUpChoiceResultRuntimeInfo(
        result,
        static_cast<std::uint64_t>(GetTickCount64()));
    return result;
}

#include "level_up_packet_handlers.inl"
