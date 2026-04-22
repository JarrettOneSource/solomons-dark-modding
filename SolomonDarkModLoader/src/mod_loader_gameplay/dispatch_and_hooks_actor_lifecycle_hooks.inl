void __fastcall HookPlayerActorEnsureProgressionHandle(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<PlayerActorNoArgMethodFn>(
        g_gameplay_keyboard_injection.player_actor_progression_handle_hook);
    if (original == nullptr) {
        return;
    }

    original(self);
}

void __fastcall HookPlayerActorDtor(void* self, void* /*unused_edx*/, char free_flag) {
    const auto original =
        GetX86HookTrampoline<PlayerActorDtorFn>(g_gameplay_keyboard_injection.player_actor_dtor_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
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
        Log(
            "[bots] player_dtor enter" +
            std::string(" actor=") + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " binding_slot=" + std::to_string(gameplay_slot) +
            " kind=" + std::to_string(static_cast<int>(tracked_kind)) +
            " arg=" + std::to_string(static_cast<int>(free_flag)) +
            " caller=" + HexString(reinterpret_cast<uintptr_t>(_ReturnAddress())) +
            " owner=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0)) +
            " slot=" + std::to_string(static_cast<int>(memory.ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                -1))) +
            " +1FC=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0)) +
            " +200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0)) +
            " +21C=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0)));
    } else {
        LogStandaloneWizardActorLifecycleEvent(
            "player_dtor enter",
            actor_address,
            0,
            static_cast<int>(free_flag),
            reinterpret_cast<uintptr_t>(_ReturnAddress()));
    }
    original(self, free_flag);
    if (tracked_wizard) {
        MarkParticipantEntityWorldUnregistered(actor_address);
    }
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

    const auto now_ms = static_cast<std::uint64_t>(::GetTickCount64());
    const auto scene_churn_until =
        g_gameplay_keyboard_injection.scene_churn_not_before_ms.load(std::memory_order_acquire);
    if (actor_address != 0 && remove_from_container == 1 && now_ms < scene_churn_until) {
        std::uint64_t bot_id = 0;
        int gameplay_slot = -1;
        if (TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, &bot_id, &gameplay_slot)) {
            Log(
                "[bots] world_unregister bypassed during scene churn. actor=" +
                HexString(actor_address) +
                " bot_id=" + std::to_string(bot_id) +
                " slot=" + std::to_string(gameplay_slot) +
                " world=" + HexString(world_address));
            MarkParticipantEntityWorldUnregistered(actor_address);
            return;
        }
    }

    if (actor_address != 0 && remove_from_container == 1) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (const auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsRegisteredGameNpcKind(binding->kind)) {
            Log(
                "[bots] world_unregister observed for registered GameNpc. bot_id=" +
                std::to_string(binding->bot_id) +
                " actor=" + HexString(actor_address) +
                " world_self=" + HexString(world_address) +
                " actor_owner=" + HexString(ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorOwnerOffset,
                    0)) +
                " remove_from_container=" + std::to_string(static_cast<int>(remove_from_container)));
        }
    }

    if (actor_address != 0 && remove_from_container == 1) {
        const auto actor_owner =
            ProcessMemory::Instance().ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
        if (actor_owner != 0 && actor_owner != world_address) {
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

    original(self, actor, remove_from_container);
    if (actor_address != 0 && remove_from_container == 1 && now_ms < scene_churn_until) {
        MarkParticipantEntityWorldUnregistered(actor_address);
    }
}

void __fastcall HookGameplaySwitchRegion(void* self, void* /*unused_edx*/, int region_index) {
    const auto original =
        GetX86HookTrampoline<GameplaySwitchRegionFn>(g_gameplay_keyboard_injection.gameplay_switch_region_hook);
    if (original == nullptr) {
        return;
    }

    const auto gameplay_address = reinterpret_cast<uintptr_t>(self);
    DematerializeAllMaterializedWizardBotsForSceneSwitch("scene switch pre-dispatch");
    g_gameplay_keyboard_injection.scene_churn_not_before_ms.store(
        static_cast<std::uint64_t>(::GetTickCount64()) + kGameplaySceneChurnDelayMs,
        std::memory_order_release);
    Log(
        "[bots] gameplay switch-region hook. gameplay=" + HexString(gameplay_address) +
        " target_region=" + std::to_string(region_index));
    original(self, region_index);
}
