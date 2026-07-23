bool InvokeNativeManaDeltaTrampolineForBotSafe(
    PlayerActorApplyManaDeltaFn fn,
    uintptr_t actor_address,
    float delta,
    std::uint8_t allow_prompt,
    std::uint8_t* result,
    DWORD* exception_code) {
    if (result != nullptr) {
        *result = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (fn == nullptr || actor_address == 0 || result == nullptr) {
        return false;
    }

    __try {
        *result = fn(reinterpret_cast<void*>(actor_address), delta, allow_prompt);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ClearIdleBotManaReserveNativeCastState(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    if (binding == nullptr || actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::int32_t primary_skill_id = 0;
    std::int32_t previous_skill_id = 0;
    std::uint32_t action_latch_e4 = 0;
    std::uint32_t action_latch_e8 = 0;
    std::uint8_t post_gate_active = 0;
    std::uint8_t no_interrupt = 0;
    std::uint8_t active_cast_group = kBotCastActorActiveCastGroupSentinel;
    std::uint16_t active_cast_slot = kBotCastActorActiveCastSlotSentinel;
    const bool state_readable =
        memory.TryReadField(actor_address, kActorPrimarySkillIdOffset, &primary_skill_id) &&
        memory.TryReadField(actor_address, kActorPreviousSkillIdOffset, &previous_skill_id) &&
        memory.TryReadField(actor_address, kActorPrimaryActionLatchE4Offset, &action_latch_e4) &&
        memory.TryReadField(actor_address, kActorPrimaryActionLatchE8Offset, &action_latch_e8) &&
        memory.TryReadField(actor_address, kActorPostGateActiveByteOffset, &post_gate_active) &&
        memory.TryReadField(actor_address, kActorNoInterruptFlagOffset, &no_interrupt) &&
        memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_cast_group) &&
        memory.TryReadField(actor_address, kActorActiveCastSlotShortOffset, &active_cast_slot);
    if (!state_readable) {
        return false;
    }

    const bool active_handle_live =
        active_cast_group != kBotCastActorActiveCastGroupSentinel &&
        active_cast_slot != kBotCastActorActiveCastSlotSentinel;
    const bool stale_cast_state =
        active_handle_live ||
        primary_skill_id != 0 ||
        previous_skill_id != 0 ||
        action_latch_e4 != 0 ||
        action_latch_e8 != 0 ||
        post_gate_active != 0 ||
        no_interrupt != 0;
    if (!stale_cast_state) {
        return false;
    }

    DWORD cleanup_exception_code = 0;
    bool cleanup_attempted = false;
    bool cleanup_ok = true;
    bool cleanup_state_available = false;
    bool cleanup_state_write_ok = false;
    bool cleanup_state_restore_ok = true;
    int cleanup_state_before = -1;
    int cleanup_state_after = -1;
    if (active_handle_live) {
        const auto cleanup_address =
            memory.ResolveGameAddressOrZero(kCastActiveHandleCleanup);
        if (cleanup_address != 0) {
            uintptr_t cleanup_state_table_address = 0;
            int cleanup_state_entry_count = 0;
            if (TryResolveGameplayIndexState(
                    &cleanup_state_table_address,
                    &cleanup_state_entry_count) &&
                cleanup_state_table_address != 0 &&
                cleanup_state_entry_count > 0 &&
                memory.TryReadValue<int>(
                    cleanup_state_table_address,
                    &cleanup_state_before)) {
                constexpr int kNativeCleanupRequiredGameplayState = 5;
                cleanup_state_available = true;
                if (cleanup_state_before != kNativeCleanupRequiredGameplayState) {
                    cleanup_state_write_ok =
                        memory.TryWriteValue<int>(
                            cleanup_state_table_address,
                            kNativeCleanupRequiredGameplayState);
                }
            }

            BotCastProcessingContext cast_context{
                binding,
                actor_address,
                cleanup_address,
                &memory};
            cleanup_attempted = true;
            InvokeBotCastWithNativeActorSlot(cast_context, [&] {
                cleanup_ok = CallCastActiveHandleCleanupSafe(
                    cleanup_address,
                    actor_address,
                    &cleanup_exception_code);
            });
            if (cleanup_state_write_ok) {
                cleanup_state_restore_ok =
                    memory.TryWriteValue<int>(
                        cleanup_state_table_address,
                        cleanup_state_before);
            }
            if (cleanup_state_available) {
                (void)memory.TryReadValue<int>(
                    cleanup_state_table_address,
                    &cleanup_state_after);
            }
        }
    }

    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0);
    (void)memory.TryWriteField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset, 0);
    (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE4Offset, 0);
    (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorPrimaryActionLatchE8Offset, 0);
    (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorPostGateActiveByteOffset, 0);
    (void)memory.TryWriteField<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0);

    std::uint8_t active_cast_group_after = kBotCastActorActiveCastGroupSentinel;
    std::uint16_t active_cast_slot_after = kBotCastActorActiveCastSlotSentinel;
    (void)memory.TryReadField(actor_address, kActorActiveCastGroupByteOffset, &active_cast_group_after);
    (void)memory.TryReadField(actor_address, kActorActiveCastSlotShortOffset, &active_cast_slot_after);

    if (now_ms - binding->last_mana_reserve_cleanup_log_ms >= 1000) {
        binding->last_mana_reserve_cleanup_log_ms = now_ms;
        Log(
            "[bots] native mana reserve idle cast cleanup. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(actor_address) +
            " cleanup_attempted=" +
                std::to_string(cleanup_attempted ? 1 : 0) +
            " cleanup_ok=" + std::to_string(cleanup_ok ? 1 : 0) +
            " cleanup_seh=" + HexString(cleanup_exception_code) +
            " cleanup_state_available=" +
                std::to_string(cleanup_state_available ? 1 : 0) +
            " cleanup_state_before=" + std::to_string(cleanup_state_before) +
            " cleanup_state_after=" + std::to_string(cleanup_state_after) +
            " cleanup_state_restore_ok=" +
                std::to_string(cleanup_state_restore_ok ? 1 : 0) +
            " skill_before=" + std::to_string(primary_skill_id) +
            " previous_before=" + std::to_string(previous_skill_id) +
            " e4_before=" + HexString(action_latch_e4) +
            " e8_before=" + HexString(action_latch_e8) +
            " post_gate_before=" + HexString(post_gate_active) +
            " no_interrupt_before=" + HexString(no_interrupt) +
            " group_before=" + HexString(active_cast_group) +
            " slot_before=" + HexString(active_cast_slot) +
            " group_after=" + HexString(active_cast_group_after) +
            " slot_after=" + HexString(active_cast_slot_after));
    }

    return true;
}

bool ApplyBotNativeManaReserveRecovery(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    if (binding == nullptr ||
        actor_address == 0 ||
        binding->bot_id == 0 ||
        !IsWizardParticipantKind(binding->kind) ||
        binding->ongoing_cast.active ||
        IsActorRuntimeDead(actor_address)) {
        return false;
    }

    (void)EnsureActorProgressionRuntimeFieldFromHandle(
        actor_address,
        "pre_native_bot_mana_recovery_progression_runtime");

    uintptr_t progression_address = 0;
    if (!TryResolveActorProgressionRuntime(actor_address, &progression_address) ||
        progression_address == 0) {
        return false;
    }

    float current_mp = 0.0f;
    float max_mp = 0.0f;
    if (!TryReadProgressionMana(progression_address, &current_mp, &max_mp)) {
        return false;
    }

    bool mana_reserve_active = false;
    if (!multiplayer::RefreshBotManaReserveState(
            binding->bot_id,
            current_mp,
            max_mp,
            &mana_reserve_active) ||
        !mana_reserve_active) {
        return false;
    }
    constexpr float kNativeManaRecoveryEpsilon = 0.001f;
    if (current_mp >= max_mp - kNativeManaRecoveryEpsilon) {
        return false;
    }

    const bool cleaned_stale_cast_state =
        ClearIdleBotManaReserveNativeCastState(binding, actor_address, now_ms);
    if (binding->mana_recovery_not_before_ms != 0 &&
        now_ms < binding->mana_recovery_not_before_ms) {
        (void)cleaned_stale_cast_state;
        return true;
    }

    const auto original =
        GetX86HookTrampoline<PlayerActorApplyManaDeltaFn>(
            g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
    if (original == nullptr) {
        return true;
    }

    const float interval_seconds =
        static_cast<float>(kBotManaReserveRecoveryIntervalMs) / 1000.0f;
    float delta =
        max_mp * kBotManaReserveRecoveryRatioPerSecond * interval_seconds;
    const float remaining_mp = max_mp - current_mp;
    if (delta > remaining_mp) {
        delta = remaining_mp;
    }
    if (!std::isfinite(delta) || delta <= kNativeManaRecoveryEpsilon) {
        return true;
    }

    binding->mana_recovery_not_before_ms =
        now_ms + kBotManaReserveRecoveryIntervalMs;

    std::uint8_t result = 0;
    DWORD exception_code = 0;
    bool invoked = false;
    std::string owner_context;
    InvokeWithBotProgressionSlotOwnerContext(
        actor_address,
        true,
        [&]() {
            invoked = InvokeNativeManaDeltaTrampolineForBotSafe(
                original,
                actor_address,
                delta,
                0,
                &result,
                &exception_code);
        },
        &owner_context);

    (void)EnsureActorProgressionRuntimeFieldFromHandle(
        actor_address,
        "post_native_bot_mana_recovery_progression_runtime");
    (void)RepairGameplayPlayerProgressionSlotOwner(
        "post_native_bot_mana_recovery",
        actor_address);

    float after_mp = current_mp;
    float after_max_mp = max_mp;
    const bool after_read =
        TryReadProgressionMana(progression_address, &after_mp, &after_max_mp);
    bool reserve_after = mana_reserve_active;
    if (after_read) {
        (void)multiplayer::RefreshBotManaReserveState(
            binding->bot_id,
            after_mp,
            after_max_mp,
            &reserve_after);
    }

    const bool should_log =
        !invoked ||
        !reserve_after ||
        (kEnableWizardBotHotPathDiagnostics &&
            now_ms - binding->last_mana_recovery_log_ms >= 1000);
    if (should_log) {
        binding->last_mana_recovery_log_ms = now_ms;
        Log(
            "[bots] native mana reserve recovery. bot_id=" +
            std::to_string(binding->bot_id) +
            " actor=" + HexString(actor_address) +
            " progression=" + HexString(progression_address) +
            " before=" + std::to_string(current_mp) +
            " after=" + std::to_string(after_mp) +
            " max=" + std::to_string(after_max_mp) +
            " delta=" + std::to_string(delta) +
            " result=" + std::to_string(static_cast<int>(result)) +
            " ok=" + (invoked ? std::string("1") : std::string("0")) +
            " seh=" + HexString(exception_code) +
            " reserve_after=" + std::to_string(reserve_after ? 1 : 0) +
            " interval_ms=" +
                std::to_string(kBotManaReserveRecoveryIntervalMs) +
            " ratio_per_second=" +
                std::to_string(kBotManaReserveRecoveryRatioPerSecond) +
            " slot_owner_context={" + owner_context + "}");
    }

    (void)invoked;
    return true;
}

std::uint8_t __fastcall HookPlayerActorApplyManaDelta(
    void* self,
    void* /*unused_edx*/,
    float delta,
    std::uint8_t allow_prompt) {
    const auto original =
        GetX86HookTrampoline<PlayerActorApplyManaDeltaFn>(
            g_gameplay_keyboard_injection.player_actor_apply_mana_delta_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    bool bot_actor = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            bot_actor = true;
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
        }
    }

    std::uint64_t participant_id = bot_id;
    if (!bot_actor) {
        SDModPlayerState player_state;
        if (TryGetPlayerState(&player_state) &&
            player_state.valid &&
            player_state.actor_address == actor_address) {
            participant_id =
                multiplayer::GetLocalTransportParticipantId();
            if (participant_id == 0) {
                participant_id = 1;
            }
        }
    }

    if (HasLuaManaChangeFilterHandlers()) {
        uintptr_t progression_address = 0;
        float current_mana = 0.0f;
        float maximum_mana = 0.0f;
        if (TryResolveActorProgressionRuntime(
                actor_address,
                &progression_address) &&
            progression_address != 0 &&
            TryReadProgressionMana(
                progression_address,
                &current_mana,
                &maximum_mana)) {
            LuaManaChangeFilterContext filtered_context;
            filtered_context.actor_address = actor_address;
            filtered_context.progression_address = progression_address;
            filtered_context.participant_id = participant_id;
            filtered_context.current_mana = current_mana;
            filtered_context.maximum_mana = maximum_mana;
            filtered_context.delta = delta;
            filtered_context.allow_prompt = allow_prompt != 0;
            if (!ApplyLuaManaChangeFilters(&filtered_context)) {
                return 1;
            }
            delta = filtered_context.delta;
        }
    }

    if (!bot_actor) {
        bool observe_local_delta = false;
        {
            std::lock_guard<std::mutex> lock(
                g_local_mana_delta_observation_mutex);
            observe_local_delta =
                g_local_mana_delta_observation.armed &&
                g_local_mana_delta_observation.actor_address == actor_address;
        }
        if (!observe_local_delta) {
            return original(self, delta, allow_prompt);
        }

        uintptr_t progression_address = 0;
        float mp_before = 0.0f;
        float max_mp_before = 0.0f;
        const bool have_before =
            TryResolveActorProgressionRuntime(
                actor_address,
                &progression_address) &&
            progression_address != 0 &&
            TryReadProgressionMana(
                progression_address,
                &mp_before,
                &max_mp_before);
        const auto result = original(self, delta, allow_prompt);
        float mp_after = 0.0f;
        float max_mp_after = 0.0f;
        const bool have_after =
            have_before &&
            TryReadProgressionMana(
                progression_address,
                &mp_after,
                &max_mp_after);
        if (have_after &&
            std::isfinite(mp_before) &&
            std::isfinite(mp_after)) {
            const float applied_delta = mp_after - mp_before;
            std::lock_guard<std::mutex> lock(
                g_local_mana_delta_observation_mutex);
            auto& observation = g_local_mana_delta_observation;
            if (!observation.armed ||
                observation.actor_address != actor_address) {
                return result;
            }
            observation.valid = true;
            ++observation.call_count;
            observation.last_delta = applied_delta;
            if (applied_delta < 0.0f) {
                ++observation.spend_call_count;
                observation.spent_total -= applied_delta;
            } else if (applied_delta > 0.0f) {
                ++observation.recovery_call_count;
                observation.recovered_total += applied_delta;
            }
        }
        return result;
    }

    (void)EnsureActorProgressionRuntimeFieldFromHandle(
        actor_address,
        "pre_native_mana_delta_progression_runtime");

    std::uint8_t result = 0;
    std::string owner_context;
    InvokeWithBotProgressionSlotOwnerContext(
        actor_address,
        true,
        [&]() {
            result = original(self, delta, allow_prompt);
        },
        &owner_context);

    (void)EnsureActorProgressionRuntimeFieldFromHandle(
        actor_address,
        "post_native_mana_delta_progression_runtime");
    (void)RepairGameplayPlayerProgressionSlotOwner(
        "post_native_bot_mana_delta",
        actor_address);

    static std::uint64_t s_last_native_mana_delta_owner_context_log_ms = 0;
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms - s_last_native_mana_delta_owner_context_log_ms >= 250) {
        s_last_native_mana_delta_owner_context_log_ms = now_ms;
        Log(
            "[bots] native mana delta owner context. bot_id=" +
            std::to_string(bot_id) +
            " actor=" + HexString(actor_address) +
            " gameplay_slot=" + std::to_string(gameplay_slot) +
            " delta=" + std::to_string(delta) +
            " allow_prompt=" + std::to_string(static_cast<int>(allow_prompt)) +
            " slot_owner_context={" + owner_context + "}");
    }

    return result;
}
