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
