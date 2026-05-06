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
        const auto unreadable = []() { return std::string("unreadable"); };
        const auto field_ptr = [&](uintptr_t base, std::size_t offset, uintptr_t* value) -> std::string {
            *value = 0;
            return memory.TryReadField(base, offset, value)
                ? HexString(*value)
                : unreadable();
        };
        uintptr_t slot_actor = 0;
        uintptr_t slot_progression_wrapper = 0;
        uintptr_t actor_progression_handle = 0;
        uintptr_t actor_progression_runtime = 0;
        uintptr_t actor_equip_handle = 0;
        uintptr_t actor_selection = 0;
        const auto slot_actor_text = field_ptr(gameplay_address, actor_slot_offset, &slot_actor);
        const auto slot_progression_wrapper_text =
            field_ptr(gameplay_address, progression_slot_offset, &slot_progression_wrapper);
        const auto slot_progression_inner = ReadSmartPointerInnerObject(slot_progression_wrapper);
        const auto actor_progression_handle_text =
            field_ptr(actor_address, kActorProgressionHandleOffset, &actor_progression_handle);
        const auto actor_progression_runtime_text =
            field_ptr(actor_address, kActorProgressionRuntimeStateOffset, &actor_progression_runtime);
        const auto actor_equip_handle_text =
            field_ptr(actor_address, kActorEquipHandleOffset, &actor_equip_handle);
        const auto actor_selection_text =
            field_ptr(actor_address, kActorAnimationSelectionStateOffset, &actor_selection);
        Log(
            "[bots] prime_slot_actor " + std::string(label) +
            " gameplay=" + HexString(gameplay_address) +
            " slot=" + std::to_string(slot_index) +
            " param_prog=" + HexString(slot_progression_address) +
            " slot_actor=" + slot_actor_text +
            " slot_prog=" + slot_progression_wrapper_text +
            " slot_prog_inner=" + HexString(slot_progression_inner) +
            " actor_prog_handle=" + actor_progression_handle_text +
            " actor_prog_inner=" + HexString(ReadSmartPointerInnerObject(actor_progression_handle)) +
            " actor_prog_runtime=" + actor_progression_runtime_text +
            " actor_equip_handle=" + actor_equip_handle_text +
            " actor_selection=" + actor_selection_text);
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

    uintptr_t equip_handle_after_refresh = 0;
    if (!memory.TryReadField(actor_address, kActorEquipHandleOffset, &equip_handle_after_refresh)) {
        if (error_message != nullptr) {
            *error_message = "Actor equip handle unreadable after runtime handle refresh.";
        }
        return false;
    }
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
        uintptr_t native_visual_actor_address = 0;
        if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &native_visual_actor_address) ||
            native_visual_actor_address == 0) {
            if (error_message != nullptr) {
                *error_message = "Unable to resolve slot-0 native visual source actor.";
            }
            return false;
        }

        std::string stage_error;
        if (!SeedGameplaySlotBotRenderStateFromSourceActor(
                actor_address,
                world_address,
                native_visual_actor_address,
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
    ApplyWizardActorFacingState(actor_address, heading);

    if (!EnsureBotOwnedProgressionMode(slot_progression_address, "gameplay_slot_prime")) {
        if (error_message != nullptr) {
            *error_message = "Gameplay-slot bot progression could not be marked as bot-owned non-local mode.";
        }
        return false;
    }

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
    const auto primary_entry = ResolveNativePrimaryEntryForElement(wizard_id);
    return primary_entry >= 0 ? primary_entry : kStandaloneWizardHiddenSelectionState;
}

int ResolveProfileSelectionState(const multiplayer::MultiplayerCharacterProfile& character_profile) {
    return ResolveStandaloneWizardSelectionState(character_profile.element_id);
}

struct ResolvedPrimaryCastDescriptor {
    ParticipantEntityBinding::OngoingCastState::Lane lane =
        ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher;
    int primary_entry_index = -1;
    int combo_entry_index = -1;
    int build_skill_id = -1;
    int dispatcher_skill_id = 0;
    int selection_state = kUnknownAnimationStateId;
};

bool TryResolvePrimaryCastDescriptorFromSelectionPair(
    int primary_entry_index,
    int combo_entry_index,
    int build_skill_id,
    ResolvedPrimaryCastDescriptor* descriptor) {
    if (descriptor == nullptr) {
        return false;
    }

    NativePrimarySpellSelection selection{};
    if (!TryResolveNativePrimarySelectionFromPair(
            primary_entry_index,
            combo_entry_index,
            &selection)) {
        return false;
    }

    *descriptor = ResolvedPrimaryCastDescriptor{};
    descriptor->primary_entry_index = primary_entry_index;
    descriptor->combo_entry_index = combo_entry_index;
    descriptor->build_skill_id = build_skill_id;

    auto Matches = [&](int a, int b) {
        return primary_entry_index == a && combo_entry_index == b;
    };

    if (Matches(0x08, 0x08) || Matches(0x10, 0x10)) {
        descriptor->lane = ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
        descriptor->selection_state = primary_entry_index;
        descriptor->dispatcher_skill_id = 0;
        return true;
    }
    if (Matches(0x18, 0x18) || Matches(0x20, 0x20) || Matches(0x28, 0x28)) {
        // Stock keeps actor+0x270 as the element selection state here. The
        // runtime dispatcher handles Air/Water/Earth primaries at 0x18/0x20/0x28,
        // while the Skills_Wizard build id is only the loadout/progression id.
        descriptor->lane = ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher;
        descriptor->selection_state = primary_entry_index;
        descriptor->dispatcher_skill_id = primary_entry_index;
        return true;
    }

    descriptor->lane = ParticipantEntityBinding::OngoingCastState::Lane::Dispatcher;
    if (build_skill_id <= 0) {
        return false;
    }
    descriptor->dispatcher_skill_id = build_skill_id;
    descriptor->selection_state = kPrimaryComboDispatcherSelectionState;
    return true;
}

bool TryResolvePrimaryCastDescriptorFromSkillId(
    uintptr_t progression_runtime_address,
    int skill_id,
    ResolvedPrimaryCastDescriptor* descriptor) {
    NativePrimarySpellSelection selection{};
    std::string selection_error;
    if (!TryResolveNativePrimarySelectionFromSkillId(
            progression_runtime_address,
            skill_id,
            &selection,
            &selection_error)) {
        return false;
    }

    return TryResolvePrimaryCastDescriptorFromSelectionPair(
        selection.primary_entry_index,
        selection.combo_entry_index,
        selection.build_skill_id,
        descriptor);
}

bool TryResolveProfilePrimaryCastDescriptor(
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    uintptr_t progression_runtime_address,
    ResolvedPrimaryCastDescriptor* descriptor) {
    if (descriptor == nullptr) {
        return false;
    }

    const auto default_entry_index =
        ResolveNativePrimaryEntryForElement(character_profile.element_id);
    const auto requested_primary =
        character_profile.loadout.primary_entry_index >= 0
            ? character_profile.loadout.primary_entry_index
            : default_entry_index;
    const auto requested_combo =
        character_profile.loadout.primary_combo_entry_index >= 0
            ? character_profile.loadout.primary_combo_entry_index
            : requested_primary;

    int build_skill_id = -1;
    NativePrimarySpellSelection live_selection{};
    std::string selection_error;
    if (progression_runtime_address != 0 &&
        TryResolveNativePrimarySelectionFromLiveProgression(
            progression_runtime_address,
            requested_primary,
            requested_combo,
            &live_selection,
            &selection_error)) {
        build_skill_id = live_selection.build_skill_id;
    }

    return TryResolvePrimaryCastDescriptorFromSelectionPair(
        requested_primary,
        requested_combo,
        build_skill_id,
        descriptor);
}

bool ApplyProfilePrimaryLoadoutToSkillsWizard(
    uintptr_t progression_address,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    int* resolved_skill_id,
    std::string* error_message) {
    constexpr bool kEnableNativeSkillsWizardPrimaryBuild = true;
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

    ResolvedPrimaryCastDescriptor descriptor{};
    if (!TryResolveProfilePrimaryCastDescriptor(character_profile, progression_address, &descriptor)) {
        if (error_message != nullptr) {
            *error_message =
                "Profile primary loadout does not resolve to a stock spell pair. primary=" +
                std::to_string(descriptor.primary_entry_index) +
                " combo=" + std::to_string(descriptor.combo_entry_index);
        }
        return false;
    }

    if (resolved_skill_id != nullptr) {
        *resolved_skill_id = descriptor.build_skill_id;
    }

    if (!kEnableNativeSkillsWizardPrimaryBuild) {
        Log(
            "[bots] skills_wizard_loadout native build skipped progression=" +
            HexString(progression_address) +
            " primary_entry=" + std::to_string(descriptor.primary_entry_index) +
            " combo_entry=" + std::to_string(descriptor.combo_entry_index) +
            " spell_id=" + std::to_string(descriptor.build_skill_id));
        return true;
    }

    Log(
        "[bots] skills_wizard_loadout begin progression=" + HexString(progression_address) +
        " primary_entry=" + std::to_string(descriptor.primary_entry_index) +
        " combo_entry=" + std::to_string(descriptor.combo_entry_index) +
        " spell_id=" + std::to_string(descriptor.build_skill_id));

    auto& memory = ProcessMemory::Instance();
    const auto build_primary_spell_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardBuildPrimarySpell);
    if (build_primary_spell_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Skills_Wizard primary spell builder.";
        }
        return false;
    }

    std::uint32_t native_spell_id = 0;
    DWORD exception_code = 0;
    if (!CallSkillsWizardBuildPrimarySpellSafe(
            build_primary_spell_address,
            progression_address,
            EncodeSkillsWizardSelectionArg(descriptor.primary_entry_index),
            EncodeSkillsWizardSelectionArg(descriptor.combo_entry_index),
            &native_spell_id,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard primary spell builder failed with 0x" +
                HexString(exception_code) + ".";
        }
        return false;
    }
    if (resolved_skill_id != nullptr && native_spell_id > 0) {
        *resolved_skill_id = static_cast<int>(native_spell_id);
    }

    return true;
}
