int NativeSkillRowForDiscipline(
    multiplayer::CharacterDisciplineId discipline_id) {
    switch (discipline_id) {
    case multiplayer::CharacterDisciplineId::Mind:
        return 6;
    case multiplayer::CharacterDisciplineId::Body:
        return 5;
    case multiplayer::CharacterDisciplineId::Arcane:
        return 7;
    }
    return -1;
}

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
    if (slot_progression_inner == 0 ||
        slot_progression_inner != progression_address) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot bot progression is not the bot's slot-owned native book.";
        }
        return false;
    }

    // Gameplay_CreatePlayerSlot allocates a fresh PlayerProgression, but the
    // late bot-clone path skips the stock new-character selection block.
    // Slot bot visuals are seeded from the native source-profile builder; only
    // mirror explicit profile choices when the profile already owns them, and
    // never invent synthetic appearance ids here.
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

    const auto discipline_skill_row =
        NativeSkillRowForDiscipline(character_profile.discipline_id);
    if (discipline_skill_row < 0) {
        if (error_message != nullptr) {
            *error_message =
                "Unable to resolve the bot's native Discipline choice.";
        }
        return false;
    }
    if (!PrimeGameplaySlotBotBaseBookState(
            progression_address,
            discipline_skill_row,
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

bool PrimeGameplaySlotBotBaseBookState(
    uintptr_t progression_inner_address,
    int discipline_skill_row,
    std::string* error_message) {
    constexpr int kStockBaseBookRowCount = 8;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_inner_address == 0 ||
        discipline_skill_row < 5 ||
        discipline_skill_row > 7) {
        if (error_message != nullptr) {
            *error_message =
                "Bot base-book prime requires a live progression and native Discipline row.";
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
            *error_message = "Bot base-book table fields are unreadable.";
        }
        return false;
    }
    if (progression_table_address == 0 ||
        progression_table_count < kStockBaseBookRowCount) {
        if (error_message != nullptr) {
            *error_message = "Bot base-book table does not contain the stock rows 0..7.";
        }
        return false;
    }

    for (int row = 0; row < kStockBaseBookRowCount; ++row) {
        const auto entry_address =
            progression_table_address +
            static_cast<std::size_t>(row) *
                kStandaloneWizardProgressionEntryStride;
        std::int16_t internal_id = -1;
        uintptr_t statbook_address = 0;
        std::int32_t maximum_rank = 0;
        if (!memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionEntryInternalIdOffset,
                &internal_id) ||
            !memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionEntryStatbookOffset,
                &statbook_address) ||
            statbook_address == 0 ||
            !memory.TryReadField(
                statbook_address,
                kStatbookMaxLevelOffset,
                &maximum_rank) ||
            internal_id != row ||
            maximum_rank < 1) {
            if (error_message != nullptr) {
                *error_message =
                    "Bot base-book row " + std::to_string(row) +
                    " does not match a rankable native definition.";
            }
            return false;
        }
    }

    for (int row = 0; row < kStockBaseBookRowCount; ++row) {
        const auto entry_address =
            progression_table_address +
            static_cast<std::size_t>(row) *
                kStandaloneWizardProgressionEntryStride;
        if (!memory.TryWriteField<std::uint16_t>(
                entry_address,
                kStandaloneWizardProgressionActiveFlagOffset,
                1)) {
            if (error_message != nullptr) {
                *error_message =
                    "Failed to prime native base-book row " +
                    std::to_string(row) + ".";
            }
            return false;
        }
    }
    if (!memory.TryWriteField<std::int32_t>(
            progression_inner_address,
            kPlayerProgressionDisciplineSkillRowOffset,
            discipline_skill_row)) {
        if (error_message != nullptr) {
            *error_message =
                "Failed to publish the bot's selected native Discipline row.";
        }
        return false;
    }

    for (int row = 0; row < kStockBaseBookRowCount; ++row) {
        const auto entry_address =
            progression_table_address +
            static_cast<std::size_t>(row) *
                kStandaloneWizardProgressionEntryStride;
        std::uint16_t active = 0;
        if (!memory.TryReadField(
                entry_address,
                kStandaloneWizardProgressionActiveFlagOffset,
                &active) ||
            active != 1) {
            if (error_message != nullptr) {
                *error_message =
                    "Native base-book verification failed for row " +
                    std::to_string(row) + ".";
            }
            return false;
        }
    }
    std::int32_t selected_row = -1;
    if (!memory.TryReadField(
            progression_inner_address,
            kPlayerProgressionDisciplineSkillRowOffset,
            &selected_row) ||
        selected_row != discipline_skill_row) {
        if (error_message != nullptr) {
            *error_message = "Native Discipline selection verification failed.";
        }
        return false;
    }
    return true;
}
