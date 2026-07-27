bool ApplyReplicatedNativeMinionTerminal(
    uintptr_t actor_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor) {
    if (actor_address == 0 ||
        !authoritative_actor.native_minion ||
        (authoritative_actor.native_minion_state.state_flags &
         multiplayer::NativeMinionStateFlagTerminal) == 0) {
        return false;
    }
    if (ReadActorRetirementPendingForNativeMinion(
            actor_address)) {
        ForgetNativeMinionActor(actor_address);
        return true;
    }

    DWORD exception_code = 0;
    bool applied = false;
    const auto reason =
        authoritative_actor.native_minion_state
            .terminal_reason;
    if (authoritative_actor.native_type_id ==
            kGolemNativeTypeId &&
        (reason ==
             multiplayer::NativeMinionTerminalReasonNativeDeath ||
         reason ==
             multiplayer::NativeMinionTerminalReasonReplaced)) {
        const auto golem_death =
            ProcessMemory::Instance()
                .ResolveGameAddressOrZero(kGolemDeath);
        applied = CallNativeMinionNoArgSafe(
            golem_death,
            actor_address,
            &exception_code);
    } else {
        applied = CallActorRequestRetirementSafe(
            actor_address,
            &exception_code);
    }
    if (applied) {
        ForgetNativeMinionActor(actor_address);
    } else {
        Log(
            "native_minion: terminal apply failed. actor=" +
            HexString(actor_address) +
            " type=" +
            HexString(
                static_cast<uintptr_t>(
                    authoritative_actor.native_type_id)) +
            " reason=" +
            std::to_string(static_cast<int>(reason)) +
            " seh=" + HexString(exception_code));
    }
    return applied;
}

bool TryMaterializeReplicatedNativeMinion(
    uintptr_t world_address,
    const multiplayer::WorldActorSnapshot& authoritative_actor,
    uintptr_t* actor_address_out) {
    if (actor_address_out != nullptr) {
        *actor_address_out = 0;
    }
    if (world_address == 0 ||
        actor_address_out == nullptr ||
        !multiplayer::IsLocalTransportClient() ||
        !authoritative_actor.native_minion ||
        !multiplayer::IsNativeMinionType(
            authoritative_actor.native_type_id) ||
        (authoritative_actor.native_minion_state.state_flags &
         multiplayer::NativeMinionStateFlagActive) == 0 ||
        (authoritative_actor.native_minion_state.state_flags &
         multiplayer::NativeMinionStateFlagTerminal) != 0 ||
        !std::isfinite(authoritative_actor.position_x) ||
        !std::isfinite(authoritative_actor.position_y)) {
        return false;
    }

    int owner_gameplay_slot = -1;
    if (!TryResolveNativeMinionOwnerGameplaySlot(
            authoritative_actor.native_minion_state
                .owner_participant_id,
            &owner_gameplay_slot)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto factory =
        memory.ResolveGameAddressOrZero(kGameObjectFactory);
    const auto factory_context =
        memory.ResolveGameAddressOrZero(
            kGameObjectFactoryContextGlobal);
    const auto register_actor =
        memory.ResolveGameAddressOrZero(kActorWorldRegister);
    if (factory == 0 ||
        factory_context == 0 ||
        register_actor == 0) {
        return false;
    }

    uintptr_t actor_address = 0;
    DWORD exception_code = 0;
    if (!CallGameObjectFactorySafe(
            factory,
            factory_context,
            static_cast<int>(
                authoritative_actor.native_type_id),
            &actor_address,
            &exception_code) ||
        actor_address == 0) {
        return false;
    }

    (void)memory.TryWriteField(
        actor_address,
        kActorPositionXOffset,
        authoritative_actor.position_x);
    (void)memory.TryWriteField(
        actor_address,
        kActorPositionYOffset,
        authoritative_actor.position_y);
    if (std::isfinite(authoritative_actor.heading)) {
        (void)memory.TryWriteField(
            actor_address,
            kActorHeadingOffset,
            authoritative_actor.heading);
    }
    RememberNativeMinionOwner(
        actor_address,
        authoritative_actor.native_minion_state
            .owner_participant_id);
    (void)ApplyReplicatedNativeMinionState(
        actor_address,
        authoritative_actor);

    exception_code = 0;
    if (!CallActorWorldRegisterSafe(
            register_actor,
            world_address,
            owner_gameplay_slot,
            actor_address,
            -1,
            0,
            &exception_code)) {
        ForgetNativeMinionActor(actor_address);
        const auto object_delete =
            memory.ResolveGameAddressOrZero(kObjectDelete);
        DWORD delete_exception = 0;
        if (object_delete != 0) {
            (void)CallObjectDeleteSafe(
                object_delete,
                actor_address,
                &delete_exception);
        }
        return false;
    }

    *actor_address_out = actor_address;
    Log(
        "native_minion: materialized observer actor. actor=" +
        HexString(actor_address) +
        " type=" +
        HexString(
            static_cast<uintptr_t>(
                authoritative_actor.native_type_id)) +
        " owner=" +
        std::to_string(
            authoritative_actor.native_minion_state
                .owner_participant_id) +
        " network_actor_id=" +
        std::to_string(
            authoritative_actor.network_actor_id));
    return true;
}

void RetireAuthoritativeNativeMinionsForOwner(
    std::uint64_t owner_participant_id,
    NativeMinionTerminalReason reason) {
    if (!multiplayer::IsLocalTransportHost() ||
        owner_participant_id == 0 ||
        (reason !=
             NativeMinionTerminalReason::OwnerDeath &&
         reason !=
             NativeMinionTerminalReason::OwnerDisconnected)) {
        return;
    }

    std::vector<uintptr_t> owned_actors;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_native_minion_state_mutex);
        for (const auto& [actor_address, owner] :
             g_native_minion_owner_by_actor) {
            if (owner == owner_participant_id) {
                owned_actors.push_back(actor_address);
            }
        }
    }
    for (const auto actor_address : owned_actors) {
        if (ReadActorRetirementPendingForNativeMinion(
                actor_address)) {
            continue;
        }
        multiplayer::NotifyLocalNativeMinionTerminal(
            actor_address,
            static_cast<
                multiplayer::NativeMinionTerminalReason>(
                reason));
        DWORD exception_code = 0;
        if (!CallActorRequestRetirementSafe(
                actor_address,
                &exception_code)) {
            Log(
                "native_minion: owner teardown retirement failed. actor=" +
                HexString(actor_address) +
                " owner=" +
                std::to_string(owner_participant_id) +
                " reason=" +
                std::to_string(
                    static_cast<int>(reason)) +
                " seh=" + HexString(exception_code));
        }
    }
}

void PumpAuthoritativeNativeMinionOwnerLifecycle() {
    if (!multiplayer::IsLocalTransportHost()) {
        return;
    }
    const auto runtime_state =
        multiplayer::SnapshotRuntimeState();
    std::unordered_set<std::uint64_t> dead_owners;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_native_minion_state_mutex);
        for (const auto& [actor_address, owner] :
             g_native_minion_owner_by_actor) {
            (void)actor_address;
            const auto* participant =
                multiplayer::FindParticipant(
                    runtime_state,
                    owner);
            if (participant != nullptr &&
                participant->runtime.valid &&
                participant->runtime.life_current <= 0.0f) {
                dead_owners.insert(owner);
            }
        }
    }
    for (const auto owner : dead_owners) {
        RetireAuthoritativeNativeMinionsForOwner(
            owner,
            NativeMinionTerminalReason::OwnerDeath);
    }
}

bool InitializeNativeMinionHooks(
    std::string* error_message) {
    const std::array<std::tuple<
        uintptr_t,
        void*,
        X86Hook*,
        const char*>, 7>
        hooks = {{
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(kGoodImpTick),
                reinterpret_cast<void*>(&HookGoodImpTick),
                &g_gameplay_keyboard_injection
                     .good_imp_tick_hook,
                "Good Imp tick",
            },
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(
                        kLeviathanTick),
                reinterpret_cast<void*>(&HookLeviathanTick),
                &g_gameplay_keyboard_injection
                     .leviathan_tick_hook,
                "Leviathan tick",
            },
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(kGolemTick),
                reinterpret_cast<void*>(&HookGolemTick),
                &g_gameplay_keyboard_injection
                     .golem_tick_hook,
                "Golem tick",
            },
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(
                        kGolemContact),
                reinterpret_cast<void*>(&HookGolemContact),
                &g_gameplay_keyboard_injection
                     .golem_contact_hook,
                "Golem contact",
            },
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(
                        kGolemDeath),
                reinterpret_cast<void*>(
                    &HookGolemDeath),
                &g_gameplay_keyboard_injection
                     .golem_death_hook,
                "Golem death",
            },
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(
                        kGameObjectFactory),
                reinterpret_cast<void*>(
                    &HookGameObjectFactoryForNativeMinions),
                &g_gameplay_keyboard_injection
                     .native_minion_game_object_factory_hook,
                "native minion factory",
            },
            {
                ProcessMemory::Instance()
                    .ResolveGameAddressOrZero(
                        kKnockbackTick),
                reinterpret_cast<void*>(&HookKnockbackTick),
                &g_gameplay_keyboard_injection
                     .knockback_tick_hook,
                "Golem Knockback tick",
            },
        }};

    std::string hook_error;
    for (const auto& [
             address,
             detour,
             hook,
             label] : hooks) {
        if (address == 0 ||
            !InstallSafeX86Hook(
                reinterpret_cast<void*>(address),
                detour,
                kNativeMinionHookMinimumPatchSize,
                hook,
                &hook_error)) {
            for (const auto& installed : hooks) {
                RemoveX86Hook(std::get<2>(installed));
            }
            if (error_message != nullptr) {
                *error_message =
                    std::string(
                        "Failed to install ") +
                    label + " hook: " +
                    (address == 0
                         ? "address unavailable"
                         : hook_error);
            }
            return false;
        }
    }
    return true;
}

void ShutdownNativeMinionHooks() {
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .good_imp_tick_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .leviathan_tick_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .golem_tick_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .golem_contact_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .golem_death_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .native_minion_game_object_factory_hook);
    RemoveX86Hook(
        &g_gameplay_keyboard_injection
             .knockback_tick_hook);
    std::lock_guard<std::recursive_mutex> lock(
        g_native_minion_state_mutex);
    g_native_minion_owner_by_actor.clear();
    g_native_minion_first_observed_ms_by_actor.clear();
    g_native_minion_knockback_owner_by_actor.clear();
}
