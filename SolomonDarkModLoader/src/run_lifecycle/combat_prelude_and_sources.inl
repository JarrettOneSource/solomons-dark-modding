bool IsCombatPreludeOnlyActive() {
    if (!g_state.combat_prelude_only_suppression.load(std::memory_order_acquire)) {
        return false;
    }

    SDModGameplayCombatState combat_state;
    if (!TryGetGameplayCombatState(&combat_state) || !combat_state.valid) {
        return false;
    }

    if (combat_state.combat_wave_index != 0 ||
        combat_state.combat_wave_counter != 999999999 ||
        combat_state.combat_transition_requested == 0 ||
        combat_state.combat_active == 0) {
        static std::uint64_t s_last_prelude_repin_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_prelude_repin_log_ms >= 1000) {
            s_last_prelude_repin_log_ms = now_ms;
            Log(
                "combat_prelude: re-pinning explicit no-wave state. arena=" +
                HexString(combat_state.arena_address) +
                " wave=" + std::to_string(combat_state.combat_wave_index) +
                " wave_counter=" + std::to_string(combat_state.combat_wave_counter) +
                " transition_requested=" +
                std::to_string(static_cast<unsigned>(combat_state.combat_transition_requested)) +
                " combat_active=" +
                std::to_string(static_cast<unsigned>(combat_state.combat_active)));
        }
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory.TryWriteField<std::int32_t>(
        combat_state.arena_address,
        kArenaCombatWaveIndexOffset,
        0);
    (void)memory.TryWriteField<std::int32_t>(
        combat_state.arena_address,
        kArenaCombatWaveCounterOffset,
        999999999);
    (void)memory.TryWriteField<std::uint8_t>(
        combat_state.arena_address,
        kArenaCombatTransitionRequestedOffset,
        static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField<std::uint8_t>(
        combat_state.arena_address,
        kArenaCombatStartedMusicOffset,
        static_cast<std::uint8_t>(1));
    (void)memory.TryWriteField<std::uint8_t>(
        combat_state.arena_address,
        kArenaCombatActiveFlagOffset,
        static_cast<std::uint8_t>(1));
    g_state.current_wave.store(0, std::memory_order_release);
    return true;
}

float BitsToFloat(std::uint32_t bits) {
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

bool IsReturnAddressNear(uintptr_t return_address, uintptr_t function_address, uintptr_t max_span) {
    const auto resolved = ProcessMemory::Instance().ResolveGameAddressOrZero(function_address);
    return resolved != 0 && return_address >= resolved && return_address < resolved + max_span;
}

const char* ClassifyGoldChangeSource(uintptr_t return_address, int delta) {
    if (IsReturnAddressNear(return_address, kGoldScriptCaller, 0x1800)) {
        return kGoldSourceScript;
    }
    if (IsReturnAddressNear(return_address, kGoldPickupCaller, 0x900)) {
        return kGoldSourcePickup;
    }
    if (IsReturnAddressNear(return_address, kGoldMirrorCaller, 0x500) ||
        IsReturnAddressNear(return_address, kGoldSpendCaller, 0x500) ||
        IsReturnAddressNear(return_address, kGoldShopCaller, 0x700)) {
        return kGoldSourceSpend;
    }
    if (delta > 0) {
        return kGoldSourcePickup;
    }
    if (delta < 0) {
        return kGoldSourceSpend;
    }
    return kGoldSourceUnknown;
}

float ReadFloatFieldOrZero(uintptr_t address, size_t offset) {
    return ProcessMemory::Instance().ReadFieldOr<float>(address, offset, 0.0f);
}

std::string DescribeSpellCastHookActorState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return "actor=0x0";
    }

    auto& memory = ProcessMemory::Instance();
    SDModPlayerState player_state{};
    const bool have_player_state = TryGetPlayerState(&player_state) && player_state.valid;
    const bool is_local_actor = have_player_state && player_state.actor_address == actor_address;

    return
        "actor=" + HexString(actor_address) +
        " local=" + std::to_string(is_local_actor ? 1 : 0) +
        " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " slot=" + std::to_string(memory.ReadFieldOr<int>(actor_address, kActorSlotOffset, -1)) +
        " world_slot=" + std::to_string(memory.ReadFieldOr<int>(actor_address, kActorWorldSlotOffset, -1)) +
        " skill=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0)) +
        " prev=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset + sizeof(std::int32_t), 0)) +
        " drive=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0)) +
        " no_int=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0)) +
        " group=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " cast_slot=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " heading=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f)) +
        " aimx=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetXOffset, 0.0f)) +
        " aimy=" + std::to_string(memory.ReadFieldOr<float>(actor_address, kActorAimTargetYOffset, 0.0f)) +
        " aux0=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0)) +
        " aux1=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0)) +
        " f278=" + std::to_string(memory.ReadFieldOr<std::uint32_t>(actor_address, 0x278, 0)) +
        " f29c=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x29C, 0.0f)) +
        " f2a0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2A0, 0.0f)) +
        " f2d0=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D0, 0.0f)) +
        " f2d4=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D4, 0.0f)) +
        " f2d8=" + std::to_string(memory.ReadFieldOr<float>(actor_address, 0x2D8, 0.0f)) +
        " selection_ptr=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)) +
        " progression_runtime=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
        " progression_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
}
