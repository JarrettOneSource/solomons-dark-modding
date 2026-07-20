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

    std::lock_guard<std::recursive_mutex> picker_lock(
        g_local_level_up_picker_mutex);
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

    std::string option_roll_error;
    if (!ArmLocalLevelUpOptionRoll(
            player_state.progression_address,
            offer,
            &option_roll_error)) {
        if (allow_native_create) {
            Log(
                "Multiplayer level-up native picker waiting for authoritative visual identity. offer_id=" +
                std::to_string(offer.offer_id) +
                " progression=" + HexString(player_state.progression_address) +
                " error=" + option_roll_error);
        }
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
