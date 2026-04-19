struct DispatchException {
    DWORD code = 0;
};

int CaptureDispatchException(EXCEPTION_POINTERS* exception_pointers, DispatchException* exception) {
    if (exception == nullptr || exception_pointers == nullptr || exception_pointers->ExceptionRecord == nullptr) {
        return EXCEPTION_EXECUTE_HANDLER;
    }

    exception->code = exception_pointers->ExceptionRecord->ExceptionCode;
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallGameplaySwitchRegionSafe(
    uintptr_t switch_region_address,
    uintptr_t gameplay_address,
    int region_index,
    DispatchException* exception) {
    auto* switch_region = reinterpret_cast<GameplaySwitchRegionFn>(switch_region_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        switch_region(reinterpret_cast<void*>(gameplay_address), region_index);
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryDispatchGameplaySwitchRegionOnGameThread(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    if (region_index < 0 || region_index > kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message = "Region index is out of range.";
        }
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());

    const auto switch_region_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    if (switch_region_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve Gameplay_SwitchRegion.";
        }
        return false;
    }

    SceneContextSnapshot before;
    (void)TryBuildSceneContextSnapshot(gameplay_address, &before);
    if (before.current_region_index == region_index && before.world_address != 0) {
        Log(
            "gameplay.switch_region: already in target region. region=" + std::to_string(region_index) +
            " scene=" + DescribeSceneName(before));
        return true;
    }

    DispatchException exception;
    if (!CallGameplaySwitchRegionSafe(switch_region_address, gameplay_address, region_index, &exception)) {
        if (error_message != nullptr) {
            *error_message = "Gameplay_SwitchRegion raised 0x" + HexString(exception.code) + ".";
        }
        Log(
            "gameplay.switch_region: dispatch failed. gameplay=" + HexString(gameplay_address) +
            " switch_region=" + HexString(switch_region_address) +
            " from=" + DescribeSceneName(before) +
            " target_region=" + std::to_string(region_index) +
            " exception_code=" + HexString(exception.code));
        return false;
    }

    SceneContextSnapshot after;
    (void)TryBuildSceneContextSnapshot(gameplay_address, &after);
    Log(
        "gameplay.switch_region: dispatched. gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(switch_region_address) +
        " from=" + DescribeSceneName(before) +
        " to=" + DescribeSceneName(after) +
        " target_region=" + std::to_string(region_index));
    return true;
}

bool CallArenaStartWavesSafe(uintptr_t start_waves_address, uintptr_t arena_address, DispatchException* exception) {
    auto* start_waves = reinterpret_cast<ArenaStartWavesFn>(start_waves_address);
    if (exception != nullptr) {
        *exception = DispatchException{};
    }

    __try {
        start_waves(reinterpret_cast<void*>(arena_address));
        return true;
    } __except (CaptureDispatchException(GetExceptionInformation(), exception)) {
        return false;
    }
}

bool TryReadArenaWaveStartState(uintptr_t arena_address, ArenaWaveStartState* state) {
    if (state == nullptr || arena_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable = 0;
    if (!memory.TryReadValue(arena_address, &vtable) || vtable == 0) {
        return false;
    }

    ArenaWaveStartState snapshot;
    memory.TryReadField(arena_address, kArenaCombatSectionIndexOffset, &snapshot.combat_section_index);
    memory.TryReadField(arena_address, kArenaCombatWaveIndexOffset, &snapshot.combat_wave_index);
    memory.TryReadField(arena_address, kArenaCombatWaitTicksOffset, &snapshot.combat_wait_ticks);
    memory.TryReadField(arena_address, kArenaCombatAdvanceModeOffset, &snapshot.combat_advance_mode);
    memory.TryReadField(arena_address, kArenaCombatAdvanceThresholdOffset, &snapshot.combat_advance_threshold);
    memory.TryReadField(arena_address, kArenaCombatWaveCounterOffset, &snapshot.combat_wave_counter);
    memory.TryReadField(arena_address, kArenaCombatStartedMusicOffset, &snapshot.combat_started_music);
    memory.TryReadField(arena_address, kArenaCombatTransitionRequestedOffset, &snapshot.combat_transition_requested);
    memory.TryReadField(arena_address, kArenaCombatActiveFlagOffset, &snapshot.combat_active);

    *state = snapshot;
    return true;
}

std::string DescribeArenaWaveStartState(const ArenaWaveStartState& candidate) {
    return
        "section=" + std::to_string(candidate.combat_section_index) +
        " wave=" + std::to_string(candidate.combat_wave_index) +
        " wait_ticks=" + std::to_string(candidate.combat_wait_ticks) +
        " advance_mode=" + std::to_string(candidate.combat_advance_mode) +
        " advance_threshold=" + std::to_string(candidate.combat_advance_threshold) +
        " wave_counter=" + std::to_string(candidate.combat_wave_counter) +
        " music_started=" + std::to_string(static_cast<unsigned>(candidate.combat_started_music)) +
        " transition_requested=" + std::to_string(static_cast<unsigned>(candidate.combat_transition_requested)) +
        " combat_active=" + std::to_string(static_cast<unsigned>(candidate.combat_active));
}

bool TryStartWavesOnGameThread() {
    auto& memory = ProcessMemory::Instance();
    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        Log("start_waves: arena is not active. arena=" + HexString(arena_address));
        return false;
    }

    const auto start_waves_address = memory.ResolveGameAddressOrZero(kArenaStartWaves);
    if (start_waves_address == 0) {
        Log(
            "start_waves: missing arena combat entrypoint. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address));
        return false;
    }

    ArenaWaveStartState before;
    const bool have_before = TryReadArenaWaveStartState(arena_address, &before);
    if (have_before && before.combat_started_music != 0 && before.combat_wave_index > 0) {
        Log(
            "start_waves: arena combat is already active. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address) +
            " state=" + DescribeArenaWaveStartState(before));
        return true;
    }

    DispatchException start_waves_exception;
    if (!CallArenaStartWavesSafe(start_waves_address, arena_address, &start_waves_exception)) {
        Log(
            "start_waves: arena combat entrypoint raised an exception. arena=" + HexString(arena_address) +
            " start_waves=" + HexString(start_waves_address) +
            " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
            " exception_code=" + HexString(start_waves_exception.code));
        return false;
    }

    ArenaWaveStartState after;
    const bool have_after = TryReadArenaWaveStartState(arena_address, &after);
    Log(
        "start_waves: arena combat entrypoint dispatched. arena=" + HexString(arena_address) +
        " start_waves=" + HexString(start_waves_address) +
        " before=" + (have_before ? DescribeArenaWaveStartState(before) : std::string("unreadable")) +
        " after=" + (have_after ? DescribeArenaWaveStartState(after) : std::string("unreadable")));
    return true;
}

bool TryDispatchHubStartTestrunOnGameThread() {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto cooldown_until =
        g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.load(std::memory_order_acquire);
    if (now_ms < cooldown_until) {
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        return false;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return false;
    }

    const auto switch_region_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameplaySwitchRegion);
    if (switch_region_address == 0) {
        return false;
    }
    const auto arena_dispatch_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kArenaStartRunDispatch);

    auto& memory = ProcessMemory::Instance();
    std::uint8_t testrun_mode_flag = 0;
    const bool have_testrun_mode_flag =
        memory.TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    uintptr_t arena_vtable = 0;
    const bool have_arena_vtable = memory.TryReadValue(arena_address, &arena_vtable);

    DispatchException exception;
    if (!CallGameplaySwitchRegionSafe(
            switch_region_address,
            gameplay_address,
            kArenaRegionIndex,
            &exception)) {
        g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(
            now_ms + kHubStartTestrunDispatchCooldownMs,
            std::memory_order_release);
        Log(
            "Hub testrun region switch raised an exception. switch_region=" +
            HexString(switch_region_address) +
            " arena=" + HexString(arena_address) +
            " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
            " gameplay=" + HexString(gameplay_address) +
            " target_region=" + std::to_string(kArenaRegionIndex) +
            " arena_enter_dispatch=" +
            (arena_dispatch_address != 0 ? HexString(arena_dispatch_address) : std::string("unresolved")) +
            " testrun_mode_flag=" +
            (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")) +
            " exception_code=" + HexString(exception.code));
        return false;
    }

    g_gameplay_keyboard_injection.hub_start_testrun_cooldown_until_ms.store(
        now_ms + kHubStartTestrunDispatchCooldownMs,
        std::memory_order_release);
    Log(
        "Hub testrun region switch completed. switch_region=" + HexString(switch_region_address) +
        " arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" +
        (arena_dispatch_address != 0 ? HexString(arena_dispatch_address) : std::string("unresolved")) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool TryDispatchStartWavesOnGameThread() {
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto retry_not_before =
        g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.load(std::memory_order_acquire);
    if (now_ms < retry_not_before) {
        return false;
    }

    if (!TryStartWavesOnGameThread()) {
        g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(
            now_ms + kWaveStartRetryDelayMs,
            std::memory_order_release);
        return false;
    }

    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);
    return true;
}

