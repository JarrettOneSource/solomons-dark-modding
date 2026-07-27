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
