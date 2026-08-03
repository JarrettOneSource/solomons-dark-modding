bool TryResolveSemanticElementFromNativeRoot(
    std::int32_t native_root,
    std::int32_t* element_id) {
    if (element_id == nullptr) {
        return false;
    }

    switch (native_root) {
    case 0:
        *element_id = 4;
        return true;
    case 1:
        *element_id = 0;
        return true;
    case 2:
        *element_id = 3;
        return true;
    case 3:
        *element_id = 1;
        return true;
    case 4:
        *element_id = 2;
        return true;
    default:
        return false;
    }
}

bool TryResolveSemanticDisciplineFromNativeRoot(
    std::int32_t native_root,
    CharacterDisciplineId* discipline_id) {
    if (discipline_id == nullptr) {
        return false;
    }

    switch (native_root) {
    case 5:
        *discipline_id = CharacterDisciplineId::Body;
        return true;
    case 6:
        *discipline_id = CharacterDisciplineId::Mind;
        return true;
    case 7:
        *discipline_id = CharacterDisciplineId::Arcane;
        return true;
    default:
        return false;
    }
}

bool TryApplyLiveNativeLoadoutSelectionToProfile(
    uintptr_t progression_address,
    MultiplayerCharacterProfile* profile) {
    if (progression_address == 0 || profile == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::int32_t element_skill_row = -1;
    std::int32_t discipline_skill_row = -1;
    std::int32_t primary_skill_row = -1;
    std::int32_t secondary_skill_row = -1;
    if (!memory.TryReadField(
            progression_address,
            kPlayerProgressionElementSkillRowOffset,
            &element_skill_row) ||
        !memory.TryReadField(
            progression_address,
            kPlayerProgressionDisciplineSkillRowOffset,
            &discipline_skill_row) ||
        !memory.TryReadField(
            progression_address,
            kPlayerProgressionPrimarySkillRowOffset,
            &primary_skill_row) ||
        !memory.TryReadField(
            progression_address,
            kPlayerProgressionSecondarySkillRowOffset,
            &secondary_skill_row)) {
        return false;
    }

    std::int32_t element_id = -1;
    CharacterDisciplineId discipline_id = CharacterDisciplineId::Arcane;
    if (!TryResolveSemanticElementFromNativeRoot(
            element_skill_row,
            &element_id) ||
        !TryResolveSemanticDisciplineFromNativeRoot(
            discipline_skill_row,
            &discipline_id)) {
        return false;
    }

    int expected_primary_skill_row = -1;
    if (!TryResolveNativePrimaryEntryForElement(
            element_id,
            &expected_primary_skill_row) ||
        primary_skill_row != expected_primary_skill_row) {
        return false;
    }

    int expected_secondary_skill_row = -1;
    switch (element_id) {
    case 0:
        expected_secondary_skill_row = 21;
        break;
    case 1:
        expected_secondary_skill_row = 35;
        break;
    case 2:
        expected_secondary_skill_row = 45;
        break;
    case 3:
        expected_secondary_skill_row = 27;
        break;
    case 4:
        expected_secondary_skill_row = 11;
        break;
    default:
        return false;
    }
    if (secondary_skill_row != expected_secondary_skill_row) {
        return false;
    }

    auto updated = *profile;
    updated.appearance.choice_ids = {
        element_skill_row,
        discipline_skill_row,
        primary_skill_row,
        secondary_skill_row,
    };
    updated.element_id = element_id;
    updated.discipline_id = discipline_id;
    updated.loadout.primary_entry_index = primary_skill_row;
    updated.loadout.primary_combo_entry_index = primary_skill_row;
    if (!IsValidCharacterProfile(updated)) {
        return false;
    }

    *profile = updated;
    return true;
}

bool TryApplyLivePrimarySelectionToProfile(
    const SDModGameplaySelectionDebugState& selection_state,
    MultiplayerCharacterProfile* profile) {
    if (profile == nullptr || !selection_state.valid) {
        return false;
    }

    const auto selected_primary_entry = selection_state.slot_selection_entries[0];
    int element_id = -1;
    switch (selected_primary_entry) {
    case 0x10:
        element_id = 0;
        break;
    case 0x20:
        element_id = 1;
        break;
    case 0x28:
        element_id = 2;
        break;
    case 0x18:
        element_id = 3;
        break;
    case 0x08:
        element_id = 4;
        break;
    default:
        break;
    }
    if (element_id < 0) {
        return false;
    }

    auto updated = *profile;
    updated.element_id = element_id;

    int resolved_primary_entry = -1;
    NativePrimarySpellSelection primary_selection;
    if (TryResolveNativePrimarySelectionFromPair(
            selected_primary_entry,
            selected_primary_entry,
            &primary_selection)) {
        resolved_primary_entry = selected_primary_entry;
    } else if (!TryResolveNativePrimaryEntryForElement(element_id, &resolved_primary_entry)) {
        return false;
    }

    updated.loadout.primary_entry_index = resolved_primary_entry;
    updated.loadout.primary_combo_entry_index = resolved_primary_entry;

    if (!IsValidCharacterProfile(updated)) {
        return false;
    }

    *profile = updated;
    return true;
}
bool TryApplyLiveBeltSkillLoadoutToProfile(MultiplayerCharacterProfile* profile) {
    if (profile == nullptr || kGameObjectGlobal == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto game_object_global_address =
        memory.ResolveGameAddressOrZero(kGameObjectGlobal);
    uintptr_t gameplay_address = 0;
    if (game_object_global_address == 0 ||
        !memory.TryReadValue(game_object_global_address, &gameplay_address) ||
        gameplay_address == 0) {
        return false;
    }

    auto secondary_entries = profile->loadout.secondary_entry_indices;
    for (std::size_t slot = 0; slot < secondary_entries.size(); ++slot) {
        const auto button_address =
            gameplay_address + kGameplayBeltButtonArrayOffset +
            slot * kGameplayBeltButtonStride;
        std::uint32_t button_type = 0;
        std::int32_t skill_entry_index = -1;
        if (!memory.TryReadField(button_address, kBeltButtonTypeOffset, &button_type) ||
            !memory.TryReadField(
                button_address,
                kBeltButtonSkillEntryIndexOffset,
                &skill_entry_index)) {
            return false;
        }
        secondary_entries[slot] =
            button_type == kBeltButtonSkillTypeId &&
                    skill_entry_index >= 0 &&
                    skill_entry_index <
                        static_cast<std::int32_t>(kParticipantProgressionBookSnapshotMaxEntries)
                ? skill_entry_index
                : -1;
    }

    profile->loadout.secondary_entry_indices = secondary_entries;
    return true;
}
