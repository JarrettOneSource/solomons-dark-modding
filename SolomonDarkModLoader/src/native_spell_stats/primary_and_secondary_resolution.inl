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

bool TryResolveNativePrimarySelectionFromBuildId(
    int build_skill_id,
    NativePrimarySpellSelection* selection) {
    if (selection != nullptr) {
        *selection = NativePrimarySpellSelection{};
    }
    const auto* mapping = FindNativePrimaryBuildMapping(build_skill_id);
    return mapping != nullptr &&
           FillNativePrimarySelection(
               mapping->primary_entry_index,
               mapping->combo_entry_index,
               mapping->native_build_id,
               selection);
}

bool TryResolveNativePrimaryBuildIdFromPair(
    int primary_entry_index,
    int combo_entry_index,
    int* normalized_build_id) {
    if (normalized_build_id != nullptr) {
        *normalized_build_id = -1;
    }
    const auto* mapping = FindNativePrimaryPairMapping(
        primary_entry_index,
        combo_entry_index);
    if (mapping == nullptr || normalized_build_id == nullptr) {
        return false;
    }
    *normalized_build_id = mapping->normalized_build_id;
    return true;
}

bool TryNormalizeNativePrimaryBuildId(
    int native_build_id,
    int* normalized_build_id) {
    if (normalized_build_id != nullptr) {
        *normalized_build_id = -1;
    }
    const auto* mapping = FindNativePrimaryBuildMapping(native_build_id);
    if (mapping == nullptr || normalized_build_id == nullptr) {
        return false;
    }
    *normalized_build_id = mapping->normalized_build_id;
    return true;
}

bool IsNativeWeldBuildId(int build_id) {
    return build_id >= 1000 && build_id <= 1009;
}

bool TryReadNativePendingWeldBuildId(
    uintptr_t progression_runtime_address,
    int* weld_build_id) {
    if (weld_build_id != nullptr) {
        *weld_build_id = -1;
    }
    if (progression_runtime_address == 0 ||
        weld_build_id == nullptr ||
        kProgressionSpecialChoiceArgumentOffset == 0) {
        return false;
    }

    int candidate = -1;
    if (!ProcessMemory::Instance().TryReadField(
            progression_runtime_address,
            kProgressionSpecialChoiceArgumentOffset,
            &candidate) ||
        !IsNativeWeldBuildId(candidate)) {
        return false;
    }
    *weld_build_id = candidate;
    return true;
}

bool TryReadNativeCurrentPrimarySelection(
    uintptr_t progression_runtime_address,
    NativePrimarySpellSelection* selection,
    int* normalized_build_id) {
    if (selection != nullptr) {
        *selection = NativePrimarySpellSelection{};
    }
    if (normalized_build_id != nullptr) {
        *normalized_build_id = -1;
    }
    if (selection == nullptr || normalized_build_id == nullptr) {
        return false;
    }

    int current_spell_id = -1;
    if (!TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &current_spell_id) ||
        !TryResolveNativePrimarySelectionFromBuildId(
            current_spell_id,
            selection) ||
        !TryNormalizeNativePrimaryBuildId(
            current_spell_id,
            normalized_build_id)) {
        *selection = NativePrimarySpellSelection{};
        *normalized_build_id = -1;
        return false;
    }
    return true;
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
            std::uint32_t exception_code = 0;
            if (!TryBuildNativePrimarySpellPreservingProgressionFlags(
                    progression_runtime_address,
                    primary_entry,
                    combo_entry,
                    &native_spell_id,
                    &exception_code,
                    nullptr)) {
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

    std::int32_t previous_current_spell_id = 0;
    const bool have_previous_current_spell_id =
        TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &previous_current_spell_id);

    std::uint32_t native_spell_id = 0;
    std::uint32_t exception_code = 0;
    std::string build_error;
    if (!TryBuildNativePrimarySpellPreservingProgressionFlags(
            progression_runtime_address,
            primary_entry_index,
            combo_entry_index,
            &native_spell_id,
            &exception_code,
            &build_error)) {
        RestoreProgressionCurrentSpellIdIfNeeded(
            progression_runtime_address,
            have_previous_current_spell_id,
            previous_current_spell_id);
        if (error_message != nullptr) {
            *error_message = build_error;
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

    std::uint32_t native_spell_id = 0;
    std::uint32_t exception_code = 0;
    std::string build_error;
    const bool build_succeeded =
        TryBuildNativePrimarySpellPreservingProgressionFlags(
            progression_runtime_address,
            selection.primary_entry_index,
            selection.combo_entry_index,
            &native_spell_id,
            &exception_code,
            &build_error);
    if (!build_succeeded) {
        stats->builder_seh_code = exception_code;
        if (error_message != nullptr) {
            *error_message = build_error;
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
    auto& memory = ProcessMemory::Instance();
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

bool TryResolveNativePrimarySpellStatsPreservingSelection(
    uintptr_t progression_runtime_address,
    const NativePrimarySpellSelection& selection,
    NativePrimarySpellStats* stats,
    std::string* error_message) {
    if (stats == nullptr) {
        return false;
    }

    *stats = NativePrimarySpellStats{};
    if (error_message != nullptr) {
        error_message->clear();
    }

    std::int32_t previous_current_spell_id = 0;
    if (!TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &previous_current_spell_id)) {
        if (error_message != nullptr) {
            *error_message =
                "observation-safe native spell stats require a readable "
                "current spell id";
        }
        return false;
    }

    NativePrimarySpellStats resolved_stats{};
    std::string resolution_error;
    const bool resolved = TryResolveNativePrimarySpellStats(
        progression_runtime_address,
        selection,
        &resolved_stats,
        &resolution_error);

    RestoreProgressionCurrentSpellIdIfNeeded(
        progression_runtime_address,
        true,
        previous_current_spell_id);
    std::int32_t restored_current_spell_id = 0;
    if (!TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &restored_current_spell_id) ||
        restored_current_spell_id != previous_current_spell_id) {
        if (error_message != nullptr) {
            *error_message =
                "observation-safe native spell stats could not restore "
                "the active spell selection";
        }
        return false;
    }

    if (!resolved) {
        if (error_message != nullptr) {
            *error_message = resolution_error;
        }
        return false;
    }

    *stats = resolved_stats;
    return true;
}

bool TryReadNativePrimarySpellStatsFromCurrentOutput(
    uintptr_t progression_runtime_address,
    const NativePrimarySpellSelection& selection,
    NativeObservedPrimarySpellStats* stats,
    std::string* error_message) {
    if (stats == nullptr) {
        return false;
    }

    *stats = NativeObservedPrimarySpellStats{};
    stats->selection = selection;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native observed spell stats require a live progression runtime";
        }
        return false;
    }
    if (!IsNativePrimaryEntryIndex(selection.primary_entry_index) ||
        !IsNativePrimaryEntryIndex(selection.combo_entry_index)) {
        if (error_message != nullptr) {
            *error_message = "native observed spell stats received an unresolved primary selection";
        }
        return false;
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
    const auto mana_output_index =
        ResolveNativePrimaryManaOutputIndex(selection);
    if (output_count <= mana_output_index) {
        if (error_message != nullptr) {
            *error_message =
                "native observed primary stat output count " +
                std::to_string(output_count) +
                " does not contain its mana field at index " +
                std::to_string(mana_output_index);
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadValue(
            output_values_address +
                static_cast<std::size_t>(mana_output_index) * sizeof(float),
            &stats->mana_cost) ||
        !std::isfinite(stats->mana_cost)) {
        if (error_message != nullptr) {
            *error_message = "native observed primary mana output read failed";
        }
        return false;
    }
    stats->mana_cost_available = true;
    stats->mana_spend_cost = stats->mana_cost;
    stats->mana_spend_cost_available = true;
    if (NativePrimaryManaOutputUsesDisplayScale(selection)) {
        float mana_output_scale = 1.0f;
        if (!TryReadNativePrimaryManaOutputScale(
                &mana_output_scale,
                error_message)) {
            return false;
        }
        stats->mana_output_scaled = true;
        stats->mana_output_scale = mana_output_scale;
        stats->mana_spend_cost = stats->mana_cost / mana_output_scale;
    }
    if (!TryReadProgressionCurrentSpellId(
            progression_runtime_address,
            &stats->current_spell_id)) {
        if (error_message != nullptr) {
            *error_message = "native observed current spell id read failed";
        }
        return false;
    }
    int current_build_id = -1;
    int selected_build_id = -1;
    if (!TryNormalizeNativePrimaryBuildId(
            stats->current_spell_id,
            &current_build_id) ||
        !TryResolveNativePrimaryBuildIdFromPair(
            selection.primary_entry_index,
            selection.combo_entry_index,
            &selected_build_id) ||
        current_build_id != selected_build_id) {
        if (error_message != nullptr) {
            *error_message =
                "native observed primary stat output belongs to a different build";
        }
        return false;
    }
    if (kProgressionLevelOffset == 0 ||
        !memory.TryReadField(
            progression_runtime_address,
            kProgressionLevelOffset,
            &stats->progression_level)) {
        if (error_message != nullptr) {
            *error_message = "native observed progression level read failed";
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

bool TryReadNativeSecondaryCooldownState(
    uintptr_t progression_runtime_address,
    int entry_index,
    NativeSecondaryCooldownState* state,
    std::string* error_message) {
    constexpr float kNativeCooldownTicksPerSecond = 100.0f;
    constexpr int kPhasingEntryIndex = 15;
    constexpr int kTeleportEntryIndex = 48;

    if (state == nullptr) {
        return false;
    }
    *state = NativeSecondaryCooldownState{};
    state->entry_index = entry_index;
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (progression_runtime_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native secondary cooldown requires a live progression runtime";
        }
        return false;
    }
    if (entry_index != kPhasingEntryIndex &&
        entry_index != kTeleportEntryIndex) {
        if (error_message != nullptr) {
            *error_message = "native secondary cooldown is unresolved for this entry";
        }
        return false;
    }
    if (kStandaloneWizardProgressionTableBaseOffset == 0 ||
        kStandaloneWizardProgressionTableCountOffset == 0 ||
        kStandaloneWizardProgressionEntryStride == 0 ||
        kStandaloneWizardProgressionCooldownCurrentOffset == 0 ||
        kStandaloneWizardProgressionCooldownCapOffset == 0) {
        if (error_message != nullptr) {
            *error_message = "native secondary cooldown row offsets are unavailable";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t table_address = 0;
    std::int32_t table_count = 0;
    if (!memory.TryReadField(
            progression_runtime_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &table_address) ||
        !memory.TryReadField(
            progression_runtime_address,
            kStandaloneWizardProgressionTableCountOffset,
            &table_count) ||
        table_address == 0 ||
        entry_index < 0 ||
        entry_index >= table_count) {
        if (error_message != nullptr) {
            *error_message = "native secondary cooldown row is unavailable";
        }
        return false;
    }

    const auto row_address =
        table_address +
        static_cast<std::size_t>(entry_index) *
            kStandaloneWizardProgressionEntryStride;
    float current_ticks = 0.0f;
    float cap_ticks = 0.0f;
    if (!memory.TryReadField(
            row_address,
            kStandaloneWizardProgressionCooldownCurrentOffset,
            &current_ticks) ||
        !memory.TryReadField(
            row_address,
            kStandaloneWizardProgressionCooldownCapOffset,
            &cap_ticks) ||
        !std::isfinite(current_ticks) ||
        !std::isfinite(cap_ticks) ||
        current_ticks < 0.0f ||
        cap_ticks <= 0.0f ||
        current_ticks > cap_ticks + 0.01f) {
        if (error_message != nullptr) {
            *error_message = "native secondary cooldown row contains invalid tick values";
        }
        return false;
    }

    state->cooldown_seconds =
        cap_ticks / kNativeCooldownTicksPerSecond;
    state->remaining_seconds =
        current_ticks / kNativeCooldownTicksPerSecond;
    state->resolved = true;
    return true;
}

}  // namespace sdmod
