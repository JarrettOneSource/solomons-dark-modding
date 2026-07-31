BotLoadoutRevisionTuple ResolveBotLoadoutRevisionTuple(
    const ParticipantInfo& participant) {
    return BotLoadoutRevisionTuple{
        participant.owned_progression.loadout_revision,
        participant.owned_progression.spellbook_revision,
        participant.owned_progression.statbook_revision,
        participant.owned_progression.derived_stat_revision,
    };
}

BotLoadoutInfo ResolveParticipantAbilityLoadout(
    const ParticipantInfo& participant) {
    return participant.owned_progression.ability_loadout_valid
        ? participant.owned_progression.ability_loadout
        : participant.character_profile.loadout;
}

bool TryReadPrimarySelectionPursuitRange(
    uintptr_t actor_address,
    float* range,
    std::string* source) {
    if (range != nullptr) {
        *range = 0.0f;
    }
    if (source != nullptr) {
        *source = "unresolved";
    }
    if (range == nullptr || source == nullptr) {
        return false;
    }

    if (actor_address == 0 ||
        kActorAnimationSelectionStateOffset == 0 ||
        kActorControlBrainPursuitRangeOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t selection_state = 0;
    if (!memory.IsReadableRange(
            actor_address + kActorAnimationSelectionStateOffset,
            sizeof(selection_state)) ||
        !memory.TryReadField(
            actor_address,
            kActorAnimationSelectionStateOffset,
            &selection_state) ||
        selection_state == 0 ||
        !memory.IsReadableRange(
            selection_state + kActorControlBrainPursuitRangeOffset,
            sizeof(float))) {
        return false;
    }

    float pursuit_range = 0.0f;
    if (!memory.TryReadField(
            selection_state,
            kActorControlBrainPursuitRangeOffset,
            &pursuit_range) ||
        !std::isfinite(pursuit_range) ||
        pursuit_range <= 0.0f) {
        return false;
    }

    *range = pursuit_range;
    *source = "native_selection_pursuit_range";
    return true;
}

void InitializeSecondaryLoadoutRows(
    const BotLoadoutInfo& loadout,
    BotLoadoutDetails* details) {
    if (details == nullptr) {
        return;
    }
    for (std::size_t index = 0;
         index < details->secondaries.size();
         ++index) {
        auto& row = details->secondaries[index];
        row = BotSecondaryLoadoutDetails{};
        row.slot = static_cast<std::int32_t>(index + 1);
        row.entry_id = loadout.secondary_entry_indices[index];
    }
}

void OverlayLivePrimaryAttackWindow(
    uintptr_t progression_runtime_address,
    uintptr_t actor_address,
    BotLoadoutDetails* details) {
    if (details == nullptr) {
        return;
    }

    details->primary.range_min = 0.0f;
    details->primary.range_max = 0.0f;
    details->primary.range_resolved = false;
    details->primary.range_source = "unresolved";

    float primary_range = 0.0f;
    std::string range_source;
    const auto water_primary_entry =
        ResolveNativePrimaryEntryForElement(1);
    const bool frost_jet =
        details->primary.entry_id == water_primary_entry &&
        details->primary.combo_entry_id == water_primary_entry;
    if (frost_jet &&
        TryResolveNativeFrostJetQueryRange(
            progression_runtime_address,
            &primary_range,
            nullptr)) {
        details->primary.range_max = primary_range;
        details->primary.range_resolved = true;
        details->primary.range_source =
            "native_frost_jet_query_range";
    } else if (!frost_jet &&
        TryReadPrimarySelectionPursuitRange(
            actor_address,
            &primary_range,
            &range_source)) {
        details->primary.range_max = primary_range;
        details->primary.range_resolved = true;
        details->primary.range_source = range_source;
    }
}

void ResolveStaticParticipantLoadoutDetails(
    const ParticipantInfo& participant,
    uintptr_t progression_runtime_address,
    uintptr_t actor_address,
    std::int32_t active_weld_build_id,
    BotLoadoutDetails* details) {
    if (details == nullptr) {
        return;
    }

    *details = BotLoadoutDetails{};
    details->available = true;
    details->participant_id = participant.participant_id;

    auto loadout = ResolveParticipantAbilityLoadout(participant);
    const auto default_primary_entry =
        ResolveNativePrimaryEntryForElement(
            participant.character_profile.element_id);
    if (loadout.primary_entry_index < 0) {
        loadout.primary_entry_index = default_primary_entry;
    }
    if (loadout.primary_combo_entry_index < 0) {
        loadout.primary_combo_entry_index =
            loadout.primary_entry_index;
    }

    details->primary.entry_id = loadout.primary_entry_index;
    details->primary.combo_entry_id =
        loadout.primary_combo_entry_index;
    InitializeSecondaryLoadoutRows(loadout, details);

    NativePrimarySpellSelection selection{};
    int normalized_build_id = -1;
    bool selection_resolved = false;
    if (IsNativeWeldBuildId(active_weld_build_id)) {
        selection_resolved =
            TryResolveNativePrimarySelectionFromBuildId(
                active_weld_build_id,
                &selection);
        if (selection_resolved) {
            normalized_build_id = active_weld_build_id;
        }
    }
    if (!selection_resolved &&
        progression_runtime_address != 0) {
        selection_resolved =
            TryReadNativeCurrentPrimarySelection(
                progression_runtime_address,
                &selection,
                &normalized_build_id);
    }
    if (!selection_resolved) {
        selection_resolved =
            TryResolveNativePrimarySelectionFromPair(
                loadout.primary_entry_index,
                loadout.primary_combo_entry_index,
                &selection);
        if (selection_resolved) {
            (void)TryResolveNativePrimaryBuildIdFromPair(
                selection.primary_entry_index,
                selection.combo_entry_index,
                &normalized_build_id);
        }
    }

    if (selection_resolved) {
        details->primary.entry_id =
            selection.primary_entry_index;
        details->primary.combo_entry_id =
            selection.combo_entry_index;
        details->primary.mana_charge_kind =
            selection.per_second_mana
                ? BotManaChargeKind::PerSecond
                : BotManaChargeKind::PerCast;
    }
    if (normalized_build_id > 0) {
        details->primary.build_id = normalized_build_id;
        details->primary.build_id_resolved = true;
    }

    if (selection_resolved &&
        progression_runtime_address != 0) {
        NativeObservedPrimarySpellStats stats{};
        std::string stats_error;
        const bool observed =
            TryReadNativePrimarySpellStatsFromCurrentOutput(
                progression_runtime_address,
                selection,
                &stats,
                &stats_error);
        if (observed &&
            stats.mana_spend_cost_available &&
            std::isfinite(stats.mana_spend_cost) &&
            stats.mana_spend_cost > 0.0f) {
            details->primary.mana_cost =
                stats.mana_spend_cost;
            details->primary.mana_cost_resolved = true;
        } else {
            NativePrimarySpellStats refreshed_stats{};
            if (TryResolveNativePrimarySpellStatsPreservingSelection(
                    progression_runtime_address,
                    selection,
                    &refreshed_stats,
                    &stats_error) &&
                refreshed_stats.mana_spend_cost_available &&
                std::isfinite(refreshed_stats.mana_spend_cost) &&
                refreshed_stats.mana_spend_cost > 0.0f) {
                details->primary.mana_cost =
                    refreshed_stats.mana_spend_cost;
                details->primary.mana_cost_resolved = true;
            }
        }
    }

    OverlayLivePrimaryAttackWindow(
        progression_runtime_address,
        actor_address,
        details);

    if (progression_runtime_address == 0) {
        return;
    }
    for (auto& row : details->secondaries) {
        if (row.entry_id < 0) {
            continue;
        }
        NativeSecondarySpellManaStats stats{};
        std::string stats_error;
        if (TryResolveNativeSecondarySpellManaStats(
                progression_runtime_address,
                row.entry_id,
                &stats,
                &stats_error) &&
            stats.resolved &&
            std::isfinite(stats.spend_cost) &&
            stats.spend_cost > 0.0f) {
            row.mana_cost = stats.spend_cost;
            row.mana_cost_resolved = true;
        }
    }
}

void OverlayLiveSecondaryCooldowns(
    uintptr_t progression_runtime_address,
    BotLoadoutDetails* details) {
    if (details == nullptr) {
        return;
    }
    for (auto& row : details->secondaries) {
        row.cooldown_seconds = 0.0f;
        row.cooldown_remaining_seconds = 0.0f;
        row.cooldown_resolved = false;
        if (progression_runtime_address == 0 ||
            row.entry_id < 0) {
            continue;
        }

        NativeSecondaryCooldownState cooldown{};
        std::string cooldown_error;
        if (TryReadNativeSecondaryCooldownState(
                progression_runtime_address,
                row.entry_id,
                &cooldown,
                &cooldown_error) &&
            cooldown.resolved) {
            row.cooldown_seconds = cooldown.cooldown_seconds;
            row.cooldown_remaining_seconds =
                cooldown.remaining_seconds;
            row.cooldown_resolved = true;
        }
    }
}
