struct SharedProgressionNativeSnapshot {
    bool valid = false;
    std::int32_t level = 0;
    float experience = 0.0f;
    std::int32_t next_experience = 0;
};

SharedProgressionNativeSnapshot ReadSharedProgressionNativeSnapshot(
    uintptr_t progression_address) {
    SharedProgressionNativeSnapshot snapshot;
    auto& memory = ProcessMemory::Instance();
    snapshot.valid =
        progression_address != 0 &&
        memory.TryReadField(
            progression_address,
            kProgressionLevelOffset,
            &snapshot.level) &&
        memory.TryReadField(
            progression_address,
            kProgressionXpOffset,
            &snapshot.experience) &&
        TryReadRunLifecycleRoundedNextXp(
            progression_address,
            &snapshot.next_experience) &&
        snapshot.level > 0 &&
        std::isfinite(snapshot.experience) &&
        snapshot.experience >= 0.0f &&
        snapshot.next_experience > 0;
    return snapshot;
}

bool CallSharedProgressionExperienceGainSafe(
    uintptr_t function_address,
    uintptr_t progression_address,
    float amount) {
    if (function_address == 0 || progression_address == 0) {
        return false;
    }
    const auto function =
        reinterpret_cast<ExperienceGainFn>(function_address);
    __try {
        function(
            reinterpret_cast<void*>(progression_address),
            amount,
            1);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

void CompleteSharedKillProgressionTransaction(
    const multiplayer::SharedKillExperienceCredit& credit,
    float expected_native_amount,
    uintptr_t local_progression_address,
    const SharedProgressionNativeSnapshot& local_before) {
    constexpr float kExperienceDeltaEpsilon = 0.0001f;
    uintptr_t canonical_progression_address = 0;
    SharedProgressionNativeSnapshot canonical_after;
    float experience_before = 0.0f;
    const char* canonical_source = "stock_slot0";

    const auto local_after =
        ReadSharedProgressionNativeSnapshot(local_progression_address);
    if (local_before.valid &&
        local_after.valid &&
        local_after.experience >
            local_before.experience + kExperienceDeltaEpsilon) {
        canonical_progression_address = local_progression_address;
        canonical_after = local_after;
        experience_before = local_before.experience;
    } else if (credit.source_progression_address != 0) {
        canonical_progression_address =
            credit.source_progression_address;
        canonical_after = ReadSharedProgressionNativeSnapshot(
            canonical_progression_address);
        experience_before = credit.source_experience_before;
        if (!canonical_after.valid ||
            canonical_after.experience <=
                experience_before + kExperienceDeltaEpsilon) {
            const auto experience_gain_address =
                ProcessMemory::Instance().ResolveGameAddressOrZero(
                    kExperienceGain);
            if (experience_gain_address == 0 ||
                !CallSharedProgressionExperienceGainSafe(
                    experience_gain_address,
                    canonical_progression_address,
                    expected_native_amount)) {
                Log(
                    "Multiplayer shared kill XP killer progression call failed. "
                    "killer_participant_id=" +
                    std::to_string(credit.participant_id) +
                    " run_nonce=" +
                    std::to_string(credit.run_nonce));
                return;
            }
            canonical_after = ReadSharedProgressionNativeSnapshot(
                canonical_progression_address);
        }
        canonical_source = "killer_progression";
    }

    if (!canonical_after.valid ||
        canonical_progression_address == 0 ||
        canonical_after.experience <=
            experience_before + kExperienceDeltaEpsilon) {
        Log(
            "Multiplayer shared kill XP native result unavailable. "
            "killer_participant_id=" +
            std::to_string(credit.participant_id) +
            " run_nonce=" + std::to_string(credit.run_nonce));
        return;
    }

    const auto credited_experience =
        canonical_after.experience - experience_before;
    multiplayer::SyncInRunParticipantsToSharedProgression(
        credit.run_nonce,
        canonical_after.level,
        canonical_after.experience,
        canonical_after.next_experience,
        canonical_progression_address);
    multiplayer::ObserveParticipantKillExperienceRewardAttribution(
        credit.participant_id,
        credited_experience);
    multiplayer::PublishAuthoritativeSharedProgression(
        credit.participant_id,
        credit.run_nonce,
        canonical_after.level,
        canonical_after.experience,
        canonical_after.next_experience);
    Log(
        "Multiplayer shared kill XP applied. killer_participant_id=" +
        std::to_string(credit.participant_id) +
        " run_nonce=" + std::to_string(credit.run_nonce) +
        " wave=" + std::to_string(credit.wave) +
        " enemy_type=" + std::to_string(credit.enemy_type) +
        " base_reward=" + std::to_string(credit.base_reward) +
        " gameplay_multiplier=" +
        std::to_string(credit.gameplay_multiplier) +
        " canonical_source=" + canonical_source +
        " level=" + std::to_string(canonical_after.level) +
        " xp_before=" + std::to_string(experience_before) +
        " xp_after=" +
        std::to_string(canonical_after.experience) +
        " next_xp=" +
        std::to_string(canonical_after.next_experience) +
        " killer_credited_xp=" +
        std::to_string(credited_experience));
}

void __fastcall HookNativeApplyDamage(
    void* self,
    void* /*unused_edx*/,
    void* target_actor) {
    const auto original =
        GetX86HookTrampoline<NativeApplyDamageFn>(
            g_state.hooks[kHookNativeApplyDamage]);
    if (original == nullptr) {
        return;
    }

    uintptr_t local_progression_address = 0;
    SDModPlayerState local_player;
    if (TryGetPlayerState(&local_player) && local_player.valid) {
        local_progression_address = local_player.progression_address;
    }
    const auto local_before =
        ReadSharedProgressionNativeSnapshot(local_progression_address);

    original(self, target_actor);

    multiplayer::SharedKillExperienceCredit credit;
    float expected_native_amount = 0.0f;
    if (!multiplayer::ConsumeSharedKillExperienceCredit(
            &credit,
            &expected_native_amount)) {
        return;
    }
    CompleteSharedKillProgressionTransaction(
        credit,
        expected_native_amount,
        local_progression_address,
        local_before);
}

int __fastcall HookEnemyDeath(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<EnemyDeathFn>(g_state.hooks[kHookEnemyDeath]);
    if (original == nullptr) {
        return 0;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    std::uint8_t already_handled_byte = 0;
    const bool have_already_handled =
        memory.TryReadField(self_address, kEnemyDeathHandledOffset, &already_handled_byte);
    int enemy_type = LookupRememberedEnemyType(self_address);
    const bool have_enemy_type = enemy_type >= 0 || TryReadEnemyTypeFromActor(self_address, &enemy_type);
    SDModLuaEnemySpawnConfig lua_enemy_config;
    const std::uint64_t content_id =
        LookupLuaEnemySpawnConfig(self_address, &lua_enemy_config)
            ? lua_enemy_config.content_id
            : 0;
    float x = 0.0f;
    float y = 0.0f;
    const bool have_position = TryReadActorPosition(self_address, &x, &y);
    const bool already_handled_before_death =
        have_already_handled && already_handled_byte != 0;
    if (have_already_handled &&
        !already_handled_before_death &&
        IsCombatArenaActiveForEnemyTracking()) {
        multiplayer::NotifyLocalRunEnemyDeath(self_address);
    }

    const auto result = original(self, unused_edx);
    {
        std::lock_guard<std::mutex> lock(g_manual_run_enemy_spawn_mutex);
        g_frozen_manual_run_enemies.erase(self_address);
    }
    if (!already_handled_before_death &&
        IsCombatArenaActiveForEnemyTracking()) {
        const auto wave_update = ObserveAuthorityWaveEnemyDeath(
            self_address);
        if (wave_update.completed_wave != 0) {
            DispatchLuaWaveCompleted(wave_update.completed_wave);
        }
    }
    if (!have_enemy_type) {
        Log("enemy.death native type unavailable. enemy=" + HexString(self_address));
        ForgetEnemyType(self_address);
        return result;
    }
    if (!have_position) {
        Log("enemy.death native position unavailable. enemy=" + HexString(self_address));
        ForgetEnemyType(self_address);
        return result;
    }
    if (!have_already_handled) {
        Log("enemy.death native handled flag unavailable. enemy=" + HexString(self_address));
        ForgetEnemyType(self_address);
        return result;
    }
    const bool already_handled = already_handled_byte != 0;
    Log(
        "enemy.death hook invoked. enemy=" + HexString(self_address) +
        " enemy_type=" + std::to_string(enemy_type) +
        " pos=(" + std::to_string(x) + "," + std::to_string(y) + ")" +
        " already_handled=" + std::to_string(already_handled ? 1 : 0) +
        " run_active=" + std::to_string(IsRunActive() ? 1 : 0) +
        " result=" + std::to_string(result));
    ForgetEnemyType(self_address);
    if (!already_handled && IsCombatArenaActiveForEnemyTracking()) {
        DispatchLuaEnemyDeath(
            enemy_type,
            x,
            y,
            kUnknownKillMethod,
            content_id);
    }

    return result;
}

int __stdcall HookGoldChanged(int delta, char allow_negative) {
    const auto original = GetX86HookTrampoline<GoldChangedFn>(g_state.hooks[kHookGoldChanged]);
    if (original == nullptr) {
        return 0;
    }

    const auto return_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto* source = ClassifyGoldChangeSource(return_address, delta);
    int gold_before = 0;
    const bool have_gold_before = TryReadResolvedGlobalInt(kGoldGlobal, &gold_before);
    auto filtered_delta = delta;
    if (have_gold_before &&
        HasLuaGoldChangeFilterHandlers() &&
        !IsApplyingAcceptedReplicatedGoldPickupFeedback()) {
        LuaGoldChangeFilterContext filter_context;
        filter_context.participant_id = multiplayer::GetLocalTransportParticipantId();
        filter_context.current_gold = gold_before;
        filter_context.delta = delta;
        filter_context.allow_negative = allow_negative != 0;
        filter_context.source = source;
        if (!ApplyLuaGoldChangeFilters(&filter_context)) {
            return 0;
        }
        filtered_delta = filter_context.delta;
    }

    const auto result = original(filtered_delta, allow_negative);
    if (result != 0) {
        int gold = 0;
        if (TryReadResolvedGlobalInt(kGoldGlobal, &gold)) {
            const auto applied_delta = have_gold_before
                ? gold - gold_before
                : filtered_delta;
            DispatchLuaGoldChanged(gold, applied_delta, source);
        } else {
            Log(
                "gold.changed native gold global unavailable. delta=" + std::to_string(filtered_delta) +
                " source=" + std::string(source));
        }
    }
    return result;
}

void __fastcall HookExperienceGain(
    void* self,
    void* /*unused_edx*/,
    float amount,
    char apply_native_scaling) {
    const auto original =
        GetX86HookTrampoline<ExperienceGainFn>(g_state.hooks[kHookExperienceGain]);
    if (original == nullptr) {
        return;
    }

    const auto progression_address = reinterpret_cast<uintptr_t>(self);
    const auto synthetic_participant_id =
        FindNaturalSyntheticParticipantForProgression(
            progression_address);
    float current_xp = 0.0f;
    const bool have_current_xp =
        progression_address != 0 &&
        ProcessMemory::Instance().TryReadField(
            progression_address,
            kProgressionXpOffset,
            &current_xp) &&
        std::isfinite(current_xp) &&
        current_xp >= 0.0f;
    if (have_current_xp &&
        std::isfinite(amount) &&
        amount >= 0.0f &&
        HasLuaXpGainFilterHandlers()) {
        LuaXpGainFilterContext filter_context;
        filter_context.progression_address = progression_address;
        filter_context.participant_id =
            IsLocalPlayerProgressionForRunLifecycle(progression_address)
                ? multiplayer::GetLocalTransportParticipantId()
                : synthetic_participant_id;
        filter_context.current_xp = current_xp;
        filter_context.amount = amount;
        filter_context.apply_native_scaling = apply_native_scaling != 0;
        filter_context.source = apply_native_scaling != 0 ? "reward" : "script";
        if (!ApplyLuaXpGainFilters(&filter_context)) {
            return;
        }
        amount = filter_context.amount;
    }

    original(self, amount, apply_native_scaling);
    if (synthetic_participant_id != 0) {
        int level = 0;
        int experience = 0;
        int next_experience = 0;
        auto& memory = ProcessMemory::Instance();
        if (memory.TryReadField(
                progression_address,
                kProgressionLevelOffset,
                &level) &&
            TryReadRunLifecycleRoundedXp(
                progression_address,
                &experience) &&
            TryReadRunLifecycleRoundedNextXp(
                progression_address,
                &next_experience)) {
            multiplayer::UpdateParticipantLevelProfileState(
                synthetic_participant_id,
                level,
                experience,
                next_experience);
        }
    }
}

void __fastcall HookDropSpawned(
    void* self,
    void* unused_edx,
    std::uint32_t x_bits,
    std::uint32_t y_bits,
    int amount,
    int lifetime) {
    const auto original = GetX86HookTrampoline<DropSpawnedFn>(g_state.hooks[kHookDropSpawned]);
    if (original == nullptr) {
        return;
    }

    original(self, unused_edx, x_bits, y_bits, amount, lifetime);
    if (!IsRunActive()) {
        return;
    }

    DispatchLuaDropSpawned(kDropKindGold, BitsToFloat(x_bits), BitsToFloat(y_bits));
}

void __fastcall HookLevelUp(void* self, void* unused_edx) {
    const auto original = GetX86HookTrampoline<LevelUpFn>(g_state.hooks[kHookLevelUp]);
    if (original == nullptr) {
        return;
    }

    const auto progression_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    int level_before = 0;
    const bool have_level_before =
        memory.TryReadField(progression_address, kProgressionLevelOffset, &level_before);
    int pending_before = 0;
    const bool have_pending_before = TryReadPendingLevelKind(&pending_before);
    const auto local_player_level_up = IsLocalPlayerProgressionForRunLifecycle(progression_address);
    const auto synthetic_participant_id =
        FindNaturalSyntheticParticipantForProgression(
            progression_address);
    const bool suppress_client_local_level_up =
        local_player_level_up && multiplayer::IsLocalTransportClient();
    // Both host and client suppress the native modal skill picker for their own
    // local-player level-up. The native picker monopolizes the gameplay thread
    // until a human dismisses it, which deadlocks the loader-driven mirror/peer
    // transform sync (the kill-loop convergence freeze). Writing non-local mode
    // around the native routine preserves the level increment but routes
    // selection through the loader's controlled, non-modal offer path for both
    // roles: the client resolves through the host authority, while the host
    // resolves its own offer locally via PublishLocalHostSelfLevelUpOffer.
    const bool suppress_local_native_picker =
        local_player_level_up &&
        (multiplayer::IsLocalTransportClient() || multiplayer::IsLocalTransportHost());
    std::uint8_t previous_progression_mode = kProgressionLocalPlayerModeValue;
    const bool have_previous_progression_mode =
        suppress_local_native_picker &&
        memory.TryReadField<std::uint8_t>(
            progression_address,
            kProgressionNonLocalModeFlagOffset,
            &previous_progression_mode);
    const bool wrote_local_level_up_gate =
        suppress_local_native_picker &&
        memory.TryWriteField<std::uint8_t>(
            progression_address,
            kProgressionNonLocalModeFlagOffset,
            kProgressionNonLocalModeValue);
    if (suppress_local_native_picker && !wrote_local_level_up_gate) {
        Log(
            "level.up local gate failed to set non-local mode before native level-up. progression=" +
            HexString(progression_address));
    }

    original(self, unused_edx);
    if (wrote_local_level_up_gate) {
        const auto restore_mode =
            have_previous_progression_mode ? previous_progression_mode : kProgressionLocalPlayerModeValue;
        if (!memory.TryWriteField<std::uint8_t>(
                progression_address,
                kProgressionNonLocalModeFlagOffset,
                restore_mode)) {
            Log(
                "level.up local gate failed to restore progression mode after native level-up. progression=" +
                HexString(progression_address) +
                " restore_mode=" + std::to_string(restore_mode));
        }
    }
    if (!IsRunActive()) {
        return;
    }

    if (!have_level_before) {
        Log(
            "level.up native level-before unavailable. progression=" +
            HexString(progression_address));
        return;
    }

    int level_after = 0;
    if (!memory.TryReadField(progression_address, kProgressionLevelOffset, &level_after)) {
        Log(
            "level.up native level-after unavailable. progression=" +
            HexString(progression_address) +
            " level_before=" + std::to_string(level_before));
        return;
    }
    if (level_after <= level_before) {
        return;
    }

    int xp_after = 0;
    if (!TryReadRunLifecycleRoundedXp(progression_address, &xp_after)) {
        Log(
            "level.up native xp unavailable. progression=" +
            HexString(progression_address) +
            " level_before=" + std::to_string(level_before) +
            " level_after=" + std::to_string(level_after));
        return;
    }
    if (!local_player_level_up || suppress_client_local_level_up) {
        if (have_pending_before) {
            RestoreNonLocalPendingLevelKind(progression_address, pending_before, level_after, xp_after);
        } else {
            Log(
                "level.up pending-level-kind global unavailable before native level-up; restore skipped. progression=" +
                HexString(progression_address) +
                " level=" + std::to_string(level_after) +
                " xp=" + std::to_string(xp_after));
        }
        if (suppress_client_local_level_up) {
            Log(
                "level.up client local picker/event gated. progression=" +
                HexString(progression_address) +
                " level=" + std::to_string(level_after) +
                " xp=" + std::to_string(xp_after));
        }
        if (synthetic_participant_id != 0) {
            std::string publish_error;
            if (!multiplayer::PublishNaturalParticipantLevelUp(
                    synthetic_participant_id,
                    progression_address,
                    level_after,
                    xp_after,
                    &publish_error)) {
                Log(
                    "[bots] natural synthetic level-up publication failed. "
                    "participant_id=" +
                    std::to_string(synthetic_participant_id) +
                    " level=" + std::to_string(level_after) +
                    " xp=" + std::to_string(xp_after) +
                    " error=" + publish_error);
            }
        }
        return;
    }

    const bool suppress_level_up_side_effects =
        multiplayer::ShouldSuppressLocalLevelUpFanout();
    if (!suppress_level_up_side_effects) {
        multiplayer::SyncBotsToSharedLevelUp(level_after, xp_after, progression_address);
        multiplayer::PublishHostLevelUpBarrierOffers(
            level_after,
            xp_after,
            progression_address);
        DispatchLuaLevelUp(level_after, xp_after);
    }
}
