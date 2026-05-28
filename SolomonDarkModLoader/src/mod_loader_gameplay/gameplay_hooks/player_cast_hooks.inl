bool IsTrackedWizardParticipantActorForHud(uintptr_t actor_address) {
    if (actor_address == 0) {
        return false;
    }

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    const auto* binding = FindParticipantEntityForActor(actor_address);
    return binding != nullptr && IsWizardParticipantKind(binding->kind);
}

void __fastcall HookPlayerActorVtable28(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.player_actor_vtable28_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    const auto previous_depth = g_player_actor_vslot28_depth;
    const auto previous_actor = g_player_actor_vslot28_actor;
    const auto previous_caller = g_player_actor_vslot28_caller;
    ++g_player_actor_vslot28_depth;
    g_player_actor_vslot28_actor = actor_address;
    g_player_actor_vslot28_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());
    const auto previous_participant_depth = g_gameplay_hud_participant_actor_depth;
    const auto previous_participant_actor = g_gameplay_hud_participant_actor;
    const auto previous_participant_caller = g_gameplay_hud_participant_actor_caller;
    ++g_gameplay_hud_participant_actor_depth;
    g_gameplay_hud_participant_actor = actor_address;
    g_gameplay_hud_participant_actor_caller = g_player_actor_vslot28_caller;
    {
        static std::uint64_t s_last_overlay_callback_log_ms = 0;
        static std::uint64_t s_last_nonlocal_overlay_callback_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        std::int8_t slot = -1;
        const bool have_slot =
            ProcessMemory::Instance().TryReadField(actor_address, kActorSlotOffset, &slot);
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            if (have_slot && slot > 0) {
                if (now_ms - s_last_nonlocal_overlay_callback_log_ms >= 1000) {
                    s_last_nonlocal_overlay_callback_log_ms = now_ms;
                    Log(
                        "[bots] nonlocal slot overlay callback. actor=" + HexString(actor_address) +
                        " slot=" + std::to_string(static_cast<int>(slot)) +
                        " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
                }
            } else if (have_slot && slot == 0 && now_ms - s_last_overlay_callback_log_ms >= 1000) {
                s_last_overlay_callback_log_ms = now_ms;
                Log(
                    "[bots] slot overlay callback. actor=" + HexString(actor_address) +
                    " slot=0 hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
            }
        }
        if (have_slot &&
            slot > 0 &&
            now_ms <= g_gameplay_slot_hud_probe_until_ms &&
            actor_address == g_gameplay_slot_hud_probe_actor) {
            Log(
                "[bots] hud_probe vslot28 actor=" + HexString(actor_address) +
                    " slot=" + std::to_string(static_cast<int>(slot)) +
                    " caller=" + HexString(g_player_actor_vslot28_caller) +
                    " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
        }
    }

    original(self);
    g_gameplay_hud_participant_actor_depth = previous_participant_depth;
    g_gameplay_hud_participant_actor = previous_participant_actor;
    g_gameplay_hud_participant_actor_caller = previous_participant_caller;
    g_player_actor_vslot28_depth = previous_depth;
    g_player_actor_vslot28_actor = previous_actor;
    g_player_actor_vslot28_caller = previous_caller;
}

void __fastcall HookPlayerActorPurePrimaryGate(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.player_actor_pure_primary_gate_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool pure_primary_startup = false;
    bool active_pure_primary_cast = false;
    bool selection_target_seed_active = false;
    bool standalone_gate_actor = false;
    bool pure_primary_bot_owner_context = false;
    std::uint8_t selection_target_group_seed = 0xFF;
    std::uint16_t selection_target_slot_seed = 0xFFFF;
    std::int32_t selection_target_hold_ticks = 0;
    bool have_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            log_this = binding->ongoing_cast.startup_in_progress;
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            standalone_gate_actor = IsStandaloneWizardKind(binding->kind);
            active_pure_primary_cast =
                binding->ongoing_cast.active &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            pure_primary_startup =
                binding->ongoing_cast.startup_in_progress &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            pure_primary_bot_owner_context =
                active_pure_primary_cast || standalone_gate_actor;
            selection_target_seed_active =
                binding->ongoing_cast.selection_target_seed_active;
            selection_target_group_seed =
                binding->ongoing_cast.selection_target_group_seed;
            selection_target_slot_seed =
                binding->ongoing_cast.selection_target_slot_seed;
            selection_target_hold_ticks =
                binding->ongoing_cast.selection_target_hold_ticks;
            have_aim_target = binding->ongoing_cast.have_aim_target;
            aim_target_x = binding->ongoing_cast.aim_target_x;
            aim_target_y = binding->ongoing_cast.aim_target_y;
        }
    }
    if constexpr (kEnableLocalPlayerCastProbeDiagnostics) {
        if (!log_this) {
            uintptr_t gameplay_address = 0;
            uintptr_t local_actor_address = 0;
            if (TryResolveCurrentGameplayScene(&gameplay_address) &&
                gameplay_address != 0 &&
                TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
                local_actor_address == actor_address) {
                log_this = true;
            }
        }
    }

    if (log_this) {
        Log(
            "[bots] pure_primary_gate enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    std::string slot_owner_context;
    InvokeWithBotProgressionSlotOwnerContext(
        actor_address,
        pure_primary_bot_owner_context,
        [&] {
            original(self);
        },
        &slot_owner_context);
    if (log_this) {
        Log(
            "[bots] pure_primary_gate exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " standalone_slot_owner_context={" + slot_owner_context + "}" +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
}

using PlayerControlBrainUpdateFn = void(__thiscall*)(void* self, void* param2, void* param3);

void __fastcall HookSpellCastDispatcher(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<SpellCastDispatcherFn>(g_gameplay_keyboard_injection.spell_cast_dispatcher_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool pure_primary_startup = false;
    bool active_pure_primary_cast = false;
    bool local_player = false;
    bool standalone_dispatch_actor = false;
    bool pure_primary_bot_owner_context = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            log_this =
                binding->ongoing_cast.startup_in_progress ||
                kEnableWizardBotHotPathDiagnostics;
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            standalone_dispatch_actor = IsStandaloneWizardKind(binding->kind);
            active_pure_primary_cast =
                binding->ongoing_cast.active &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            pure_primary_startup =
                binding->ongoing_cast.startup_in_progress &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            pure_primary_bot_owner_context =
                active_pure_primary_cast || standalone_dispatch_actor;
            if (binding->ongoing_cast.active &&
                OngoingCastNeedsNativeTargetActor(binding->ongoing_cast)) {
                if (OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                    (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
                }
                const auto native_target_actor_address =
                    ResolveOngoingCastNativeTargetActor(binding, binding->ongoing_cast);
                if (native_target_actor_address != 0) {
                    (void)WriteOngoingCastNativeTargetActor(
                        actor_address,
                        &binding->ongoing_cast,
                        native_target_actor_address);
                }
            }
        }
    }
    if constexpr (kEnableLocalPlayerCastProbeDiagnostics) {
        if (!log_this) {
            uintptr_t gameplay_address = 0;
            uintptr_t local_actor_address = 0;
            if (TryResolveCurrentGameplayScene(&gameplay_address) &&
                gameplay_address != 0 &&
                TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) &&
                local_actor_address == actor_address &&
                g_local_player_cast_probe.ticks_remaining > 0) {
                log_this = true;
                local_player = true;
            }
        }
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t actor_slot = 0xFF;
    const bool have_actor_slot =
        memory.TryReadField(actor_address, kActorSlotOffset, &actor_slot);
    uintptr_t actor200_wrapper = 0;
    const bool have_actor200_wrapper =
        memory.TryReadField(actor_address, kActorProgressionHandleOffset, &actor200_wrapper);
    const auto actor200_inner =
        have_actor200_wrapper ? ReadSmartPointerInnerObject(actor200_wrapper) : 0;
    uintptr_t gameplay_global = 0;
    const bool have_gameplay_global =
        TryReadResolvedGamePointerAbsolute(kGameObjectGlobal, &gameplay_global);
    const auto slot_wrapper_entry =
        have_gameplay_global && gameplay_global != 0 && have_actor_slot
            ? gameplay_global + kGameplayPlayerProgressionHandleOffset +
                  static_cast<std::size_t>(actor_slot) * sizeof(uintptr_t)
            : 0;
    uintptr_t slot_wrapper = 0;
    const bool have_slot_wrapper =
        slot_wrapper_entry != 0 &&
        memory.TryReadValue(slot_wrapper_entry, &slot_wrapper);
    const auto slot_inner = have_slot_wrapper ? ReadSmartPointerInnerObject(slot_wrapper) : 0;
    uintptr_t actor_runtime_vtable = 0;
    const bool have_actor_runtime_vtable =
        actor200_inner != 0 &&
        memory.TryReadValue(actor200_inner + kObjectVtableOffset, &actor_runtime_vtable);
    uintptr_t actor_runtime_probe_vfunc = 0;
    const bool have_actor_runtime_probe_vfunc =
        have_actor_runtime_vtable &&
        actor_runtime_vtable != 0 &&
        memory.TryReadValue(actor_runtime_vtable + kSkillsWizardProbeVfuncOffset, &actor_runtime_probe_vfunc);
    std::int32_t actor_runtime_spell_id = 0;
    const bool have_actor_runtime_spell_id =
        actor200_inner != 0 &&
        memory.TryReadValue(actor200_inner + kProgressionCurrentSpellIdOffset, &actor_runtime_spell_id);

    SpellDispatchProbeState saved_probe = g_spell_dispatch_probe;
    if (log_this) {
        g_spell_dispatch_probe.depth = saved_probe.depth + 1;
        g_spell_dispatch_probe.actor_address = actor_address;
        g_spell_dispatch_probe.bot_id = bot_id;
        g_spell_dispatch_probe.startup = startup;
        g_spell_dispatch_probe.pure_primary_startup = pure_primary_startup;
        g_spell_dispatch_probe.local_player = local_player;
        Log(
            "[bots] spell_dispatch enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " local_player=" + std::to_string(local_player ? 1 : 0) +
            " slot=" + (have_actor_slot ? HexString(actor_slot) : UnreadableMemoryFieldText()) +
            " actor200_wrapper=" + (have_actor200_wrapper ? HexString(actor200_wrapper) : UnreadableMemoryFieldText()) +
            " actor200_inner=" + HexString(actor200_inner) +
            " slot_wrapper_entry=" + (slot_wrapper_entry != 0 ? HexString(slot_wrapper_entry) : UnreadableMemoryFieldText()) +
            " slot_wrapper=" + (have_slot_wrapper ? HexString(slot_wrapper) : UnreadableMemoryFieldText()) +
            " slot_inner=" + HexString(slot_inner) +
            " actor_runtime_vtable=" + (have_actor_runtime_vtable
                ? HexString(actor_runtime_vtable)
                : UnreadableMemoryFieldText()) +
            " actor_runtime_probe_vfunc=" + (have_actor_runtime_probe_vfunc
                ? HexString(actor_runtime_probe_vfunc)
                : UnreadableMemoryFieldText()) +
            " actor_runtime_spell_id=" + (have_actor_runtime_spell_id
                ? std::to_string(actor_runtime_spell_id)
                : UnreadableMemoryFieldText()) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
        if constexpr (kEnableLocalPlayerCastProbeDiagnostics) {
            if (local_player) {
                uintptr_t gameplay_address = 0;
                TryResolveCurrentGameplayScene(&gameplay_address);
                Log("[player-cast-probe] dispatch enter. " +
                    DescribeLocalPlayerCastProbeState(gameplay_address, actor_address, "dispatch-enter"));
            }
        }
    }

    std::string slot_owner_context;
    InvokeWithBotProgressionSlotOwnerContext(
        actor_address,
        pure_primary_bot_owner_context,
        [&] {
            original(self);
        },
        &slot_owner_context);

    if (log_this) {
        Log(
            "[bots] spell_dispatch exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " standalone_slot_owner_context={" + slot_owner_context + "}" +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    g_spell_dispatch_probe = saved_probe;
}

void __fastcall HookSpellActionBuilder(
    void* self,
    void* /*unused_edx*/,
    int mode,
    int arg2) {
    const auto original = GetX86HookTrampoline<SpellActionBuilderFn>(
        g_gameplay_keyboard_injection.spell_action_builder_hook);
    if (original == nullptr) {
        return;
    }

    const auto probe = g_spell_dispatch_probe;
    const bool log_this = probe.depth > 0;
    const bool global_log_candidate =
        !log_this &&
        arg2 == 0 &&
        (mode == 3 || mode == 6 || mode == 9) &&
        g_spell_action_builder_global_log_budget > 0;
    const bool global_log_this = global_log_candidate;
    if (global_log_this) {
        --g_spell_action_builder_global_log_budget;
    }
    if (log_this || global_log_this) {
        Log(
            "[bots] spell_action_builder enter actor=" + HexString(probe.actor_address) +
            " bot_id=" + std::to_string(probe.bot_id) +
            " global=" + std::to_string(global_log_this ? 1 : 0) +
            " startup=" + std::to_string(probe.startup ? 1 : 0) +
            " pure_primary_startup=" + std::to_string(probe.pure_primary_startup ? 1 : 0) +
            " local_player=" + std::to_string(probe.local_player ? 1 : 0) +
            " self=" + HexString(reinterpret_cast<uintptr_t>(self)) +
            " mode=" + HexString(static_cast<std::uint32_t>(mode)) +
            " arg2=" + HexString(static_cast<std::uint32_t>(arg2)) +
            " caller=" + HexString(reinterpret_cast<uintptr_t>(_ReturnAddress())) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(probe.actor_address) + "}");
    }

    original(self, mode, arg2);

    if (log_this || global_log_this) {
        Log(
            "[bots] spell_action_builder exit actor=" + HexString(probe.actor_address) +
            " bot_id=" + std::to_string(probe.bot_id) +
            " global=" + std::to_string(global_log_this ? 1 : 0) +
            " self=" + HexString(reinterpret_cast<uintptr_t>(self)) +
            " mode=" + HexString(static_cast<std::uint32_t>(mode)) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(probe.actor_address) + "}");
    }
}

void __cdecl HookSpellBuilderReset() {
    const auto original = GetX86HookTrampoline<SpellBuilderResetFn>(
        g_gameplay_keyboard_injection.spell_builder_reset_hook);
    if (original == nullptr) {
        return;
    }

    const auto probe = g_spell_dispatch_probe;
    if (probe.depth > 0) {
        Log(
            "[bots] spell_builder_reset actor=" + HexString(probe.actor_address) +
            " bot_id=" + std::to_string(probe.bot_id) +
            " startup=" + std::to_string(probe.startup ? 1 : 0) +
            " pure_primary_startup=" + std::to_string(probe.pure_primary_startup ? 1 : 0) +
            " local_player=" + std::to_string(probe.local_player ? 1 : 0) +
            " caller=" + HexString(reinterpret_cast<uintptr_t>(_ReturnAddress())) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(probe.actor_address) + "}");
    }

    original();
}

void __cdecl HookSpellBuilderFinalize() {
    const auto original = GetX86HookTrampoline<SpellBuilderFinalizeFn>(
        g_gameplay_keyboard_injection.spell_builder_finalize_hook);
    if (original == nullptr) {
        return;
    }

    const auto probe = g_spell_dispatch_probe;
    if (probe.depth > 0) {
        Log(
            "[bots] spell_builder_finalize actor=" + HexString(probe.actor_address) +
            " bot_id=" + std::to_string(probe.bot_id) +
            " startup=" + std::to_string(probe.startup ? 1 : 0) +
            " pure_primary_startup=" + std::to_string(probe.pure_primary_startup ? 1 : 0) +
            " local_player=" + std::to_string(probe.local_player ? 1 : 0) +
            " caller=" + HexString(reinterpret_cast<uintptr_t>(_ReturnAddress())) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(probe.actor_address) + "}");
    }

    original();
}
