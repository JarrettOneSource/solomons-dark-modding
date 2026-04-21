bool PrimeGameplaySlotBotActor(
    uintptr_t gameplay_address,
    uintptr_t world_address,
    int slot_index,
    uintptr_t actor_address,
    uintptr_t slot_progression_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    float x,
    float y,
    float heading,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (gameplay_address == 0 || world_address == 0 || actor_address == 0 ||
        slot_index < 0 || slot_progression_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Gameplay-slot priming requires a live gameplay scene, world, slot index, actor, and slot progression runtime.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();

    const auto log_prime_state = [&](std::string_view label) {
        const auto actor_slot_offset =
            kGameplayPlayerActorOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
        const auto progression_slot_offset =
            kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(slot_index) * kGameplayPlayerSlotStride;
        const auto slot_actor =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
        const auto slot_progression_wrapper =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, progression_slot_offset, 0);
        const auto slot_progression_inner =
            ReadSmartPointerInnerObject(slot_progression_wrapper);
        Log(
            "[bots] prime_slot_actor " + std::string(label) +
            " gameplay=" + HexString(gameplay_address) +
            " slot=" + std::to_string(slot_index) +
            " param_prog=" + HexString(slot_progression_address) +
            " slot_actor=" + HexString(slot_actor) +
            " slot_prog=" + HexString(slot_progression_wrapper) +
            " slot_prog_inner=" + HexString(slot_progression_inner) +
            " actor_prog_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0)) +
            " actor_prog_inner=" + HexString(ReadSmartPointerInnerObject(
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0))) +
            " actor_prog_runtime=" + HexString(
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
            " actor_equip_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0)) +
            " actor_selection=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)));
    };
    log_prime_state("enter");

    const auto ensure_progression_handle_address =
        memory.ResolveGameAddressOrZero(kPlayerActorEnsureProgressionHandle);
    if (ensure_progression_handle_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerActor_EnsureProgressionHandleFromGameplaySlot.";
        }
        return false;
    }
    {
        DWORD exception_code = 0;
        if (!CallPlayerActorEnsureProgressionHandleSafe(
                ensure_progression_handle_address,
                actor_address,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "PlayerActor_EnsureProgressionHandleFromGameplaySlot failed with 0x" +
                    HexString(exception_code) + ".";
            }
            return false;
        }
    }

    const auto refresh_runtime_handles_address =
        memory.ResolveGameAddressOrZero(kPlayerActorRefreshRuntimeHandles);
    if (refresh_runtime_handles_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve PlayerActor_RefreshRuntimeHandles.";
        }
        return false;
    }
    {
        DWORD exception_code = 0;
        if (!CallPlayerActorRefreshRuntimeHandlesSafe(
                refresh_runtime_handles_address,
                actor_address,
                &exception_code)) {
            if (error_message != nullptr) {
                *error_message =
                    "PlayerActor_RefreshRuntimeHandles failed with 0x" +
                    HexString(exception_code) + ".";
            }
            return false;
        }
    }

    const auto equip_handle_after_refresh =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
    if (equip_handle_after_refresh == 0) {
        std::string stage_error;
        if (!WireGameplaySlotBotRuntimeHandles(actor_address, &stage_error)) {
            if (error_message != nullptr) {
                *error_message = stage_error;
            }
            return false;
        }
    }

    {
        std::string stage_error;
        if (!SeedGameplaySlotBotRenderStateFromSourceActor(
                actor_address,
                world_address,
                character_profile,
                x,
                y,
                heading,
                &stage_error)) {
            if (error_message != nullptr) {
                *error_message = stage_error;
            }
            return false;
        }
    }

    {
        std::string stage_error;
        if (!AttachGameplaySlotBotStaffItem(actor_address, &stage_error)) {
            if (error_message != nullptr) {
                *error_message = stage_error;
            }
            return false;
        }
    }

    {
        std::string stage_error;
        if (!PrimeGameplaySlotBotSelectionState(
                actor_address,
                slot_progression_address,
                slot_index,
                character_profile,
                &stage_error)) {
            if (error_message != nullptr) {
                *error_message = stage_error;
            }
            return false;
        }
    }

    (void)memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    (void)memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);

    log_prime_state("exit");
    return true;
}

int ResolveStandaloneWizardRenderSelectionIndex(int wizard_id) {
    // `actor/source +0x23F` is the coarse selector byte consumed by the stock
    // clone/render bridge:
    //   0 -> 0x08, 1 -> 0x10, 2 -> 0x18, 3 -> 0x20, 4 -> 0x28.
    // Keep the public bot element ids aligned to the user-facing colors:
    //   fire, water, earth, air, ether.
    switch ((std::max)(0, (std::min)(wizard_id, 4))) {
    case 0: // Fire
        return 1;
    case 1: // Water
        return 3;
    case 2: // Earth
        return 4;
    case 3: // Air
        return 2;
    case 4: // Ether
    default:
        return 0;
    }
}

int ResolveStandaloneWizardSelectionState(int wizard_id) {
    // Convert the coarse selector byte back through the stock clone mapping so
    // source-profile staging and concrete actor selection stay on the same
    // element branch.
    switch (ResolveStandaloneWizardRenderSelectionIndex(wizard_id)) {
    case 0:
        return 0x08;
    case 1:
        return 0x10;
    case 2:
        return 0x18;
    case 3:
        return 0x20;
    case 4:
        return 0x28;
    default:
        return kStandaloneWizardHiddenSelectionState;
    }
}

int ResolveProfileSelectionState(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return ResolveStandaloneWizardSelectionState(ResolveProfileElementId(character_profile));
}

float EncodeSkillsWizardSelectionArg(int selection_value) {
    std::uint32_t bits = static_cast<std::uint32_t>(selection_value);
    float encoded = 0.0f;
    std::memcpy(&encoded, &bits, sizeof(encoded));
    return encoded;
}

bool TryResolvePrimarySpellIdFromSelectionPair(
    int primary_entry_index,
    int combo_entry_index,
    int* skill_id) {
    if (skill_id == nullptr) {
        return false;
    }

    *skill_id = -1;
    auto Matches = [&](int a, int b) {
        return primary_entry_index == a && combo_entry_index == b;
    };

    if (Matches(0x08, 0x10) || Matches(0x10, 0x08)) {
        *skill_id = 1000;
    } else if (Matches(0x08, 0x18) || Matches(0x18, 0x08)) {
        *skill_id = 0x3EA;
    } else if (Matches(0x08, 0x20) || Matches(0x20, 0x08)) {
        *skill_id = 0x3E9;
    } else if (Matches(0x08, 0x28) || Matches(0x28, 0x08)) {
        *skill_id = 0x3EE;
    } else if (Matches(0x10, 0x18) || Matches(0x18, 0x10)) {
        *skill_id = 0x3EB;
    } else if (Matches(0x10, 0x20) || Matches(0x20, 0x10)) {
        *skill_id = 0x3ED;
    } else if (Matches(0x10, 0x28) || Matches(0x28, 0x10)) {
        *skill_id = 0x3EF;
    } else if (Matches(0x18, 0x20) || Matches(0x20, 0x18)) {
        *skill_id = 0x3EC;
    } else if (Matches(0x18, 0x28) || Matches(0x28, 0x18)) {
        *skill_id = 0x3F1;
    } else if (Matches(0x20, 0x28) || Matches(0x28, 0x20)) {
        *skill_id = 0x3F0;
    } else if (Matches(0x08, 0x08)) {
        *skill_id = 0x3F2;
    } else if (Matches(0x10, 0x10)) {
        *skill_id = 0x3F3;
    } else if (Matches(0x18, 0x18)) {
        *skill_id = 0x3F5;
    } else if (Matches(0x20, 0x20)) {
        *skill_id = 0x3F4;
    } else if (Matches(0x28, 0x28)) {
        *skill_id = 0x3F6;
    }

    return *skill_id > 0;
}

bool TryResolveProfilePrimarySelectionPair(
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    int* primary_entry_index,
    int* combo_entry_index,
    int* skill_id) {
    if (primary_entry_index == nullptr || combo_entry_index == nullptr || skill_id == nullptr) {
        return false;
    }

    const auto default_entry_index = ResolveProfileSelectionState(character_profile);
    const auto requested_primary =
        character_profile.loadout.primary_entry_index >= 0
            ? character_profile.loadout.primary_entry_index
            : default_entry_index;
    const auto requested_combo =
        character_profile.loadout.primary_combo_entry_index >= 0
            ? character_profile.loadout.primary_combo_entry_index
            : requested_primary;

    *primary_entry_index = requested_primary;
    *combo_entry_index = requested_combo;
    return TryResolvePrimarySpellIdFromSelectionPair(
        requested_primary,
        requested_combo,
        skill_id);
}

bool ApplyProfilePrimaryLoadoutToSkillsWizard(
    uintptr_t progression_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    int* resolved_skill_id,
    std::string* error_message) {
    if (resolved_skill_id != nullptr) {
        *resolved_skill_id = -1;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Skills_Wizard loadout projection requires a live progression runtime.";
        }
        return false;
    }

    int primary_entry_index = -1;
    int combo_entry_index = -1;
    int skill_id = -1;
    if (!TryResolveProfilePrimarySelectionPair(
            character_profile,
            &primary_entry_index,
            &combo_entry_index,
            &skill_id)) {
        if (error_message != nullptr) {
            *error_message =
                "Profile primary loadout does not resolve to a stock spell pair. primary=" +
                std::to_string(primary_entry_index) +
                " combo=" + std::to_string(combo_entry_index);
        }
        return false;
    }

    Log(
        "[bots] skills_wizard_loadout begin progression=" + HexString(progression_address) +
        " primary_entry=" + std::to_string(primary_entry_index) +
        " combo_entry=" + std::to_string(combo_entry_index) +
        " spell_id=" + std::to_string(skill_id));

    auto& memory = ProcessMemory::Instance();
    const auto build_primary_spell_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardBuildPrimarySpell);
    if (build_primary_spell_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Skills_Wizard primary spell builder.";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallSkillsWizardBuildPrimarySpellSafe(
            build_primary_spell_address,
            progression_address,
            EncodeSkillsWizardSelectionArg(primary_entry_index),
            EncodeSkillsWizardSelectionArg(combo_entry_index),
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard primary spell builder failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }

    if (resolved_skill_id != nullptr) {
        *resolved_skill_id = skill_id;
    }
    return true;
}
