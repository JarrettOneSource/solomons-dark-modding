namespace {

struct LocalPlayerCastProbeState {
    std::uint64_t armed_click_serial = 0;
    int ticks_remaining = 0;
};

LocalPlayerCastProbeState g_local_player_cast_probe = {};

struct SpellDispatchProbeState {
    int depth = 0;
    uintptr_t actor_address = 0;
    std::uint64_t bot_id = 0;
    uintptr_t pure_primary_item_sink_fallback = 0;
    bool startup = false;
    bool pure_primary_startup = false;
    bool local_player = false;
};

SpellDispatchProbeState g_spell_dispatch_probe = {};
std::int32_t g_spell_action_builder_global_log_budget = 16;
std::int32_t g_pure_primary_control_log_budget = 32;
std::int32_t g_pure_primary_post_builder_log_budget = 64;
void* g_pure_primary_post_builder_trampoline = nullptr;

struct PurePrimaryLocalActorWindowShim {
    struct Field {
        std::size_t offset = 0;
        std::uint32_t before = 0;
        bool restored = false;
    };

    bool active = false;
    std::array<Field, 1> fields{};
};

PurePrimaryLocalActorWindowShim EnterPurePrimaryLocalActorWindow(uintptr_t actor_address) {
    PurePrimaryLocalActorWindowShim state{};
    if (actor_address == 0) {
        return state;
    }

    state.active = true;
    state.fields = {{
        {0x1FC, 0, false},
    }};

    auto& memory = ProcessMemory::Instance();
    for (auto& field : state.fields) {
        if (field.offset == 0) {
            continue;
        }
        field.before = memory.ReadFieldOr<std::uint32_t>(actor_address, field.offset, 0);
        if (field.before != 0 &&
            memory.TryWriteField<std::uint32_t>(actor_address, field.offset, 0)) {
            field.restored = true;
        }
    }
    return state;
}

void LeavePurePrimaryLocalActorWindow(
    uintptr_t actor_address,
    const PurePrimaryLocalActorWindowShim& state) {
    if (!state.active || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    for (auto it = state.fields.rbegin(); it != state.fields.rend(); ++it) {
        if (!it->restored || it->offset == 0) {
            continue;
        }
        (void)memory.TryWriteField<std::uint32_t>(
            actor_address,
            it->offset,
            it->before);
    }
}

void __cdecl OnPurePrimaryPostBuilder(uintptr_t builder_result) {
    const auto probe = g_spell_dispatch_probe;
    if (!probe.pure_primary_startup || probe.actor_address == 0 ||
        g_pure_primary_post_builder_log_budget <= 0) {
        return;
    }
    --g_pure_primary_post_builder_log_budget;

    auto& memory = ProcessMemory::Instance();
    const auto result_type =
        builder_result != 0 && kGameObjectTypeIdOffset != 0 &&
                memory.IsReadableRange(builder_result + kGameObjectTypeIdOffset, sizeof(std::uint32_t))
            ? memory.ReadFieldOr<std::uint32_t>(builder_result, kGameObjectTypeIdOffset, 0)
            : 0;
    const auto result_field34 =
        builder_result != 0 && memory.IsReadableRange(builder_result + 0x34, sizeof(float))
            ? memory.ReadValueOr<float>(builder_result + 0x34, 0.0f)
            : 0.0f;
    const auto result_field38 =
        builder_result != 0 && memory.IsReadableRange(builder_result + 0x38, sizeof(float))
            ? memory.ReadValueOr<float>(builder_result + 0x38, 0.0f)
            : 0.0f;
    const auto active_cast_group =
        memory.ReadFieldOr<std::uint8_t>(probe.actor_address, kActorActiveCastGroupByteOffset, 0xFF);
    const auto active_cast_slot =
        memory.ReadFieldOr<std::uint16_t>(probe.actor_address, kActorActiveCastSlotShortOffset, 0xFFFF);
    Log(
        "[bots] pure_primary_post_builder actor=" + HexString(probe.actor_address) +
        " bot_id=" + std::to_string(probe.bot_id) +
        " builder_result=" + HexString(builder_result) +
        " result_type=" + HexString(result_type) +
        " result_f34=" + std::to_string(result_field34) +
        " result_f38=" + std::to_string(result_field38) +
        " active_cast_group=" + HexString(active_cast_group) +
        " active_cast_slot=" + HexString(active_cast_slot) +
        " startup_state={" + DescribeGameplaySlotCastStartupWindow(probe.actor_address) + "}");
}

__declspec(naked) void HookPurePrimaryPostBuilder() {
    __asm {
        pushfd
        pushad
        push dword ptr [esp + 28]
        call OnPurePrimaryPostBuilder
        add esp, 4
        popad
        popfd
        jmp dword ptr [g_pure_primary_post_builder_trampoline]
    }
}

std::uint8_t ReadGameplayMouseLeftLiveByte(uintptr_t gameplay_address) {
    if (gameplay_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto input_buffer_index =
        memory.ReadFieldOr<int>(gameplay_address, kGameplayInputBufferIndexOffset, -1);
    if (input_buffer_index < 0) {
        return memory.ReadFieldOr<std::uint8_t>(gameplay_address, kGameplayMouseLeftButtonOffset, 0);
    }

    const auto live_mouse_left_offset =
        static_cast<std::size_t>(
            input_buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
    return memory.ReadFieldOr<std::uint8_t>(gameplay_address, live_mouse_left_offset, 0);
}

std::string DescribeLocalPlayerCastProbeState(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    const char* phase) {
    auto& memory = ProcessMemory::Instance();
    const auto gameplay_cast_intent =
        memory.ReadFieldOr<std::uint32_t>(gameplay_address, kGameplayCastIntentOffset, 0);
    const auto gameplay_mouse_left = ReadGameplayMouseLeftLiveByte(gameplay_address);
    const auto click_serial = GetGameplayMouseLeftEdgeSerial();
    const auto click_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto click_age_ms =
        click_tick_ms != 0 && now_ms >= click_tick_ms ? (now_ms - click_tick_ms) : 0;

    int slot0_selection_state = kUnknownAnimationStateId;
    (void)TryReadGameplayIndexStateValue(
        static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex),
        &slot0_selection_state);
    const auto slot0_selection_global = ReadResolvedGlobalIntOr(kPlayerSelectionState0Global, 0);
    const auto actor_selection_state = ResolveActorAnimationStateId(actor_address);
    const auto selection_pointer =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    const auto progression_handle =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
    const auto progression_runtime = ReadSmartPointerInnerObject(progression_handle);

    return
        "phase=" + std::string(phase) +
        " gameplay=" + HexString(gameplay_address) +
        " cast_intent=" + HexString(gameplay_cast_intent) +
        " mouse_left=" + HexString(gameplay_mouse_left) +
        " click_serial=" + std::to_string(click_serial) +
        " click_age_ms=" + std::to_string(click_age_ms) +
        " actor=" + HexString(actor_address) +
        " actor200=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x200, 0)) +
        " actor21c=" + HexString(memory.ReadFieldOr<uintptr_t>(actor_address, 0x21C, 0)) +
        " skill=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset, 0)) +
        " prev=" + std::to_string(memory.ReadFieldOr<std::int32_t>(actor_address, kActorPrimarySkillIdOffset + sizeof(std::int32_t), 0)) +
        " drive=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0)) +
        " no_int=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorNoInterruptFlagOffset, 0)) +
        " group=" + HexString(memory.ReadFieldOr<std::uint8_t>(actor_address, kActorActiveCastGroupByteOffset, 0xFF)) +
        " cast_slot=" + HexString(memory.ReadFieldOr<std::uint16_t>(actor_address, kActorActiveCastSlotShortOffset, 0xFFFF)) +
        " anim_state=" + std::to_string(actor_selection_state) +
        " slot0_sel=" + std::to_string(slot0_selection_state) +
        " slot0_global=" + std::to_string(slot0_selection_global) +
        " selection_ptr=" + HexString(selection_pointer) +
        " progression_handle=" + HexString(progression_handle) +
        " progression_runtime=" + HexString(progression_runtime) +
        " prog750=" + std::to_string(memory.ReadValueOr<std::uint32_t>(progression_runtime + 0x750, 0));
}

void MaybeArmLocalPlayerCastProbe(uintptr_t gameplay_address, uintptr_t actor_address) {
    if (gameplay_address == 0 || actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto gameplay_cast_intent =
        memory.ReadFieldOr<std::uint32_t>(gameplay_address, kGameplayCastIntentOffset, 0);
    const auto click_serial = GetGameplayMouseLeftEdgeSerial();

    if (gameplay_cast_intent == 0 && click_serial == 0) {
        return;
    }
    if (click_serial != 0 && click_serial == g_local_player_cast_probe.armed_click_serial) {
        return;
    }
    if (click_serial == 0 && g_local_player_cast_probe.ticks_remaining > 0) {
        return;
    }

    g_local_player_cast_probe.armed_click_serial = click_serial;
    g_local_player_cast_probe.ticks_remaining = 12;
    Log("[player-cast-probe] arm. " + DescribeLocalPlayerCastProbeState(gameplay_address, actor_address, "arm"));
}

void MaybeLogLocalPlayerCastProbe(uintptr_t gameplay_address, uintptr_t actor_address, bool post_tick) {
    if (g_local_player_cast_probe.ticks_remaining <= 0 ||
        gameplay_address == 0 ||
        actor_address == 0) {
        return;
    }

    Log(
        "[player-cast-probe] tick. " +
        DescribeLocalPlayerCastProbeState(
            gameplay_address,
            actor_address,
            post_tick ? "post" : "pre"));
    if (post_tick) {
        --g_local_player_cast_probe.ticks_remaining;
    }
}

} // namespace

void __fastcall HookMonsterPathfindingRefreshTarget(void* self, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<MonsterPathfindingRefreshTargetFn>(
        g_gameplay_keyboard_injection.monster_pathfinding_refresh_target_hook);
    if (original == nullptr) {
        return;
    }

    original(self, nullptr);

    // The hostile-target widening path is only validated on stock wave-spawned
    // enemies. Pre-wave/manual spawn surfaces have repeatedly shown instability
    // when hostile AI is redirected onto gameplay-slot bots before the combat
    // system is fully active, so keep the widening dormant until a run has
    // actually entered wave combat.
    if (!IsRunLifecycleActive() || GetRunLifecycleCurrentWave() <= 0) {
        return;
    }

    const auto hostile_actor_address = reinterpret_cast<uintptr_t>(self);
    if (hostile_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    const auto hostile_world_address =
        memory.ReadFieldOr<uintptr_t>(hostile_actor_address, kActorOwnerOffset, 0);
    if (hostile_world_address == 0) {
        return;
    }

    const auto hostile_actor_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
            hostile_actor_address,
            kActorSlotOffset,
            static_cast<std::int8_t>(-1)));
    if (hostile_actor_slot < 0) {
        return;
    }

    const auto compute_distance_to = [&](uintptr_t candidate_actor_address, float* distance) -> bool {
        if (distance == nullptr || candidate_actor_address == 0 || candidate_actor_address == hostile_actor_address) {
            return false;
        }
        if (memory.ReadFieldOr<uintptr_t>(candidate_actor_address, kActorOwnerOffset, 0) != hostile_world_address) {
            return false;
        }
        if (IsActorRuntimeDead(candidate_actor_address)) {
            return false;
        }
        if (memory.ReadFieldOr<std::uint8_t>(candidate_actor_address, kActorAnimationDriveStateByteOffset, 0) != 0) {
            return false;
        }

        const auto delta_x =
            memory.ReadFieldOr<float>(hostile_actor_address, kActorPositionXOffset, 0.0f) -
            memory.ReadFieldOr<float>(candidate_actor_address, kActorPositionXOffset, 0.0f);
        const auto delta_y =
            memory.ReadFieldOr<float>(hostile_actor_address, kActorPositionYOffset, 0.0f) -
            memory.ReadFieldOr<float>(candidate_actor_address, kActorPositionYOffset, 0.0f);
        *distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        return true;
    };

    auto best_distance = (std::numeric_limits<float>::max)();
    uintptr_t best_actor_address = 0;
    const auto current_target_actor_address =
        memory.ReadFieldOr<uintptr_t>(hostile_actor_address, kHostileCurrentTargetActorOffset, 0);
    bool current_target_is_dead_bot = false;
    if (!compute_distance_to(current_target_actor_address, &best_distance) &&
        current_target_actor_address != 0 &&
        IsActorRuntimeDead(current_target_actor_address)) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto* current_binding = FindParticipantEntityForActor(current_target_actor_address);
        current_target_is_dead_bot =
            current_binding != nullptr && IsWizardParticipantKind(current_binding->kind);
    }

    std::vector<uintptr_t> candidate_actor_addresses;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        candidate_actor_addresses.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind) || binding.actor_address == 0) {
                continue;
            }
            if (binding.materialized_scene_address != 0 &&
                binding.materialized_scene_address != gameplay_address) {
                continue;
            }
            candidate_actor_addresses.push_back(binding.actor_address);
        }
    }

    for (const auto candidate_actor_address : candidate_actor_addresses) {
        if (candidate_actor_address == 0) {
            continue;
        }

        auto candidate_distance = 0.0f;
        if (!compute_distance_to(candidate_actor_address, &candidate_distance)) {
            continue;
        }

        if (candidate_distance < best_distance) {
            best_distance = candidate_distance;
            best_actor_address = candidate_actor_address;
        }
    }

    if (best_actor_address == 0) {
        if (current_target_is_dead_bot) {
            (void)memory.TryWriteField<uintptr_t>(
                hostile_actor_address,
                kHostileCurrentTargetActorOffset,
                0);
            (void)memory.TryWriteField<std::int32_t>(
                hostile_actor_address,
                kHostileTargetBucketDeltaOffset,
                0);
            static std::uint64_t s_last_dead_target_clear_log_ms = 0;
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            if (now_ms - s_last_dead_target_clear_log_ms >= 250) {
                s_last_dead_target_clear_log_ms = now_ms;
                Log(
                    std::string("[hostile_ai] cleared dead bot target") +
                    ". hostile=" + HexString(hostile_actor_address) +
                    " dead_target=" + HexString(current_target_actor_address));
            }
        }
        return;
    }

    const auto best_world_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int16_t>(
            best_actor_address,
            kActorWorldSlotOffset,
            static_cast<std::int16_t>(-1)));
    if (best_world_slot < 0) {
        return;
    }

    const auto current_target_world_slot =
        current_target_actor_address != 0
            ? static_cast<std::int32_t>(memory.ReadFieldOr<std::int16_t>(
                  current_target_actor_address,
                  kActorWorldSlotOffset,
                  static_cast<std::int16_t>(-1)))
            : -1;
    const auto current_target_slot =
        current_target_actor_address != 0
            ? static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
                  current_target_actor_address,
                  kActorSlotOffset,
                  static_cast<std::int8_t>(-1)))
            : -1;
    const auto best_actor_slot =
        static_cast<std::int32_t>(memory.ReadFieldOr<std::int8_t>(
            best_actor_address,
            kActorSlotOffset,
            static_cast<std::int8_t>(-1)));
    if (best_actor_slot < 0) {
        return;
    }

    const auto best_bucket_delta =
        best_actor_slot * kActorWorldBucketStride + best_world_slot -
        hostile_actor_slot * kActorWorldBucketStride;

    (void)memory.TryWriteField(hostile_actor_address, kHostileCurrentTargetActorOffset, best_actor_address);
    (void)memory.TryWriteField(hostile_actor_address, kHostileTargetBucketDeltaOffset, best_bucket_delta);

    if (best_actor_address != current_target_actor_address) {
        static std::uint64_t s_last_selector_promotion_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_selector_promotion_log_ms >= 250) {
            s_last_selector_promotion_log_ms = now_ms;
            Log(
                std::string("[hostile_ai] selector promoted wizard participant") +
                ". hostile=" + HexString(hostile_actor_address) +
                " stock_target=" + HexString(current_target_actor_address) +
                " stock_slot=" + std::to_string(current_target_slot) +
                " stock_world_slot=" + std::to_string(current_target_world_slot) +
                " promoted_target=" + HexString(best_actor_address) +
                " promoted_slot=" + std::to_string(best_actor_slot) +
                " promoted_world_slot=" + std::to_string(best_world_slot) +
                " promoted_bucket_delta=" + std::to_string(best_bucket_delta));
        }
    }
}

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
        if (slot > 0) {
            if (now_ms - s_last_nonlocal_overlay_callback_log_ms >= 1000) {
                s_last_nonlocal_overlay_callback_log_ms = now_ms;
                Log(
                    "[bots] nonlocal slot overlay callback. actor=" + HexString(actor_address) +
                    " slot=" + std::to_string(static_cast<int>(slot)) +
                    " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
            }
            if (now_ms <= g_gameplay_slot_hud_probe_until_ms &&
                actor_address == g_gameplay_slot_hud_probe_actor) {
                Log(
                    "[bots] hud_probe vslot28 actor=" + HexString(actor_address) +
                    " slot=" + std::to_string(static_cast<int>(slot)) +
                    " caller=" + HexString(g_player_actor_vslot28_caller) +
                    " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
            }
        } else if (slot == 0 && now_ms - s_last_overlay_callback_log_ms >= 1000) {
            s_last_overlay_callback_log_ms = now_ms;
            Log(
                "[bots] slot overlay callback. actor=" + HexString(actor_address) +
                " slot=0 hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
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
            binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
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
            binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
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

uintptr_t ResolveActorAttachmentLaneItem(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto attachment_lane = ReadEquipVisualLaneState(
        equip_runtime,
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    if (attachment_lane.current_object_address == 0 ||
        !memory.IsReadableRange(attachment_lane.current_object_address, 0x0C)) {
        return 0;
    }

    return attachment_lane.current_object_address;
}

int __fastcall HookEquipAttachmentSinkGetCurrentItem(int sink, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<EquipAttachmentSinkGetCurrentItemFn>(
        g_gameplay_keyboard_injection.equip_attachment_get_current_item_hook);
    if (original == nullptr) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto sink_address = static_cast<uintptr_t>(sink);
    const auto sink_vtable =
        sink_address != 0 && memory.IsReadableRange(sink_address, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(sink_address, 0)
            : 0;
    const auto sink_item_before =
        sink_address != 0 && memory.IsReadableRange(sink_address + 4, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(sink_address + 4, 0)
            : 0;

    const auto result = original(sink);
    uintptr_t fallback_result = 0;
    if (g_spell_dispatch_probe.depth > 0 &&
        !g_spell_dispatch_probe.local_player &&
        g_spell_dispatch_probe.actor_address != 0) {
        fallback_result = g_spell_dispatch_probe.pure_primary_item_sink_fallback;
        if (fallback_result == 0) {
            fallback_result = ResolveActorAttachmentLaneItem(g_spell_dispatch_probe.actor_address);
        }
        if (fallback_result == static_cast<uintptr_t>(result)) {
            fallback_result = 0;
        }
    }

    if (g_spell_dispatch_probe.depth > 0) {
        const auto item_type =
            (result != 0 || fallback_result != 0) &&
                    memory.IsReadableRange((result != 0 ? static_cast<uintptr_t>(result) : fallback_result) + 8, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>((result != 0 ? static_cast<uintptr_t>(result) : fallback_result) + 8, 0)
                : 0;
        Log(
            "[bots] equip_sink_get_current_item actor=" + HexString(g_spell_dispatch_probe.actor_address) +
            " bot_id=" + std::to_string(g_spell_dispatch_probe.bot_id) +
            " startup=" + std::to_string(g_spell_dispatch_probe.startup ? 1 : 0) +
            " pure_primary_startup=" + std::to_string(g_spell_dispatch_probe.pure_primary_startup ? 1 : 0) +
            " local_player=" + std::to_string(g_spell_dispatch_probe.local_player ? 1 : 0) +
            " sink=" + HexString(sink_address) +
            " sink_vtable=" + HexString(sink_vtable) +
            " sink_item_before=" + HexString(sink_item_before) +
            " result=" + HexString(static_cast<uintptr_t>(result)) +
            " fallback_result=" + HexString(fallback_result) +
            " result_type=" + HexString(item_type));
    }

    return fallback_result != 0 ? static_cast<int>(fallback_result) : result;
}

void __fastcall HookPlayerControlBrainUpdate(
    void* self,
    void* /*unused_edx*/,
    void* param2,
    void* param3) {
    const auto original =
        GetX86HookTrampoline<PlayerControlBrainUpdateFn>(
            g_gameplay_keyboard_injection.player_control_brain_update_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    auto& memory = ProcessMemory::Instance();
    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool native_target_control_active = false;
    bool selection_target_seed_active = false;
    std::uint8_t selection_target_group_seed = 0xFF;
    std::uint16_t selection_target_slot_seed = 0xFFFF;
    std::int32_t selection_target_hold_ticks = 0;
    bool have_aim_target = false;
    float aim_target_x = 0.0f;
    float aim_target_y = 0.0f;
    bool face_control_active = false;
    bool have_face_vector = false;
    float face_vector_x = 0.0f;
    float face_vector_y = 0.0f;
    bool have_startup_move_vector = false;
    float startup_move_vector_x = 0.0f;
    float startup_move_vector_y = 0.0f;
    float face_heading = 0.0f;
    bool have_face_target = false;
    float face_target_x = 0.0f;
    float face_target_y = 0.0f;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
            if (binding->ongoing_cast.active &&
                OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
            }
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
            have_startup_move_vector = TryGetBindingMovementInputVector(
                *binding,
                &startup_move_vector_x,
                &startup_move_vector_y);
            face_control_active = binding->facing_heading_valid;
            face_heading = binding->facing_heading_value;
            if (binding->facing_target_actor_address != 0) {
                float live_face_heading = 0.0f;
                float live_target_x = 0.0f;
                float live_target_y = 0.0f;
                if (TryComputeActorAimTowardTargetFromOrigin(
                        actor_address,
                        binding->facing_target_actor_address,
                        binding->stock_tick_facing_origin_valid,
                        binding->stock_tick_facing_origin_x,
                        binding->stock_tick_facing_origin_y,
                        &live_face_heading,
                        &live_target_x,
                        &live_target_y)) {
                    face_control_active = true;
                    have_face_target = true;
                    face_target_x = live_target_x;
                    face_target_y = live_target_y;
                    face_heading = live_face_heading;
                    const auto origin_x =
                        binding->stock_tick_facing_origin_valid
                            ? binding->stock_tick_facing_origin_x
                            : memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
                    const auto origin_y =
                        binding->stock_tick_facing_origin_valid
                            ? binding->stock_tick_facing_origin_y
                            : memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
                    const auto dx = live_target_x - origin_x;
                    const auto dy = live_target_y - origin_y;
                    const auto distance = std::sqrt((dx * dx) + (dy * dy));
                    if (std::isfinite(distance) && distance > 0.0001f) {
                        have_face_vector = true;
                        face_vector_x = dx / distance;
                        face_vector_y = dy / distance;
                    }
                }
            }
            if (face_control_active && !have_face_vector) {
                const auto radians =
                    (NormalizeWizardActorHeadingForWrite(face_heading) - 90.0f) /
                    kWizardHeadingRadiansToDegrees;
                face_vector_x = std::cos(radians);
                face_vector_y = std::sin(radians);
                have_face_vector = std::isfinite(face_vector_x) && std::isfinite(face_vector_y);
            }
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            native_target_control_active =
                binding->ongoing_cast.active &&
                OngoingCastNeedsNativeTargetActor(binding->ongoing_cast);
            log_this = startup;
            if (!log_this &&
                native_target_control_active &&
                g_pure_primary_control_log_budget > 0) {
                log_this = true;
                --g_pure_primary_control_log_budget;
            }
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
            local_actor_address == actor_address &&
            g_local_player_cast_probe.ticks_remaining > 0) {
            log_this = true;
        }
    }

    const auto selection_pointer =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorAnimationSelectionStateOffset, 0);
    constexpr auto kControlBrainVectorSize = sizeof(float) * 2;
    const auto read_vector2 = [&](void* vector_pointer, float* x, float* y) -> bool {
        if (x == nullptr || y == nullptr) {
            return false;
        }
        *x = 0.0f;
        *y = 0.0f;
        const auto address = reinterpret_cast<uintptr_t>(vector_pointer);
        if (address == 0 || !memory.IsReadableRange(address, kControlBrainVectorSize)) {
            return false;
        }
        *x = memory.ReadValueOr<float>(address, 0.0f);
        *y = memory.ReadValueOr<float>(address + sizeof(float), 0.0f);
        return true;
    };
    const auto write_vector2 = [&](void* vector_pointer, float x, float y) -> bool {
        const auto address = reinterpret_cast<uintptr_t>(vector_pointer);
        if (address == 0 || !memory.IsWritableRange(address, kControlBrainVectorSize)) {
            return false;
        }
        const auto wrote_x = memory.TryWriteValue<float>(address, x);
        const auto wrote_y = memory.TryWriteValue<float>(address + sizeof(float), y);
        return wrote_x && wrote_y;
    };
    float move_x_before = 0.0f;
    float move_y_before = 0.0f;
    float face_x_before = 0.0f;
    float face_y_before = 0.0f;
    (void)read_vector2(param2, &move_x_before, &move_y_before);
    (void)read_vector2(param3, &face_x_before, &face_y_before);
    if (log_this) {
        Log(
            "[bots] control_brain enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " native_target_control=" + std::to_string(native_target_control_active ? 1 : 0) +
            " sel_ptr=" + HexString(selection_pointer) +
            " sel_group=" +
                HexString(selection_pointer != 0 ? memory.ReadValueOr<std::uint8_t>(selection_pointer + 0x4, 0xFF) : 0xFF) +
            " sel_slot=" +
                HexString(selection_pointer != 0 ? memory.ReadValueOr<std::uint16_t>(selection_pointer + 0x6, 0xFFFF) : 0xFFFF) +
            " sel_t8=" +
                std::to_string(selection_pointer != 0 ? memory.ReadValueOr<std::int32_t>(selection_pointer + 0x8, 0) : 0) +
            " move_before=(" + std::to_string(move_x_before) + "," + std::to_string(move_y_before) + ")" +
            " face_before=(" + std::to_string(face_x_before) + "," + std::to_string(face_y_before) + ")" +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }

    const auto seed_selection_target = [&]() {
        if (!native_target_control_active || selection_pointer == 0 || !selection_target_seed_active) {
            return;
        }
        (void)memory.TryWriteField<std::uint8_t>(
            selection_pointer,
            0x04,
            selection_target_group_seed);
        (void)memory.TryWriteField<std::uint16_t>(
            selection_pointer,
            0x06,
            selection_target_slot_seed);
        (void)memory.TryWriteField<std::int32_t>(
            selection_pointer,
            0x08,
            selection_target_hold_ticks);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x0C, 0);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x10, 0);
        (void)memory.TryWriteField<std::int32_t>(selection_pointer, 0x14, 0);
    };

    const auto apply_face_control = [&]() {
        if (!face_control_active || !have_face_vector) {
            return;
        }
        (void)write_vector2(param3, face_vector_x, face_vector_y);
        ApplyWizardActorFacingState(actor_address, face_heading);
        if (native_target_control_active && startup && selection_pointer != 0) {
            // The stock pure-primary startup gate needs a non-zero movement
            // vector. Use the follow lane while moving and only fall back to
            // attack-facing when idle.
            const auto startup_input_x =
                have_startup_move_vector ? startup_move_vector_x : face_vector_x;
            const auto startup_input_y =
                have_startup_move_vector ? startup_move_vector_y : face_vector_y;
            (void)memory.TryWriteValue<float>(
                selection_pointer + kActorControlBrainMoveInputXOffset,
                startup_input_x);
            (void)memory.TryWriteValue<float>(
                selection_pointer + kActorControlBrainMoveInputYOffset,
                startup_input_y);
        }
        if (have_face_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, face_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, face_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        } else if (have_aim_target) {
            (void)memory.TryWriteField(actor_address, kActorAimTargetXOffset, aim_target_x);
            (void)memory.TryWriteField(actor_address, kActorAimTargetYOffset, aim_target_y);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux0Offset, 0);
            (void)memory.TryWriteField<std::uint32_t>(actor_address, kActorAimTargetAux1Offset, 0);
        }
    };

    // Stock attack/cast code consumes the face lane during its own update, so
    // provide the current target-facing vector before the original runs. Re-pin
    // after the original too because stock may clear the cached target fields.
    seed_selection_target();
    apply_face_control();
    original(self, param2, param3);

    float raw_move_x_after = 0.0f;
    float raw_move_y_after = 0.0f;
    float raw_face_x_after = 0.0f;
    float raw_face_y_after = 0.0f;
    (void)read_vector2(param2, &raw_move_x_after, &raw_move_y_after);
    (void)read_vector2(param3, &raw_face_x_after, &raw_face_y_after);
    const auto raw_move_mag_sq_after =
        raw_move_x_after * raw_move_x_after + raw_move_y_after * raw_move_y_after;
    const auto raw_face_mag_sq_after =
        raw_face_x_after * raw_face_x_after + raw_face_y_after * raw_face_y_after;

    seed_selection_target();
    apply_face_control();

    float move_x_after = 0.0f;
    float move_y_after = 0.0f;
    float face_x_after = 0.0f;
    float face_y_after = 0.0f;
    (void)read_vector2(param2, &move_x_after, &move_y_after);
    (void)read_vector2(param3, &face_x_after, &face_y_after);
    if (log_this) {
        Log(
            "[bots] control_brain exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " native_target_control=" + std::to_string(native_target_control_active ? 1 : 0) +
            " raw_move_after=(" + std::to_string(raw_move_x_after) + "," + std::to_string(raw_move_y_after) + ")" +
            " raw_move_mag_sq=" + std::to_string(raw_move_mag_sq_after) +
            " raw_face_after=(" + std::to_string(raw_face_x_after) + "," + std::to_string(raw_face_y_after) + ")" +
            " raw_face_mag_sq=" + std::to_string(raw_face_mag_sq_after) +
            " move_after=(" + std::to_string(move_x_after) + "," + std::to_string(move_y_after) + ")" +
            " face_after=(" + std::to_string(face_x_after) + "," + std::to_string(face_y_after) + ")" +
            " startup_state={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
}

void __fastcall HookPurePrimarySpellStart(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorNoArgMethodFn>(g_gameplay_keyboard_injection.pure_primary_spell_start_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    bool log_this = false;
    std::uint64_t bot_id = 0;
    bool startup = false;
    bool apply_local_selection_shim = false;
    bool local_player = false;
    uintptr_t fallback_slot_obj = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
            SyncWizardBotMovementIntent(binding);
            log_this = true;
            bot_id = binding->bot_id;
            startup = binding->ongoing_cast.startup_in_progress;
            apply_local_selection_shim =
                binding->ongoing_cast.active &&
                binding->ongoing_cast.lane ==
                    ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
            if (apply_local_selection_shim) {
                (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
            }
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
            local_player = true;
        }
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t pure_primary_slot_sink_inner = 0;
    uintptr_t pure_primary_attachment_item = 0;
    std::uint32_t pure_primary_saved_slot_item = 0;
    bool pure_primary_slot_item_shim_applied = false;
    if (apply_local_selection_shim) {
        pure_primary_attachment_item = ResolveActorAttachmentLaneItem(actor_address);
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
                if (pure_primary_attachment_item != 0) {
                    binding->ongoing_cast.pure_primary_item_sink_fallback =
                        pure_primary_attachment_item;
                } else {
                    pure_primary_attachment_item =
                        binding->ongoing_cast.pure_primary_item_sink_fallback;
                }
            }
        }
    }

    PurePrimaryLocalActorWindowShim pure_primary_actor_window_shim{};
    if (apply_local_selection_shim) {
        pure_primary_actor_window_shim = EnterPurePrimaryLocalActorWindow(actor_address);
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
            SyncWizardBotMovementIntent(binding);
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
        }
    }

    if (apply_local_selection_shim) {
        const auto gameplay_global = memory.ReadValueOr<uintptr_t>(
            memory.ResolveGameAddressOrZero(0x0081c264),
            0);
        const auto shim_slot_obj =
            gameplay_global != 0
                ? gameplay_global + 0x1410
                : 0;
        const auto fallback_slot_obj30 =
            shim_slot_obj != 0 &&
                    memory.IsReadableRange(shim_slot_obj + 0x30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(shim_slot_obj + 0x30, 0)
                : 0;
        pure_primary_slot_sink_inner =
            fallback_slot_obj30 != 0 &&
                    memory.IsReadableRange(fallback_slot_obj30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(fallback_slot_obj30, 0)
                : 0;
        if (pure_primary_attachment_item != 0 &&
            pure_primary_slot_sink_inner != 0 &&
            memory.IsReadableRange(pure_primary_slot_sink_inner + 4, sizeof(std::uint32_t))) {
            pure_primary_saved_slot_item =
                memory.ReadValueOr<std::uint32_t>(pure_primary_slot_sink_inner + 4, 0);
            pure_primary_slot_item_shim_applied =
                memory.TryWriteValue<std::uint32_t>(
                    pure_primary_slot_sink_inner + 4,
                    static_cast<std::uint32_t>(pure_primary_attachment_item));
        }
    }

    if (log_this) {
        const auto actor_1fc = memory.ReadFieldOr<std::uint32_t>(actor_address, 0x1FC, 0);
        const auto actor_1fc_ptr = static_cast<uintptr_t>(actor_1fc);
        const auto actor_1fc_obj30 =
            actor_1fc_ptr != 0 && memory.IsReadableRange(actor_1fc_ptr + 0x30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(actor_1fc_ptr + 0x30, 0)
                : 0;
        const auto actor_1fc_inner =
            actor_1fc_obj30 != 0 && memory.IsReadableRange(actor_1fc_obj30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(actor_1fc_obj30, 0)
                : 0;
        const auto actor_1fc_plus4 =
            actor_1fc_inner != 0 && memory.IsReadableRange(actor_1fc_inner + 4, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(actor_1fc_inner + 4, 0)
                : 0;
        const auto actor_1fc_plus4_type =
            actor_1fc_plus4 != 0 && memory.IsReadableRange(static_cast<uintptr_t>(actor_1fc_plus4) + 8, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(static_cast<uintptr_t>(actor_1fc_plus4) + 8, 0)
                : 0;
        std::uint8_t effective_slot_byte =
            memory.ReadFieldOr<std::uint8_t>(actor_address, kActorSlotOffset, 0xFF);
        if (apply_local_selection_shim) {
            effective_slot_byte = 0;
        }
        const auto gameplay_global =
            ProcessMemory::Instance().ReadValueOr<uintptr_t>(
                ProcessMemory::Instance().ResolveGameAddressOrZero(0x0081c264),
                0);
        fallback_slot_obj =
            gameplay_global != 0
                ? gameplay_global +
                    static_cast<std::size_t>(effective_slot_byte) * 0x64 +
                    0x1410
                : 0;
        const auto fallback_slot_obj30 =
            fallback_slot_obj != 0 && memory.IsReadableRange(fallback_slot_obj + 0x30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(fallback_slot_obj + 0x30, 0)
                : 0;
        const auto fallback_slot_inner =
            fallback_slot_obj30 != 0 && memory.IsReadableRange(fallback_slot_obj30, sizeof(uintptr_t))
                ? memory.ReadValueOr<uintptr_t>(fallback_slot_obj30, 0)
                : 0;
        const auto fallback_slot_plus4 =
            fallback_slot_inner != 0 && memory.IsReadableRange(fallback_slot_inner + 4, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(fallback_slot_inner + 4, 0)
                : 0;
        const auto fallback_slot_plus4_type =
            fallback_slot_plus4 != 0 && memory.IsReadableRange(static_cast<uintptr_t>(fallback_slot_plus4) + 8, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>(static_cast<uintptr_t>(fallback_slot_plus4) + 8, 0)
                : 0;
        Log(
            "[bots] pure_primary_start enter actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup=" + std::to_string(startup ? 1 : 0) +
            " local_sel_shim=" + std::to_string(apply_local_selection_shim ? 1 : 0) +
            " local_window_shim=" + std::to_string(pure_primary_actor_window_shim.active ? 1 : 0) +
            " actor1fc=" + HexString(actor_1fc_ptr) +
            " actor1fc30=" + HexString(actor_1fc_obj30) +
            " actor1fc_inner=" + HexString(actor_1fc_inner) +
            " actor1fc_plus4=" + HexString(actor_1fc_plus4) +
            " actor1fc_plus4_type=" + HexString(actor_1fc_plus4_type) +
            " fallback_slot_byte=" + HexString(effective_slot_byte) +
            " fallback_slot_obj=" + HexString(fallback_slot_obj) +
            " fallback_slot_obj30=" + HexString(fallback_slot_obj30) +
            " fallback_slot_inner=" + HexString(fallback_slot_inner) +
            " fallback_slot_plus4=" + HexString(fallback_slot_plus4) +
            " fallback_slot_plus4_type=" + HexString(fallback_slot_plus4_type) +
            " slot_item_shim=" + std::to_string(pure_primary_slot_item_shim_applied ? 1 : 0) +
            " slot_item_saved=" + HexString(pure_primary_saved_slot_item) +
            " attachment_item=" + HexString(pure_primary_attachment_item) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    SpellDispatchProbeState saved_probe = g_spell_dispatch_probe;
    if (log_this) {
        g_spell_dispatch_probe.depth = saved_probe.depth + 1;
        g_spell_dispatch_probe.actor_address = actor_address;
        g_spell_dispatch_probe.bot_id = bot_id;
        g_spell_dispatch_probe.pure_primary_item_sink_fallback =
            pure_primary_attachment_item;
        g_spell_dispatch_probe.startup = startup;
        g_spell_dispatch_probe.pure_primary_startup = apply_local_selection_shim;
        g_spell_dispatch_probe.local_player = local_player;
    }
    original(self);
    if (pure_primary_slot_item_shim_applied) {
        (void)memory.TryWriteValue<std::uint32_t>(
            pure_primary_slot_sink_inner + 4,
            pure_primary_saved_slot_item);
    }
    g_spell_dispatch_probe = saved_probe;
    if (apply_local_selection_shim) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
            (void)RefreshAndApplyWizardBindingFacingState(binding, actor_address);
        }
    }
    if (log_this) {
        Log(
            "[bots] pure_primary_start exit actor=" + HexString(actor_address) +
            " bot_id=" + std::to_string(bot_id) +
            " startup={" + DescribeGameplaySlotCastStartupWindow(actor_address) + "}");
    }
    LeavePurePrimaryLocalActorWindow(actor_address, pure_primary_actor_window_shim);
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
    if (static_cast<std::uint64_t>(GetTickCount64()) <= g_gameplay_slot_hud_probe_until_ms) {
        Log(
            "[bots] hud_probe case100 owner=" + HexString(g_gameplay_hud_case100_owner) +
            " caller=" + HexString(g_gameplay_hud_case100_caller) +
            " active_vslot28_actor=" + HexString(g_player_actor_vslot28_actor) +
            " active_vslot28_caller=" + HexString(g_player_actor_vslot28_caller));
    }
    original(self, render_case);
    g_gameplay_hud_case100_depth = previous_depth;
    g_gameplay_hud_case100_owner = previous_owner;
    g_gameplay_hud_case100_caller = previous_caller;
}

bool CallGameplayExactTextObjectRenderSafe(
    uintptr_t string_assign_address,
    uintptr_t text_object_render_address,
    uintptr_t text_object_address,
    const char* text,
    float x,
    float y,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (string_assign_address == 0 || text_object_render_address == 0 || text_object_address == 0 ||
        text == nullptr || text[0] == '\0') {
        return false;
    }

    auto* string_assign = reinterpret_cast<NativeStringAssignFn>(string_assign_address);
    auto* render = reinterpret_cast<NativeExactTextObjectRenderFn>(text_object_render_address);
    NativeGameString native_text{};
    __try {
        string_assign(&native_text, const_cast<char*>(text));
        render(reinterpret_cast<void*>(text_object_address), native_text, x, y);
        string_assign(&native_text, nullptr);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool DrawGameplayHudParticipantName(
    uintptr_t actor_address,
    const std::string& display_name,
    float* draw_x,
    float* draw_y,
    DWORD* exception_code) {
    if (draw_x != nullptr) {
        *draw_x = 0.0f;
    }
    if (draw_y != nullptr) {
        *draw_y = 0.0f;
    }
    if (actor_address == 0 || display_name.empty()) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto string_assign_address = memory.ResolveGameAddressOrZero(kGameplayStringAssign);
    const auto text_object_render_address = memory.ResolveGameAddressOrZero(kGameplayExactTextObjectRender);
    const auto text_object_global_address = memory.ResolveGameAddressOrZero(kGameplayExactTextObjectGlobal);
    if (string_assign_address == 0 ||
        text_object_render_address == 0 ||
        text_object_global_address == 0 ||
        kGameplayNameplateTextObjectOffset == 0 ||
        !memory.IsReadableRange(text_object_global_address, sizeof(uintptr_t))) {
        return false;
    }

    const auto text_object_base = memory.ReadValueOr<uintptr_t>(text_object_global_address, 0);
    if (text_object_base == 0) {
        return false;
    }

    const auto text_object_address = text_object_base + kGameplayNameplateTextObjectOffset;
    if (!memory.IsReadableRange(text_object_address, sizeof(uintptr_t))) {
        return false;
    }

    const auto x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f) - 45.0f;
    if (draw_x != nullptr) {
        *draw_x = x;
    }
    if (draw_y != nullptr) {
        *draw_y = y;
    }

    return CallGameplayExactTextObjectRenderSafe(
        string_assign_address,
        text_object_render_address,
        text_object_address,
        display_name.c_str(),
        x,
        y,
        exception_code);
}

void __fastcall HookActorAnimationAdvance(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<ActorAnimationAdvanceFn>(g_gameplay_keyboard_injection.actor_animation_advance_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    const auto previous_depth = g_player_actor_vslot1c_depth;
    const auto previous_actor = g_player_actor_vslot1c_actor;
    const auto previous_caller = g_player_actor_vslot1c_caller;
    ++g_player_actor_vslot1c_depth;
    g_player_actor_vslot1c_actor = actor_address;
    g_player_actor_vslot1c_caller = reinterpret_cast<uintptr_t>(_ReturnAddress());

    const auto previous_participant_depth = g_gameplay_hud_participant_actor_depth;
    const auto previous_participant_actor = g_gameplay_hud_participant_actor;
    const auto previous_participant_caller = g_gameplay_hud_participant_actor_caller;
    ++g_gameplay_hud_participant_actor_depth;
    g_gameplay_hud_participant_actor = actor_address;
    g_gameplay_hud_participant_actor_caller = g_player_actor_vslot1c_caller;

    static int s_vslot1c_logs_remaining = 24;
    if (s_vslot1c_logs_remaining > 0 && IsTrackedWizardParticipantActorForHud(actor_address)) {
        std::string display_name;
        std::uint64_t participant_id = 0;
        const auto resolved =
            TryGetGameplayHudParticipantDisplayNameForActor(actor_address, &display_name, &participant_id);
        --s_vslot1c_logs_remaining;
        Log(
            "[bots] vslot1c overlay callback. actor=" + HexString(actor_address) +
            " participant=" + std::to_string(participant_id) +
            " resolved=" + std::string(resolved ? "1" : "0") +
            " name=" + display_name +
            " caller=" + HexString(g_player_actor_vslot1c_caller) +
            " hud_case100_depth=" + std::to_string(g_gameplay_hud_case100_depth));
    }

    const bool standalone_wizard_actor =
        TryCaptureTrackedStandaloneWizardBindingIdentity(actor_address, nullptr, nullptr);
    if (standalone_wizard_actor) {
        NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
    }
    original(self);
    if (IsTrackedWizardParticipantActorForHud(actor_address)) {
        std::string display_name;
        std::uint64_t participant_id = 0;
        if (TryGetGameplayHudParticipantDisplayNameForActor(actor_address, &display_name, &participant_id) &&
            !display_name.empty()) {
            DWORD exception_code = 0;
            float draw_x = 0.0f;
            float draw_y = 0.0f;
            const bool drew_label =
                DrawGameplayHudParticipantName(actor_address, display_name, &draw_x, &draw_y, &exception_code);
            static int s_native_hud_name_draw_logs_remaining = 24;
            if (s_native_hud_name_draw_logs_remaining > 0) {
                --s_native_hud_name_draw_logs_remaining;
                Log(
                    "[bots] native gameplay HUD participant name draw. actor=" + HexString(actor_address) +
                    " participant=" + std::to_string(participant_id) +
                    " name=" + display_name +
                    " ok=" + std::string(drew_label ? "1" : "0") +
                    " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
                    " xy=(" + std::to_string(draw_x) + "," + std::to_string(draw_y) + ")");
            }
        }
    }

    g_gameplay_hud_participant_actor_depth = previous_participant_depth;
    g_gameplay_hud_participant_actor = previous_participant_actor;
    g_gameplay_hud_participant_actor_caller = previous_participant_caller;
    g_player_actor_vslot1c_depth = previous_depth;
    g_player_actor_vslot1c_actor = previous_actor;
    g_player_actor_vslot1c_caller = previous_caller;
}

// The loader-owned standalone puppet bot is not registered in the world
// movement controller's primary collider list, so the stock tick never applies
// collision response to it. Replicate a simple circle-vs-circle push here:
// after `pusher_actor_address` ticks, compare its radius-inflated position
// against each tracked standalone puppet and nudge the puppet along the
// separating axis until the radii no longer overlap.
void ApplyStandalonePuppetCollisionPushFromActor(uintptr_t pusher_actor_address) {
    if (pusher_actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto pusher_x =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorPositionXOffset, 0.0f);
    const auto pusher_y =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorPositionYOffset, 0.0f);
    const auto pusher_radius =
        memory.ReadFieldOr<float>(pusher_actor_address, kActorCollisionRadiusOffset, 0.0f);
    if (!std::isfinite(pusher_x) || !std::isfinite(pusher_y) ||
        !std::isfinite(pusher_radius) || pusher_radius <= 0.0f) {
        return;
    }
    const auto pusher_world =
        memory.ReadFieldOr<uintptr_t>(pusher_actor_address, kActorOwnerOffset, 0);

    std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
    for (auto& binding : g_participant_entities) {
        if (binding.actor_address == 0 ||
            binding.actor_address == pusher_actor_address) {
            continue;
        }
        if (!IsStandaloneWizardKind(binding.kind)) {
            continue;
        }
        const auto bot_world =
            memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
        if (pusher_world != 0 && bot_world != 0 && pusher_world != bot_world) {
            continue;
        }
        const auto bot_x =
            memory.ReadFieldOr<float>(binding.actor_address, kActorPositionXOffset, 0.0f);
        const auto bot_y =
            memory.ReadFieldOr<float>(binding.actor_address, kActorPositionYOffset, 0.0f);
        const auto bot_radius =
            memory.ReadFieldOr<float>(binding.actor_address, kActorCollisionRadiusOffset, 0.0f);
        if (!std::isfinite(bot_x) || !std::isfinite(bot_y) ||
            !std::isfinite(bot_radius) || bot_radius <= 0.0f) {
            continue;
        }
        const auto dx = bot_x - pusher_x;
        const auto dy = bot_y - pusher_y;
        const auto min_sep = pusher_radius + bot_radius;
        const auto dist2 = dx * dx + dy * dy;
        if (dist2 >= min_sep * min_sep) {
            continue;
        }
        const auto dist = std::sqrt(dist2);
        float direction_x = 1.0f;
        float direction_y = 0.0f;
        if (dist > 0.0001f) {
            direction_x = dx / dist;
            direction_y = dy / dist;
        }
        const auto pushed_x = pusher_x + direction_x * min_sep;
        const auto pushed_y = pusher_y + direction_y * min_sep;
        (void)memory.TryWriteField(binding.actor_address, kActorPositionXOffset, pushed_x);
        (void)memory.TryWriteField(binding.actor_address, kActorPositionYOffset, pushed_y);

        static std::uint64_t s_last_puppet_push_log_ms = 0;
        const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
        if (now_ms - s_last_puppet_push_log_ms >= 1000) {
            s_last_puppet_push_log_ms = now_ms;
            Log(
                "[bots] pushed standalone puppet. bot_id=" + std::to_string(binding.bot_id) +
                " actor=" + HexString(binding.actor_address) +
                " pusher=" + HexString(pusher_actor_address) +
                " before=(" + std::to_string(bot_x) + "," + std::to_string(bot_y) + ")" +
                " after=(" + std::to_string(pushed_x) + "," + std::to_string(pushed_y) + ")" +
                " overlap=" + std::to_string(min_sep - dist));
        }
    }
}

// The game's scene dispatcher only ticks the player's Skills_Wizard (via a
// global slot at DAT_0081c264+0x1654 in the shipping binary). Bots allocate
// their own Skills_Wizard instance during WizardCloneFromSourceActor but are
// never reached by that dispatcher, so HP/MP regen never fires for them.
// Drive each bot's own Skills_Wizard::Tick (vtable slot 2) from our per-actor
// tick hook so every entity maintains its own stat pool.
void TickBotOwnedSkillsWizard(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    uintptr_t progression_address =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (progression_address == 0) {
        progression_address = ReadSmartPointerInnerObject(
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0));
    }
    if (progression_address == 0) {
        return;
    }
    const auto vtable_address =
        memory.ReadFieldOr<uintptr_t>(progression_address, 0, 0);
    if (vtable_address == 0) {
        return;
    }
    const auto tick_fn_address =
        memory.ReadFieldOr<uintptr_t>(vtable_address, 0x8, 0);
    if (tick_fn_address == 0) {
        return;
    }
    using SkillsWizardTickFn = void(__thiscall*)(void*);
    auto* tick_fn = reinterpret_cast<SkillsWizardTickFn>(tick_fn_address);
    __try {
        tick_fn(reinterpret_cast<void*>(progression_address));
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
}

void __fastcall HookPlayerActorTick(void* self, void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorTickFn>(g_gameplay_keyboard_injection.player_actor_tick_hook);
    if (original == nullptr) {
        return;
    }

    const auto actor_address = reinterpret_cast<uintptr_t>(self);
    uintptr_t gameplay_address_for_pump = 0;
    uintptr_t local_actor_address = 0;
    if (TryResolveCurrentGameplayScene(&gameplay_address_for_pump) &&
        gameplay_address_for_pump != 0 &&
        TryResolvePlayerActorForSlot(gameplay_address_for_pump, 0, &local_actor_address) &&
        local_actor_address == actor_address) {
        MaybeArmLocalPlayerCastProbe(gameplay_address_for_pump, actor_address);
        const auto previous_allow = g_allow_gameplay_action_pump_in_gameplay;
        g_allow_gameplay_action_pump_in_gameplay = true;
        PumpQueuedGameplayActions();
        const SDModRuntimeTickContext lua_tick_context = {
            sizeof(SDModRuntimeTickContext),
            GetRuntimeTickServiceIntervalMs(),
            0,
            static_cast<std::uint64_t>(GetTickCount64()),
        };
        PumpLuaWorkOnGameplayThread(lua_tick_context);
        g_allow_gameplay_action_pump_in_gameplay = previous_allow;
    }

    const bool local_player_actor =
        gameplay_address_for_pump != 0 &&
        local_actor_address != 0 &&
        local_actor_address == actor_address;

    bool standalone_puppet_actor = false;
    bool gameplay_slot_wizard_actor = false;
    bool tracked_actor_moving = false;
    bool tracked_actor_should_restore_desired_heading = false;
    float tracked_actor_desired_heading = 0.0f;
    uintptr_t tracked_actor_world = 0;
    int tracked_actor_slot = -1;
    uintptr_t tracked_actor_progression_runtime = 0;
    uintptr_t tracked_actor_equip_runtime = 0;
    uintptr_t tracked_actor_selection_state = 0;
    bool tracked_actor_runtime_invalid = false;
    bool tracked_actor_dead = false;
    std::string tracked_path_error_message;
    std::string tracked_move_error_message;
    const auto native_tick_now_ms = static_cast<std::uint64_t>(GetTickCount64());
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        if (auto* binding = FindParticipantEntityForActor(actor_address);
            binding != nullptr && IsWizardParticipantKind(binding->kind)) {
            standalone_puppet_actor = IsStandaloneWizardKind(binding->kind);
            gameplay_slot_wizard_actor = IsGameplaySlotWizardKind(binding->kind);
            tracked_actor_dead = IsActorRuntimeDead(actor_address);
            if (tracked_actor_dead) {
                QuiesceDeadWizardBinding(binding);
                StopDeadWizardBotActorMotion(actor_address);
            } else {
                binding->death_transition_stock_tick_seen = false;
                SyncWizardBotMovementIntent(binding);
                if (!UpdateWizardBotPathMotion(binding, native_tick_now_ms, &tracked_path_error_message) &&
                    !tracked_path_error_message.empty()) {
                    Log(
                        "[bots] native tick path update failed. bot_id=" + std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + tracked_path_error_message);
                    tracked_path_error_message.clear();
                }
            }
            tracked_actor_moving = binding->movement_active;
            tracked_actor_should_restore_desired_heading =
                !tracked_actor_dead &&
                binding->movement_active &&
                binding->desired_heading_valid &&
                binding->controller_state != multiplayer::BotControllerState::Attacking;
            tracked_actor_desired_heading = binding->desired_heading;
            tracked_actor_slot = static_cast<int>(ProcessMemory::Instance().ReadFieldOr<std::int8_t>(
                actor_address,
                kActorSlotOffset,
                static_cast<std::int8_t>(-1)));
            tracked_actor_world = ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                actor_address,
                kActorOwnerOffset,
                binding->materialized_world_address);
            tracked_actor_progression_runtime =
                ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorProgressionRuntimeStateOffset,
                    0);
            tracked_actor_equip_runtime =
                ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorEquipRuntimeStateOffset,
                    0);
            tracked_actor_selection_state =
                ProcessMemory::Instance().ReadFieldOr<uintptr_t>(
                    actor_address,
                    kActorAnimationSelectionStateOffset,
                    0);
            if (binding->materialized_world_address != tracked_actor_world) {
                Log(
                    "[bots] tracked actor owner changed. bot_id=" + std::to_string(binding->bot_id) +
                    " actor=" + HexString(actor_address) +
                    " kind=" + std::to_string(static_cast<int>(binding->kind)) +
                    " old_world=" + HexString(binding->materialized_world_address) +
                    " new_world=" + HexString(tracked_actor_world));
            }
            if (tracked_actor_world != 0 &&
                binding->materialized_world_address != tracked_actor_world) {
                binding->materialized_world_address = tracked_actor_world;
            }
            tracked_actor_runtime_invalid =
                binding->materialized_world_address != 0 &&
                (tracked_actor_world == 0 ||
                 tracked_actor_slot < 0 ||
                 (tracked_actor_progression_runtime == 0 &&
                  tracked_actor_equip_runtime == 0 &&
                  tracked_actor_selection_state == 0));
        }
    }

    if ((standalone_puppet_actor || gameplay_slot_wizard_actor) && tracked_actor_runtime_invalid) {
        Log(
            "[bots] tracked actor invalidated out-of-band. actor=" + HexString(actor_address) +
            " kind=" + std::to_string(static_cast<int>(
                gameplay_slot_wizard_actor
                    ? ParticipantEntityBinding::Kind::GameplaySlotWizard
                    : ParticipantEntityBinding::Kind::StandaloneWizard)) +
            " live_owner=" + HexString(tracked_actor_world) +
            " live_slot=" + std::to_string(tracked_actor_slot) +
            " live_progression=" + HexString(tracked_actor_progression_runtime) +
            " live_equip=" + HexString(tracked_actor_equip_runtime) +
            " live_selection=" + HexString(tracked_actor_selection_state));
        MarkParticipantEntityWorldUnregistered(actor_address);
        return;
    }

    auto& memory = ProcessMemory::Instance();
    auto RunStockTick = [&](ParticipantEntityBinding* binding) {
        if (binding == nullptr) {
            original(self);
            return;
        }

        uintptr_t gameplay_address = 0;
        std::uint8_t saved_cast_intent = 0;
        std::uint8_t saved_mouse_left = 0;
        std::size_t live_mouse_left_offset = 0;
        bool synthetic_cast_intent_applied = false;
        bool synthetic_mouse_left_applied = false;
        LocalPlayerCastShimState stock_tick_shim_state;
        bool stock_tick_shim_active = false;
        std::uint8_t saved_global_1abe_for_stock_tick = 0;
        bool global_1abe_zeroed_for_stock_tick = false;
        PurePrimaryLocalActorWindowShim pure_primary_actor_window_shim{};
        // Press the stock cast gate for startup, and keep it held for continuous
        // pure primaries whose damage hitbox only runs while input is down.
        // Aim is refreshed before stock tick, so held input does not freeze the
        // first target sample.
        const bool drive_stock_cast_input =
            binding->ongoing_cast.active &&
            OngoingCastShouldDriveSyntheticCastInput(binding->ongoing_cast);
        const bool apply_local_slot_for_native_tick =
            binding->ongoing_cast.active &&
            (binding->ongoing_cast.startup_in_progress ||
             binding->ongoing_cast.requires_local_slot_native_tick);
        const bool pure_primary_stock_shim =
            apply_local_slot_for_native_tick &&
            binding->ongoing_cast.lane == ParticipantEntityBinding::OngoingCastState::Lane::PurePrimary;
        const bool refresh_selection_target_for_stock_tick =
            apply_local_slot_for_native_tick &&
            OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast) &&
            binding->ongoing_cast.selection_target_seed_active;
        if (drive_stock_cast_input &&
            TryResolveCurrentGameplayScene(&gameplay_address) &&
            gameplay_address != 0) {
            saved_cast_intent = memory.ReadFieldOr<std::uint8_t>(
                gameplay_address,
                kGameplayCastIntentOffset,
                0);
            synthetic_cast_intent_applied =
                memory.TryWriteField<std::uint8_t>(
                    gameplay_address,
                    kGameplayCastIntentOffset,
                    static_cast<std::uint8_t>(1));
            const auto input_buffer_index =
                memory.ReadFieldOr<int>(gameplay_address, kGameplayInputBufferIndexOffset, -1);
            if (input_buffer_index >= 0) {
                live_mouse_left_offset =
                    static_cast<std::size_t>(
                        input_buffer_index * kGameplayInputBufferStride +
                        kGameplayMouseLeftButtonOffset);
                saved_mouse_left = memory.ReadFieldOr<std::uint8_t>(
                    gameplay_address,
                    live_mouse_left_offset,
                    0);
                synthetic_mouse_left_applied =
                    memory.TryWriteField<std::uint8_t>(
                        gameplay_address,
                        live_mouse_left_offset,
                        static_cast<std::uint8_t>(1));
            } else {
                live_mouse_left_offset = kGameplayMouseLeftButtonOffset;
                saved_mouse_left = memory.ReadFieldOr<std::uint8_t>(
                    gameplay_address,
                    live_mouse_left_offset,
                    0);
                synthetic_mouse_left_applied =
                    memory.TryWriteField<std::uint8_t>(
                        gameplay_address,
                        live_mouse_left_offset,
                        static_cast<std::uint8_t>(1));
            }
        }
        if (apply_local_slot_for_native_tick) {
            stock_tick_shim_active = EnterLocalPlayerCastShim(binding, &stock_tick_shim_state);
            if (pure_primary_stock_shim) {
                const auto global_1abe_address =
                    memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABE);
                saved_global_1abe_for_stock_tick =
                    memory.ReadValueOr<std::uint8_t>(global_1abe_address, 0);
                if (global_1abe_address != 0 && saved_global_1abe_for_stock_tick != 0) {
                    global_1abe_zeroed_for_stock_tick =
                        memory.TryWriteValue<std::uint8_t>(
                            global_1abe_address,
                            0);
                }
                pure_primary_actor_window_shim =
                    EnterPurePrimaryLocalActorWindow(actor_address);
            }
        }
        if (refresh_selection_target_for_stock_tick) {
            RefreshSelectionBrainTargetForOngoingCast(binding->ongoing_cast);
        }
        if (binding->ongoing_cast.active &&
            binding->ongoing_cast.uses_dispatcher_skill_id &&
            OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
            ReapplyOngoingCastSelectionState(binding, actor_address, binding->ongoing_cast, true);
        }
        original(self);
        LeavePurePrimaryLocalActorWindow(actor_address, pure_primary_actor_window_shim);
        if (refresh_selection_target_for_stock_tick) {
            RefreshSelectionBrainTargetForOngoingCast(binding->ongoing_cast);
        }
        if (global_1abe_zeroed_for_stock_tick) {
            (void)memory.TryWriteValue<std::uint8_t>(
                memory.ResolveGameAddressOrZero(0x0081C264 + 0x1ABE),
                saved_global_1abe_for_stock_tick);
        }
        if (stock_tick_shim_active) {
            LeaveLocalPlayerCastShim(stock_tick_shim_state);
        }

        if (synthetic_cast_intent_applied) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address,
                kGameplayCastIntentOffset,
                saved_cast_intent);
        }
        if (synthetic_mouse_left_applied) {
            (void)memory.TryWriteField<std::uint8_t>(
                gameplay_address,
                live_mouse_left_offset,
                saved_mouse_left);
        }
        if (synthetic_cast_intent_applied) {
            static std::uint64_t s_last_synthetic_cast_intent_log_ms = 0;
            if (native_tick_now_ms - s_last_synthetic_cast_intent_log_ms >= 250) {
                s_last_synthetic_cast_intent_log_ms = native_tick_now_ms;
                Log(
                    "[bots] gameplay-slot synthetic cast intent. actor=" +
                    HexString(actor_address) +
                    " gameplay=" + HexString(gameplay_address) +
                    " mouse_left=" + (synthetic_mouse_left_applied ? std::string("1") : std::string("0")) +
                    " gameplay_slot=" + std::to_string(binding->gameplay_slot));
            }
        }
    };

    if (standalone_puppet_actor) {
        static std::uint64_t s_last_native_bot_tick_log_ms = 0;
        if (native_tick_now_ms - s_last_native_bot_tick_log_ms >= 1000) {
            s_last_native_bot_tick_log_ms = native_tick_now_ms;
            Log(
                "[bots] native bot tick. actor=" + HexString(actor_address) +
                " moving=" + std::to_string(tracked_actor_moving ? 1 : 0) +
                " desired_heading=" + std::to_string(tracked_actor_desired_heading));
        }
        const auto position_before_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_before_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto heading_before =
            memory.ReadFieldOr<float>(actor_address, kActorHeadingOffset, 0.0f);

        if (tracked_actor_dead) {
            bool run_stock_death_transition = false;
            {
                std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
                if (auto* binding = FindParticipantEntityForActor(actor_address);
                    binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                    std::string cast_error_message;
                    QuiesceDeadWizardBinding(binding);
                    StopDeadWizardBotActorMotion(actor_address);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    run_stock_death_transition = !binding->death_transition_stock_tick_seen;
                    binding->death_transition_stock_tick_seen = true;
                    PublishParticipantGameplaySnapshot(*binding);
                }
            }
            if (run_stock_death_transition) {
                original(self);
                (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
                (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
                StopDeadWizardBotActorMotion(actor_address);
                std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
                if (auto* binding = FindParticipantEntityForActor(actor_address);
                    binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                    PublishParticipantGameplaySnapshot(*binding);
                }
            }
            return;
        }

        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            tracked_actor_world,
            "player_tick",
            nullptr);
        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                ApplyStandaloneWizardAnimationDriveProfile(
                    binding,
                    actor_address,
                    tracked_actor_moving);
                ApplyStandaloneWizardPuppetDriveState(
                    binding,
                    actor_address,
                    tracked_actor_moving);
                if (!binding->ongoing_cast.active) {
                    ClearLiveWizardActorAnimationDriveState(actor_address);
                } else {
                    if (OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                        (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
                    }
                }
                (void)RefreshWizardBindingTargetFacing(binding);
                (void)ApplyWizardBindingFacingState(binding, actor_address);
            }
        }
        original(self);

        const auto position_after_stock_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, position_before_x);
        const auto position_after_stock_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, position_before_y);
        const auto stock_delta_x = position_after_stock_x - position_before_x;
        const auto stock_delta_y = position_after_stock_y - position_before_y;
        const auto stock_displacement =
            std::sqrt((stock_delta_x * stock_delta_x) + (stock_delta_y * stock_delta_y));
        if (stock_displacement > 0.01f) {
            static std::uint64_t s_last_stock_position_drift_log_ms = 0;
            if (native_tick_now_ms - s_last_stock_position_drift_log_ms >= 1000) {
                s_last_stock_position_drift_log_ms = native_tick_now_ms;
                Log(
                    "[bots] standalone stock tick rewrote actor position. actor=" +
                    HexString(actor_address) +
                    " before=(" + std::to_string(position_before_x) + ", " +
                        std::to_string(position_before_y) + ")" +
                    " stock_after=(" + std::to_string(position_after_stock_x) + ", " +
                        std::to_string(position_after_stock_y) + ")" +
                    " moving=" + std::to_string(tracked_actor_moving ? 1 : 0));
            }
        }

        // Standalone clone-rail actor position is loader-owned. Live probes
        // showed stock PlayerActorTick continuing to move idle clones whenever
        // stale +0x158/+0x15C walk accumulators were left behind, which caused
        // the visible "sliding" regression. Always discard the stock tick's
        // position write here, then apply only loader-owned movement and
        // explicit collision-push logic below.
        (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
        (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);

        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsStandaloneWizardKind(binding->kind)) {
                if (tracked_actor_dead) {
                    std::string cast_error_message;
                    QuiesceDeadWizardBinding(binding);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    PublishParticipantGameplaySnapshot(*binding);
                    return;
                }
                if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                    !tracked_move_error_message.empty()) {
                    Log(
                        "[bots] native tick movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + tracked_move_error_message);
                    tracked_move_error_message.clear();
                }
                // Movement step contributes to facing first. Cast (below) runs
                // after and overrides when both fire on the same tick, making
                // attack direction take priority over movement direction.
                if (tracked_actor_should_restore_desired_heading && !binding->facing_heading_valid) {
                    binding->facing_heading_value = tracked_actor_desired_heading;
                    binding->facing_heading_valid = true;
                }
                std::string cast_error_message;
                (void)ProcessPendingBotCast(binding, &cast_error_message);
                (void)RefreshWizardBindingTargetFacing(binding);
                if (!ApplyWizardBindingFacingState(binding, actor_address)) {
                    ApplyWizardActorFacingState(actor_address, heading_before);
                }
                if (!binding->ongoing_cast.active) {
                    const bool moved_this_tick =
                        binding->movement_active && binding->last_movement_displacement > 0.0001f;
                    if (moved_this_tick) {
                        ApplyObservedBotAnimationState(binding, actor_address, true);
                    } else {
                        StopWizardBotActorMotion(actor_address);
                        (void)ApplyWizardBindingFacingState(binding, actor_address);
                    }
                }
                PublishParticipantGameplaySnapshot(*binding);
            }
        }
        NormalizeGameplaySlotBotSyntheticVisualState(actor_address);
        ApplyStandalonePuppetCollisionPushFromActor(actor_address);
        TickBotOwnedSkillsWizard(actor_address);
        return;
    }

    if (gameplay_slot_wizard_actor) {
        const auto position_before_x =
            memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_before_y =
            memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        auto position_after_stock_x = position_before_x;
        auto position_after_stock_y = position_before_y;

        {
            std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
            if (auto* binding = FindParticipantEntityForActor(actor_address);
                binding != nullptr && IsGameplaySlotWizardKind(binding->kind)) {
                std::string cast_error_message;
                binding->stock_tick_facing_origin_valid = true;
                binding->stock_tick_facing_origin_x = position_before_x;
                binding->stock_tick_facing_origin_y = position_before_y;
                if (tracked_actor_dead) {
                    const bool run_stock_death_transition = !binding->death_transition_stock_tick_seen;
                    QuiesceDeadWizardBinding(binding);
                    StopDeadWizardBotActorMotion(actor_address);
                    (void)ProcessPendingBotCast(binding, &cast_error_message);
                    binding->death_transition_stock_tick_seen = true;
                    if (run_stock_death_transition) {
                        RunStockTick(binding);
                        (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
                        (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
                        StopDeadWizardBotActorMotion(actor_address);
                    }
                    if (!cast_error_message.empty()) {
                        Log(
                            "[bots] gameplay-slot dead cast cleanup detail. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + cast_error_message);
                    }
                    PublishParticipantGameplaySnapshot(*binding);
                    return;
                }
                if (!binding->ongoing_cast.active) {
                    (void)PreparePendingGameplaySlotBotCast(binding, &cast_error_message);
                    if (!cast_error_message.empty()) {
                        Log(
                            "[bots] gameplay-slot cast prepare failed. bot_id=" +
                            std::to_string(binding->bot_id) +
                            " actor=" + HexString(actor_address) +
                            " error=" + cast_error_message);
                        cast_error_message.clear();
                    }
                } else {
                    if (OngoingCastShouldRefreshNativeTargetState(binding->ongoing_cast)) {
                        (void)RefreshOngoingCastAimFromFacingTarget(binding, &binding->ongoing_cast);
                    }
                }
                if (!binding->ongoing_cast.active) {
                    ResetStandaloneWizardControlBrain(actor_address);
                }
                (void)RefreshWizardBindingTargetFacing(binding);
                (void)ApplyWizardBindingFacingState(binding, actor_address);
                RunStockTick(binding);
                position_after_stock_x =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, position_before_x);
                position_after_stock_y =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, position_before_y);
                // Gameplay-slot bots still run through the stock player-family
                // tick, but the loader owns their transform just like the
                // standalone clone rail. Restore pre-stock position before the
                // loader-owned path/move step reads actor coordinates.
                (void)memory.TryWriteField(actor_address, kActorPositionXOffset, position_before_x);
                (void)memory.TryWriteField(actor_address, kActorPositionYOffset, position_before_y);
                if (!ApplyWizardBotMovementStep(binding, &tracked_move_error_message) &&
                    !tracked_move_error_message.empty()) {
                    Log(
                        "[bots] gameplay-slot movement step failed. bot_id=" + std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + tracked_move_error_message);
                    tracked_move_error_message.clear();
                }
                binding->stock_tick_facing_origin_valid = true;
                binding->stock_tick_facing_origin_x =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, position_before_x);
                binding->stock_tick_facing_origin_y =
                    memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, position_before_y);
                if (binding->movement_active &&
                    tracked_actor_should_restore_desired_heading &&
                    !binding->facing_heading_valid) {
                    binding->facing_heading_value = tracked_actor_desired_heading;
                    binding->facing_heading_valid = true;
                }
                (void)ProcessPendingBotCast(binding, &cast_error_message);
                if (!binding->ongoing_cast.active) {
                    ResetStandaloneWizardControlBrain(actor_address);
                }
                (void)RefreshWizardBindingTargetFacing(binding);
                if (!cast_error_message.empty()) {
                    Log(
                        "[bots] gameplay-slot cast post-tick detail. bot_id=" +
                        std::to_string(binding->bot_id) +
                        " actor=" + HexString(actor_address) +
                        " error=" + cast_error_message);
                }
                if (!binding->ongoing_cast.active) {
                    const bool moved_this_tick =
                        binding->movement_active && binding->last_movement_displacement > 0.0001f;
                    if (moved_this_tick) {
                        ApplyActorAnimationDriveState(actor_address, true);
                    } else {
                        StopWizardBotActorMotion(actor_address);
                    }
                }
                (void)ApplyWizardBindingFacingState(binding, actor_address);
                PublishParticipantGameplaySnapshot(*binding);
            }
        }
        const auto stock_delta_x = position_after_stock_x - position_before_x;
        const auto stock_delta_y = position_after_stock_y - position_before_y;
        const auto stock_displacement =
            std::sqrt((stock_delta_x * stock_delta_x) + (stock_delta_y * stock_delta_y));
        if (stock_displacement > 0.01f) {
            static std::uint64_t s_last_gameplay_slot_stock_position_drift_log_ms = 0;
            if (native_tick_now_ms - s_last_gameplay_slot_stock_position_drift_log_ms >= 1000) {
                s_last_gameplay_slot_stock_position_drift_log_ms = native_tick_now_ms;
                Log(
                    "[bots] gameplay-slot stock tick rewrote actor position. actor=" +
                    HexString(actor_address) +
                    " before=(" + std::to_string(position_before_x) + ", " +
                        std::to_string(position_before_y) + ")" +
                    " stock_after=(" + std::to_string(position_after_stock_x) + ", " +
                        std::to_string(position_after_stock_y) + ")" +
                    " moving=" + std::to_string(tracked_actor_moving ? 1 : 0));
            }
        }
        ApplyStandalonePuppetCollisionPushFromActor(actor_address);
        TickBotOwnedSkillsWizard(actor_address);
        return;
    }

    if (local_player_actor) {
        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, false);
    }
    original(self);
    if (local_player_actor) {
        MaybeLogLocalPlayerCastProbe(gameplay_address_for_pump, actor_address, true);
    }
    ApplyStandalonePuppetCollisionPushFromActor(actor_address);
    if (memory.ReadFieldOr<std::int8_t>(actor_address, kActorSlotOffset, static_cast<std::int8_t>(-1)) == 0) {
        TickParticipantSceneBindingsIfActive();
    }
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
