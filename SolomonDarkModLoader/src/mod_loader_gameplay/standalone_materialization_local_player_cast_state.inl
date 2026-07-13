struct LocalPlayerRunCastPrimeSnapshot {
    uintptr_t actor_address = 0;
    uintptr_t progression_handle = 0;
    uintptr_t progression_inner = 0;
    uintptr_t progression_runtime = 0;
    uintptr_t equip_handle = 0;
    uintptr_t equip_inner = 0;
    uintptr_t equip_runtime = 0;
    uintptr_t selection_pointer = 0;
    std::int32_t actor_primary_skill_id = 0;
    std::int32_t actor_previous_skill_id = 0;
    std::int32_t actor_selection_state = kUnknownAnimationStateId;
    std::int32_t progression_spell_id = 0;
    bool progression_spell_readable = false;
};

LocalPlayerRunCastPrimeSnapshot CaptureLocalPlayerRunCastPrimeSnapshot(
    uintptr_t actor_address) {
    LocalPlayerRunCastPrimeSnapshot snapshot{};
    snapshot.actor_address = actor_address;
    if (actor_address == 0) {
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryReadField(
        actor_address,
        kActorProgressionHandleOffset,
        &snapshot.progression_handle);
    snapshot.progression_inner = ReadSmartPointerInnerObject(snapshot.progression_handle);
    (void)memory.TryReadField(
        actor_address,
        kActorProgressionRuntimeStateOffset,
        &snapshot.progression_runtime);
    (void)memory.TryReadField(
        actor_address,
        kActorEquipHandleOffset,
        &snapshot.equip_handle);
    snapshot.equip_inner = ReadSmartPointerInnerObject(snapshot.equip_handle);
    (void)memory.TryReadField(
        actor_address,
        kActorEquipRuntimeStateOffset,
        &snapshot.equip_runtime);
    (void)memory.TryReadField(
        actor_address,
        kActorAnimationSelectionStateOffset,
        &snapshot.selection_pointer);
    (void)memory.TryReadField(
        actor_address,
        kActorPrimarySkillIdOffset,
        &snapshot.actor_primary_skill_id);
    (void)memory.TryReadField(
        actor_address,
        kActorPreviousSkillIdOffset,
        &snapshot.actor_previous_skill_id);
    snapshot.actor_selection_state = ResolveActorAnimationStateId(actor_address);

    const auto progression_for_spell =
        snapshot.progression_runtime != 0
            ? snapshot.progression_runtime
            : snapshot.progression_inner;
    if (progression_for_spell != 0) {
        snapshot.progression_spell_readable = memory.TryReadField(
            progression_for_spell,
            kProgressionCurrentSpellIdOffset,
            &snapshot.progression_spell_id);
    }
    return snapshot;
}

std::string DescribeLocalPlayerRunCastPrimeSnapshot(
    const LocalPlayerRunCastPrimeSnapshot& snapshot) {
    return
        "actor=" + HexString(snapshot.actor_address) +
        " prog_handle=" + HexString(snapshot.progression_handle) +
        " prog_inner=" + HexString(snapshot.progression_inner) +
        " prog_runtime=" + HexString(snapshot.progression_runtime) +
        " equip_handle=" + HexString(snapshot.equip_handle) +
        " equip_inner=" + HexString(snapshot.equip_inner) +
        " equip_runtime=" + HexString(snapshot.equip_runtime) +
        " selection_ptr=" + HexString(snapshot.selection_pointer) +
        " actor_sel=" + std::to_string(snapshot.actor_selection_state) +
        " skill=" + std::to_string(snapshot.actor_primary_skill_id) +
        " prev=" + std::to_string(snapshot.actor_previous_skill_id) +
        " prog_spell=" +
            (snapshot.progression_spell_readable
                ? std::to_string(snapshot.progression_spell_id)
                : UnreadableMemoryFieldText());
}

multiplayer::MultiplayerCharacterProfile BuildLocalPlayerRunCastProfile(
    const multiplayer::ParticipantInfo& local_participant) {
    auto profile = local_participant.character_profile;
    if (local_participant.owned_progression.ability_loadout_valid) {
        profile.loadout = local_participant.owned_progression.ability_loadout;
    } else {
        if (local_participant.runtime.primary_entry_index >= 0) {
            profile.loadout.primary_entry_index =
                local_participant.runtime.primary_entry_index;
        }
        if (local_participant.runtime.primary_combo_entry_index >= 0) {
            profile.loadout.primary_combo_entry_index =
                local_participant.runtime.primary_combo_entry_index;
        }
    }
    if (local_participant.runtime.level > 0) {
        profile.level = local_participant.runtime.level;
    }
    if (local_participant.runtime.experience_current >= 0) {
        profile.experience = local_participant.runtime.experience_current;
    }
    return profile;
}

bool MaybePrimeLocalPlayerRunCastState(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    if (gameplay_address == 0 ||
        actor_address == 0 ||
        !multiplayer::IsLocalTransportEnabled() ||
        !IsRunLifecycleActive()) {
        return false;
    }

    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address != actor_address) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* local_participant = multiplayer::FindLocalParticipant(runtime_state);
    if (local_participant == nullptr) {
        return false;
    }

    const auto profile = BuildLocalPlayerRunCastProfile(*local_participant);
    const auto selection_state = ResolveProfileSelectionState(profile);
    const auto& loadout = profile.loadout;

    static uintptr_t s_last_primed_actor = 0;
    static std::int32_t s_last_primary_entry = -2;
    static std::int32_t s_last_combo_entry = -2;
    static std::int32_t s_last_element_id = -1;
    static std::uint32_t s_last_spellbook_revision = 0;
    static std::uint32_t s_last_statbook_revision = 0;
    static std::uint32_t s_last_loadout_revision = 0;
    static std::uint64_t s_last_failure_log_ms = 0;

    const bool signature_changed =
        s_last_primed_actor != actor_address ||
        s_last_primary_entry != loadout.primary_entry_index ||
        s_last_combo_entry != loadout.primary_combo_entry_index ||
        s_last_element_id != profile.element_id ||
        s_last_spellbook_revision !=
            local_participant->owned_progression.spellbook_revision ||
        s_last_statbook_revision !=
            local_participant->owned_progression.statbook_revision ||
        s_last_loadout_revision !=
            local_participant->owned_progression.loadout_revision;

    const auto before = CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
    const bool progression_cache_ready =
        before.progression_inner != 0 &&
        before.progression_runtime == before.progression_inner;
    const bool selection_ready =
        before.selection_pointer != 0 &&
        before.actor_selection_state == selection_state;
    const bool spell_ready =
        before.progression_spell_readable &&
        before.progression_spell_id > 0;
    const bool equip_runtime_ready =
        before.equip_runtime != 0;
    if (!signature_changed &&
        progression_cache_ready &&
        equip_runtime_ready &&
        selection_ready &&
        spell_ready) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto ensure_progression_handle_address =
        memory.ResolveGameAddressOrZero(kPlayerActorEnsureProgressionHandle);
    const auto refresh_runtime_handles_address =
        memory.ResolveGameAddressOrZero(kPlayerActorRefreshRuntimeHandles);
    if (ensure_progression_handle_address == 0 ||
        refresh_runtime_handles_address == 0) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] native handle functions unavailable. "
                "ensure=" + HexString(ensure_progression_handle_address) +
                " refresh=" + HexString(refresh_runtime_handles_address) +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }

    DWORD exception_code = 0;
    if (!CallPlayerActorEnsureProgressionHandleSafe(
            ensure_progression_handle_address,
            actor_address,
            &exception_code)) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] ensure progression handle failed. seh=" +
                HexString(exception_code) +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }
    exception_code = 0;
    if (!CallPlayerActorRefreshRuntimeHandlesSafe(
            refresh_runtime_handles_address,
            actor_address,
            &exception_code)) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] refresh runtime handles failed. seh=" +
                HexString(exception_code) +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }
    const auto after_handle_refresh = CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
    if (after_handle_refresh.equip_runtime == 0) {
        std::string equip_repair_error;
        if (!EnsureWizardActorEquipRuntimeHandles(
                actor_address,
                "local_player_run_cast_prime",
                &equip_repair_error)) {
            if (now_ms - s_last_failure_log_ms >= 500) {
                s_last_failure_log_ms = now_ms;
                Log(
                    "[player-cast-prime] equip runtime repair failed. error=" +
                    equip_repair_error +
                    " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
                    "} after_refresh={" +
                    DescribeLocalPlayerRunCastPrimeSnapshot(after_handle_refresh) + "}");
            }
            return false;
        }

        const auto after_equip_repair = CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
        if (after_equip_repair.equip_runtime == 0) {
            if (now_ms - s_last_failure_log_ms >= 500) {
                s_last_failure_log_ms = now_ms;
                Log(
                    "[player-cast-prime] equip runtime repair left actor incomplete. "
                    "before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
                    "} after_refresh={" +
                    DescribeLocalPlayerRunCastPrimeSnapshot(after_handle_refresh) +
                    "} after_repair={" +
                    DescribeLocalPlayerRunCastPrimeSnapshot(after_equip_repair) + "}");
            }
            return false;
        }
    }
    const auto after_equip_ready = CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
    if (after_equip_ready.equip_runtime == 0) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] deferred until equip runtime is ready. "
                "before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
                "} after_refresh={" +
                DescribeLocalPlayerRunCastPrimeSnapshot(after_handle_refresh) +
                "} after_repair={" +
                DescribeLocalPlayerRunCastPrimeSnapshot(after_equip_ready) + "}");
        }
        return false;
    }

    if (!EnsureActorProgressionRuntimeFieldFromHandle(
            actor_address,
            "local_player_run_cast_prime")) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            const auto after_refresh =
                CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
            Log(
                "[player-cast-prime] progression runtime cache repair failed. "
                "before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
                "} after_refresh={" +
                DescribeLocalPlayerRunCastPrimeSnapshot(after_refresh) + "}");
        }
        return false;
    }

    uintptr_t progression_runtime = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_runtime) ||
        progression_runtime == 0) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            const auto after_refresh =
                CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
            Log(
                "[player-cast-prime] progression runtime resolve failed. "
                "before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
                "} after_refresh={" +
                DescribeLocalPlayerRunCastPrimeSnapshot(after_refresh) + "}");
        }
        return false;
    }

    // The cast-state prime calls character-selection helpers and actor refresh
    // routines that legitimately rebuild spell dispatch state, but those stock
    // routines also rewrite progression active/visible flags as if a new
    // character were being created. Preserve the live native book across the
    // complete prime transaction so runtime upgrades are never collapsed back
    // to their base selection levels.
    std::vector<PrimaryBuildProgressionFlagSnapshot> cast_prime_progression_flags;
    const bool have_cast_prime_progression_flags =
        CapturePrimaryBuildProgressionFlags(
            progression_runtime,
            &cast_prime_progression_flags);
    auto restore_cast_prime_progression_flags = [&](int* restored_entry_count) {
        if (restored_entry_count != nullptr) {
            *restored_entry_count = 0;
        }
        return !have_cast_prime_progression_flags ||
               RestorePrimaryBuildProgressionFlags(
                   cast_prime_progression_flags,
                   restored_entry_count);
    };

    std::string stage_error;
    if (!TryWriteGameplaySelectionStateForSlot(0, selection_state, &stage_error)) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] gameplay selection write failed. error=" +
                stage_error +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }
    (void)TryWriteActorAnimationStateIdDirect(actor_address, selection_state);

    if (!PrimeStandaloneWizardProgressionSelectionState(
            progression_runtime,
            selection_state,
            &stage_error)) {
        (void)restore_cast_prime_progression_flags(nullptr);
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] progression selection prime failed. error=" +
                stage_error +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }

    const auto refresh_progression_address =
        memory.ResolveGameAddressOrZero(kActorProgressionRefresh);
    if (refresh_progression_address == 0) {
        (void)restore_cast_prime_progression_flags(nullptr);
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] actor progression refresh unavailable. "
                "before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }
    exception_code = 0;
    if (!CallActorProgressionRefreshSafe(
            refresh_progression_address,
            actor_address,
            &exception_code)) {
        (void)restore_cast_prime_progression_flags(nullptr);
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] progression refresh failed. seh=" +
                HexString(exception_code) +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }

    int resolved_primary_skill_id = -1;
    if (!ApplyProfilePrimaryLoadoutToSkillsWizard(
            progression_runtime,
            profile,
            &resolved_primary_skill_id,
            &stage_error)) {
        (void)restore_cast_prime_progression_flags(nullptr);
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] primary loadout projection failed. error=" +
                stage_error +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }

    exception_code = 0;
    if (!CallActorProgressionRefreshSafe(
            refresh_progression_address,
            actor_address,
            &exception_code)) {
        (void)restore_cast_prime_progression_flags(nullptr);
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] progression refresh after loadout failed. seh=" +
                HexString(exception_code) +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) + "}");
        }
        return false;
    }
    int restored_cast_prime_entry_count = 0;
    if (!restore_cast_prime_progression_flags(
            &restored_cast_prime_entry_count)) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] progression flags could not be restored after cast-state prime. "
                "progression=" + HexString(progression_runtime));
        }
        return false;
    }
    if (restored_cast_prime_entry_count > 0) {
        Log(
            "[player-cast-prime] restored native progression flags after cast-state prime. progression=" +
            HexString(progression_runtime) +
            " restored_entries=" +
            std::to_string(restored_cast_prime_entry_count));
    }
    (void)EnsureActorProgressionRuntimeFieldFromHandle(
        actor_address,
        "local_player_run_cast_prime_post_loadout");

    const auto after = CaptureLocalPlayerRunCastPrimeSnapshot(actor_address);
    const bool after_ready =
        after.progression_inner != 0 &&
        after.progression_runtime == after.progression_inner &&
        after.equip_runtime != 0 &&
        after.selection_pointer != 0 &&
        after.actor_selection_state == selection_state &&
        after.progression_spell_readable &&
        after.progression_spell_id > 0;
    if (!after_ready) {
        if (now_ms - s_last_failure_log_ms >= 500) {
            s_last_failure_log_ms = now_ms;
            Log(
                "[player-cast-prime] local run cast state still incomplete. "
                "selection_state=" + std::to_string(selection_state) +
                " resolved_primary_skill=" + std::to_string(resolved_primary_skill_id) +
                " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
                "} after={" + DescribeLocalPlayerRunCastPrimeSnapshot(after) + "}");
        }
        return false;
    }

    s_last_primed_actor = actor_address;
    s_last_primary_entry = loadout.primary_entry_index;
    s_last_combo_entry = loadout.primary_combo_entry_index;
    s_last_element_id = profile.element_id;
    s_last_spellbook_revision =
        local_participant->owned_progression.spellbook_revision;
    s_last_statbook_revision =
        local_participant->owned_progression.statbook_revision;
    s_last_loadout_revision =
        local_participant->owned_progression.loadout_revision;

    Log(
        "[player-cast-prime] local run cast state primed. "
        "selection_state=" + std::to_string(selection_state) +
        " primary_entry=" + std::to_string(loadout.primary_entry_index) +
        " combo_entry=" + std::to_string(loadout.primary_combo_entry_index) +
        " resolved_primary_skill=" + std::to_string(resolved_primary_skill_id) +
        " spellbook_revision=" +
            std::to_string(local_participant->owned_progression.spellbook_revision) +
        " statbook_revision=" +
            std::to_string(local_participant->owned_progression.statbook_revision) +
        " loadout_revision=" +
            std::to_string(local_participant->owned_progression.loadout_revision) +
        " before={" + DescribeLocalPlayerRunCastPrimeSnapshot(before) +
        "} after={" + DescribeLocalPlayerRunCastPrimeSnapshot(after) + "}");
    return true;
}
