bool TryResolveNativePrimarySelectionFromPair(
    int primary_entry_index,
    int combo_entry_index,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr) {
        return false;
    }

    return FillNativePrimarySelection(
        primary_entry_index,
        combo_entry_index,
        -1,
        selection);
}

bool TryResolveNativePrimarySelectionFromSkillId(
    uintptr_t progression_runtime_address,
    int skill_id,
    NativePrimarySpellSelection* selection,
    std::string* error_message) {
    if (selection != nullptr) {
        *selection = NativePrimarySpellSelection{};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection == nullptr || skill_id <= 0) {
        if (error_message != nullptr) {
            *error_message = "native primary skill-id resolution requires a positive skill id";
        }
        return false;
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native primary skill-id resolution requires a live progression runtime";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto build_primary_spell_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardBuildPrimarySpell);
    if (build_primary_spell_address == 0) {
        if (error_message != nullptr) {
            *error_message = "unable to resolve Skills_Wizard primary spell builder";
        }
        return false;
    }

    std::int32_t previous_current_spell_id = 0;
    const bool have_previous_current_spell_id =
        TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &previous_current_spell_id);

    DWORD last_exception_code = 0;
    for (std::size_t primary_index = 0;
         primary_index < std::size(kNativePrimaryEntryIndices);
         ++primary_index) {
        for (std::size_t combo_index = primary_index;
             combo_index < std::size(kNativePrimaryEntryIndices);
             ++combo_index) {
            const auto primary_entry = kNativePrimaryEntryIndices[primary_index];
            const auto combo_entry = kNativePrimaryEntryIndices[combo_index];
            std::uint32_t native_spell_id = 0;
            DWORD exception_code = 0;
            if (!CallSkillsWizardBuildPrimarySpellSafe(
                    build_primary_spell_address,
                    progression_runtime_address,
                    EncodeSkillsWizardSelectionArg(primary_entry),
                    EncodeSkillsWizardSelectionArg(combo_entry),
                    &native_spell_id,
                    &exception_code)) {
                last_exception_code = exception_code;
                continue;
            }

            if (native_spell_id == 0) {
                std::int32_t current_spell_id = 0;
                if (TryReadProgressionCurrentSpellId(
                        progression_runtime_address,
                        &current_spell_id)) {
                    native_spell_id = static_cast<std::uint32_t>(current_spell_id);
                }
            }
            if (native_spell_id == static_cast<std::uint32_t>(skill_id) &&
                FillNativePrimarySelection(
                    primary_entry,
                    combo_entry,
                    skill_id,
                    selection)) {
                RestoreProgressionCurrentSpellIdIfNeeded(
                    progression_runtime_address,
                    have_previous_current_spell_id,
                    previous_current_spell_id);
                return true;
            }
        }
    }

    RestoreProgressionCurrentSpellIdIfNeeded(
        progression_runtime_address,
        have_previous_current_spell_id,
        previous_current_spell_id);
    if (error_message != nullptr) {
        *error_message =
            last_exception_code == 0
                ? "Skills_Wizard did not resolve the requested primary skill id"
                : "Skills_Wizard primary skill-id scan failed with 0x" +
                    std::to_string(last_exception_code);
    }
    return false;
}

bool TryResolveNativePrimarySelectionFromLiveProgression(
    uintptr_t progression_runtime_address,
    int primary_entry_index,
    int combo_entry_index,
    NativePrimarySpellSelection* selection,
    std::string* error_message) {
    if (selection != nullptr) {
        *selection = NativePrimarySpellSelection{};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (selection == nullptr ||
        !IsNativePrimaryEntryIndex(primary_entry_index) ||
        !IsNativePrimaryEntryIndex(combo_entry_index)) {
        if (error_message != nullptr) {
            *error_message = "native primary selection requires valid primary/combo entries";
        }
        return false;
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native primary selection requires a live progression runtime";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto build_primary_spell_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardBuildPrimarySpell);
    if (build_primary_spell_address == 0) {
        if (error_message != nullptr) {
            *error_message = "unable to resolve Skills_Wizard primary spell builder";
        }
        return false;
    }

    std::int32_t previous_current_spell_id = 0;
    const bool have_previous_current_spell_id =
        TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &previous_current_spell_id);

    std::uint32_t native_spell_id = 0;
    DWORD exception_code = 0;
    if (!CallSkillsWizardBuildPrimarySpellSafe(
            build_primary_spell_address,
            progression_runtime_address,
            EncodeSkillsWizardSelectionArg(primary_entry_index),
            EncodeSkillsWizardSelectionArg(combo_entry_index),
            &native_spell_id,
            &exception_code)) {
        RestoreProgressionCurrentSpellIdIfNeeded(
            progression_runtime_address,
            have_previous_current_spell_id,
            previous_current_spell_id);
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard primary selection failed with 0x" +
                std::to_string(exception_code);
        }
        return false;
    }
    if (native_spell_id == 0) {
        std::int32_t current_spell_id = 0;
        if (TryReadProgressionCurrentSpellId(progression_runtime_address, &current_spell_id)) {
            native_spell_id = static_cast<std::uint32_t>(current_spell_id);
        }
    }
    RestoreProgressionCurrentSpellIdIfNeeded(
        progression_runtime_address,
        have_previous_current_spell_id,
        previous_current_spell_id);

    if (native_spell_id == 0 ||
        !FillNativePrimarySelection(
            primary_entry_index,
            combo_entry_index,
            static_cast<int>(native_spell_id),
            selection)) {
        if (error_message != nullptr) {
            *error_message = "Skills_Wizard primary selection did not produce a spell id";
        }
        return false;
    }
    return true;
}

bool TryResolveNativePrimarySelectionForProfile(
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    NativePrimarySpellSelection* selection) {
    if (selection == nullptr) {
        return false;
    }

    const auto default_entry = ResolveNativePrimaryEntryForElement(character_profile.element_id);
    const auto primary_entry =
        character_profile.loadout.primary_entry_index >= 0
            ? character_profile.loadout.primary_entry_index
            : default_entry;
    const auto combo_entry =
        character_profile.loadout.primary_combo_entry_index >= 0
            ? character_profile.loadout.primary_combo_entry_index
            : primary_entry;
    return TryResolveNativePrimarySelectionFromPair(primary_entry, combo_entry, selection);
}

bool TryResolveNativePrimarySpellStats(
    uintptr_t progression_runtime_address,
    const NativePrimarySpellSelection& selection,
    NativePrimarySpellStats* stats,
    std::string* error_message) {
    if (stats == nullptr) {
        return false;
    }

    *stats = NativePrimarySpellStats{};
    stats->selection = selection;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native spell stats require a live progression runtime";
        }
        return false;
    }
    if (!IsNativePrimaryEntryIndex(selection.primary_entry_index) ||
        !IsNativePrimaryEntryIndex(selection.combo_entry_index)) {
        if (error_message != nullptr) {
            *error_message = "native spell stats received an unresolved primary selection";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto build_primary_spell_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardBuildPrimarySpell);
    if (build_primary_spell_address == 0) {
        if (error_message != nullptr) {
            *error_message = "unable to resolve Skills_Wizard primary spell builder";
        }
        return false;
    }

    std::uint32_t native_spell_id = 0;
    DWORD exception_code = 0;
    const bool build_succeeded = CallSkillsWizardBuildPrimarySpellSafe(
        build_primary_spell_address,
        progression_runtime_address,
        EncodeSkillsWizardSelectionArg(selection.primary_entry_index),
        EncodeSkillsWizardSelectionArg(selection.combo_entry_index),
        &native_spell_id,
        &exception_code);
    if (!build_succeeded) {
        stats->builder_seh_code = exception_code;
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard primary spell builder failed with 0x" +
                std::to_string(exception_code);
        }
        return false;
    }
    stats->builder_seh_code = exception_code;
    if (native_spell_id > 0) {
        stats->selection.build_skill_id = static_cast<int>(native_spell_id);
    }

    uintptr_t output_values_address = 0;
    std::size_t output_count = 0;
    if (!TryReadNativePrimaryStatOutputs(
            progression_runtime_address,
            kMinimumNativePrimaryStatOutputCount,
            &output_values_address,
            &output_count,
            error_message)) {
        return false;
    }
    const auto mana_output_index = ResolveNativePrimaryManaOutputIndex(selection);
    if (output_count <= mana_output_index) {
        if (error_message != nullptr) {
            *error_message =
                "native primary spell stat output count " +
                std::to_string(output_count) +
                " does not contain its base mana field at index " +
                std::to_string(mana_output_index);
        }
        return false;
    }

    stats->output_values_address = output_values_address;
    stats->output_count = output_count;
    if (!memory.TryReadValue(output_values_address, &stats->damage)) {
        if (error_message != nullptr) {
            *error_message = "native primary damage output read failed";
        }
        return false;
    }
    if (mana_output_index > 1) {
        if (!memory.TryReadValue(output_values_address + sizeof(float), &stats->secondary_damage)) {
            if (error_message != nullptr) {
                *error_message = "native primary secondary damage output read failed";
            }
            return false;
        }
        stats->secondary_damage_available = true;
    }
    if (!memory.TryReadValue(
            output_values_address + static_cast<std::size_t>(mana_output_index) * sizeof(float),
            &stats->mana_cost)) {
        if (error_message != nullptr) {
            *error_message = "native primary mana output read failed";
        }
        return false;
    }
    stats->mana_cost_available = true;
    stats->mana_spend_cost = stats->mana_cost;
    stats->mana_spend_cost_available = true;
    if (NativePrimaryManaOutputUsesDisplayScale(selection)) {
        float mana_output_scale = 1.0f;
        if (!TryReadNativePrimaryManaOutputScale(&mana_output_scale, error_message)) {
            return false;
        }
        stats->mana_output_scaled = true;
        stats->mana_output_scale = mana_output_scale;
        stats->mana_spend_cost = stats->mana_cost / mana_output_scale;
    }
    if (!TryReadProgressionCurrentSpellId(progression_runtime_address, &stats->current_spell_id)) {
        if (error_message != nullptr) {
            *error_message = "native current spell id read failed";
        }
        return false;
    }
    if (kProgressionLevelOffset == 0 ||
        !memory.TryReadField(
            progression_runtime_address,
            kProgressionLevelOffset,
            &stats->progression_level)) {
        if (error_message != nullptr) {
            *error_message = "native progression level read failed";
        }
        return false;
    }
    stats->resolved = true;
    return true;
}

bool TryResolveNativeSecondarySpellManaStats(
    uintptr_t progression_runtime_address,
    int entry_index,
    NativeSecondarySpellManaStats* stats,
    std::string* error_message) {
    if (stats == nullptr) {
        return false;
    }

    *stats = NativeSecondarySpellManaStats{};
    stats->entry_index = entry_index;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native secondary mana requires a live progression runtime";
        }
        return false;
    }
    if (entry_index < 0 || entry_index > 0x4F) {
        if (error_message != nullptr) {
            *error_message = "native secondary mana received an invalid progression entry";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolve_base_cost_address =
        memory.ResolveGameAddressOrZero(kSkillsWizardGetSecondaryManaCost);
    const auto compute_spend_cost_address =
        memory.ResolveGameAddressOrZero(kStatBookComputeCost);
    if (resolve_base_cost_address == 0 || compute_spend_cost_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native secondary mana seams are unavailable";
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallSkillsWizardGetSecondaryManaCostSafe(
            resolve_base_cost_address,
            progression_runtime_address,
            entry_index,
            &stats->base_cost,
            &exception_code)) {
        stats->resolver_seh_code = exception_code;
        if (error_message != nullptr) {
            *error_message =
                "Skills_Wizard secondary mana resolver failed with 0x" +
                std::to_string(exception_code);
        }
        return false;
    }
    if (!std::isfinite(stats->base_cost) || stats->base_cost <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary base mana cost is unavailable or non-positive";
        }
        return false;
    }

    exception_code = 0;
    if (!CallStatBookComputeCostSafe(
            compute_spend_cost_address,
            progression_runtime_address,
            stats->base_cost,
            entry_index,
            &stats->spend_cost,
            &exception_code)) {
        stats->resolver_seh_code = exception_code;
        if (error_message != nullptr) {
            *error_message =
                "native secondary spend-cost resolver failed with 0x" +
                std::to_string(exception_code);
        }
        return false;
    }
    if (!std::isfinite(stats->spend_cost) || stats->spend_cost <= 0.0f) {
        if (error_message != nullptr) {
            *error_message = "native secondary spend mana cost is non-positive";
        }
        return false;
    }
    if (kProgressionLevelOffset == 0 ||
        !memory.TryReadField(
            progression_runtime_address,
            kProgressionLevelOffset,
            &stats->progression_level)) {
        if (error_message != nullptr) {
            *error_message = "native secondary progression level read failed";
        }
        return false;
    }

    stats->resolver_seh_code = 0;
    stats->resolved = true;
    return true;
}

}  // namespace sdmod
