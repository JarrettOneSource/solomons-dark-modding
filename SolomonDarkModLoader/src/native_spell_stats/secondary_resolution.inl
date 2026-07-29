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
            *error_message =
                "native secondary mana requires a live progression runtime";
        }
        return false;
    }
    if (entry_index < 0 || entry_index > 0x4F) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary mana received an invalid progression entry";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolve_base_cost_address =
        memory.ResolveGameAddressOrZero(
            kSkillsWizardGetSecondaryManaCost);
    const auto compute_spend_cost_address =
        memory.ResolveGameAddressOrZero(kStatBookComputeCost);
    if (resolve_base_cost_address == 0 ||
        compute_spend_cost_address == 0) {
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
    if (!std::isfinite(stats->base_cost) ||
        stats->base_cost <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary base mana cost is unavailable or "
                "non-positive";
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
    if (!std::isfinite(stats->spend_cost) ||
        stats->spend_cost <= 0.0f) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary spend mana cost is non-positive";
        }
        return false;
    }
    if (kProgressionLevelOffset == 0 ||
        !memory.TryReadField(
            progression_runtime_address,
            kProgressionLevelOffset,
            &stats->progression_level)) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary progression level read failed";
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
            *error_message =
                "native secondary cooldown requires a live progression "
                "runtime";
        }
        return false;
    }
    if (entry_index != kPhasingEntryIndex &&
        entry_index != kTeleportEntryIndex) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary cooldown is unresolved for this entry";
        }
        return false;
    }
    if (kStandaloneWizardProgressionTableBaseOffset == 0 ||
        kStandaloneWizardProgressionTableCountOffset == 0 ||
        kStandaloneWizardProgressionEntryStride == 0 ||
        kStandaloneWizardProgressionCooldownCurrentOffset == 0 ||
        kStandaloneWizardProgressionCooldownCapOffset == 0) {
        if (error_message != nullptr) {
            *error_message =
                "native secondary cooldown row offsets are unavailable";
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
            *error_message =
                "native secondary cooldown row is unavailable";
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
            *error_message =
                "native secondary cooldown row contains invalid tick values";
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
