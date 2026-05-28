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
    const auto& choice_ids = character_profile.appearance.choice_ids;
    const auto selection_state = ResolveProfileSelectionState(character_profile);
    uintptr_t gameplay_address = 0;
    uintptr_t slot_progression_wrapper = 0;
    uintptr_t slot_progression_inner = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0) {
        (void)TryResolvePlayerProgressionHandleForSlot(
            gameplay_address,
            slot_index,
            &slot_progression_wrapper);
        slot_progression_inner = ReadSmartPointerInnerObject(slot_progression_wrapper);
    }
    uintptr_t actor_progression_runtime = 0;
    uintptr_t actor_progression_handle = 0;
    (void)memory.TryReadField(actor_address, kActorProgressionRuntimeStateOffset, &actor_progression_runtime);
    (void)memory.TryReadField(actor_address, kActorProgressionHandleOffset, &actor_progression_handle);
    Log(
        "[bots] selection_prime entry actor=" + HexString(actor_address) +
        " slot=" + std::to_string(slot_index) +
        " param_prog=" + HexString(progression_address) +
        " actor_prog_runtime=" + HexString(actor_progression_runtime) +
        " actor_prog_handle=" + HexString(actor_progression_handle) +
        " actor_prog_inner=" + HexString(ReadSmartPointerInnerObject(actor_progression_handle)) +
        " slot_prog=" + HexString(slot_progression_wrapper) +
        " slot_prog_inner=" + HexString(slot_progression_inner));

    // Gameplay_CreatePlayerSlot allocates a fresh PlayerProgression, but the
    // stock "new character" flow (FUN_005D0290) is what grows the appearance
    // table vector at progression+0x20 before PlayerAppearance_ApplyChoice.
    // Slot bot visuals are therefore seeded from the native visual snapshot
    // path; only mirror explicit profile choices when the profile already owns
    // them, and never invent synthetic appearance ids here.
    const bool has_primary_choice_ids =
        choice_ids[0] >= 0 && choice_ids[1] >= 0 && choice_ids[2] >= 0;
    if (has_primary_choice_ids) {
        if (!memory.TryWriteField<std::int32_t>(
                progression_address,
                kPlayerProgressionAppearancePrimaryAOffset,
                choice_ids[0]) ||
            !memory.TryWriteField<std::int32_t>(
                progression_address,
                kPlayerProgressionAppearancePrimaryBOffset,
                choice_ids[1]) ||
            !memory.TryWriteField<std::int32_t>(
                progression_address,
                kPlayerProgressionAppearancePrimaryCOffset,
                choice_ids[2])) {
            if (error_message != nullptr) {
                *error_message =
                    "Failed to mirror explicit primary wizard appearance ids into the slot progression object.";
            }
            return false;
        }
    }

    if (!TryWriteGameplaySelectionStateForSlot(slot_index, selection_state, error_message)) {
        return false;
    }
    (void)TryWriteActorAnimationStateIdDirect(actor_address, selection_state);

    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        Log(
            "[bots] visual stage=selection_pre_refresh bot={" +
            BuildActorVisualDebugSummary(actor_address) +
            "} progression=" + HexString(progression_address) +
            " choice_ids=" + std::to_string(choice_ids[0]) + "/" +
            std::to_string(choice_ids[1]) + "/" +
            std::to_string(choice_ids[2]) + "/" +
            std::to_string(choice_ids[3]));
    }

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

    int resolved_primary_skill_id = -1;
    std::string loadout_error;
    const auto loadout_ok =
        ApplyProfilePrimaryLoadoutToSkillsWizard(
            progression_address,
            character_profile,
            &resolved_primary_skill_id,
            &loadout_error);
    if (!loadout_ok) {
        if (error_message != nullptr) {
            *error_message = std::move(loadout_error);
        }
        return false;
    }

    if (choice_ids[3] >= 0) {
        if (!memory.TryWriteField<std::int32_t>(
                progression_address,
                kPlayerProgressionAppearanceSecondaryOffset,
                choice_ids[3])) {
            if (error_message != nullptr) {
                *error_message =
                    "Failed to mirror explicit secondary wizard appearance id into the slot progression object.";
            }
            return false;
        }
    }

    // The pure-primary builder mutates the progression runtime after the
    // initial refresh above. Re-run the stock progression refresh so the live
    // actor mirrors the rebuilt primary spell before any combat startup.
    exception_code = 0;
    if (!CallActorProgressionRefreshSafe(
            refresh_progression_address,
            actor_address,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Actor progression refresh (post primary build) failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    // Keep gameplay-slot actors on the stock slot-handle path for progression,
    // but preserve their owned selection/control object. Bots need an actor-
    // local selection brain so cast targeting and future per-participant
    // combat/loadout state do not collapse back through shared gameplay input
    // globals.
    (void)memory.TryWriteField<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    ApplyStandaloneWizardPuppetDriveState(nullptr, actor_address, false);
    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        Log(
            "[bots] visual stage=selection_post_refresh bot={" +
            BuildActorVisualDebugSummary(actor_address) +
            "} progression=" + HexString(progression_address) +
            " selection_state=" + std::to_string(selection_state) +
            " primary_spell_id=" + std::to_string(resolved_primary_skill_id));
    }
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
    uintptr_t progression_table_address = 0;
    int progression_table_count = 0;
    if (!memory.TryReadField(
            progression_inner_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &progression_table_address) ||
        !memory.TryReadField(
            progression_inner_address,
            kStandaloneWizardProgressionTableCountOffset,
            &progression_table_count)) {
        if (error_message != nullptr) {
            *error_message = "Standalone progression selection table fields are unreadable.";
        }
        return false;
    }
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
