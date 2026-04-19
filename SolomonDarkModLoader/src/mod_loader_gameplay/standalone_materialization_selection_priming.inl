bool PrimeGameplaySlotBotSelectionState(
    uintptr_t actor_address,
    uintptr_t progression_address,
    int slot_index,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 || progression_address == 0 || slot_index < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot selection prime requires a live actor, progression object, and slot index.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto choice_ids = ResolveProfileAppearanceChoiceIds(character_profile);
    const auto selection_state = ResolveProfileSelectionState(character_profile);
    const auto apply_choice_address = memory.ResolveGameAddressOrZero(kPlayerAppearanceApplyChoice);
    if (apply_choice_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerAppearance_ApplyChoice.";
        }
        return false;
    }

    const auto apply_choice = [&](int choice_id, int ensure_assets, const char* label) {
        DWORD exception_code = 0;
        if (CallPlayerAppearanceApplyChoiceSafe(
                apply_choice_address,
                progression_address,
                choice_id,
                ensure_assets,
                &exception_code)) {
            return true;
        }
        if (error_message != nullptr) {
            *error_message =
                std::string("PlayerAppearance_ApplyChoice failed for ") + label +
                " with 0x" + HexString(exception_code) + ".";
        }
        return false;
    };

    if (!apply_choice(choice_ids.primary_a, 0, "primary_a") ||
        !apply_choice(choice_ids.primary_b, 0, "primary_b") ||
        !apply_choice(choice_ids.primary_c, 0, "primary_c")) {
        return false;
    }

    if (!memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearancePrimaryAOffset,
            static_cast<std::int32_t>(choice_ids.primary_a)) ||
        !memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearancePrimaryBOffset,
            static_cast<std::int32_t>(choice_ids.primary_b)) ||
        !memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearancePrimaryCOffset,
            static_cast<std::int32_t>(choice_ids.primary_c))) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to mirror the primary wizard appearance ids into the slot progression object.";
        }
        return false;
    }

    if (!apply_choice(choice_ids.secondary, 1, "secondary")) {
        return false;
    }

    if (!TryWriteGameplaySelectionStateForSlot(slot_index, selection_state, error_message)) {
        return false;
    }

    const auto animation_selection_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    if (animation_selection_state_address != 0) {
        (void)memory.TryWriteValue(animation_selection_state_address, selection_state);
    }
    Log(
        "[bots] visual stage=selection_pre_refresh bot={" +
        BuildActorVisualDebugSummary(actor_address) +
        "} progression=" + HexString(progression_address) +
        " choice_ids=" + std::to_string(choice_ids.primary_a) + "/" +
        std::to_string(choice_ids.primary_b) + "/" +
        std::to_string(choice_ids.primary_c) + "/" +
        std::to_string(choice_ids.secondary));

    if (!PrimeStandaloneWizardProgressionSelectionState(
            progression_address,
            selection_state,
            error_message)) {
        return false;
    }

    const auto refresh_progression_address = memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
    if (refresh_progression_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve ActorProgressionRefresh.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallActorProgressionRefreshSafe(
            refresh_progression_address,
            actor_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Actor progression refresh failed with 0x" + HexString(exception_code) + ".";
        }
        return false;
    }

    if (!memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearanceSecondaryOffset,
            static_cast<std::int32_t>(choice_ids.secondary))) {
        if (error_message != nullptr) {
            *error_message = "Failed to mirror the secondary wizard appearance id into the slot progression object.";
        }
        return false;
    }

    if (animation_selection_state_address != 0) {
        (void)memory.TryWriteValue(animation_selection_state_address, selection_state);
    }
    if (!TryWriteActorAnimationStateIdDirect(actor_address, selection_state)) {
        Log(
            "[bots] gameplay-slot actor animation prime skipped. actor=" + HexString(actor_address) +
            " desired=" + std::to_string(selection_state));
    }
    ApplyStandaloneWizardPuppetDriveState(nullptr, actor_address, false);
    Log(
        "[bots] visual stage=selection_post_refresh bot={" +
        BuildActorVisualDebugSummary(actor_address) +
        "} progression=" + HexString(progression_address) +
        " selection_state=" + std::to_string(selection_state));
    return true;
}

bool PrimeStandaloneWizardProgressionSelectionState(
    uintptr_t progression_inner_address,
    int selection_state,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection_state < 0) {
        return true;
    }
    if (progression_inner_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Standalone progression selection prime requires a live runtime object.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto progression_table_address = memory.ReadFieldOr<uintptr_t>(
        progression_inner_address,
        kStandaloneWizardProgressionTableBaseOffset,
        0);
    const auto progression_table_count = memory.ReadFieldOr<int>(
        progression_inner_address,
        kStandaloneWizardProgressionTableCountOffset,
        0);
    if (progression_table_address == 0 || progression_table_count <= selection_state) {
        if (error_message != nullptr) {
            *error_message =
                "Standalone progression selection table is unavailable for state=" +
                std::to_string(selection_state) + ".";
        }
        return false;
    }

    const auto selection_offset =
        static_cast<std::size_t>(selection_state) * kStandaloneWizardProgressionEntryStride;
    if (!memory.TryWriteField<std::uint16_t>(
            progression_table_address,
            selection_offset + kStandaloneWizardProgressionActiveFlagOffset,
            1) ||
        !memory.TryWriteField<std::uint16_t>(
            progression_table_address,
            selection_offset + kStandaloneWizardProgressionVisibleFlagOffset,
            1)) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to mark standalone progression state=" + std::to_string(selection_state) +
                " as active.";
        }
        return false;
    }

    return true;
}

