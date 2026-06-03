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
    bool startup = false;
    bool pure_primary_startup = false;
    bool local_player = false;
};

SpellDispatchProbeState g_spell_dispatch_probe = {};
std::int32_t g_spell_action_builder_global_log_budget = 16;
std::int32_t g_pure_primary_control_log_budget = 32;
std::int32_t g_pure_primary_post_builder_log_budget = 64;
void* g_pure_primary_post_builder_trampoline = nullptr;

void __cdecl OnPurePrimaryPostBuilder(uintptr_t builder_result) {
    const auto probe = g_spell_dispatch_probe;
    if (!probe.pure_primary_startup || probe.actor_address == 0 ||
        g_pure_primary_post_builder_log_budget <= 0) {
        return;
    }
    --g_pure_primary_post_builder_log_budget;

    Log(
        "[bots] pure_primary_post_builder actor=" + HexString(probe.actor_address) +
        " bot_id=" + std::to_string(probe.bot_id) +
        " builder_result=" + HexString(builder_result) +
        " result_type=" + ReadU32FieldHexText(builder_result, kGameObjectTypeIdOffset) +
        " result_f34=" + ReadFloatValueText(builder_result + kSpellBuilderResultParamAOffset) +
        " result_f38=" + ReadFloatValueText(builder_result + kSpellBuilderResultParamBOffset) +
        " active_cast_group=" + ReadU8FieldHexText(probe.actor_address, kActorActiveCastGroupByteOffset) +
        " active_cast_slot=" + ReadU16FieldHexText(probe.actor_address, kActorActiveCastSlotShortOffset) +
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

bool TryReadGameplayMouseLeftLiveByte(uintptr_t gameplay_address, std::uint8_t* value) {
    if (value != nullptr) {
        *value = 0;
    }
    if (gameplay_address == 0 || value == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    int input_buffer_index = 0;
    if (!memory.TryReadField(gameplay_address, kGameplayInputBufferIndexOffset, &input_buffer_index)) {
        return false;
    }
    if (input_buffer_index < 0) {
        return memory.TryReadField(gameplay_address, kGameplayMouseLeftButtonOffset, value);
    }

    const auto live_mouse_left_offset =
        static_cast<std::size_t>(
            input_buffer_index * kGameplayInputBufferStride + kGameplayMouseLeftButtonOffset);
    return memory.TryReadField(gameplay_address, live_mouse_left_offset, value);
}

std::string DescribeLocalPlayerCastProbeState(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    const char* phase) {
    auto& memory = ProcessMemory::Instance();
    std::uint8_t gameplay_mouse_left = 0;
    const bool have_gameplay_mouse_left =
        TryReadGameplayMouseLeftLiveByte(gameplay_address, &gameplay_mouse_left);
    const auto click_serial = GetGameplayMouseLeftEdgeSerial();
    const auto click_tick_ms = GetGameplayMouseLeftEdgeTickMs();
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    const auto click_age_ms =
        click_tick_ms != 0 && now_ms >= click_tick_ms ? (now_ms - click_tick_ms) : 0;

    int slot0_selection_state = kUnknownAnimationStateId;
    (void)TryReadGameplayIndexStateValue(
        static_cast<int>(kGameplayIndexStateActorSelectionBaseIndex),
        &slot0_selection_state);
    int slot0_selection_global = kUnknownAnimationStateId;
    (void)TryReadResolvedGlobalInt(kPlayerSelectionState0Global, &slot0_selection_global);
    const auto actor_selection_state = ResolveActorAnimationStateId(actor_address);
    uintptr_t progression_handle = 0;
    const bool have_progression_handle =
        memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle);
    const auto progression_runtime =
        have_progression_handle ? ReadSmartPointerInnerObject(progression_handle) : 0;

    return
        "phase=" + std::string(phase) +
        " gameplay=" + HexString(gameplay_address) +
        " cast_intent=" + ReadU32FieldHexText(gameplay_address, kGameplayCastIntentOffset) +
        " mouse_left=" + (have_gameplay_mouse_left
            ? HexString(gameplay_mouse_left)
            : UnreadableMemoryFieldText()) +
        " click_serial=" + std::to_string(click_serial) +
        " click_age_ms=" + std::to_string(click_age_ms) +
        " actor=" + HexString(actor_address) +
        " progression_runtime=" + ReadPointerFieldText(actor_address, kActorProgressionRuntimeStateOffset) +
        " animation_selection=" + ReadPointerFieldText(actor_address, kActorAnimationSelectionStateOffset) +
        " skill=" + ReadI32FieldText(actor_address, kActorPrimarySkillIdOffset) +
        " prev=" + ReadI32FieldText(actor_address, kActorPreviousSkillIdOffset) +
        " drive=" + ReadU8FieldHexText(actor_address, kActorAnimationDriveStateByteOffset) +
        " no_int=" + ReadU8FieldHexText(actor_address, kActorNoInterruptFlagOffset) +
        " group=" + ReadU8FieldHexText(actor_address, kActorActiveCastGroupByteOffset) +
        " cast_slot=" + ReadU16FieldHexText(actor_address, kActorActiveCastSlotShortOffset) +
        " anim_state=" + std::to_string(actor_selection_state) +
        " slot0_sel=" + std::to_string(slot0_selection_state) +
        " slot0_global=" + std::to_string(slot0_selection_global) +
        " selection_ptr=" + ReadPointerFieldText(actor_address, kActorAnimationSelectionStateOffset) +
        " progression_handle=" + (have_progression_handle ? HexString(progression_handle) : UnreadableMemoryFieldText()) +
        " progression_runtime=" + HexString(progression_runtime) +
        " prog750=" + ReadU32ValueHexText(progression_runtime + kProgressionCurrentSpellIdOffset);
}

void MaybeArmLocalPlayerCastProbe(uintptr_t gameplay_address, uintptr_t actor_address) {
    if constexpr (!kEnableLocalPlayerCastProbeDiagnostics) {
        return;
    }
    if (gameplay_address == 0 || actor_address == 0) {
        return;
    }

    std::uint32_t gameplay_cast_intent = 0;
    const bool have_gameplay_cast_intent = ProcessMemory::Instance().TryReadField(
        gameplay_address,
        kGameplayCastIntentOffset,
        &gameplay_cast_intent);
    const auto click_serial = GetGameplayMouseLeftEdgeSerial();

    if (!have_gameplay_cast_intent || (gameplay_cast_intent == 0 && click_serial == 0)) {
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
    if constexpr (!kEnableLocalPlayerCastProbeDiagnostics) {
        return;
    }
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
