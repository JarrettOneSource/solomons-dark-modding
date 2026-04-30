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
        const auto slot =
            ProcessMemory::Instance().ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                static_cast<std::int8_t>(-1));
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            if (slot > 0) {
                if (now_ms - s_last_nonlocal_overlay_callback_log_ms >= 1000) {
                    s_last_nonlocal_overlay_callback_log_ms = now_ms;
                    Log(
                        "[bots] nonlocal slot overlay callback. actor=" + HexString(actor_address) +
                        " slot=" + std::to_string(static_cast<int>(slot)) +
                        " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
                }
            } else if (slot == 0 && now_ms - s_last_overlay_callback_log_ms >= 1000) {
                s_last_overlay_callback_log_ms = now_ms;
                Log(
                    "[bots] slot overlay callback. actor=" + HexString(actor_address) +
                    " slot=0 hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
            }
        }
        if (slot > 0 &&
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
    bool selection_target_seed_active = false;
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
            pure_primary_startup =
                binding->ongoing_cast.startup_in_progress &&
                !binding->ongoing_cast.uses_dispatcher_skill_id;
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

    if (log_this) {
        Log(
            "[bots] pure_primary_gate enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    original(self);
    if (log_this) {
        Log(
            "[bots] pure_primary_gate exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
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
    uintptr_t pure_primary_item_sink_fallback = 0;
    bool local_player = false;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr &&
            (IsGameplaySlotWizardKind(binding->kind) ||
             IsStandaloneWizardKind(binding->kind))) {
            log_this = true;
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            pure_primary_startup =
                binding->ongoing_cast.startup_in_progress &&
                !binding->ongoing_cast.uses_dispatcher_skill_id;
            if (binding->ongoing_cast.active &&
                OngoingCastNeedsNativeTargetActor(binding->ongoing_cast)) {
                if (binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary) {
                    pure_primary_item_sink_fallback =
                        binding->ongoing_cast.pure_primary_item_sink_fallback;
                }
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

    auto& memory = ProcessMemory::Instance();
    const auto actor_slot =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorSlotOffset, 0xFF);
    const auto actor200_wrapper =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    const auto actor200_inner = ReadSmartPointerInnerObject(actor200_wrapper);
    const auto gameplay_global =
        memory.ReadValueOr<uintptr_t>(
            memory.ResolveGameAddressOrZero(0x0081C264),
            0);
    const auto slot_wrapper_entry =
        gameplay_global != 0
            ? gameplay_global + 0x1654 + static_cast<std::size_t>(actor_slot) * sizeof(uintptr_t)
            : 0;
    const auto slot_wrapper =
        slot_wrapper_entry != 0 && memory.IsReadableRange(slot_wrapper_entry, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(slot_wrapper_entry, 0)
            : 0;
    const auto slot_inner = ReadSmartPointerInnerObject(slot_wrapper);
    const auto chosen_runtime = actor200_inner != 0 ? actor200_inner : slot_inner;
    const auto chosen_vtable =
        chosen_runtime != 0 && memory.IsReadableRange(chosen_runtime, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(chosen_runtime, 0)
            : 0;
    const auto chosen_vt68 =
        chosen_vtable != 0 && memory.IsReadableRange(chosen_vtable + 0x68, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(chosen_vtable + 0x68, 0)
            : 0;
    const auto chosen_spell_id =
        chosen_runtime != 0 && memory.IsReadableRange(chosen_runtime + 0x750, sizeof(std::int32_t))
            ? memory.ReadValueOr<std::int32_t>(chosen_runtime + 0x750, 0)
            : 0;

    SpellDispatchProbeState saved_probe = g_spell_dispatch_probe;
    if (log_this) {
        g_spell_dispatch_probe.depth = saved_probe.depth + 1;
        g_spell_dispatch_probe.actor_address = actor_address;
        g_spell_dispatch_probe.bot_id = bot_id;
        g_spell_dispatch_probe.startup = startup;
        g_spell_dispatch_probe.pure_primary_startup = pure_primary_startup;
        g_spell_dispatch_probe.pure_primary_item_sink_fallback =
            pure_primary_item_sink_fallback;
        g_spell_dispatch_probe.local_player = local_player;
        Log(
            "[bots] spell_dispatch enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " local_player=" + std::to_string(local_player ? 1 : 0) +
            " slot=" + HexString(actor_slot) +
            " actor200_wrapper=" + HexString(actor200_wrapper) +
            " actor200_inner=" + HexString(actor200_inner) +
            " slot_wrapper_entry=" + HexString(slot_wrapper_entry) +
            " slot_wrapper=" + HexString(slot_wrapper) +
            " slot_inner=" + HexString(slot_inner) +
            " chosen_runtime=" + HexString(chosen_runtime) +
            " chosen_vtable=" + HexString(chosen_vtable) +
            " chosen_vt68=" + HexString(chosen_vt68) +
            " chosen_spell_id=" + std::to_string(chosen_spell_id) +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
        if (local_player) {
            uintptr_t gameplay_address = 0;
            TryResolveCurrentGameplayScene(&gameplay_address);
            Log("[player-cast-probe] dispatch enter. " +
                DescribeLocalPlayerCastProbeState(gameplay_address, actor_address, "dispatch-enter"));
        }
    }

    original(self);

    if (log_this) {
        Log(
            "[bots] spell_dispatch exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
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
