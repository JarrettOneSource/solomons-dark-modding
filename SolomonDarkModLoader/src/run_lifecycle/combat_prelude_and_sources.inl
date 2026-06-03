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

bool TryReadFloatField(uintptr_t address, size_t offset, float* value) {
    if (value == nullptr) {
        return false;
    }

    *value = 0.0f;
    if (address == 0) {
        return false;
    }

    return ProcessMemory::Instance().TryReadField(address, offset, value) &&
           std::isfinite(*value);
}

bool TryReadActorPosition(uintptr_t actor_address, float* x, float* y) {
    return TryReadFloatField(actor_address, kActorPositionXOffset, x) &&
           TryReadFloatField(actor_address, kActorPositionYOffset, y);
}

template <typename T>
std::string FormatReadableNativeField(uintptr_t base_address, size_t offset) {
    T value{};
    if (!ProcessMemory::Instance().TryReadField(base_address, offset, &value)) {
        return "unreadable";
    }

    return std::to_string(value);
}

template <typename T>
std::string FormatReadableNativeFieldHex(uintptr_t base_address, size_t offset) {
    T value{};
    if (!ProcessMemory::Instance().TryReadField(base_address, offset, &value)) {
        return "unreadable";
    }

    return HexString(static_cast<uintptr_t>(value));
}

std::string FormatReadableNativeFloatField(uintptr_t base_address, size_t offset) {
    float value = 0.0f;
    if (!TryReadFloatField(base_address, offset, &value)) {
        return "unreadable";
    }

    return std::to_string(value);
}

std::string DescribeSpellCastHookActorState(uintptr_t actor_address) {
    if (actor_address == 0) {
        return "actor=0x0";
    }

    SDModPlayerState player_state{};
    const bool have_player_state = TryGetPlayerState(&player_state) && player_state.valid;
    const bool is_local_actor = have_player_state && player_state.actor_address == actor_address;

    return
        "actor=" + HexString(actor_address) +
        " local=" + std::to_string(is_local_actor ? 1 : 0) +
        " owner=" + FormatReadableNativeFieldHex<uintptr_t>(actor_address, kActorOwnerOffset) +
        " slot=" + FormatReadableNativeField<int>(actor_address, kActorSlotOffset) +
        " world_slot=" + FormatReadableNativeField<int>(actor_address, kActorWorldSlotOffset) +
        " skill=" + FormatReadableNativeField<std::int32_t>(actor_address, kActorPrimarySkillIdOffset) +
        " prev=" + FormatReadableNativeField<std::int32_t>(actor_address, kActorPreviousSkillIdOffset) +
        " drive=" + FormatReadableNativeFieldHex<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset) +
        " no_int=" + FormatReadableNativeFieldHex<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset) +
        " group=" + FormatReadableNativeFieldHex<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset) +
        " cast_slot=" + FormatReadableNativeFieldHex<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset) +
        " heading=" + FormatReadableNativeFloatField(actor_address, kActorHeadingOffset) +
        " aimx=" + FormatReadableNativeFloatField(actor_address, kActorAimTargetXOffset) +
        " aimy=" + FormatReadableNativeFloatField(actor_address, kActorAimTargetYOffset) +
        " aux0=" + FormatReadableNativeFieldHex<std::uint32_t>(actor_address, kActorAimTargetAux0Offset) +
        " aux1=" + FormatReadableNativeFieldHex<std::uint32_t>(actor_address, kActorAimTargetAux1Offset) +
        " f278=" + FormatReadableNativeField<std::uint32_t>(actor_address, kActorStartupCounterOffset) +
        " f29c=" + FormatReadableNativeFloatField(actor_address, kActorSpellConfig29cOffset) +
        " f2a0=" + FormatReadableNativeFloatField(actor_address, kActorSpellConfig2a0Offset) +
        " f2d0=" + FormatReadableNativeFloatField(actor_address, kActorSpellConfig2d0Offset) +
        " f2d4=" + FormatReadableNativeFloatField(actor_address, kActorSpellConfig2d4Offset) +
        " f2d8=" + FormatReadableNativeFloatField(actor_address, kActorSpellConfig2d8Offset) +
        " selection_ptr=" + FormatReadableNativeFieldHex<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset) +
        " progression_runtime=" + FormatReadableNativeFieldHex<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset) +
        " progression_handle=" + FormatReadableNativeFieldHex<uintptr_t>(actor_address, kActorProgressionHandleOffset);
}
