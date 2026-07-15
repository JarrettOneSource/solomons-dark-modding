bool TryApplyLocalProgrammaticLevelUpChoiceThroughNativePicker(
    std::uint64_t offer_id,
    std::int32_t option_index,
    const LevelUpChoiceOptionState& selected_option,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    if (option_index <= 0 || selected_option.option_id < 0) {
        return fail("programmatic native level-up apply requires a resolved offered option");
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0 ||
        kProgressionLocalSkillPickerScreenOffset == 0) {
        return fail("programmatic native level-up apply requires a live player picker progression");
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t screen_address = 0;
    if (!memory.TryReadField(
            player_state.progression_address,
            kProgressionLocalSkillPickerScreenOffset,
            &screen_address) ||
        screen_address == 0) {
        return fail("programmatic native level-up apply requires a presented native picker");
    }

    const std::int32_t zero_based_selected_index = option_index - 1;
    (void)memory.TryWriteField(
        screen_address,
        kLevelUpScreenSelectedOptionIndexOffset,
        zero_based_selected_index);

    BotSkillChoiceOption option;
    option.option_id = selected_option.option_id;
    option.apply_count = selected_option.apply_count;

    std::string apply_error;
    if (!ApplyLocalPlayerSkillChoiceOption(option, &apply_error)) {
        return fail("programmatic local skill choice apply failed: " + apply_error);
    }

    const bool cleanup_ok = ClearLocalLevelUpPickerAfterProgrammaticChoice(
        offer_id,
        option_index,
        selected_option.option_id,
        false);

    Log(
        "Multiplayer level-up native picker applied locally through programmatic choice. offer_id=" +
        std::to_string(offer_id) +
        " option_index=" + std::to_string(option_index) +
        " option_id=" + std::to_string(selected_option.option_id) +
        " screen=" + HexString(screen_address) +
        " cleanup_ok=" + std::to_string(cleanup_ok ? 1 : 0));
    if (!cleanup_ok) {
        return fail("programmatic native level-up picker did not close cleanly");
    }
    return true;
}

bool ResolveHostSelfLevelUpChoice(
    std::uint64_t offer_id,
    std::int32_t resolved_option_index,
    const LevelUpChoiceOptionState& selected_option,
    std::string* error_message,
    bool auto_picked = false,
    bool native_picker_local_apply_observed = false) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };

    auto issued = g_local_transport.issued_level_up_offers_by_id.find(offer_id);
    if (issued == g_local_transport.issued_level_up_offers_by_id.end() ||
        issued->second.target_participant_id != g_local_transport.local_peer_id ||
        issued->second.resolved) {
        return fail("host-self level-up offer is missing, mismatched, or already resolved");
    }

    auto& offer = issued->second;
    if (offer.local_progression_applied &&
        (offer.local_progression_option_index != resolved_option_index ||
         offer.local_progression_option_id != selected_option.option_id)) {
        return fail("host-self level-up retry does not match the already-applied option");
    }

    if (native_picker_local_apply_observed) {
        offer.local_progression_applied = true;
        offer.local_progression_option_index = resolved_option_index;
        offer.local_progression_option_id = selected_option.option_id;
    }

    // A stock picker selection has already mutated progression. Programmatic
    // choices apply exactly once and record that fact before attempting UI
    // cleanup, so a failed close can be retried without granting the skill
    // again.
    BotSkillChoiceOption option;
    option.option_id = selected_option.option_id;
    option.apply_count = selected_option.apply_count;

    if (!offer.local_progression_applied) {
        std::string apply_error;
        if (!ApplyLocalPlayerSkillChoiceOption(option, &apply_error)) {
            return fail("host-self level-up apply failed: " + apply_error);
        }
        offer.local_progression_applied = true;
        offer.local_progression_option_index = resolved_option_index;
        offer.local_progression_option_id = selected_option.option_id;
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        if (state.active_level_up_offer.valid &&
            state.active_level_up_offer.offer_id == offer_id) {
            state.active_level_up_offer.native_picker_local_apply_observed = true;
        }
    });

    // Close before clearing the progression pointer. The synchronized barrier
    // must never resume while a native picker remains visible.
    if (!ClearLocalLevelUpPickerAfterProgrammaticChoice(
        offer_id,
        resolved_option_index,
        selected_option.option_id,
        false)) {
        return fail("host-self native level-up picker did not close cleanly");
    }

    // The host is its own authority: resolve the issued offer so the
    // synchronized level-up pause clears for both peers, and retire the active
    // offer locally without any wire round-trip.
    issued->second.resolved = true;
    issued->second.auto_picked = auto_picked;
    issued->second.result_code = LevelUpChoiceResultCode::Accepted;
    g_local_transport.pending_level_up_offer_targets_by_participant.erase(
        g_local_transport.local_peer_id);

    UpdateRuntimeState([&](RuntimeState& state) {
        if (state.active_level_up_offer.valid &&
            state.active_level_up_offer.offer_id == offer_id) {
            state.active_level_up_offer.selection_submitted = true;
            state.active_level_up_offer.native_picker_local_apply_observed = true;
            state.active_level_up_offer.selected_option_index = resolved_option_index;
            state.active_level_up_offer.selected_option_id = selected_option.option_id;
            state.active_level_up_offer.valid = false;
        }
    });

    // A host-owned choice has no inbound client request to drive the normal
    // result relay. Publish the same authoritative result packet explicitly so
    // every connected client applies the upgrade to its native remote clone of
    // the host. This also makes the choice visible to observer peers and keeps
    // the host/client paths symmetric.
    std::uint16_t resulting_active = 0;
    (void)TryReadParticipantProgressionEntryActive(
        g_local_transport.local_peer_id,
        option.option_id,
        &resulting_active);
    const auto result = BuildLevelUpChoiceResultPacket(
        offer_id,
        g_local_transport.local_peer_id,
        issued->second.run_nonce,
        issued->second.level,
        issued->second.experience,
        resolved_option_index,
        option,
        LevelUpChoiceResultCode::Accepted,
        resulting_active,
        auto_picked);
    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(result, endpoint);
    }
    PublishLevelUpChoiceResultRuntimeInfo(
        result,
        static_cast<std::uint64_t>(GetTickCount64()));
    MarkHostLevelUpBarrierParticipantResolved(
        result,
        auto_picked,
        static_cast<std::uint64_t>(GetTickCount64()));

    Log(
        "Multiplayer host-self level-up choice resolved and broadcast. offer_id=" +
        std::to_string(offer_id) +
        " option_index=" + std::to_string(resolved_option_index) +
        " option_id=" + std::to_string(selected_option.option_id) +
        " auto_picked=" + std::to_string(auto_picked ? 1 : 0) +
        " peer_endpoint_count=" + std::to_string(endpoints.size()));
    return true;
}

bool QueueLocalLevelUpChoiceInternal(
    std::uint64_t offer_id,
    std::int32_t option_index,
    std::int32_t option_id,
    bool native_picker_local_apply_observed,
    std::string* error_message) {
    auto fail = [&](const char* message) {
        if (error_message != nullptr) {
            *error_message = message;
        }
        return false;
    };

    const bool is_host_self = IsLocalTransportHost();
    if (!IsLocalTransportClient() && !is_host_self) {
        return fail("level-up choices require an active local transport role");
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto& offer = runtime_state.active_level_up_offer;
    if (!offer.valid) {
        return fail("no active level-up offer");
    }
    if (offer_id == 0) {
        offer_id = offer.offer_id;
    }
    if (offer.offer_id != offer_id) {
        return fail("level-up offer id is stale");
    }
    if (offer.target_participant_id != g_local_transport.local_peer_id) {
        return fail("level-up offer target does not match the local participant");
    }
    if (offer.selection_submitted) {
        return fail("level-up offer already has a submitted choice");
    }

    LevelUpChoiceOptionState selected_option;
    if (!TryResolveOfferedLevelUpOption(
            offer.options,
            option_index,
            option_id,
            &selected_option)) {
        return fail("level-up choice was not in the active offer");
    }

    std::int32_t resolved_option_index = option_index;
    if (resolved_option_index <= 0) {
        for (std::size_t index = 0; index < offer.options.size(); ++index) {
            if (offer.options[index].option_id == selected_option.option_id) {
                resolved_option_index = static_cast<std::int32_t>(index + 1);
                break;
            }
        }
    }
    if (resolved_option_index <= 0) {
        return fail("level-up choice index could not be resolved");
    }

    if (is_host_self) {
        // The host owns the authority for its own offer: apply, clear the
        // picker, and retire the offer locally with no client-to-host wire hop.
        return ResolveHostSelfLevelUpChoice(
            offer_id,
            resolved_option_index,
            selected_option,
            error_message,
            false,
            native_picker_local_apply_observed);
    }

    bool local_native_apply_observed = native_picker_local_apply_observed;
    if (!local_native_apply_observed && !offer.suppress_native_picker) {
        std::string local_apply_error;
        if (TryApplyLocalProgrammaticLevelUpChoiceThroughNativePicker(
                offer_id,
                resolved_option_index,
                selected_option,
                &local_apply_error)) {
            local_native_apply_observed = true;
        } else if (!local_apply_error.empty()) {
            Log(
                "Multiplayer level-up programmatic native picker local apply skipped. offer_id=" +
                std::to_string(offer_id) +
                " option_index=" + std::to_string(resolved_option_index) +
                " option_id=" + std::to_string(selected_option.option_id) +
                " error=" + local_apply_error);
        }
    }

    {
        std::lock_guard<std::mutex> lock(g_local_transport_event_mutex);
        constexpr std::size_t kMaxQueuedLocalLevelUpChoices = 8;
        if (g_queued_local_level_up_choices.size() >= kMaxQueuedLocalLevelUpChoices) {
            g_queued_local_level_up_choices.erase(g_queued_local_level_up_choices.begin());
        }
        QueuedLocalLevelUpChoice choice;
        choice.offer_id = offer_id;
        choice.option_index = resolved_option_index;
        choice.option_id = selected_option.option_id;
        g_queued_local_level_up_choices.push_back(choice);
    }

    UpdateRuntimeState([&](RuntimeState& state) {
        if (!state.active_level_up_offer.valid ||
            state.active_level_up_offer.offer_id != offer_id) {
            return;
        }
        state.active_level_up_offer.selection_submitted = true;
        state.active_level_up_offer.native_picker_local_apply_observed =
            state.active_level_up_offer.native_picker_local_apply_observed ||
            local_native_apply_observed;
        state.active_level_up_offer.selected_option_index = resolved_option_index;
        state.active_level_up_offer.selected_option_id = selected_option.option_id;
    });
    return true;
}

int CaptureLocalTransportSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code) {
    if (exception_code != nullptr &&
        exception_pointers != nullptr &&
        exception_pointers->ExceptionRecord != nullptr) {
        *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallLevelUpScreenCreateSafe(
    uintptr_t progression_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    const auto create_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kLevelUpScreenCreate);
    auto* create_screen = reinterpret_cast<NativeLevelUpScreenCreateFn>(create_address);
    if (create_screen == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        create_screen(reinterpret_cast<void*>(progression_address), 0);
        return true;
    } __except (CaptureLocalTransportSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryReadLocalLevelUpScreen(
    uintptr_t progression_address,
    uintptr_t* screen_address) {
    if (screen_address != nullptr) {
        *screen_address = 0;
    }
    if (screen_address == nullptr ||
        progression_address == 0 ||
        kProgressionLocalSkillPickerScreenOffset == 0) {
        return false;
    }

    uintptr_t read_screen = 0;
    if (!ProcessMemory::Instance().TryReadField(
            progression_address,
            kProgressionLocalSkillPickerScreenOffset,
            &read_screen)) {
        return false;
    }
    *screen_address = read_screen;
    return read_screen != 0;
}

bool TryPresentLocalLevelUpPicker(
    uintptr_t progression_address,
    uintptr_t* screen_address,
    DWORD* exception_code) {
    if (screen_address != nullptr) {
        *screen_address = 0;
    }
    if (progression_address == 0) {
        return false;
    }

    uintptr_t existing_screen = 0;
    if (TryReadLocalLevelUpScreen(progression_address, &existing_screen)) {
        if (screen_address != nullptr) {
            *screen_address = existing_screen;
        }
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const std::int32_t no_pending_choices = 0;
    const std::int32_t one_incoming_choice = 1;
    (void)memory.TryWriteField(
        progression_address,
        kProgressionLevelUpPendingChoiceCountOffset,
        no_pending_choices);
    (void)memory.TryWriteField(
        progression_address,
        kProgressionLevelUpIncomingChoiceCountOffset,
        one_incoming_choice);

    if (!CallLevelUpScreenCreateSafe(progression_address, exception_code)) {
        return false;
    }

    return TryReadLocalLevelUpScreen(progression_address, screen_address);
}

bool TryPinLevelUpPickerOptions(
    uintptr_t screen_address,
    const std::vector<LevelUpChoiceOptionState>& options) {
    if (screen_address == 0 || options.empty() || options.size() > kLevelUpOfferMaxOptions) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto desired_count = static_cast<std::int32_t>(options.size());
    bool wrote =
        memory.TryWriteField(
            screen_address,
            kLevelUpScreenDesiredChoiceCountOffset,
            desired_count);

    uintptr_t values_address = 0;
    std::int32_t native_count = 0;
    if (!memory.TryReadField(
            screen_address,
            kLevelUpScreenOptionValuesOffset,
            &values_address) ||
        !memory.TryReadField(
            screen_address,
            kLevelUpScreenOptionCountOffset,
            &native_count) ||
        values_address == 0 ||
        native_count < desired_count) {
        return false;
    }

    for (std::int32_t index = 0; index < desired_count; ++index) {
        wrote = memory.TryWriteValue<std::int32_t>(
            values_address + static_cast<std::size_t>(index) * sizeof(std::int32_t),
            options[static_cast<std::size_t>(index)].option_id) && wrote;
    }
    wrote = memory.TryWriteField(
        screen_address,
        kLevelUpScreenOptionCountOffset,
        desired_count) && wrote;
    return wrote;
}

bool TryReadPinnedLevelUpPickerSelection(
    uintptr_t screen_address,
    const std::vector<LevelUpChoiceOptionState>& options,
    std::int32_t* option_index,
    std::int32_t* option_id) {
    if (option_index != nullptr) {
        *option_index = -1;
    }
    if (option_id != nullptr) {
        *option_id = -1;
    }
    if (screen_address == 0 || options.empty() || option_index == nullptr || option_id == nullptr) {
        return false;
    }

    std::int32_t zero_based_selection = -1;
    if (!ProcessMemory::Instance().TryReadField(
            screen_address,
            kLevelUpScreenSelectedOptionIndexOffset,
            &zero_based_selection) ||
        zero_based_selection < 0 ||
        static_cast<std::size_t>(zero_based_selection) >= options.size()) {
        return false;
    }

    *option_index = zero_based_selection + 1;
    *option_id = options[static_cast<std::size_t>(zero_based_selection)].option_id;
    return true;
}

void UpdateActiveLevelUpOfferNativePresentation(
    std::uint64_t offer_id,
    bool picker_presented,
    bool options_pinned,
    bool local_apply_observed) {
    UpdateRuntimeState([&](RuntimeState& state) {
        if (!state.active_level_up_offer.valid ||
            state.active_level_up_offer.offer_id != offer_id) {
            return;
        }
        state.active_level_up_offer.native_picker_presented =
            state.active_level_up_offer.native_picker_presented || picker_presented;
        state.active_level_up_offer.native_picker_options_pinned =
            state.active_level_up_offer.native_picker_options_pinned || options_pinned;
        state.active_level_up_offer.native_picker_local_apply_observed =
            state.active_level_up_offer.native_picker_local_apply_observed || local_apply_observed;
    });
}

void ReconcileLocalLevelUpOfferPresentation(std::uint64_t now_ms, bool allow_native_create) {
    if (!IsLocalTransportClient() && !IsLocalTransportHost()) {
        return;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto offer = runtime_state.active_level_up_offer;
    if (!offer.valid ||
        offer.selection_submitted ||
        offer.suppress_native_picker ||
        offer.target_participant_id != g_local_transport.local_peer_id ||
        offer.options.empty()) {
        return;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        return;
    }

    uintptr_t screen_address = 0;
    bool picker_presented =
        TryReadLocalLevelUpScreen(player_state.progression_address, &screen_address);
    DWORD exception_code = 0;
    if (!picker_presented && allow_native_create) {
        picker_presented = TryPresentLocalLevelUpPicker(
            player_state.progression_address,
            &screen_address,
            &exception_code);
    }
    if (!picker_presented || screen_address == 0) {
        if (allow_native_create) {
            Log(
                "Multiplayer level-up native picker presentation pending. offer_id=" +
                std::to_string(offer.offer_id) +
                " progression=" + HexString(player_state.progression_address) +
                " seh=" + HexString(static_cast<uintptr_t>(exception_code)) +
                " now_ms=" + std::to_string(now_ms));
        }
        return;
    }

    const bool options_pinned = TryPinLevelUpPickerOptions(screen_address, offer.options);
    UpdateActiveLevelUpOfferNativePresentation(
        offer.offer_id,
        true,
        options_pinned,
        false);

    if (!options_pinned) {
        return;
    }

    std::int32_t selected_option_index = -1;
    std::int32_t selected_option_id = -1;
    if (!TryReadPinnedLevelUpPickerSelection(
            screen_address,
            offer.options,
            &selected_option_index,
            &selected_option_id)) {
        return;
    }

    std::string error_message;
    if (QueueLocalLevelUpChoiceInternal(
            offer.offer_id,
            selected_option_index,
            selected_option_id,
            true,
            &error_message)) {
        UpdateActiveLevelUpOfferNativePresentation(
            offer.offer_id,
            true,
            true,
            true);
        Log(
            "Multiplayer level-up native picker choice queued. offer_id=" +
            std::to_string(offer.offer_id) +
            " option_index=" + std::to_string(selected_option_index) +
            " option_id=" + std::to_string(selected_option_id));
        return;
    }

    Log(
        "Multiplayer level-up native picker choice rejected locally. offer_id=" +
        std::to_string(offer.offer_id) +
        " option_index=" + std::to_string(selected_option_index) +
        " option_id=" + std::to_string(selected_option_id) +
        " error=" + error_message);
}
