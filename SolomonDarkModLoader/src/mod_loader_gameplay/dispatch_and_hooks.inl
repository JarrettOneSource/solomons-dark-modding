void* CallSpawnEnemyInternal(SpawnEnemyCallContext* context, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (context == nullptr ||
        context->arena_address == 0 ||
        context->config_ctor == nullptr ||
        context->config_dtor == nullptr ||
        context->build_config == nullptr ||
        context->spawn_enemy == nullptr ||
        context->modifiers == nullptr ||
        context->config_wrapper == nullptr ||
        context->config_buffer == nullptr) {
        return nullptr;
    }

    __try {
        context->config_ctor(context->config_wrapper);
        context->build_config(
            reinterpret_cast<void*>(context->arena_address),
            context->type_id,
            kSpawnEnemyVariantDefault,
            context->config_buffer,
            context->modifiers);
        context->enemy = context->spawn_enemy(
            reinterpret_cast<void*>(context->arena_address),
            nullptr,
            context->config_buffer,
            kSpawnEnemyModeDefault,
            kSpawnEnemyParam5Default,
            kSpawnEnemyParam6Default,
            kSpawnEnemyAllowOverrideDefault);
        context->config_dtor(context->config_wrapper);
        return context->enemy;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return nullptr;
    }
}

bool QueueEnemySpawnRequest(const PendingEnemySpawnRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_enemy_spawn_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The enemy spawn queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_enemy_spawn_requests.push_back(request);
    return true;
}

bool QueueRewardSpawnRequest(const PendingRewardSpawnRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (g_gameplay_keyboard_injection.pending_reward_spawn_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The reward spawn queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_reward_spawn_requests.push_back(request);
    return true;
}

bool QueueWizardBotSyncRequest(const PendingWizardBotSyncRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    auto immediate_request = request;
    immediate_request.next_attempt_ms = static_cast<std::uint64_t>(GetTickCount64());

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    if (FindPendingWizardBotSyncRequest(immediate_request.bot_id) != nullptr) {
        UpsertPendingWizardBotSyncRequest(immediate_request);
        Log(
            "[bots] queued sync update bot_id=" + std::to_string(immediate_request.bot_id) +
            " wizard_id=" + std::to_string(immediate_request.wizard_id) +
            " has_transform=" + std::to_string(immediate_request.has_transform ? 1 : 0) +
            " x=" + std::to_string(immediate_request.x) +
            " y=" + std::to_string(immediate_request.y) +
            " heading=" + std::to_string(immediate_request.heading));
        return true;
    }

    if (g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The wizard bot sync queue is full.";
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.push_back(immediate_request);
    Log(
        "[bots] queued sync bot_id=" + std::to_string(immediate_request.bot_id) +
        " wizard_id=" + std::to_string(immediate_request.wizard_id) +
        " has_transform=" + std::to_string(immediate_request.has_transform ? 1 : 0) +
        " x=" + std::to_string(immediate_request.x) +
        " y=" + std::to_string(immediate_request.y) +
        " heading=" + std::to_string(immediate_request.heading));
    return true;
}

bool QueueWizardBotDestroyRequest(std::uint64_t bot_id, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    UpsertPendingWizardBotDestroyRequest(bot_id);
    return true;
}

bool TryUpdateBotEntity(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* /*error_message*/) {
    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    auto* binding = FindBotEntity(request.bot_id);
    if (binding == nullptr || binding->actor_address == 0) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveWizardBotTransform(gameplay_address, request, &x, &y, &heading)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(binding->actor_address, kActorPositionXOffset, x) ||
        !memory.TryWriteField(binding->actor_address, kActorPositionYOffset, y)) {
        DematerializeWizardBotEntityNow(request.bot_id, true, "update transform write failed");
        return false;
    }

    (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, heading);
    binding->wizard_id = request.wizard_id;
    PublishWizardBotGameplaySnapshot(*binding);
    return true;
}

bool TrySpawnStandaloneWizardBotEntity(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* error_message);

bool TrySpawnStandaloneWizardBotEntitySafe(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnStandaloneWizardBotEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteWizardBotSyncNow(const PendingWizardBotSyncRequest& request, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Gameplay scene is not active.";
        }
        return false;
    }

    SceneContextSnapshot scene_context;
    std::string readiness_error;
    if (!TryValidateWizardBotSpawnReadiness(
            gameplay_address,
            &scene_context,
            &readiness_error)) {
        if (error_message != nullptr) {
            *error_message = readiness_error;
        }
        return false;
    }

    if (TryUpdateBotEntity(gameplay_address, request, error_message)) {
        Log(
            "[bots] sync updated existing entity. bot_id=" + std::to_string(request.bot_id) +
            " wizard_id=" + std::to_string(request.wizard_id));
        return true;
    }

    Log(
        "[bots] sync spawning standalone actor. bot_id=" + std::to_string(request.bot_id) +
        " wizard_id=" + std::to_string(request.wizard_id) +
        " gameplay=" + HexString(gameplay_address));
    DWORD exception_code = 0;
    if (TrySpawnStandaloneWizardBotEntitySafe(gameplay_address, request, error_message, &exception_code)) {
        return true;
    }
    if (error_message != nullptr && error_message->empty()) {
        if (exception_code != 0) {
            *error_message = "TrySpawnStandaloneWizardBotEntity threw 0x" + HexString(exception_code) + ".";
        } else {
            *error_message = "TrySpawnStandaloneWizardBotEntity returned false without an error message.";
        }
    }
    return false;
}

void DestroyWizardBotEntityNow(std::uint64_t bot_id) {
    RemovePendingWizardBotSyncRequest(bot_id);
    RemovePendingWizardBotDestroyRequest(bot_id);
    DematerializeWizardBotEntityNow(bot_id, true, "destroy");
}

bool ExecuteSpawnEnemyNow(int type_id, float x, float y, uintptr_t* out_enemy_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (out_enemy_address != nullptr) {
        *out_enemy_address = 0;
    }

    uintptr_t arena_address = 0;
    if (!TryResolveArena(&arena_address) || arena_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Arena is not active.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto enemy_config_ctor_address = memory.ResolveGameAddressOrZero(kEnemyConfigCtor);
    const auto enemy_config_dtor_address = memory.ResolveGameAddressOrZero(kEnemyConfigDtor);
    const auto build_config_address = memory.ResolveGameAddressOrZero(kBuildEnemyConfig);
    const auto spawn_enemy_address = memory.ResolveGameAddressOrZero(kSpawnEnemy);
    if (enemy_config_ctor_address == 0 ||
        enemy_config_dtor_address == 0 ||
        build_config_address == 0 ||
        spawn_enemy_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve one or more enemy spawn entrypoints.";
        }
        return false;
    }

    EnemyModifierList modifiers;
    ResetEnemyModifierList(&modifiers);
    if (modifiers.vtable == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the Array<int> vtable used by enemy modifiers.";
        }
        return false;
    }

    alignas(void*) std::array<std::uint8_t, kEnemyConfigWrapperSize> config_wrapper{};
    void* const config_wrapper_address = config_wrapper.data();
    void* const config_buffer_address = config_wrapper.data() + 4;

    SpawnEnemyCallContext call_context;
    call_context.arena_address = arena_address;
    call_context.config_ctor = reinterpret_cast<EnemyConfigCtorFn>(enemy_config_ctor_address);
    call_context.config_dtor = reinterpret_cast<EnemyConfigDtorFn>(enemy_config_dtor_address);
    call_context.build_config = reinterpret_cast<EnemyConfigBuildFn>(build_config_address);
    call_context.spawn_enemy = reinterpret_cast<EnemySpawnFn>(spawn_enemy_address);
    call_context.modifiers = &modifiers;
    call_context.config_wrapper = config_wrapper_address;
    call_context.config_buffer = config_buffer_address;
    call_context.type_id = type_id;

    DWORD exception_code = 0;
    auto* enemy = CallSpawnEnemyInternal(&call_context, &exception_code);
    CleanupEnemyModifierList(&modifiers);
    if (enemy == nullptr) {
        if (error_message != nullptr) {
            *error_message =
                "Enemy_Create failed for type_id=" + std::to_string(type_id) +
                " exception=" + HexString(exception_code);
        }
        return false;
    }

    const auto enemy_address = reinterpret_cast<uintptr_t>(enemy);
    if (out_enemy_address != nullptr) {
        *out_enemy_address = enemy_address;
    }
    const bool wrote_x = memory.TryWriteField(enemy_address, kActorPositionXOffset, x);
    const bool wrote_y = memory.TryWriteField(enemy_address, kActorPositionYOffset, y);
    if (!wrote_x || !wrote_y) {
        Log(
            "spawn_enemy: created enemy but failed to overwrite final position. type_id=" +
            std::to_string(type_id) +
            " enemy=" + HexString(enemy_address) +
            " wrote_x=" + std::to_string(wrote_x ? 1 : 0) +
            " wrote_y=" + std::to_string(wrote_y ? 1 : 0));
    }

    return true;
}

bool TrySpawnStandaloneWizardBotEntity(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    uintptr_t local_actor_address = 0;
    if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) ||
        local_actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player actor is not ready.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto world_address =
        memory.ReadFieldOr<uintptr_t>(local_actor_address, kActorOwnerOffset, 0);
    if (world_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Local slot-0 player world is not ready.";
        }
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveWizardBotTransform(gameplay_address, request, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    int gameplay_slot = -1;
    if (!ReserveWizardBotGameplaySlot(request.bot_id, &gameplay_slot) ||
        gameplay_slot < kFirstWizardBotSlot) {
        if (error_message != nullptr) {
            *error_message = "No gameplay slot is available for a wizard bot.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (actor_address != 0 ||
            memory.ReadFieldOr<uintptr_t>(
                gameplay_address,
                kGameplayPlayerActorOffset +
                    static_cast<std::size_t>(gameplay_slot) * kGameplayPlayerSlotStride,
                0) != 0) {
            (void)DestroyGameplaySlotBotResources(
                gameplay_address,
                gameplay_slot,
                actor_address,
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0),
                memory.ReadFieldOr<uintptr_t>(
                    gameplay_address,
                    kGameplayPlayerActorOffset +
                        static_cast<std::size_t>(gameplay_slot) * kGameplayPlayerSlotStride,
                    0) != 0,
                0,
                &cleanup_error);
        }
        actor_address = 0;
        progression_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
            if (!cleanup_error.empty()) {
                *error_message += " cleanup=" + cleanup_error;
            }
        }
        return false;
    };

    uintptr_t stale_actor_address = 0;
    uintptr_t stale_progression_handle_address = 0;
    const bool stale_actor_present =
        TryResolvePlayerActorForSlot(gameplay_address, gameplay_slot, &stale_actor_address) &&
        stale_actor_address != 0;
    const bool stale_progression_present =
        TryResolvePlayerProgressionHandleForSlot(
            gameplay_address,
            gameplay_slot,
            &stale_progression_handle_address) &&
        stale_progression_handle_address != 0;
    if (stale_actor_present || stale_progression_present) {
        std::string stale_cleanup_error;
        const auto stale_world_address =
            memory.ReadFieldOr<uintptr_t>(stale_actor_address, kActorOwnerOffset, 0);
        if (!DestroyGameplaySlotBotResources(
                gameplay_address,
                gameplay_slot,
                stale_actor_address,
                stale_world_address,
                stale_world_address != 0,
                0,
                &stale_cleanup_error)) {
            if (error_message != nullptr) {
                *error_message =
                    "Gameplay slot cleanup failed before bot spawn. " + stale_cleanup_error;
            }
            return false;
        }
    }

    std::string stage_error;
    if (!CreateGameplaySlotBotActor(
            gameplay_address,
            world_address,
            gameplay_slot,
            request.wizard_id,
            x,
            y,
            heading,
            &actor_address,
            &progression_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    LogBotVisualDebugStage(
        "spawn_after_slot_create",
        local_actor_address,
        actor_address,
        0);

    if (!FinalizeGameplaySlotBotRegistration(
            gameplay_address,
            world_address,
            gameplay_slot,
            actor_address,
            nullptr,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    LogLocalPlayerAnimationProbe();
    RememberBotEntity(
        request.bot_id,
        request.wizard_id,
        actor_address,
        BotEntityBinding::Kind::StandaloneWizard,
        gameplay_slot,
        false);
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_bot_entities_mutex);
        if (auto* binding = FindBotEntity(request.bot_id); binding != nullptr) {
            binding->controller_state = multiplayer::BotControllerState::Idle;
            binding->movement_active = false;
            binding->has_target = false;
            binding->desired_heading_valid = false;
            binding->next_scene_materialize_retry_ms = 0;
            binding->materialized_scene_address = gameplay_address;
            binding->materialized_world_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address);
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = true;
            binding->gameplay_slot = gameplay_slot;
            binding->raw_allocation = false;
            binding->standalone_progression_wrapper_address = 0;
            binding->standalone_progression_inner_address = 0;
            binding->standalone_equip_wrapper_address = 0;
            binding->standalone_equip_inner_address = 0;
            binding->synthetic_source_profile_address = 0;
            SeedStandaloneWizardAnimationDriveProfiles(binding, actor_address);

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
                UpdateBotHomeScene(binding, scene_context);
            }

            PublishWizardBotGameplaySnapshot(*binding);
        }
    }
    LogBotVisualDebugStage(
        "spawn_after_binding_publish",
        local_actor_address,
        actor_address,
        0);

    Log(
        "[bots] created gameplay-slot wizard actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address)) +
        " gameplay_slot=" + std::to_string(gameplay_slot) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " slot_anim_state=" + std::to_string(ResolveActorAnimationStateSlotIndex(actor_address)) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " progression_handle=" +
        HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0)) +
        " equip_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0)) +
        " attachment=" + HexString(memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorHubVisualAttachmentPtrOffset,
            0)));
    return true;
}

bool ExecuteSpawnRewardNow(std::string_view kind, int amount, float x, float y, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (kind != "gold") {
        if (error_message != nullptr) {
            *error_message = "Only gold rewards are supported right now.";
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

    const auto spawn_reward_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kSpawnRewardGold);
    if (spawn_reward_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve the gold reward spawn function.";
        }
        return false;
    }

    auto spawn_reward = reinterpret_cast<SpawnRewardGoldFn>(spawn_reward_address);
    spawn_reward(
        reinterpret_cast<void*>(arena_address),
        FloatToBits(x),
        FloatToBits(y),
        amount,
        kSpawnRewardDefaultLifetime);
    return true;
}

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

void PumpQueuedGameplayActions() {
    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto wizard_bot_sync_not_before_ms =
        g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.load(std::memory_order_acquire);

    auto pending =
        g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.load(std::memory_order_acquire);
    while (pending > 0) {
        if (!g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.compare_exchange_weak(
                pending,
                pending - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        if (!TryDispatchHubStartTestrunOnGameThread()) {
            g_gameplay_keyboard_injection.pending_hub_start_testrun_requests.fetch_add(
                1,
                std::memory_order_acq_rel);
        }
        break;
    }

    pending = g_gameplay_keyboard_injection.pending_start_waves_requests.load(std::memory_order_acquire);
    while (pending > 0) {
        if (!g_gameplay_keyboard_injection.pending_start_waves_requests.compare_exchange_weak(
                pending,
                pending - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        if (!TryDispatchStartWavesOnGameThread()) {
            g_gameplay_keyboard_injection.pending_start_waves_requests.fetch_add(
                1,
                std::memory_order_acq_rel);
        }
        break;
    }

    PendingRewardSpawnRequest reward_request;
    bool have_reward_request = false;
    PendingEnemySpawnRequest enemy_request;
    bool have_enemy_request = false;
    PendingWizardBotSyncRequest wizard_bot_request;
    bool have_wizard_bot_request = false;
    PendingGameplayRegionSwitchRequest region_switch_request;
    bool have_region_switch_request = false;
    std::vector<std::uint64_t> destroy_requests;
    {
        std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
        if (wizard_bot_sync_not_before_ms <= now_ms &&
            !g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.empty()) {
            const auto pending_sync_count =
                g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.size();
            for (std::size_t index = 0; index < pending_sync_count; ++index) {
                auto pending_request = g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.front();
                g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.pop_front();
                if (!have_wizard_bot_request && pending_request.next_attempt_ms <= now_ms) {
                    wizard_bot_request = pending_request;
                    have_wizard_bot_request = true;
                    g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                        now_ms + kWizardBotSyncDispatchSpacingMs,
                        std::memory_order_release);
                    continue;
                }

                g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.push_back(pending_request);
            }
        }
        const auto region_switch_not_before_ms =
            g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.load(std::memory_order_acquire);
        if (region_switch_not_before_ms <= now_ms &&
            !g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.empty()) {
            const auto pending_region_switch_count =
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.size();
            for (std::size_t index = 0; index < pending_region_switch_count; ++index) {
                auto pending_request = g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.front();
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.pop_front();
                if (!have_region_switch_request && pending_request.next_attempt_ms <= now_ms) {
                    region_switch_request = pending_request;
                    have_region_switch_request = true;
                    g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(
                        now_ms + kGameplayRegionSwitchDispatchSpacingMs,
                        std::memory_order_release);
                    continue;
                }

                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(pending_request);
            }
        }
        while (!g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.empty()) {
            destroy_requests.push_back(g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.front());
            g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.pop_front();
        }
        if (!g_gameplay_keyboard_injection.pending_reward_spawn_requests.empty()) {
            reward_request = std::move(g_gameplay_keyboard_injection.pending_reward_spawn_requests.front());
            g_gameplay_keyboard_injection.pending_reward_spawn_requests.pop_front();
            have_reward_request = true;
        }
        if (!g_gameplay_keyboard_injection.pending_enemy_spawn_requests.empty()) {
            enemy_request = g_gameplay_keyboard_injection.pending_enemy_spawn_requests.front();
            g_gameplay_keyboard_injection.pending_enemy_spawn_requests.pop_front();
            have_enemy_request = true;
        }
    }

    for (const auto bot_id : destroy_requests) {
        DestroyWizardBotEntityNow(bot_id);
    }

    if (have_region_switch_request) {
        std::string error_message;
        if (!TryDispatchGameplaySwitchRegionOnGameThread(region_switch_request.region_index, &error_message)) {
            region_switch_request.next_attempt_ms = now_ms + kGameplayRegionSwitchRetryDelayMs;
            g_gameplay_keyboard_injection.gameplay_region_switch_not_before_ms.store(
                region_switch_request.next_attempt_ms,
                std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
                g_gameplay_keyboard_injection.pending_gameplay_region_switch_requests.push_back(region_switch_request);
            }
            Log(
                "gameplay.switch_region: queued request deferred. region=" +
                std::to_string(region_switch_request.region_index) +
                " retry_in_ms=" + std::to_string(kGameplayRegionSwitchRetryDelayMs) +
                " error=" + error_message);
        }
    }

    if (have_wizard_bot_request) {
        Log(
            "[bots] pump sync bot_id=" + std::to_string(wizard_bot_request.bot_id) +
            " wizard_id=" + std::to_string(wizard_bot_request.wizard_id) +
            " has_transform=" + std::to_string(wizard_bot_request.has_transform ? 1 : 0) +
            " x=" + std::to_string(wizard_bot_request.x) +
            " y=" + std::to_string(wizard_bot_request.y) +
            " heading=" + std::to_string(wizard_bot_request.heading));
        std::string error_message;
        if (!ExecuteWizardBotSyncNow(wizard_bot_request, &error_message)) {
            wizard_bot_request.next_attempt_ms = now_ms + kWizardBotSyncRetryDelayMs;
            g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                wizard_bot_request.next_attempt_ms,
                std::memory_order_release);
            {
                std::lock_guard<std::mutex> lock(g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
                UpsertPendingWizardBotSyncRequest(wizard_bot_request);
            }
            Log(
                "[bots] queued sync deferred. bot_id=" + std::to_string(wizard_bot_request.bot_id) +
                " wizard_id=" + std::to_string(wizard_bot_request.wizard_id) +
                " has_transform=" + std::to_string(wizard_bot_request.has_transform ? 1 : 0) +
                " x=" + std::to_string(wizard_bot_request.x) +
                " y=" + std::to_string(wizard_bot_request.y) +
                " heading=" + std::to_string(wizard_bot_request.heading) +
                " retry_in_ms=" + std::to_string(kWizardBotSyncRetryDelayMs) +
                " error=" + error_message);
        } else {
            g_gameplay_keyboard_injection.wizard_bot_sync_not_before_ms.store(
                now_ms + kWizardBotSyncDispatchSpacingMs,
                std::memory_order_release);
        }
    }

    if (have_reward_request) {
        std::string error_message;
        if (!ExecuteSpawnRewardNow(
                reward_request.kind,
                reward_request.amount,
                reward_request.x,
                reward_request.y,
                &error_message)) {
            Log(
                "spawn_reward: queued request failed. kind=" + reward_request.kind +
                " amount=" + std::to_string(reward_request.amount) +
                " x=" + std::to_string(reward_request.x) +
                " y=" + std::to_string(reward_request.y) +
                " error=" + error_message);
        }
    }

    if (have_enemy_request) {
        std::string error_message;
        if (!ExecuteSpawnEnemyNow(enemy_request.type_id, enemy_request.x, enemy_request.y, nullptr, &error_message)) {
            Log(
                "spawn_enemy: queued request failed. type_id=" + std::to_string(enemy_request.type_id) +
                " x=" + std::to_string(enemy_request.x) +
                " y=" + std::to_string(enemy_request.y) +
                " error=" + error_message);
        }
    }
}

void __fastcall HookGameplayMouseRefresh(void* self, void* unused_edx) {
    const auto original =
        GetX86HookTrampoline<GameplayMouseRefreshFn>(g_gameplay_keyboard_injection.mouse_refresh_hook);
    if (original != nullptr) {
        original(self, unused_edx);
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    if (self_address == 0) {
        return;
    }

    const auto live_buffer_index =
        ProcessMemory::Instance().ReadFieldOr<int>(self_address, kGameplayInputBufferIndexOffset, -1);
    if (live_buffer_index >= 0) {
        const auto live_mouse_button_offset = static_cast<std::size_t>(
            live_buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
        const bool is_pressed =
            ProcessMemory::Instance().ReadFieldOr<std::uint8_t>(self_address, live_mouse_button_offset, 0) != 0;
        const bool was_pressed =
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.exchange(is_pressed, std::memory_order_acq_rel);
        if (is_pressed && !was_pressed) {
            RecordGameplayMouseLeftEdge();
        }
    }

    auto& pending = g_gameplay_keyboard_injection.pending_mouse_left_frames;
    auto available = pending.load(std::memory_order_acquire);
    while (available > 0) {
        if (!pending.compare_exchange_weak(
                available,
                available - 1,
                std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            continue;
        }

        const auto buffer_index =
            ProcessMemory::Instance().ReadFieldOr<int>(self_address, kGameplayInputBufferIndexOffset, -1);
        if (buffer_index < 0) {
            return;
        }

        const auto mouse_button_offset = static_cast<std::size_t>(
            buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
        const std::uint8_t pressed = 1;
        const bool wrote_mouse_button =
            ProcessMemory::Instance().TryWriteField(self_address, mouse_button_offset, pressed);

        uintptr_t gameplay_address = 0;
        const bool have_gameplay_address =
            TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0;
        const bool wrote_cast_intent =
            have_gameplay_address &&
            ProcessMemory::Instance().TryWriteField(gameplay_address, kGameplayCastIntentOffset, pressed);

        if (wrote_mouse_button || wrote_cast_intent) {
            g_gameplay_keyboard_injection.last_observed_mouse_left_down.store(true, std::memory_order_release);
            auto& pending_edge_events = g_gameplay_keyboard_injection.pending_mouse_left_edge_events;
            auto available_edge_events = pending_edge_events.load(std::memory_order_acquire);
            while (available_edge_events > 0) {
                if (!pending_edge_events.compare_exchange_weak(
                        available_edge_events,
                        available_edge_events - 1,
                        std::memory_order_acq_rel,
                        std::memory_order_acquire)) {
                    continue;
                }
                RecordGameplayMouseLeftEdge();
                break;
            }
            Log(
                "Injected gameplay mouse-left click. input_state=" + HexString(self_address) +
                " buffer_index=" + std::to_string(buffer_index) +
                " gameplay=" + (have_gameplay_address ? HexString(gameplay_address) : std::string("0x00000000")) +
                " cast_intent=" + std::to_string(wrote_cast_intent ? 1 : 0));
        }
        TickWizardBotMovementControllersIfActive();
        return;
    }

    TickWizardBotMovementControllersIfActive();
}

void LogStandaloneWizardActorLifecycleEvent(
    std::string_view label,
    uintptr_t actor_address,
    uintptr_t world_address,
    int free_flag_or_slot,
    uintptr_t caller_address) {
    if (actor_address == 0) {
        return;
    }

    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    bool tracked = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        if (const auto* binding = FindBotEntityForActor(actor_address);
            binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
            tracked = true;
        }
    }
    if (!tracked) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    Log(
        "[bots] " + std::string(label) +
        " actor=" + HexString(actor_address) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " arg=" + std::to_string(free_flag_or_slot) +
        " caller=" + HexString(caller_address) +
        " vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0)) +
        " +04=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kObjectHeaderWordOffset, 0)) +
        " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " world_self=" + HexString(world_address) +
        " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " +1FC=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0)) +
        " +200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
        " +21C=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)));
}

std::string CaptureStackTraceSummary(std::size_t frames_to_skip, std::size_t max_frames) {
    std::array<void*, 16> frames{};
    const auto captured = static_cast<std::size_t>(RtlCaptureStackBackTrace(
        0,
        static_cast<ULONG>(frames.size()),
        frames.data(),
        nullptr));
    if (captured <= frames_to_skip || max_frames == 0) {
        return {};
    }

    std::string summary;
    const auto requested_end = frames_to_skip + max_frames;
    const auto end = captured < requested_end ? captured : requested_end;
    for (std::size_t index = frames_to_skip; index < end; ++index) {
        if (!summary.empty()) {
            summary += ",";
        }
        summary += HexString(reinterpret_cast<uintptr_t>(frames[index]));
    }
    return summary;
}

thread_local int g_player_actor_vslot28_depth = 0;
thread_local uintptr_t g_player_actor_vslot28_actor = 0;
thread_local uintptr_t g_player_actor_vslot28_caller = 0;
thread_local int g_gameplay_hud_case100_depth = 0;
thread_local uintptr_t g_gameplay_hud_case100_owner = 0;
thread_local uintptr_t g_gameplay_hud_case100_caller = 0;
thread_local int g_puppet_manager_delete_batch_depth = 0;
thread_local uintptr_t g_puppet_manager_delete_batch_self = 0;
thread_local uintptr_t g_puppet_manager_delete_batch_list = 0;

bool TryCaptureTrackedStandaloneWizardBindingIdentity(
    uintptr_t actor_address,
    std::uint64_t* out_bot_id,
    int* out_gameplay_slot);

bool TryFindTrackedStandaloneWizardInPointerList(
    uintptr_t list_address,
    std::uint64_t* out_bot_id,
    int* out_gameplay_slot,
    uintptr_t* out_actor_address,
    int* out_tracked_count) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }
    if (out_gameplay_slot != nullptr) {
        *out_gameplay_slot = -1;
    }
    if (out_actor_address != nullptr) {
        *out_actor_address = 0;
    }
    if (out_tracked_count != nullptr) {
        *out_tracked_count = 0;
    }
    if (list_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto count = memory.ReadFieldOr<int>(list_address, kPointerListCountOffset, 0);
    const auto items_address = memory.ReadFieldOr<uintptr_t>(list_address, kPointerListItemsOffset, 0);
    if (count <= 0 || count > 1024 || items_address == 0) {
        return false;
    }

    int tracked_count = 0;
    for (int index = 0; index < count; ++index) {
        const auto actor_address =
            memory.ReadValueOr<uintptr_t>(items_address + static_cast<std::size_t>(index) * sizeof(std::uint32_t), 0);
        if (actor_address == 0) {
            continue;
        }

        std::uint64_t bot_id = 0;
        int gameplay_slot = -1;
        if (!TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot)) {
            continue;
        }

        ++tracked_count;
        if (tracked_count == 1) {
            if (out_bot_id != nullptr) {
                *out_bot_id = bot_id;
            }
            if (out_gameplay_slot != nullptr) {
                *out_gameplay_slot = gameplay_slot;
            }
            if (out_actor_address != nullptr) {
                *out_actor_address = actor_address;
            }
        }
    }

    if (out_tracked_count != nullptr) {
        *out_tracked_count = tracked_count;
    }
    return tracked_count > 0;
}

bool LogTrackedStandaloneWizardPuppetManagerDeleteBatchEvent(
    std::string_view label,
    uintptr_t self_address,
    uintptr_t list_address,
    uintptr_t caller_address) {
    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    uintptr_t actor_address = 0;
    int tracked_count = 0;
    if (!TryFindTrackedStandaloneWizardInPointerList(
            list_address,
            &bot_id,
            &gameplay_slot,
            &actor_address,
            &tracked_count)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto count = memory.ReadFieldOr<int>(list_address, kPointerListCountOffset, 0);
    const auto capacity = memory.ReadFieldOr<int>(list_address, kPointerListCapacityOffset, 0);
    const auto items_address = memory.ReadFieldOr<uintptr_t>(list_address, kPointerListItemsOffset, 0);
    const auto owns_storage = static_cast<unsigned>(memory.ReadFieldOr<std::uint8_t>(
        list_address,
        kPointerListOwnsStorageFlagOffset,
        0));
    const auto self_vtable = memory.ReadFieldOr<uintptr_t>(self_address, 0x00, 0);
    const auto owner_region = memory.ReadFieldOr<uintptr_t>(self_address, kPuppetManagerOwnerRegionOffset, 0);
    const auto expected_manager =
        owner_region == 0 ? 0 : owner_region + kRegionPuppetManagerOffset;
    const auto puppet_manager_vtable = memory.ResolveGameAddressOrZero(kPuppetManagerVtable);
    const auto list_delta = list_address >= self_address
        ? list_address - self_address
        : self_address - list_address;

    Log(
        "[bots] " + std::string(label) +
        " self=" + HexString(self_address) +
        " self_vtable=" + HexString(self_vtable) +
        " puppet_manager_vtable=" + HexString(puppet_manager_vtable) +
        " owner_region=" + HexString(owner_region) +
        " expected_manager=" + HexString(expected_manager) +
        " list=" + HexString(list_address) +
        " list_delta=" + HexString(list_delta) +
        " count=" + std::to_string(count) +
        " capacity=" + std::to_string(capacity) +
        " owns_storage=" + std::to_string(owns_storage) +
        " items=" + HexString(items_address) +
        " tracked_actor=" + HexString(actor_address) +
        " tracked_bot_id=" + std::to_string(bot_id) +
        " tracked_binding_slot=" + std::to_string(gameplay_slot) +
        " tracked_count=" + std::to_string(tracked_count) +
        " caller=" + HexString(caller_address) +
        " stack=" + CaptureStackTraceSummary(1, 5));
    return true;
}

void LogStandaloneWizardRegionDeleteEvent(
    std::string_view label,
    uintptr_t deleter_address,
    uintptr_t actor_address,
    uintptr_t caller_address) {
    if (actor_address == 0) {
        return;
    }

    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    bool tracked = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        if (const auto* binding = FindBotEntityForActor(actor_address);
            binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
            tracked = true;
        }
    }
    if (!tracked) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    Log(
        "[bots] " + std::string(label) +
        " actor=" + HexString(actor_address) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " caller=" + HexString(caller_address) +
        " deleter_self=" + HexString(deleter_address) +
        " deleter_vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(deleter_address, 0x00, 0)) +
        " deleter_world=" + HexString(memory.ReadFieldOr<uintptr_t>(
            deleter_address,
            kPuppetManagerOwnerRegionOffset,
            0)) +
        " actor_vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0)) +
        " actor_owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " active_vslot28_depth=" + std::to_string(g_player_actor_vslot28_depth) +
        " active_vslot28_actor=" + HexString(g_player_actor_vslot28_actor) +
        " active_vslot28_caller=" + HexString(g_player_actor_vslot28_caller) +
        " active_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth) +
        " active_case100_owner=" + HexString(g_gameplay_hud_case100_owner) +
        " active_case100_caller=" + HexString(g_gameplay_hud_case100_caller) +
        " active_puppet_batch_depth=" + std::to_string(g_puppet_manager_delete_batch_depth) +
        " active_puppet_batch_self=" + HexString(g_puppet_manager_delete_batch_self) +
        " active_puppet_batch_list=" + HexString(g_puppet_manager_delete_batch_list) +
        " stack=" + CaptureStackTraceSummary(1, 5));
}

bool TryCaptureTrackedStandaloneWizardBindingIdentity(
    uintptr_t actor_address,
    std::uint64_t* out_bot_id,
    int* out_gameplay_slot) {
    if (out_bot_id != nullptr) {
        *out_bot_id = 0;
    }
    if (out_gameplay_slot != nullptr) {
        *out_gameplay_slot = -1;
    }
    if (actor_address == 0) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    if (const auto* binding = FindBotEntityForActor(actor_address);
        binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
        if (out_bot_id != nullptr) {
            *out_bot_id = binding->bot_id;
        }
        if (out_gameplay_slot != nullptr) {
            *out_gameplay_slot = binding->gameplay_slot;
        }
        return true;
    }
    return false;
}

void LogStandaloneWizardActorBoundaryEvent(
    std::string_view label,
    uintptr_t actor_address,
    std::uint64_t bot_id,
    int gameplay_slot,
    uintptr_t caller_address) {
    if (actor_address == 0 || bot_id == 0) {
        return;
    }

    Log(
        "[bots] " + std::string(label) +
        " actor=" + HexString(actor_address) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " caller=" + HexString(caller_address) +
        " stack=" + CaptureStackTraceSummary(1, 5));
}

void LogStandaloneWizardActorProbeEvent(
    std::string_view label,
    uintptr_t actor_address,
    uintptr_t caller_address) {
    if (actor_address == 0) {
        return;
    }

    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    bool tracked = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        if (const auto* binding = FindBotEntityForActor(actor_address);
            binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
            tracked = true;
        }
    }
    if (!tracked) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    uintptr_t slot_table_actor_address = 0;
    uintptr_t slot_table_progression_wrapper = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address) &&
        gameplay_address != 0 &&
        gameplay_slot >= 0 &&
        gameplay_slot < static_cast<int>(kGameplayPlayerSlotCount)) {
        const auto actor_slot_offset =
            kGameplayPlayerActorOffset + static_cast<std::size_t>(gameplay_slot) * kGameplayPlayerSlotStride;
        const auto progression_slot_offset =
            kGameplayPlayerProgressionHandleOffset + static_cast<std::size_t>(gameplay_slot) * kGameplayPlayerSlotStride;
        slot_table_actor_address =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, actor_slot_offset, 0);
        slot_table_progression_wrapper =
            memory.ReadFieldOr<uintptr_t>(gameplay_address, progression_slot_offset, 0);
    }

    const auto actor_progression_wrapper =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    const auto actor_equip_wrapper =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
    Log(
        "[bots] " + std::string(label) +
        " actor=" + HexString(actor_address) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " caller=" + HexString(caller_address) +
        " vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0)) +
        " +04=" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kObjectHeaderWordOffset, 0)) +
        " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
        " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " reg_slot=" + std::to_string(static_cast<unsigned>(memory.ReadFieldOr<std::uint8_t>(
            actor_address,
            kActorRegisteredSlotMirrorOffset,
            0xFF))) +
        " reg_id=" + std::to_string(static_cast<unsigned>(memory.ReadFieldOr<std::uint16_t>(
            actor_address,
            kActorRegisteredSlotIdMirrorOffset,
            0xFFFF))) +
        " +160=" + std::to_string(static_cast<unsigned>(memory.ReadFieldOr<std::uint8_t>(
            actor_address,
            kActorAnimationDriveStateByteOffset,
            0))) +
        " +1BC=" + std::to_string(memory.ReadFieldOr<std::int32_t>(
            actor_address,
            kActorAnimationMoveDurationTicksOffset,
            0)) +
        " slot_table_actor=" + HexString(slot_table_actor_address) +
        " slot_table_prog=" + HexString(slot_table_progression_wrapper) +
        " slot_table_prog_inner=" + HexString(ReadSmartPointerInnerObject(slot_table_progression_wrapper)) +
        " actor_prog=" + HexString(actor_progression_wrapper) +
        " actor_prog_inner=" + HexString(ReadSmartPointerInnerObject(actor_progression_wrapper)) +
        " actor_equip=" + HexString(actor_equip_wrapper) +
        " actor_equip_inner=" + HexString(ReadSmartPointerInnerObject(actor_equip_wrapper)) +
        " +1FC=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0)) +
        " +200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
        " +21C=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)) +
        " stack=" + CaptureStackTraceSummary(1, 5));
}

void LogTrackedAttachmentManagerStateIfChanged(
    std::string_view label,
    uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto lane = ReadEquipVisualLaneState(
        equip_runtime_address,
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    if (lane.current_object_address == 0) {
        return;
    }

    const auto signature = HashMemoryBlockFNV1a32(
        lane.current_object_address + 0x6C,
        0x1C);
    const std::uint64_t combined_signature =
        (static_cast<std::uint64_t>(static_cast<std::uint32_t>(lane.current_object_address)) << 32) |
        static_cast<std::uint64_t>(signature);
    const auto previous = g_tracked_attachment_manager_signatures.find(actor_address);
    if (previous != g_tracked_attachment_manager_signatures.end() &&
        previous->second == combined_signature) {
        return;
    }
    g_tracked_attachment_manager_signatures[actor_address] = combined_signature;

    std::ostringstream out;
    out << "[bots] " << label
        << " actor=" << HexString(actor_address)
        << " attachment=" << HexString(lane.current_object_address)
        << " type=0x" << HexString(static_cast<uintptr_t>(lane.current_object_type_id))
        << " mgr_sig=0x" << HexString(signature)
        << " +6C=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x6C, 0))
        << " +70=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x70, 0))
        << " +74=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x74, 0))
        << " +78=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x78, 0))
        << " +7C=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x7C, 0))
        << " +80=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x80, 0))
        << " +84=" << HexString(memory.ReadFieldOr<std::uint32_t>(lane.current_object_address, 0x84, 0));
    Log(out.str());
}

void __fastcall HookPlayerActorEnsureProgressionHandle(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<PlayerActorNoArgMethodFn>(
        g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
    if (original == nullptr) {
        return;
    }

    LogStandaloneWizardActorProbeEvent(
        "player_vslot_04 enter",
        reinterpret_cast<uintptr_t>(self),
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    original(self);
}

void __fastcall HookPlayerActorDtor(void* self, void* /*unused_edx*/, char free_flag) {
    const auto original =
        GetX86HookTrampoline<PlayerActorDtorFn>(g_gameplay_keyboard_injection.player_actor_dtor_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    LogStandaloneWizardActorLifecycleEvent(
        "player_dtor enter",
        actor_address,
        0,
        static_cast<int>(free_flag),
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    original(self, free_flag);
}

void __fastcall HookPuppetManagerDeletePuppet(void* self, void* /*unused_edx*/, void* actor) {
    const auto original = GetX86HookTrampoline<PuppetManagerDeletePuppetFn>(
        g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
    if (original == nullptr) {
        return;
    }

    LogStandaloneWizardRegionDeleteEvent(
        "puppet_manager_delete_puppet enter",
        reinterpret_cast<uintptr_t>(self),
        reinterpret_cast<uintptr_t>(actor),
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    original(self, actor);
}

void __fastcall HookPointerListDeleteBatch(void* self, void* /*unused_edx*/, void* list) {
    const auto original = GetX86HookTrampoline<PointerListDeleteBatchFn>(
        g_gameplay_keyboard_injection.pointer_list_delete_batch_hook);
    if (original == nullptr) {
        return;
    }

    const auto self_address = reinterpret_cast<uintptr_t>(self);
    const auto list_address = reinterpret_cast<uintptr_t>(list);
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const bool tracked = LogTrackedStandaloneWizardPuppetManagerDeleteBatchEvent(
        "puppet_manager_delete_batch enter",
        self_address,
        list_address,
        caller_address);
    const auto previous_depth = g_puppet_manager_delete_batch_depth;
    const auto previous_self = g_puppet_manager_delete_batch_self;
    const auto previous_list = g_puppet_manager_delete_batch_list;
    if (tracked) {
        ++g_puppet_manager_delete_batch_depth;
        g_puppet_manager_delete_batch_self = self_address;
        g_puppet_manager_delete_batch_list = list_address;
    }
    original(self, list);
    if (tracked) {
        g_puppet_manager_delete_batch_depth = previous_depth;
        g_puppet_manager_delete_batch_self = previous_self;
        g_puppet_manager_delete_batch_list = previous_list;
        (void)LogTrackedStandaloneWizardPuppetManagerDeleteBatchEvent(
            "puppet_manager_delete_batch exit",
            self_address,
            list_address,
            caller_address);
    }
}

void __fastcall HookActorWorldUnregister(
    void* self,
    void* /*unused_edx*/,
    void* actor,
    char remove_from_container) {
    const auto original =
        GetX86HookTrampoline<ActorWorldUnregisterFn>(g_gameplay_keyboard_injection.actor_world_unregister_hook);
    if (original == nullptr) {
        return;
    }

    const auto world_address = reinterpret_cast<uintptr_t>(self);
    const auto actor_address = reinterpret_cast<uintptr_t>(actor);
    LogStandaloneWizardActorLifecycleEvent(
        "world_unregister enter",
        actor_address,
        world_address,
        static_cast<int>(remove_from_container),
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    original(self, actor, remove_from_container);
}

void __fastcall HookPlayerActorVtable28(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.player_actor_vtable28_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    const bool tracked =
        TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot);
    const auto previous_depth = g_player_actor_vslot28_depth;
    const auto previous_actor = g_player_actor_vslot28_actor;
    const auto previous_caller = g_player_actor_vslot28_caller;
    ++g_player_actor_vslot28_depth;
    g_player_actor_vslot28_actor = actor_address;
    g_player_actor_vslot28_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());
    LogStandaloneWizardActorProbeEvent(
        "player_vslot_28 enter",
        actor_address,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    if (tracked) {
        LogTrackedAttachmentManagerStateIfChanged("player_vslot_28 pre_attachment", actor_address);
    }
    original(self);
    g_player_actor_vslot28_depth = previous_depth;
    g_player_actor_vslot28_actor = previous_actor;
    g_player_actor_vslot28_caller = previous_caller;
    if (tracked) {
        LogTrackedAttachmentManagerStateIfChanged("player_vslot_28 post_attachment", actor_address);
        LogStandaloneWizardActorBoundaryEvent(
            "player_vslot_28 exit",
            actor_address,
            bot_id,
            gameplay_slot,
            reinterpret_cast<uintptr_t>(_ReturnAddress()));
    }
}

void __fastcall HookGameplayHudRenderDispatch(void* self, void* /*unused_edx*/, int render_case) {
    const auto original = GetX86HookTrampoline<GameplayHudRenderDispatchFn>(
        g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
    if (original == nullptr) {
        return;
    }

    if (render_case != 100) {
        original(self, render_case);
        return;
    }

    const auto previous_depth = g_gameplay_hud_case100_depth;
    const auto previous_owner = g_gameplay_hud_case100_owner;
    const auto previous_caller = g_gameplay_hud_case100_caller;
    ++g_gameplay_hud_case100_depth;
    g_gameplay_hud_case100_owner = reinterpret_cast<uintptr_t>(self);
    g_gameplay_hud_case100_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());
    original(self, render_case);
    g_gameplay_hud_case100_depth = previous_depth;
    g_gameplay_hud_case100_owner = previous_owner;
    g_gameplay_hud_case100_caller = previous_caller;
}

void __fastcall HookActorAnimationAdvance(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    const bool tracked =
        TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot);
    LogStandaloneWizardActorProbeEvent(
        "actor_animation_advance enter",
        actor_address,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    if (tracked) {
        LogTrackedAttachmentManagerStateIfChanged("anim_advance pre_attachment", actor_address);
    }
    if (tracked) {
        NormalizeGameplaySlotBotActorVisualState(actor_address);
    }
    original(self);
    if (tracked) {
        LogTrackedAttachmentManagerStateIfChanged("anim_advance post_attachment", actor_address);
        LogStandaloneWizardActorBoundaryEvent(
            "actor_animation_advance exit",
            actor_address,
            bot_id,
            gameplay_slot,
            reinterpret_cast<uintptr_t>(_ReturnAddress()));
    }
}

void __fastcall HookPlayerActorTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorTickFn>(g_gameplay_keyboard_injection.player_actor_tick_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    bool standalone_puppet_actor = false;
    bool standalone_actor_moving = false;
    uintptr_t standalone_actor_world = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        if (const auto* binding = FindBotEntityForActor(actor_address);
            binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
            standalone_puppet_actor = true;
            standalone_actor_moving = binding->movement_active;
            standalone_actor_world = binding->materialized_world_address;
        }
    }

    auto& memory = ProcessMemory::Instance();
    if (standalone_puppet_actor) {
        const auto vtable_before =
            memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0);
        const auto position_before_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_before_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto heading_before =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);
        Log(
            "[bots] tick enter actor=" + HexString(actor_address) +
            " vtable=" + HexString(vtable_before) +
            " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
            " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                -1))) +
            " +1FC=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0)) +
            " +200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
            " +21C=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)));
        LogTrackedAttachmentManagerStateIfChanged("tick pre_attachment", actor_address);

        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            standalone_actor_world,
            "player_tick",
            nullptr);
        {
            std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
            if (const auto* binding = FindBotEntityForActor(actor_address);
                binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
                ApplyStandaloneWizardAnimationDriveProfile(
                    binding,
                    actor_address,
                    standalone_actor_moving);
            }
        }
        ApplyStandaloneWizardPuppetDriveState(actor_address, standalone_actor_moving);
        original(self);
        Log(
            "[bots] tick exit actor=" + HexString(actor_address) +
            " vtable=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x00, 0)) +
            " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
            " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                -1))) +
            " +1FC=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0)) +
            " +200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
            " +21C=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)));
        LogTrackedAttachmentManagerStateIfChanged("tick post_attachment", actor_address);

        // The native player tick can still mirror owner transform/anim state onto
        // the puppet. Restore transform and then re-apply the desired animation
        // selection on the live control object after native writes have landed.
        (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
        (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
        (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading_before);

        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        if (auto* binding = FindBotEntityForActor(actor_address);
            binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
            ApplyObservedBotAnimationState(binding, actor_address, standalone_actor_moving);
        }
        NormalizeGameplaySlotBotActorVisualState(actor_address);
        return;
    }

    original(self);
    LogLocalPlayerAnimationProbe();
}

std::uint8_t __fastcall HookGameplayKeyboardEdge(void* self, void* /*unused_edx*/, std::uint32_t scancode) {
    if (scancode < g_gameplay_keyboard_injection.pending_scancodes.size()) {
        auto& pending = g_gameplay_keyboard_injection.pending_scancodes[scancode];
        auto available = pending.load(std::memory_order_acquire);
        while (available > 0) {
            if (pending.compare_exchange_weak(
                    available,
                    available - 1,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                return 1;
            }
        }
    }

    const auto original =
        GetX86HookTrampoline<GameplayKeyboardEdgeFn>(g_gameplay_keyboard_injection.edge_hook);
    return original != nullptr ? original(self, scancode) : 0;
}
