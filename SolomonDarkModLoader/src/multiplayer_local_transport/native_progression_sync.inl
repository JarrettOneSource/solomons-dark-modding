// Remote participant progression is materialized as a real native progression
// object. This reconciler keeps that object aligned with the owning peer's
// authoritative level, live stats, skillbook, and statbook snapshots.

struct NativeProgressionBookTableView {
    uintptr_t progression_address = 0;
    uintptr_t table_address = 0;
    std::int32_t entry_count = 0;
};

struct NativeProgressionBookEntryView {
    uintptr_t entry_address = 0;
    std::int32_t internal_id = -1;
    std::uint16_t active = 0;
    std::uint16_t visible = 0;
    std::uint16_t category = 0;
};

bool TryReadNativeProgressionBookTable(
    uintptr_t progression_address,
    NativeProgressionBookTableView* view) {
    if (view == nullptr) {
        return false;
    }
    *view = NativeProgressionBookTableView{};
    if (progression_address == 0 ||
        kStandaloneWizardProgressionTableBaseOffset == 0 ||
        kStandaloneWizardProgressionTableCountOffset == 0 ||
        kStandaloneWizardProgressionEntryStride == 0 ||
        kStandaloneWizardProgressionEntryInternalIdOffset == 0 ||
        kStandaloneWizardProgressionActiveFlagOffset == 0 ||
        kStandaloneWizardProgressionVisibleFlagOffset == 0 ||
        kStandaloneWizardProgressionEntryCategoryOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t table_address = 0;
    std::int32_t entry_count = 0;
    if (!memory.TryReadField(
            progression_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &table_address) ||
        !memory.TryReadField(
            progression_address,
            kStandaloneWizardProgressionTableCountOffset,
            &entry_count) ||
        table_address == 0 ||
        entry_count <= 0 ||
        entry_count > 4096) {
        return false;
    }

    view->progression_address = progression_address;
    view->table_address = table_address;
    view->entry_count = entry_count;
    return true;
}

bool TryReadNativeProgressionBookEntry(
    const NativeProgressionBookTableView& table,
    std::int32_t entry_index,
    NativeProgressionBookEntryView* view) {
    if (view == nullptr) {
        return false;
    }
    *view = NativeProgressionBookEntryView{};
    if (table.table_address == 0 ||
        entry_index < 0 ||
        entry_index >= table.entry_count) {
        return false;
    }

    const uintptr_t entry_address =
        table.table_address +
        static_cast<std::size_t>(entry_index) * kStandaloneWizardProgressionEntryStride;
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadField(
            entry_address,
            kStandaloneWizardProgressionEntryInternalIdOffset,
            &view->internal_id) ||
        !memory.TryReadField(
            entry_address,
            kStandaloneWizardProgressionActiveFlagOffset,
            &view->active) ||
        !memory.TryReadField(
            entry_address,
            kStandaloneWizardProgressionVisibleFlagOffset,
            &view->visible) ||
        !memory.TryReadField(
            entry_address,
            kStandaloneWizardProgressionEntryCategoryOffset,
            &view->category)) {
        return false;
    }
    view->entry_address = entry_address;
    return true;
}

bool ApplyAuthoritativeParticipantDerivedStats(
    uintptr_t progression_address,
    const ParticipantDerivedStatState& desired,
    int* write_count) {
    if (write_count != nullptr) {
        *write_count = 0;
    }
    if (progression_address == 0 || !desired.valid) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    int writes = 0;
    const auto reconcile_float = [&](std::size_t offset, float value) {
        if (offset == 0 || !std::isfinite(value) ||
            std::fabs(value) > 1000000.0f) {
            return false;
        }
        float current = 0.0f;
        if (!memory.TryReadField(progression_address, offset, &current) ||
            !std::isfinite(current)) {
            return false;
        }
        if (std::fabs(current - value) <= 0.00001f) {
            return true;
        }
        float verified = 0.0f;
        if (!memory.TryWriteField(progression_address, offset, value) ||
            !memory.TryReadField(progression_address, offset, &verified) ||
            !std::isfinite(verified) ||
            std::fabs(verified - value) > 0.00001f) {
            return false;
        }
        ++writes;
        return true;
    };

    bool complete =
        reconcile_float(
            kProgressionCastSpeedMultiplierOffset,
            desired.cast_speed_multiplier) &&
        reconcile_float(
            kProgressionManaRecoveryMultiplierOffset,
            desired.mana_recovery_multiplier) &&
        reconcile_float(
            kProgressionResistMagicFractionOffset,
            desired.resist_magic_fraction) &&
        reconcile_float(
            kProgressionResistPoisonFractionOffset,
            desired.resist_poison_fraction) &&
        reconcile_float(kProgressionDeflectChanceOffset, desired.deflect_chance) &&
        reconcile_float(
            kProgressionStaffMeleeDamageAOffset,
            desired.staff_melee_damage_a) &&
        reconcile_float(
            kProgressionStaffMeleeDamageBOffset,
            desired.staff_melee_damage_b) &&
        reconcile_float(kProgressionPickupRangeOffset, desired.pickup_range) &&
        reconcile_float(
            kProgressionSecondaryRechargeMultiplierOffset,
            desired.secondary_recharge_multiplier) &&
        reconcile_float(
            kProgressionOffensiveDamageMultiplierOffset,
            desired.offensive_damage_multiplier) &&
        reconcile_float(
            kProgressionOffensiveManaMultiplierOffset,
            desired.offensive_mana_multiplier) &&
        reconcile_float(
            kProgressionMeditationRecoveryBonusOffset,
            desired.meditation_recovery_bonus);

    std::int32_t current_idle_ticks = 0;
    if (kProgressionMeditationIdleTicksOffset == 0 ||
        desired.meditation_idle_ticks < -1 ||
        desired.meditation_idle_ticks > 1000000000 ||
        !memory.TryReadField(
            progression_address,
            kProgressionMeditationIdleTicksOffset,
            &current_idle_ticks)) {
        complete = false;
    } else if (current_idle_ticks != desired.meditation_idle_ticks) {
        std::int32_t verified_idle_ticks = 0;
        if (!memory.TryWriteField(
                progression_address,
                kProgressionMeditationIdleTicksOffset,
                desired.meditation_idle_ticks) ||
            !memory.TryReadField(
                progression_address,
                kProgressionMeditationIdleTicksOffset,
                &verified_idle_ticks) ||
            verified_idle_ticks != desired.meditation_idle_ticks) {
            complete = false;
        } else {
            ++writes;
        }
    }

    if (write_count != nullptr) {
        *write_count = writes;
    }
    return complete;
}

void ReconcileRemoteParticipantNativeProgression(std::uint64_t now_ms) {
    const auto runtime_state = SnapshotRuntimeState();
    std::unordered_set<std::uint64_t> live_remote_participant_ids;

    for (const auto& participant : runtime_state.participants) {
        if (!IsRemoteParticipant(participant) ||
            !IsNativeControlledParticipant(participant) ||
            !participant.transport_connected ||
            !participant.runtime.valid ||
            participant.participant_id == 0) {
            continue;
        }
        live_remote_participant_ids.insert(participant.participant_id);

        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(participant.participant_id, &gameplay_state) ||
            !gameplay_state.available ||
            gameplay_state.progression_runtime_state_address == 0) {
            continue;
        }
        const uintptr_t progression_address =
            gameplay_state.progression_runtime_state_address;

        auto& checkpoint =
            g_local_transport.native_progression_reconcile_by_participant[
                participant.participant_id];
        const bool progression_target_changed =
            checkpoint.progression_address != progression_address ||
            checkpoint.gameplay_slot != gameplay_state.gameplay_slot;
        const bool concentration_target_changed =
            checkpoint.concentration_revision !=
                participant.owned_progression.concentration_revision ||
            checkpoint.concentration_selection_valid !=
                participant.owned_progression.concentration_selection_valid ||
            checkpoint.concentration_entry_a !=
                participant.owned_progression.concentration_entry_a ||
            checkpoint.concentration_entry_b !=
                participant.owned_progression.concentration_entry_b;
        const bool target_changed =
            progression_target_changed ||
            checkpoint.spellbook_revision != participant.owned_progression.spellbook_revision ||
            checkpoint.statbook_revision != participant.owned_progression.statbook_revision ||
            concentration_target_changed ||
            checkpoint.derived_stat_revision !=
                participant.owned_progression.derived_stat_revision ||
            checkpoint.level != participant.runtime.level ||
            checkpoint.experience != participant.runtime.experience_current ||
            checkpoint.move_speed != participant.runtime.move_speed;
        const auto retry_interval = checkpoint.complete
            ? kNativeProgressionReconcileAuditMs
            : kNativeProgressionReconcileRetryMs;
        if (!target_changed &&
            checkpoint.last_attempt_ms != 0 &&
            now_ms - checkpoint.last_attempt_ms < retry_interval) {
            continue;
        }

        const bool was_complete = checkpoint.complete;
        checkpoint.progression_address = progression_address;
        checkpoint.gameplay_slot = gameplay_state.gameplay_slot;
        checkpoint.spellbook_revision = participant.owned_progression.spellbook_revision;
        checkpoint.statbook_revision = participant.owned_progression.statbook_revision;
        checkpoint.concentration_revision =
            participant.owned_progression.concentration_revision;
        checkpoint.derived_stat_revision =
            participant.owned_progression.derived_stat_revision;
        checkpoint.concentration_selection_valid =
            participant.owned_progression.concentration_selection_valid;
        checkpoint.concentration_entry_a =
            participant.owned_progression.concentration_entry_a;
        checkpoint.concentration_entry_b =
            participant.owned_progression.concentration_entry_b;
        checkpoint.level = participant.runtime.level;
        checkpoint.experience = participant.runtime.experience_current;
        checkpoint.move_speed = participant.runtime.move_speed;
        checkpoint.last_attempt_ms = now_ms;
        checkpoint.complete = false;

        bool complete = true;
        bool level_synchronized = false;
        bool move_speed_synchronized = false;
        bool concentration_synchronized = false;
        bool derived_stats_synchronized = false;
        int applied_entry_count = 0;
        int visibility_write_count = 0;
        int derived_stat_write_count = 0;

        auto& memory = ProcessMemory::Instance();
        std::int32_t native_level = 0;
        float native_experience = 0.0f;
        const bool native_level_read =
            memory.TryReadField(progression_address, kProgressionLevelOffset, &native_level) &&
            memory.TryReadField(progression_address, kProgressionXpOffset, &native_experience) &&
            std::isfinite(native_experience);
        if (!native_level_read) {
            complete = false;
        } else if (participant.runtime.level > 0 &&
                   (native_level != participant.runtime.level ||
                    std::fabs(
                        native_experience -
                        static_cast<float>(participant.runtime.experience_current)) > 0.5f)) {
            if (native_level > participant.runtime.level) {
                complete = false;
                Log(
                    "Multiplayer native progression reconcile refused a level rollback. participant_id=" +
                    std::to_string(participant.participant_id) +
                    " native_level=" + std::to_string(native_level) +
                    " desired_level=" + std::to_string(participant.runtime.level));
            } else {
                std::string sync_error;
                if (!SyncParticipantProgressionToSharedLevelUp(
                        participant.participant_id,
                        participant.runtime.level,
                        (std::max)(0, participant.runtime.experience_current),
                        0,
                        &sync_error)) {
                    complete = false;
                    Log(
                        "Multiplayer native progression level reconcile deferred. participant_id=" +
                        std::to_string(participant.participant_id) +
                        " level=" + std::to_string(participant.runtime.level) +
                        " xp=" + std::to_string(participant.runtime.experience_current) +
                        " error=" + sync_error);
                } else {
                    level_synchronized = true;
                }
            }
        }

        const float desired_move_speed = participant.runtime.move_speed;
        float native_move_speed = 0.0f;
        if (!std::isfinite(desired_move_speed) ||
            desired_move_speed <= 0.0f ||
            desired_move_speed > 100.0f ||
            !memory.TryReadField(
                progression_address,
                kProgressionMoveSpeedOffset,
                &native_move_speed) ||
            !std::isfinite(native_move_speed)) {
            complete = false;
        } else if (std::fabs(native_move_speed - desired_move_speed) > 0.001f) {
            float verified_move_speed = 0.0f;
            if (!memory.TryWriteField(
                    progression_address,
                    kProgressionMoveSpeedOffset,
                    desired_move_speed) ||
                !memory.TryReadField(
                    progression_address,
                    kProgressionMoveSpeedOffset,
                    &verified_move_speed) ||
                !std::isfinite(verified_move_speed) ||
                std::fabs(verified_move_speed - desired_move_speed) > 0.001f) {
                complete = false;
            } else {
                move_speed_synchronized = true;
            }
        }

        NativeProgressionBookTableView table;
        if (!participant.owned_progression.initialized ||
            participant.owned_progression.progression_book_entries.empty()) {
            complete = false;
        } else if (!TryReadNativeProgressionBookTable(progression_address, &table)) {
            complete = false;
        } else {
            int apply_calls = 0;
            for (const auto& desired : participant.owned_progression.progression_book_entries) {
                NativeProgressionBookEntryView native;
                if (!TryReadNativeProgressionBookEntry(table, desired.entry_index, &native) ||
                    native.internal_id != desired.internal_id) {
                    complete = false;
                    continue;
                }
                const bool structural_tail_record =
                    desired.entry_index >= table.entry_count - 3 &&
                    (desired.internal_id == 0xFFFF ||
                     desired.statbook_max_level == 0);
                if (structural_tail_record) {
                    continue;
                }
                if (native.category != desired.category) {
                    complete = false;
                    continue;
                }

                while (native.active < desired.active &&
                       apply_calls < kNativeProgressionReconcileMaxApplyCallsPerTick) {
                    BotSkillChoiceOption option;
                    option.option_id = desired.entry_index;
                    option.apply_count = (std::min)(
                        2,
                        static_cast<int>(desired.active - native.active));
                    const auto active_before = native.active;
                    std::string apply_error;
                    if (!ApplyParticipantSkillChoiceOption(
                            participant.participant_id,
                            option,
                            &apply_error)) {
                        complete = false;
                        Log(
                            "Multiplayer native progression entry reconcile deferred. participant_id=" +
                            std::to_string(participant.participant_id) +
                            " entry_index=" + std::to_string(desired.entry_index) +
                            " desired_active=" + std::to_string(desired.active) +
                            " native_active=" + std::to_string(active_before) +
                            " error=" + apply_error);
                        break;
                    }
                    ++apply_calls;
                    ++applied_entry_count;
                    if (!TryReadNativeProgressionBookEntry(table, desired.entry_index, &native) ||
                        native.active <= active_before) {
                        complete = false;
                        break;
                    }
                }

                if (native.active != desired.active) {
                    complete = false;
                }
                if (native.active >= desired.active && native.visible != desired.visible) {
                    if (memory.TryWriteField(
                            native.entry_address,
                            kStandaloneWizardProgressionVisibleFlagOffset,
                            desired.visible)) {
                        native.visible = desired.visible;
                        ++visibility_write_count;
                    } else {
                        complete = false;
                    }
                }
                if (native.visible != desired.visible) {
                    complete = false;
                }
            }
            if (participant.owned_progression.progression_book_truncated ||
                participant.owned_progression.progression_book_entry_total_count !=
                    participant.owned_progression.progression_book_entries.size()) {
                complete = false;
            }
        }

        // Native rank/level application performs its own progression refresh,
        // which reads the observer process's two global Concentrate entries.
        // Apply the owning participant's scoped context last so the remote
        // object's final derived fields cannot be overwritten by that refresh.
        if (participant.owned_progression.concentration_selection_valid) {
            std::string concentration_error;
            const bool refresh_concentration_derived_state =
                target_changed || !was_complete || applied_entry_count > 0 ||
                level_synchronized;
            const bool concentration_ok = refresh_concentration_derived_state
                ? TryApplyParticipantConcentrationSelections(
                      participant.participant_id,
                      participant.owned_progression.concentration_entry_a,
                      participant.owned_progression.concentration_entry_b,
                      &concentration_error)
                : TryReconcileParticipantConcentrationRuntimeSelections(
                      participant.participant_id,
                      participant.owned_progression.concentration_entry_a,
                      participant.owned_progression.concentration_entry_b,
                      &concentration_error);
            if (!concentration_ok) {
                complete = false;
                Log(
                    "Multiplayer native Concentrate reconcile deferred. participant_id=" +
                    std::to_string(participant.participant_id) +
                    " gameplay_slot=" + std::to_string(gameplay_state.gameplay_slot) +
                    " entry_a=" +
                    std::to_string(participant.owned_progression.concentration_entry_a) +
                    " entry_b=" +
                    std::to_string(participant.owned_progression.concentration_entry_b) +
                    " revision=" +
                    std::to_string(participant.owned_progression.concentration_revision) +
                    " refresh_derived=" +
                    std::to_string(refresh_concentration_derived_state ? 1 : 0) +
                    " error=" + concentration_error);
            } else {
                concentration_synchronized = true;
            }
        }

        if (participant.owned_progression.derived_stats.valid) {
            if (!ApplyAuthoritativeParticipantDerivedStats(
                    progression_address,
                    participant.owned_progression.derived_stats,
                    &derived_stat_write_count)) {
                complete = false;
                Log(
                    "Multiplayer authoritative derived-stat reconcile deferred. participant_id=" +
                    std::to_string(participant.participant_id) +
                    " revision=" +
                    std::to_string(participant.owned_progression.derived_stat_revision));
            } else {
                derived_stats_synchronized = true;
            }
        }

        checkpoint.complete = complete;
        if (level_synchronized ||
            move_speed_synchronized ||
            concentration_synchronized ||
            derived_stat_write_count > 0 ||
            applied_entry_count > 0 ||
            visibility_write_count > 0 ||
            (!was_complete && complete)) {
            Log(
                "Multiplayer native progression reconciled. participant_id=" +
                std::to_string(participant.participant_id) +
                " progression=" + HexString(progression_address) +
                " level_synced=" + std::to_string(level_synchronized ? 1 : 0) +
                " move_speed_synced=" +
                    std::to_string(move_speed_synchronized ? 1 : 0) +
                " move_speed=" + std::to_string(desired_move_speed) +
                " concentrate_synced=" +
                    std::to_string(concentration_synchronized ? 1 : 0) +
                " concentrate_a=" +
                    std::to_string(participant.owned_progression.concentration_entry_a) +
                " concentrate_b=" +
                    std::to_string(participant.owned_progression.concentration_entry_b) +
                " derived_stats_synced=" +
                    std::to_string(derived_stats_synchronized ? 1 : 0) +
                " derived_stat_writes=" +
                    std::to_string(derived_stat_write_count) +
                " derived_stat_revision=" +
                    std::to_string(participant.owned_progression.derived_stat_revision) +
                " applied_entries=" + std::to_string(applied_entry_count) +
                " visibility_writes=" + std::to_string(visibility_write_count) +
                " spellbook_revision=" +
                    std::to_string(participant.owned_progression.spellbook_revision) +
                " statbook_revision=" +
                    std::to_string(participant.owned_progression.statbook_revision) +
                " complete=" + std::to_string(complete ? 1 : 0));
        }
    }

    for (auto it =
             g_local_transport.native_progression_reconcile_by_participant.begin();
         it != g_local_transport.native_progression_reconcile_by_participant.end();) {
        if (live_remote_participant_ids.find(it->first) ==
            live_remote_participant_ids.end()) {
            it = g_local_transport.native_progression_reconcile_by_participant.erase(it);
        } else {
            ++it;
        }
    }
}
