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
