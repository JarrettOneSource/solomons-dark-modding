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
    Log(
        "[bots] selection_prime entry actor=" + HexString(actor_address) +
        " slot=" + std::to_string(slot_index) +
        " param_prog=" + HexString(progression_address) +
        " actor_prog_runtime=" + HexString(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
        " actor_prog_handle=" + HexString(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0)) +
        " actor_prog_inner=" + HexString(ReadSmartPointerInnerObject(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0))) +
        " slot_prog=" + HexString(slot_progression_wrapper) +
        " slot_prog_inner=" + HexString(slot_progression_inner));

    // Gameplay_CreatePlayerSlot allocates a fresh PlayerProgression, but the
    // stock "new character" flow (FUN_005D0290) is what actually grows the
    // appearance table vector at progression+0x20 before calling
    // PlayerAppearance_ApplyChoice. For arena bots we skip ApplyChoice — the
    // slot's appearance vector is empty, so ApplyChoice(choice_id >= table_count)
    // access-violates inside the grow path. Direct writes to the choice-id
    // fields plus ActorProgressionRefresh downstream give us the same observable
    // progression state, and the actor's visuals come from the cloned source
    // descriptor seeded by SeedGameplaySlotBotRenderStateFromSourceActor, which
    // does not require ApplyChoice to have run.
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

    if (!TryWriteGameplaySelectionStateForSlot(slot_index, selection_state, error_message)) {
        return false;
    }
    (void)TryWriteActorAnimationStateIdDirect(actor_address, selection_state);

    const auto animation_selection_state_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
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

    if (!memory.TryWriteField(
            progression_address,
            kPlayerProgressionAppearanceSecondaryOffset,
            static_cast<std::int32_t>(choice_ids.secondary))) {
        if (error_message != nullptr) {
            *error_message = "Failed to mirror the secondary wizard appearance id into the slot progression object.";
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
    Log(
        "[bots] visual stage=selection_post_refresh bot={" +
        BuildActorVisualDebugSummary(actor_address) +
        "} progression=" + HexString(progression_address) +
        " selection_state=" + std::to_string(selection_state) +
        " primary_spell_id=" + std::to_string(resolved_primary_skill_id));
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
