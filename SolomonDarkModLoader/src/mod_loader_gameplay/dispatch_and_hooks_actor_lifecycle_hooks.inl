void __fastcall HookPlayerActorEnsureProgressionHandle(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<PlayerActorNoArgMethodFn>(
        g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
    if (original == nullptr) {
        return;
    }

    original(self);
}

bool IsLocalPlayerActorDestructorTarget(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    SDModPlayerState player_state{};
    if (TryGetPlayerState(&player_state) && player_state.valid && player_state.actor_address == actor_address) {
        return true;
    }

    uintptr_t gameplay_address = 0;
    uintptr_t local_actor_address = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address) && gameplay_address != 0 &&
        TryResolveLocalPlayerWorldContext(gameplay_address, &local_actor_address, nullptr, nullptr) &&
        local_actor_address == actor_address) {
        return true;
    }

    return false;
}

void HandleLocalPlayerActorDestructorTeardown(uintptr_t actor_address, uintptr_t caller_address) {
    static thread_local bool s_handling_local_player_teardown = false;
    if (s_handling_local_player_teardown || !IsLocalPlayerActorDestructorTarget(actor_address)) {
        return;
    }

    s_handling_local_player_teardown = true;
    ClearLocalPlayerTickOwnership();
    const bool ended_active_run = EndRunLifecycleFromExternal("leave_game");
    Log(
        "[bots] local player destructor teardown" +
        std::string(" actor=") + HexString(actor_address) +
        " caller=" + HexString(caller_address) +
        " ended_run=" + std::to_string(ended_active_run ? 1 : 0));
    DematerializeAllMaterializedWizardBotsForSceneSwitch("local player destructor teardown");
    FlushNavGridSnapshotOnSceneUnload();
    s_handling_local_player_teardown = false;
}

void __fastcall HookPlayerActorDtor(void* self, void* /*unused_edx*/, char free_flag) {
    const auto original =
        GetX86HookTrampoline<PlayerActorDtorFn>(g_gameplay_keyboard_injection.player_actor_dtor_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    bool tracked_wizard = false;
    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    ParticipantEntityBinding::Kind tracked_kind = ParticipantEntityBinding::Kind::StandaloneWizard;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (const auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            tracked_wizard = true;
            bot_id = binding->bot_id;
            gameplay_slot = binding->gameplay_slot;
            tracked_kind = binding->kind;
        }
    }
    if (tracked_wizard) {
        auto& memory = ProcessMemory::Instance();
        const auto actor_pointer_field = [&](uintptr_t offset) {
            uintptr_t value = 0;
            return memory.TryReadField(actor_address, offset, &value)
                ? HexString(value)
                : std::string("unreadable");
        };
        std::int8_t actor_slot = 0;
        const auto actor_slot_text = memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot)
            ? std::to_string(static_cast<int>(actor_slot))
            : std::string("unreadable");
        Log(
            "[bots] player_dtor enter" +
            std::string(" actor=") + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " binding_slot=" + std::to_string(gameplay_slot) +
            " kind=" + std::to_string(static_cast<int>(tracked_kind)) +
            " arg=" + std::to_string(static_cast<int>(free_flag)) +
            " caller=" + HexString(caller_address) +
            " owner=" + actor_pointer_field(kActorOwnerOffset) +
            " slot=" + actor_slot_text +
            " +1FC=" + actor_pointer_field(kActorEquipRuntimeStateOffset) +
            " +200=" + actor_pointer_field(kActorProgressionRuntimeStateOffset) +
            " +21C=" + actor_pointer_field(kActorAnimationSelectionStateOffset));
    } else {
        LogStandaloneWizardActorLifecycleEvent(
            "player_dtor enter",
            actor_address,
            0,
            static_cast<int>(free_flag),
            caller_address);
    }
    HandleLocalPlayerActorDestructorTeardown(actor_address, caller_address);
    original(self, free_flag);
    if (tracked_wizard) {
        MarkParticipantEntityWorldUnregistered(actor_address);
    }
}

bool TryReadActorWorldUnregisterNotifyVfunc(
    uintptr_t actor_address,
    uintptr_t* actor_vtable,
    uintptr_t* notify_vfunc) {
    if (actor_vtable != nullptr) {
        *actor_vtable = 0;
    }
    if (notify_vfunc != nullptr) {
        *notify_vfunc = 0;
    }
    if (actor_address == 0 || kActorWorldUnregisterNotifyVfuncOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable = 0;
    uintptr_t vfunc = 0;
    if (!memory.TryReadValue(actor_address, &vtable) ||
        vtable == 0 ||
        !memory.TryReadValue(vtable + kActorWorldUnregisterNotifyVfuncOffset, &vfunc) ||
        vfunc == 0) {
        if (actor_vtable != nullptr) {
            *actor_vtable = vtable;
        }
        if (notify_vfunc != nullptr) {
            *notify_vfunc = vfunc;
        }
        return false;
    }

    if (actor_vtable != nullptr) {
        *actor_vtable = vtable;
    }
    if (notify_vfunc != nullptr) {
        *notify_vfunc = vfunc;
    }
    return true;
}

bool IsActorWorldUnregisterNotifyCallable(
    uintptr_t actor_address,
    uintptr_t* actor_vtable,
    uintptr_t* notify_vfunc) {
    uintptr_t vtable = 0;
    uintptr_t vfunc = 0;
    const bool resolved = TryReadActorWorldUnregisterNotifyVfunc(actor_address, &vtable, &vfunc);
    if (actor_vtable != nullptr) {
        *actor_vtable = vtable;
    }
    if (notify_vfunc != nullptr) {
        *notify_vfunc = vfunc;
    }
    return resolved && ProcessMemory::Instance().IsExecutableRange(vfunc, 1);
}

void __fastcall HookPuppetManagerDeletePuppet(void* self, void* /*unused_edx*/, void* actor) {
    const auto original = GetX86HookTrampoline<PuppetManagerDeletePuppetFn>(
        g_gameplay_keyboard_injection.puppet_manager_delete_puppet_hook);
    if (original == nullptr) {
        return;
    }

    const auto manager_address = reinterpret_cast<uintptr_t>(self);
    const auto actor_address = reinterpret_cast<uintptr_t>(actor);
    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    const auto scene_churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    std::uint64_t scene_churn_bot_id = 0;
    int scene_churn_gameplay_slot = -1;
    if (actor_address != 0 &&
        now_ms < scene_churn_until &&
        TryCaptureTrackedStandaloneWizardBindingIdentity(
            actor_address,
            &scene_churn_bot_id,
            &scene_churn_gameplay_slot)) {
        auto& memory = ProcessMemory::Instance();
        uintptr_t world_address = 0;
        (void)memory.TryReadField(manager_address, kPuppetManagerOwnerRegionOffset, &world_address);
        const auto unregister_address = memory.ResolveGameAddressOrZero(kActorWorldUnregister);
        DWORD exception_code = 0;
        bool unregistered = false;
        if (world_address != 0 && unregister_address != 0) {
            ++g_loader_owned_actor_destroy_unregister_depth;
            unregistered = CallActorWorldUnregisterSafe(
                unregister_address,
                world_address,
                actor_address,
                0,
                &exception_code);
            --g_loader_owned_actor_destroy_unregister_depth;
        }
        MarkParticipantEntityWorldUnregistered(actor_address);
        Log(
            "[bots] puppet_manager_delete_puppet skipped object delete during scene churn. actor=" +
            HexString(actor_address) +
            " bot_id=" + std::to_string(scene_churn_bot_id) +
            " slot=" + std::to_string(scene_churn_gameplay_slot) +
            " manager=" + HexString(manager_address) +
            " world=" + HexString(world_address) +
            " unregister=" + std::to_string(unregistered ? 1 : 0) +
            " unregister_seh=" + HexString(static_cast<uintptr_t>(exception_code)));
        return;
    }

    uintptr_t actor_vtable = 0;
    uintptr_t actor_unregister_notify_vfunc = 0;
    if (actor_address != 0 &&
        now_ms < scene_churn_until &&
        kActorWorldUnregisterNotifyVfuncOffset != 0 &&
        !IsActorWorldUnregisterNotifyCallable(
            actor_address,
            &actor_vtable,
            &actor_unregister_notify_vfunc)) {
        uintptr_t current_gameplay = 0;
        uintptr_t current_slot0_actor = 0;
        const bool have_gameplay =
            TryResolveCurrentGameplayScene(&current_gameplay) && current_gameplay != 0;
        if (have_gameplay) {
            (void)ProcessMemory::Instance().TryReadField(
                current_gameplay,
                kGameplayPlayerActorOffset,
                &current_slot0_actor);
        }
        Log(
            "[bots] puppet_manager_delete_puppet skipped stale native teardown during scene churn. actor=" +
            HexString(actor_address) +
            " manager=" + HexString(manager_address) +
            " actor_vtable=" + HexString(actor_vtable) +
            " actor_unregister_notify_vfunc=" + HexString(actor_unregister_notify_vfunc) +
            " current_gameplay=" + (have_gameplay ? HexString(current_gameplay) : std::string("unresolved")) +
            " current_slot0=" + HexString(current_slot0_actor) +
            " caller=" + HexString(reinterpret_cast<uintptr_t>(_ReturnAddress())) +
            " stack=" + CaptureStackTraceSummary(1, 5));
        return;
    }

    LogStandaloneWizardRegionDeleteEvent(
        "puppet_manager_delete_puppet enter",
        manager_address,
        actor_address,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    original(self, actor);
}

int DisableStaleManagedPointerReleaseCallbacks(
    uintptr_t self_address,
    uintptr_t list_address,
    uintptr_t caller_address) {
    if (self_address == 0 || list_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t self_vtable = 0;
    uintptr_t delete_callback = 0;
    const auto managed_pointer_release_callback =
        memory.ResolveGameAddressOrZero(kObjectDelete);
    if (managed_pointer_release_callback == 0 ||
        !memory.TryReadValue(self_address, &self_vtable) ||
        self_vtable == 0 ||
        !memory.TryReadValue(
            self_vtable + kManagedPointerReleaseOwnerVtableOffset,
            &delete_callback) ||
        delete_callback != managed_pointer_release_callback) {
        return 0;
    }

    int count = 0;
    uintptr_t items_address = 0;
    if (!memory.TryReadField(list_address, kPointerListCountOffset, &count) ||
        !memory.TryReadField(list_address, kPointerListItemsOffset, &items_address) ||
        count <= 0 ||
        count > kManagedPointerReleasePreflightMaxCount ||
        items_address == 0) {
        return 0;
    }

    int disabled_count = 0;
    for (int index = 0; index < count; ++index) {
        uintptr_t item_address = 0;
        if (!memory.TryReadValue(
                items_address + static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &item_address) ||
            item_address == 0) {
            continue;
        }

        std::uint8_t callback_enabled = 0;
        if (!memory.TryReadField(
                item_address,
                kManagedPointerReleaseCallbackEnabledOffset,
                &callback_enabled) ||
            callback_enabled == 0) {
            continue;
        }

        uintptr_t callback_cell = 0;
        uintptr_t callback_address = 0;
        const bool callback_is_callable =
            memory.TryReadField(
                item_address,
                kManagedPointerReleaseCallbackCellOffset,
                &callback_cell) &&
            callback_cell != 0 &&
            memory.TryReadValue(callback_cell, &callback_address) &&
            memory.IsExecutableRange(callback_address, 1);
        if (callback_is_callable) {
            continue;
        }

        const std::uint8_t disabled = 0;
        if (!memory.TryWriteField(
                item_address,
                kManagedPointerReleaseCallbackEnabledOffset,
                disabled)) {
            continue;
        }

        ++disabled_count;
        Log(
            "pointer_list_delete_batch: disabled stale managed release callback. item=" +
            HexString(item_address) +
            " callback_cell=" + HexString(callback_cell) +
            " callback=" + HexString(callback_address) +
            " list=" + HexString(list_address) +
            " index=" + std::to_string(index) +
            " caller=" + HexString(caller_address));
    }
    return disabled_count;
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
    (void)DisableStaleManagedPointerReleaseCallbacks(
        self_address,
        list_address,
        caller_address);
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

void LogSceneChurnActorWorldUnregisterCandidate(
    uintptr_t actor_address,
    uintptr_t world_address,
    int remove_from_container,
    uintptr_t caller_address) {
    if (actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t actor_vtable = 0;
    uintptr_t actor_vtable_48 = 0;
    uintptr_t current_gameplay = 0;
    uintptr_t current_slot0_actor = 0;
    uintptr_t current_slot0_vtable = 0;
    const bool have_gameplay =
        TryResolveCurrentGameplayScene(&current_gameplay) && current_gameplay != 0;
    if (have_gameplay) {
        (void)memory.TryReadField(
            current_gameplay,
            kGameplayPlayerActorOffset,
            &current_slot0_actor);
        if (current_slot0_actor != 0) {
            (void)memory.TryReadValue(current_slot0_actor, &current_slot0_vtable);
        }
    }

    (void)memory.TryReadValue(actor_address, &actor_vtable);
    if (actor_vtable != 0) {
        (void)memory.TryReadValue(
            actor_vtable + kActorWorldUnregisterNotifyVfuncOffset,
            &actor_vtable_48);
    }

    std::uint64_t bot_id = 0;
    int gameplay_slot = -1;
    const bool tracked_standalone =
        TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot);

    Log(
        "[bots] scene_churn_world_unregister_candidate actor=" + HexString(actor_address) +
        " world=" + HexString(world_address) +
        " arg=" + std::to_string(remove_from_container) +
        " caller=" + HexString(caller_address) +
        " tracked_standalone=" + std::to_string(tracked_standalone ? 1 : 0) +
        " bot_id=" + std::to_string(bot_id) +
        " binding_slot=" + std::to_string(gameplay_slot) +
        " current_gameplay=" + (have_gameplay ? HexString(current_gameplay) : std::string("unresolved")) +
        " current_slot0=" + HexString(current_slot0_actor) +
        " current_slot0_vtable=" + HexString(current_slot0_vtable) +
        " actor_is_current_slot0=" + std::to_string(actor_address == current_slot0_actor ? 1 : 0) +
        " actor_vtable=" + HexString(actor_vtable) +
        " actor_vtable48=" + HexString(actor_vtable_48) +
        " owner=" + ReadPointerFieldText(actor_address, kActorOwnerOffset) +
        " slot=" + ReadI8FieldText(actor_address, kActorSlotOffset) +
        " progression_runtime=" + ReadPointerFieldText(actor_address, kActorProgressionRuntimeStateOffset) +
        " equip_runtime=" + ReadPointerFieldText(actor_address, kActorEquipRuntimeStateOffset) +
        " selection=" + ReadPointerFieldText(actor_address, kActorAnimationSelectionStateOffset) +
        " stack=" + CaptureStackTraceSummary(1, 5));
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

    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    const auto scene_churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    if (actor_address != 0 && now_ms < scene_churn_until) {
        LogSceneChurnActorWorldUnregisterCandidate(
            actor_address,
            world_address,
            static_cast<int>(remove_from_container),
            reinterpret_cast<uintptr_t>(_ReturnAddress()));
    }
    const bool tracked_standalone_scene_churn_actor =
        actor_address != 0 &&
        now_ms < scene_churn_until &&
        TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, nullptr, nullptr);
    if (actor_address != 0 &&
        now_ms < scene_churn_until &&
        g_loader_owned_actor_destroy_unregister_depth == 0) {
        std::uint64_t bot_id = 0;
        int gameplay_slot = -1;
        if (TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot)) {
            Log(
                "[bots] world_unregister bypassed during scene churn. actor=" +
                HexString(actor_address) +
                " bot_id=" + std::to_string(bot_id) +
                " slot=" + std::to_string(gameplay_slot) +
                " world=" + HexString(world_address) +
                " arg=" + std::to_string(static_cast<int>(remove_from_container)));
            MarkParticipantEntityWorldUnregistered(actor_address);
            return;
        }
    }

    if (actor_address != 0 && remove_from_container == 1) {
        uintptr_t actor_owner = 0;
        if (ProcessMemory::Instance().TryReadField(actor_address, kActorOwnerOffset, &actor_owner) &&
            actor_owner != 0 &&
            actor_owner != world_address) {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (const auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && binding->kind == ParticipantEntityBinding::Kind::StandaloneWizard) {
                Log(
                    "[bots] world_unregister suppressed for foreign region. actor=" +
                    HexString(actor_address) +
                    " owner=" + HexString(actor_owner) +
                    " world_self=" + HexString(world_address) +
                    " slot=" + std::to_string(binding->gameplay_slot));
                return;
            }
        }
    }

    ForgetAuthoritativeTurnUndeadTargetLocksForActor(actor_address);
    if (actor_address != 0 && remove_from_container == 1) {
        multiplayer::NotifyLocalWorldActorUnregistered(actor_address);
        ForgetRunLifecycleEnemyTracking(actor_address);
    }
    original(self, actor, remove_from_container);
    if (tracked_standalone_scene_churn_actor ||
        (actor_address != 0 && remove_from_container == 1 && now_ms < scene_churn_until)) {
        MarkParticipantEntityWorldUnregistered(actor_address);
    }
}

void __fastcall HookGameplaySwitchRegion(void* self, void* /*unused_edx*/, int region_index) {
    const auto original =
        GetX86HookTrampoline<GameplaySwitchRegionFn>(g_gameplay_keyboard_injection.gameplay_switch_region_hook);
    if (original == nullptr) {
        return;
    }

    if (region_index == kArenaRegionIndex &&
        multiplayer::IsLocalTransportClient() &&
        g_multiplayer_client_authorized_hub_run_switch_depth == 0) {
        std::string authorization_error;
        if (!multiplayer::TryAuthorizeLocalClientRunSwitch(&authorization_error)) {
            Log(
                "Blocked client run switch_region while connected to multiplayer; waiting for host run intent. error=" +
                authorization_error);
            return;
        }
        Log("Authorized client run switch_region from fresh authenticated host intent.");
    }

    ClearAuthoritativeTurnUndeadTargetLocks();
    const auto gameplay_address = reinterpret_cast<uintptr_t>(self);
    (void)PrepareGameplaySceneSwitchOnGameThread(
        gameplay_address,
        region_index,
        "gameplay_switch_region_pre_dispatch");
    Log(
        "[bots] gameplay switch-region hook. gameplay=" + HexString(gameplay_address) +
        " target_region=" + std::to_string(region_index));
    original(self, region_index);
}
