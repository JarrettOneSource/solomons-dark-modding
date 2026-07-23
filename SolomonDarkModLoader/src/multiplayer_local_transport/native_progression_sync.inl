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

bool HydrateAuthoritativeRemoteProgressionEntryState(
    std::uint64_t participant_id,
    std::int32_t entry_index,
    std::uint16_t resulting_active,
    std::uint16_t resulting_visible,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (participant_id == 0 ||
        participant_id == g_local_transport.local_peer_id ||
        entry_index < 0) {
        return fail("authoritative remote progression hydration received invalid state");
    }

    SDModParticipantGameplayState gameplay_state;
    if (!TryGetParticipantGameplayState(participant_id, &gameplay_state) ||
        !gameplay_state.available ||
        gameplay_state.progression_runtime_state_address == 0) {
        return fail("authoritative remote progression hydration requires a materialized progression");
    }

    NativeProgressionBookTableView table;
    NativeProgressionBookEntryView native;
    if (!TryReadNativeProgressionBookTable(
            gameplay_state.progression_runtime_state_address,
            &table) ||
        !TryReadNativeProgressionBookEntry(table, entry_index, &native)) {
        return fail("authoritative remote progression entry is unavailable");
    }

    auto& memory = ProcessMemory::Instance();
    if (native.active != resulting_active &&
        !memory.TryWriteField(
            native.entry_address,
            kStandaloneWizardProgressionActiveFlagOffset,
            resulting_active)) {
        return fail("authoritative remote progression active-state write failed");
    }
    if (native.visible != resulting_visible &&
        !memory.TryWriteField(
            native.entry_address,
            kStandaloneWizardProgressionVisibleFlagOffset,
            resulting_visible)) {
        return fail("authoritative remote progression visibility write failed");
    }

    NativeProgressionBookEntryView verified;
    if (!TryReadNativeProgressionBookEntry(table, entry_index, &verified) ||
        verified.entry_address != native.entry_address ||
        verified.internal_id != native.internal_id ||
        verified.category != native.category ||
        verified.active != resulting_active ||
        verified.visible != resulting_visible) {
        return fail("authoritative remote progression state verification failed");
    }
    return true;
}

bool ApplyAuthoritativeRemoteSkillRankDelta(
    std::uint64_t participant_id,
    const BotSkillChoiceOption& option,
    std::uint16_t* resulting_active,
    std::string* error_message) {
    auto fail = [&](std::string message) {
        if (resulting_active != nullptr) {
            *resulting_active = 0;
        }
        if (error_message != nullptr) {
            *error_message = std::move(message);
        }
        return false;
    };
    if (option.option_id < 0 ||
        option.apply_count <= 0) {
        return fail("authoritative remote skill-rank delta received invalid state");
    }

    std::uint16_t active_before = 0;
    if (!TryReadParticipantProgressionEntryActive(
            participant_id,
            option.option_id,
            &active_before)) {
        return fail("authoritative remote skill-rank delta could not read the current rank");
    }
    const auto active_after =
        static_cast<std::uint32_t>(active_before) +
        static_cast<std::uint32_t>(option.apply_count);
    if (active_after >
        static_cast<std::uint32_t>(
            (std::numeric_limits<std::uint16_t>::max)())) {
        return fail("authoritative remote skill-rank delta overflowed the native rank field");
    }

    const auto desired_active = static_cast<std::uint16_t>(active_after);
    if (!HydrateAuthoritativeRemoteProgressionEntryState(
            participant_id,
            option.option_id,
            desired_active,
            1,
            error_message)) {
        return false;
    }
    if (resulting_active != nullptr) {
        *resulting_active = desired_active;
    }
    return true;
}

#include "native_progression_derived_stats.inl"

void ReconcileRemoteParticipantDamageX4State(
    const ParticipantInfo& participant,
    uintptr_t progression_address) {
    if (progression_address == 0 ||
        kProgressionDamageX4RemainingTicksOffset == 0 ||
        (participant.runtime.transient_status_flags &
         ParticipantTransientStatusFlagSnapshotValid) == 0) {
        return;
    }

    const auto desired_ticks =
        (participant.runtime.transient_status_flags &
         ParticipantTransientStatusFlagDamageX4) != 0
            ? (std::clamp)(
                  participant.runtime.damage_x4_remaining_ticks,
                  std::int32_t{1},
                  kParticipantDamageX4MaxDurationTicks)
            : 0;
    std::int32_t native_ticks = 0;
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryReadField(
            progression_address,
            kProgressionDamageX4RemainingTicksOffset,
            &native_ticks) ||
        native_ticks == desired_ticks) {
        return;
    }
    (void)memory.TryWriteField(
        progression_address,
        kProgressionDamageX4RemainingTicksOffset,
        desired_ticks);
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
        if (!DoesLocalSceneMatchParticipantIntent(participant.runtime.scene_intent)) {
            g_local_transport.native_progression_reconcile_by_participant.erase(
                participant.participant_id);
            continue;
        }
        if (g_remote_native_progression_reconcile_suppressed_for_test.load(
                std::memory_order_acquire) == participant.participant_id) {
            continue;
        }

        SDModParticipantGameplayState gameplay_state;
        if (!TryGetParticipantGameplayState(participant.participant_id, &gameplay_state) ||
            !gameplay_state.available ||
            !gameplay_state.entity_materialized ||
            gameplay_state.progression_runtime_state_address == 0) {
            g_local_transport.native_progression_reconcile_by_participant.erase(
                participant.participant_id);
            continue;
        }
        const uintptr_t progression_address =
            gameplay_state.progression_runtime_state_address;
        ReconcileRemoteParticipantDamageX4State(
            participant,
            progression_address);
        const bool defer_progression_book_reconcile =
            IsLocalTransportHost() &&
            HasUnresolvedIssuedLevelUpOfferForParticipant(
                participant.participant_id);

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
            checkpoint.hagatha_perk_revision !=
                participant.owned_progression.hagatha_perk_revision ||
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
        checkpoint.hagatha_perk_revision =
            participant.owned_progression.hagatha_perk_revision;
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
        bool hagatha_perks_synchronized = false;
        int entry_state_write_count = 0;
        int derived_stat_write_count = 0;
        int hagatha_perk_mutation_count = 0;

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
        if (defer_progression_book_reconcile) {
            // The client applies its stock picker choice before the explicit
            // authority request reaches the host. Do not let its state packet
            // apply that rank to the remote clone first; the accepted choice
            // packet is the sole mutation while this offer is unresolved.
            complete = false;
        } else if (!participant.owned_progression.initialized ||
            participant.owned_progression.progression_book_entries.empty()) {
            complete = false;
        } else if (!TryReadNativeProgressionBookTable(progression_address, &table)) {
            complete = false;
        } else {
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

                if (native.active != desired.active ||
                    native.visible != desired.visible) {
                    if (entry_state_write_count >=
                        kNativeProgressionReconcileMaxEntryWritesPerTick) {
                        complete = false;
                        continue;
                    }
                    std::string hydration_error;
                    if (!HydrateAuthoritativeRemoteProgressionEntryState(
                            participant.participant_id,
                            desired.entry_index,
                            desired.active,
                            desired.visible,
                            &hydration_error) ||
                        !TryReadNativeProgressionBookEntry(
                            table,
                            desired.entry_index,
                            &native) ||
                        native.internal_id != desired.internal_id ||
                        native.category != desired.category ||
                        native.active != desired.active ||
                        native.visible != desired.visible) {
                        complete = false;
                        Log(
                            "Multiplayer authoritative progression entry hydration deferred. participant_id=" +
                            std::to_string(participant.participant_id) +
                            " entry_index=" + std::to_string(desired.entry_index) +
                            " desired_active=" + std::to_string(desired.active) +
                            " desired_visible=" + std::to_string(desired.visible) +
                            " error=" + hydration_error);
                        continue;
                    }
                    ++entry_state_write_count;
                }
            }
            if (participant.owned_progression.progression_book_truncated ||
                participant.owned_progression.progression_book_entry_total_count !=
                    participant.owned_progression.progression_book_entries.size()) {
                complete = false;
            }
        }

        if (participant.owned_progression.hagatha_perks.valid) {
            const bool apply_hagatha_runtime_state =
                !g_local_transport.is_host ||
                !participant.runtime.in_run ||
                progression_target_changed;
            if (!ReconcileRemoteHagathaPerks(
                    progression_address,
                    participant.owned_progression.hagatha_perks,
                    apply_hagatha_runtime_state,
                    &hagatha_perk_mutation_count)) {
                complete = false;
            } else {
                hagatha_perks_synchronized = true;
            }
        } else {
            complete = false;
        }

        // Observer-owned remote progression is passive replicated state. Keep
        // its per-gameplay-slot Concentrate lanes aligned without invoking the
        // stock progression refresh; exact owner-derived fields are copied below.
        if (participant.owned_progression.concentration_selection_valid) {
            std::string concentration_error;
            const bool concentration_ok =
                TryReconcileParticipantConcentrationRuntimeSelections(
                    participant.participant_id,
                    participant.owned_progression.concentration_entry_a,
                    participant.owned_progression.concentration_entry_b,
                    &concentration_error);
            if (!concentration_ok) {
                complete = false;
                if (checkpoint.last_concentration_failure_log_ms == 0 ||
                    now_ms - checkpoint.last_concentration_failure_log_ms >=
                        5000) {
                    checkpoint.last_concentration_failure_log_ms = now_ms;
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
                        " error=" + concentration_error);
                }
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
                if (checkpoint.last_derived_stat_failure_log_ms == 0 ||
                    now_ms - checkpoint.last_derived_stat_failure_log_ms >=
                        5000) {
                    checkpoint.last_derived_stat_failure_log_ms = now_ms;
                    Log(
                        "Multiplayer authoritative derived-stat reconcile deferred. participant_id=" +
                        std::to_string(participant.participant_id) +
                        " revision=" +
                        std::to_string(participant.owned_progression.derived_stat_revision));
                }
            } else {
                derived_stats_synchronized = true;
            }
        }

        checkpoint.complete = complete;
        if (level_synchronized ||
            move_speed_synchronized ||
            derived_stat_write_count > 0 ||
            hagatha_perk_mutation_count > 0 ||
            entry_state_write_count > 0 ||
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
                " hagatha_perks_synced=" +
                    std::to_string(hagatha_perks_synchronized ? 1 : 0) +
                " hagatha_perk_mutations=" +
                    std::to_string(hagatha_perk_mutation_count) +
                " hagatha_perk_revision=" +
                    std::to_string(participant.owned_progression.hagatha_perk_revision) +
                " entry_state_writes=" + std::to_string(entry_state_write_count) +
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
