bool TryReadArenaWaveStartState(uintptr_t arena_address, ArenaWaveStartState* state);
std::string DescribeArenaWaveStartState(const ArenaWaveStartState& candidate);

bool TryUpdateParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* /*error_message*/) {
    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    auto* binding = FindParticipantEntity(request.bot_id);
    if (binding == nullptr || binding->actor_address == 0) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, &x, &y, &heading)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(binding->actor_address, kActorPositionXOffset, x) ||
        !memory.TryWriteField(binding->actor_address, kActorPositionYOffset, y)) {
        DematerializeParticipantEntityNow(request.bot_id, true, "update transform write failed");
        return false;
    }

    (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, heading);
    binding->character_profile = request.character_profile;
    binding->scene_intent = request.scene_intent;
    PublishParticipantGameplaySnapshot(*binding);
    return true;
}

bool TrySpawnStandaloneRemoteWizardParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message);

bool TrySpawnRegisteredGameNpcParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message);

bool TrySpawnGameplaySlotBotParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message);

bool ShouldUseGameplaySlotBotParticipantRail(const SceneContextSnapshot& scene_context) {
    // Arena scenes expose the gameplay player-slot array (slots 1..3) that the
    // stock hostile pathfinder scans for targets via HookMonsterPathfindingRefreshTarget.
    // Spawning bots through the standalone clone rail leaves them invisible to
    // enemies (they aren't in the slot array) — see enemy_targeting_bot_slots.md.
    // Routing arena bots through Gameplay_CreatePlayerSlot + ActorWorld_RegisterGameplaySlotActor
    // places them in slots 1..3 so enemies actually aggro them.
    return IsArenaSceneContext(scene_context);
}

bool ShouldUseRegisteredGameNpcParticipantRail(const SceneContextSnapshot& scene_context) {
    (void)scene_context;
    // Keep hub bots on the standalone clone rail until a true long-lived
    // GameNpc (0x1397) publication contract is recovered. The clone-handoff
    // path uses WizardCloneFromSourceActor, which returns a player-family actor
    // (PlayerActorCtor writes object_type=0x1). Binding that result as
    // RegisteredGameNpc and driving GameNpc_SetMoveGoal on it corrupted the
    // actor's player-side state and crashed stock PlayerActorTick.
    return false;
}

bool TrySpawnStandaloneRemoteWizardParticipantEntitySafe(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnStandaloneRemoteWizardParticipantEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TrySpawnRegisteredGameNpcParticipantEntitySafe(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnRegisteredGameNpcParticipantEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TrySpawnGameplaySlotBotParticipantEntitySafe(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    __try {
        return TrySpawnGameplaySlotBotParticipantEntity(gameplay_address, request, error_message);
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteParticipantEntitySyncNow(
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    multiplayer::BotSnapshot bot_snapshot;
    if (!multiplayer::ReadBotSnapshot(request.bot_id, &bot_snapshot) || !bot_snapshot.available) {
        Log(
            "[bots] sync skipped stale request. bot_id=" + std::to_string(request.bot_id) +
            " element_id=" + std::to_string(request.character_profile.element_id));
        return true;
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
    if (!TryValidateRemoteParticipantSpawnReadiness(
            gameplay_address,
            &scene_context,
            &readiness_error)) {
        if (error_message != nullptr) {
            *error_message = readiness_error;
        }
        return false;
    }

    if (TryUpdateParticipantEntity(gameplay_address, request, error_message)) {
        Log(
            "[bots] sync updated existing entity. bot_id=" + std::to_string(request.bot_id) +
            " element_id=" + std::to_string(request.character_profile.element_id));
        return true;
    }

    const bool use_slot_bot_rail =
        ShouldUseGameplaySlotBotParticipantRail(scene_context);
    const bool use_registered_gamenpc_rail =
        !use_slot_bot_rail && ShouldUseRegisteredGameNpcParticipantRail(scene_context);
    const char* rail_name =
        use_slot_bot_rail ? "gameplay_slot_bot"
                          : (use_registered_gamenpc_rail ? "registered_gamenpc" : "standalone_clone");
    Log(
        "[bots] sync spawning actor. bot_id=" + std::to_string(request.bot_id) +
        " element_id=" + std::to_string(request.character_profile.element_id) +
        " rail=" + std::string(rail_name) +
        " gameplay=" + HexString(gameplay_address));
    DWORD exception_code = 0;
    const bool spawned =
        use_slot_bot_rail
            ? TrySpawnGameplaySlotBotParticipantEntitySafe(
                  gameplay_address,
                  request,
                  error_message,
                  &exception_code)
            : (use_registered_gamenpc_rail
                   ? TrySpawnRegisteredGameNpcParticipantEntitySafe(
                         gameplay_address,
                         request,
                         error_message,
                         &exception_code)
                   : TrySpawnStandaloneRemoteWizardParticipantEntitySafe(
                         gameplay_address,
                         request,
                         error_message,
                         &exception_code));
    if (spawned) {
        return true;
    }
    if (error_message != nullptr && error_message->empty()) {
        const char* rail_fn_name =
            use_slot_bot_rail ? "TrySpawnGameplaySlotBotParticipantEntity"
                              : (use_registered_gamenpc_rail
                                     ? "TrySpawnRegisteredGameNpcParticipantEntity"
                                     : "TrySpawnStandaloneRemoteWizardParticipantEntity");
        if (exception_code != 0) {
            *error_message =
                std::string(rail_fn_name) + " threw 0x" + HexString(exception_code) + ".";
        } else {
            *error_message =
                std::string(rail_fn_name) + " returned false without an error message.";
        }
    }
    return false;
}

void DestroyParticipantEntityNow(std::uint64_t bot_id) {
    RemovePendingParticipantSyncRequest(bot_id);
    RemovePendingParticipantDestroyRequest(bot_id);
    DematerializeParticipantEntityNow(bot_id, true, "destroy");
}

bool ExecuteSpawnEnemyNow(int type_id, float x, float y, uintptr_t* out_enemy_address, std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (out_enemy_address != nullptr) {
        *out_enemy_address = 0;
    }

    if (type_id <= 0) {
        if (error_message != nullptr) {
            *error_message =
                "spawn_enemy: invalid type_id=" + std::to_string(type_id) +
                " (must be > 0; known-good types include 2012 and 5010).";
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

    ArenaWaveStartState wave_state;
    if (TryReadArenaWaveStartState(arena_address, &wave_state) && wave_state.combat_active != 0) {
        if (error_message != nullptr) {
            *error_message =
                "spawn_enemy: refusing manual spawn while arena combat is active. "
                "Our hardcoded (anchor=nullptr, mode=0, param_5=0, param_6=0, override=0) call "
                "shape wedges Enemy_Create's placement sweep once combat state is populated. "
                "arena=" + HexString(arena_address) +
                " state=" + DescribeArenaWaveStartState(wave_state);
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

bool TrySpawnStandaloneRemoteWizardParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
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
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    uintptr_t source_actor_address = 0;
    uintptr_t source_profile_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (actor_address != 0) {
            (void)DestroyLoaderOwnedWizardActor(
                actor_address,
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address),
                false,
                &cleanup_error);
        }
        if (source_actor_address != 0) {
            std::string source_cleanup_error;
            (void)DestroyWizardCloneSourceActor(source_actor_address, &source_cleanup_error);
            if (cleanup_error.empty() && !source_cleanup_error.empty()) {
                cleanup_error = source_cleanup_error;
            }
        }
        if (source_profile_address != 0) {
            DestroySyntheticWizardSourceProfile(source_profile_address);
        }
        actor_address = 0;
        source_actor_address = 0;
        source_profile_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
            if (!cleanup_error.empty()) {
                *error_message += " cleanup=" + cleanup_error;
            }
        }
        return false;
    };

    std::string stage_error;
    if (!CreateWizardCloneSourceActor(
            world_address,
            request.character_profile,
            x,
            y,
            heading,
            &source_actor_address,
            &source_profile_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    LogBotVisualDebugStage(
        "spawn_after_source_create",
        local_actor_address,
        0,
        source_actor_address);

    const auto clone_from_source_address =
        memory.ResolveGameAddressOrZero(kWizardCloneFromSourceActor);
    if (clone_from_source_address == 0) {
        return cleanup_spawn("Unable to resolve WizardCloneFromSourceActor.");
    }

    DWORD clone_exception_code = 0;
    if (!CallWizardCloneFromSourceActorSafe(
            clone_from_source_address,
            source_actor_address,
            &actor_address,
            &clone_exception_code) ||
        actor_address == 0) {
        return cleanup_spawn(
            "WizardCloneFromSourceActor failed with 0x" +
            HexString(clone_exception_code) + ".");
    }

    {
        const auto selection_state_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
        if (selection_state_address != 0) {
            (void)memory.TryWriteField<std::uint8_t>(selection_state_address, 0x24, 1);
        }

        uintptr_t progression_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
        if (progression_address == 0) {
            progression_address = ReadSmartPointerInnerObject(
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
        }
        if (progression_address != 0) {
            constexpr float kDefaultAllyHp = 25.0f;
            (void)memory.TryWriteField<float>(
                progression_address,
                kProgressionHpOffset,
                kDefaultAllyHp);
            (void)memory.TryWriteField<float>(
                progression_address,
                kProgressionMaxHpOffset,
                kDefaultAllyHp);
        }
    }

    if (!DestroyWizardCloneSourceActor(source_actor_address, &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    source_actor_address = 0;
    DestroySyntheticWizardSourceProfile(source_profile_address);
    source_profile_address = 0;

    const auto rebind_actor_address =
        memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
    if (rebind_actor_address == 0) {
        return cleanup_spawn("Unable to resolve WorldCellGrid_RebindActor.");
    }

    DWORD rebind_exception_code = 0;
    if (!CallWorldCellGridRebindActorSafe(
            rebind_actor_address,
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address),
            actor_address,
            &rebind_exception_code)) {
        return cleanup_spawn(
            "WorldCellGrid_RebindActor failed for standalone wizard with 0x" +
            HexString(rebind_exception_code) + ".");
    }

    LogLocalPlayerAnimationProbe();
    RememberParticipantEntity(
        request.bot_id,
        request.character_profile,
        request.scene_intent,
        actor_address,
        ParticipantEntityBinding::Kind::StandaloneWizard,
        -1,
        false);
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntity(request.bot_id); binding != nullptr) {
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
            binding->gameplay_slot = -1;
            binding->raw_allocation = false;
            binding->standalone_progression_wrapper_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
            binding->standalone_progression_inner_address =
                ReadSmartPointerInnerObject(binding->standalone_progression_wrapper_address);
            binding->standalone_equip_wrapper_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0);
            binding->standalone_equip_inner_address =
                ReadSmartPointerInnerObject(binding->standalone_equip_wrapper_address);
            binding->synthetic_source_profile_address = 0;
            SeedStandaloneWizardAnimationDriveProfiles(binding, actor_address);

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
            }

            PublishParticipantGameplaySnapshot(*binding);
        }
    }
    LogBotVisualDebugStage(
        "spawn_after_binding_publish",
        local_actor_address,
        actor_address,
        0);

    const auto moved_x = memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    const auto moved_y = memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);
    if (!moved_x || !moved_y) {
        Log(
            "[bots] standalone clone transform write incomplete. actor=" +
            HexString(actor_address) +
            " wrote_x=" + std::to_string(moved_x ? 1 : 0) +
            " wrote_y=" + std::to_string(moved_y ? 1 : 0));
    }

    Log(
        "[bots] created standalone clone wizard actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address)) +
        " gameplay_slot=-1" +
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

bool TrySpawnGameplaySlotBotParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
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
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    int target_slot = -1;
    for (int candidate = kFirstWizardBotSlot;
         candidate < static_cast<int>(kGameplayPlayerSlotCount);
         ++candidate) {
        uintptr_t existing_actor = 0;
        if (!TryResolvePlayerActorForSlot(gameplay_address, candidate, &existing_actor) ||
            existing_actor == 0) {
            target_slot = candidate;
            break;
        }
    }
    if (target_slot < 0) {
        if (error_message != nullptr) {
            *error_message = "All gameplay bot slots (1..3) are occupied.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        (void)DestroyGameplaySlotBotResources(
            gameplay_address,
            target_slot,
            actor_address,
            world_address,
            0,
            &cleanup_error);
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

    std::string stage_error;
    if (!CreateGameplaySlotBotActor(
            gameplay_address,
            world_address,
            target_slot,
            request.character_profile,
            x,
            y,
            heading,
            &actor_address,
            &progression_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    if (!FinalizeGameplaySlotBotRegistration(
            gameplay_address,
            world_address,
            target_slot,
            actor_address,
            nullptr,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    RememberParticipantEntity(
        request.bot_id,
        request.character_profile,
        request.scene_intent,
        actor_address,
        ParticipantEntityBinding::Kind::GameplaySlotWizard,
        target_slot,
        false);
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntity(request.bot_id); binding != nullptr) {
            binding->controller_state = multiplayer::BotControllerState::Idle;
            binding->movement_active = false;
            binding->has_target = false;
            binding->desired_heading_valid = false;
            binding->next_scene_materialize_retry_ms = 0;
            binding->materialized_scene_address = gameplay_address;
            binding->materialized_world_address = world_address;
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = true;
            binding->gameplay_slot = target_slot;
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
            }

            PublishParticipantGameplaySnapshot(*binding);
        }
    }

    Log(
        "[bots] created gameplay-slot wizard actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(world_address) +
        " gameplay_slot=" + std::to_string(target_slot) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " progression_handle=" +
        HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0)) +
        " equip_handle=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipHandleOffset, 0)));
    return true;
}

bool TrySpawnRegisteredGameNpcParticipantEntity(
    uintptr_t gameplay_address,
    const PendingParticipantEntitySyncRequest& request,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }

    // Reserved for a real GameNpc (0x1397) rail. WizardCloneFromSourceActor
    // returns a player-family clone and must stay on the standalone wizard
    // path instead of being remembered as RegisteredGameNpc.

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
    if (!ResolveParticipantSpawnTransform(gameplay_address, request, &x, &y, &heading)) {
        if (error_message != nullptr) {
            *error_message = "Unable to resolve a bot transform.";
        }
        return false;
    }

    uintptr_t actor_address = 0;
    uintptr_t source_actor_address = 0;
    uintptr_t source_profile_address = 0;
    auto cleanup_spawn = [&](std::string_view failure_message) {
        std::string cleanup_error;
        if (actor_address != 0) {
            (void)DestroyRegisteredGameNpcActor(
                actor_address,
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address),
                &cleanup_error);
        }
        if (source_actor_address != 0) {
            std::string source_cleanup_error;
            (void)DestroyWizardCloneSourceActor(source_actor_address, &source_cleanup_error);
            if (cleanup_error.empty() && !source_cleanup_error.empty()) {
                cleanup_error = source_cleanup_error;
            }
        }
        if (source_profile_address != 0) {
            DestroySyntheticWizardSourceProfile(source_profile_address);
        }
        actor_address = 0;
        source_actor_address = 0;
        source_profile_address = 0;
        if (error_message != nullptr) {
            *error_message = std::string(failure_message);
            if (!cleanup_error.empty()) {
                *error_message += " cleanup=" + cleanup_error;
            }
        }
        return false;
    };

    std::string stage_error;
    if (!CreateWizardCloneSourceActor(
            world_address,
            request.character_profile,
            x,
            y,
            heading,
            &source_actor_address,
            &source_profile_address,
            &stage_error)) {
        return cleanup_spawn(stage_error);
    }

    const auto clone_from_source_address =
        memory.ResolveGameAddressOrZero(kWizardCloneFromSourceActor);
    if (clone_from_source_address == 0) {
        return cleanup_spawn("Unable to resolve WizardCloneFromSourceActor.");
    }

    DWORD clone_exception_code = 0;
    if (!CallWizardCloneFromSourceActorSafe(
            clone_from_source_address,
            source_actor_address,
            &actor_address,
            &clone_exception_code) ||
        actor_address == 0) {
        return cleanup_spawn(
            "WizardCloneFromSourceActor failed with 0x" +
            HexString(clone_exception_code) + ".");
    }

    {
        const auto selection_state_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
        if (selection_state_address != 0) {
            (void)memory.TryWriteField<std::uint8_t>(selection_state_address, 0x24, 1);
        }

        uintptr_t progression_address =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
        if (progression_address == 0) {
            progression_address = ReadSmartPointerInnerObject(
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
        }
        if (progression_address != 0) {
            constexpr float kDefaultAllyHp = 25.0f;
            (void)memory.TryWriteField<float>(
                progression_address,
                kProgressionHpOffset,
                kDefaultAllyHp);
            (void)memory.TryWriteField<float>(
                progression_address,
                kProgressionMaxHpOffset,
                kDefaultAllyHp);
        }
    }

    if (!DestroyWizardCloneSourceActor(source_actor_address, &stage_error)) {
        return cleanup_spawn(stage_error);
    }
    source_actor_address = 0;
    DestroySyntheticWizardSourceProfile(source_profile_address);
    source_profile_address = 0;

    const auto rebind_actor_address =
        memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
    if (rebind_actor_address == 0) {
        return cleanup_spawn("Unable to resolve WorldCellGrid_RebindActor.");
    }

    DWORD rebind_exception_code = 0;
    if (!CallWorldCellGridRebindActorSafe(
            rebind_actor_address,
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address),
            actor_address,
            &rebind_exception_code)) {
        return cleanup_spawn(
            "WorldCellGrid_RebindActor failed with 0x" +
            HexString(rebind_exception_code) + ".");
    }

    RememberParticipantEntity(
        request.bot_id,
        request.character_profile,
        request.scene_intent,
        actor_address,
        ParticipantEntityBinding::Kind::RegisteredGameNpc,
        -1,
        false);
    {
        std::lock_guard<std::recursive_mutex> binding_lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntity(request.bot_id); binding != nullptr) {
            binding->controller_state = multiplayer::BotControllerState::Idle;
            binding->movement_active = false;
            binding->has_target = false;
            binding->desired_heading_valid = false;
            binding->next_scene_materialize_retry_ms = 0;
            binding->materialized_scene_address = gameplay_address;
            binding->materialized_world_address =
                memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address);
            binding->materialized_region_index = -1;
            binding->gameplay_attach_applied = false;
            binding->gameplay_slot = -1;
            binding->raw_allocation = false;
            binding->standalone_progression_wrapper_address = 0;
            binding->standalone_progression_inner_address = 0;
            binding->standalone_equip_wrapper_address = 0;
            binding->standalone_equip_inner_address = 0;
            binding->registered_gamenpc_goal_active = false;
            binding->registered_gamenpc_following_local_slot = false;
            binding->registered_gamenpc_goal_x = 0.0f;
            binding->registered_gamenpc_goal_y = 0.0f;
            binding->synthetic_source_profile_address = 0;

            SceneContextSnapshot scene_context;
            if (TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
                binding->materialized_region_index = scene_context.current_region_index;
            }

            PublishParticipantGameplaySnapshot(*binding);
        }
    }

    const auto moved_x = memory.TryWriteField(actor_address, kActorPositionXOffset, x);
    const auto moved_y = memory.TryWriteField(actor_address, kActorPositionYOffset, y);
    (void)memory.TryWriteField(actor_address, kActorHeadingOffset, heading);
    if (!moved_x || !moved_y) {
        Log(
            "[bots] registered_gamenpc transform write incomplete. actor=" + HexString(actor_address) +
            " wrote_x=" + std::to_string(moved_x ? 1 : 0) +
            " wrote_y=" + std::to_string(moved_y ? 1 : 0));
    }

    Log(
        "[bots] created registered GameNpc actor. bot_id=" + std::to_string(request.bot_id) +
        " actor=" + HexString(actor_address) +
        " world=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, world_address)) +
        " object_type=0x" + HexString(memory.ReadFieldOr<std::uint32_t>(actor_address, kGameObjectTypeIdOffset, 0)) +
        " actor_slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
            actor_address,
            kActorSlotOffset,
            -1))) +
        " resolved_anim_state=" + std::to_string(ResolveActorAnimationStateId(actor_address)) +
        " source_kind=" + std::to_string(memory.ReadFieldOr<std::int32_t>(
            actor_address,
            kActorHubVisualSourceKindOffset,
            0)) +
        " source_profile=" + HexString(memory.ReadFieldOr<uintptr_t>(
            actor_address,
            kActorHubVisualSourceProfileOffset,
            0)) +
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
