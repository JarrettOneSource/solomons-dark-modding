bool QueueHubStartTestrun(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena state is not active.";
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

    multiplayer::SetAllBotSceneIntentsToRun();

    g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.exchange(1, std::memory_order_acq_rel);
    std::uint8_t testrun_mode_flag = 0;
    uintptr_t arena_vtable = 0;
    const bool have_testrun_mode_flag =
        ProcessMemory::Instance().TryReadField(gameplay_address, kGameplayTestrunModeFlagOffset, &testrun_mode_flag);
    const bool have_arena_vtable = ProcessMemory::Instance().TryReadValue(arena_address, &arena_vtable);
    Log(
        "Queued hub testrun request. arena=" + HexString(arena_address) +
        " arena_vtable=" + (have_arena_vtable ? HexString(arena_vtable) : std::string("unreadable")) +
        " gameplay=" + HexString(gameplay_address) +
        " switch_region=" + HexString(kGameplaySwitchRegion) +
        " target_region=" + std::to_string(kArenaRegionIndex) +
        " arena_enter_dispatch=" + HexString(kArenaStartRunDispatch) +
        " create=" + HexString(kArenaCreate) +
        " testrun_mode_flag=" +
        (have_testrun_mode_flag ? std::to_string(static_cast<unsigned>(testrun_mode_flag)) : std::string("unreadable")));
    return true;
}

bool QueueGameplaySwitchRegion(int region_index, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
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

    SceneContextSnapshot scene_context;
    if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context) &&
        scene_context.current_region_index == kArenaRegionIndex &&
        region_index != kArenaRegionIndex) {
        if (error_message != nullptr) {
            *error_message =
                "Raw Gameplay_SwitchRegion cannot leave testrun safely. Use the stock UI Leave Game path instead.";
        }
        return false;
    }

    PendingGameplayRegionSwitchRequest request;
    request.region_index = region_index;
    request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The gameplay region switch queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(request);
    Log("gameplay.switch_region: queued region=" + std::to_string(region_index));
    return true;
}

bool QueueGameplayStartWaves(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    uintptr_t scene_address = 0;
    if (!TryResolveCurrentGameplayScene(&scene_address) || scene_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_start_waves_requests.exchange(1, std::memory_order_acq_rel);
    g_gameplay_keyboard_injection.start_waves_retry_not_before_ms.store(0, std::memory_order_release);

    ArenaWaveStartState arena_state;
    const bool have_arena_state = TryReadArenaWaveStartState(arena_address, &arena_state);
    Log(
        "Queued gameplay start_waves request. scene=" + HexString(scene_address) +
        " arena=" + HexString(arena_address) +
        " start_waves=" + HexString(kArenaStartWaves) +
        " state=" + (have_arena_state ? DescribeArenaWaveStartState(arena_state) : std::string("unreadable")));
    return true;
}

