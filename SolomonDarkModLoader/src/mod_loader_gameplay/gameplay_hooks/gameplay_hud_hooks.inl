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

    struct HudCase100ContextScope {
        int previous_depth = 0;
        uintptr_t previous_owner = 0;
        uintptr_t previous_caller = 0;

        HudCase100ContextScope(uintptr_t owner, uintptr_t caller)
            : previous_depth(g_gameplay_hud_case100_depth),
              previous_owner(g_gameplay_hud_case100_owner),
              previous_caller(g_gameplay_hud_case100_caller) {
            ++g_gameplay_hud_case100_depth;
            g_gameplay_hud_case100_owner = owner;
            g_gameplay_hud_case100_caller = caller;
        }

        ~HudCase100ContextScope() {
            g_gameplay_hud_case100_depth = previous_depth;
            g_gameplay_hud_case100_owner = previous_owner;
            g_gameplay_hud_case100_caller = previous_caller;
        }
    } context_scope(
        reinterpret_cast<uintptr_t>(self),
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    if constexpr (kEnableWizardBotHotPathDiagnostics) {
        if (static_cast<std::uint64_t>(GetTickCount64()) <= g_gameplay_slot_hud_probe_until_ms) {
            Log(
                "[bots] hud_probe case100 owner=" + HexString(g_gameplay_hud_case100_owner) +
                " caller=" + HexString(g_gameplay_hud_case100_caller) +
                " active_vslot28_actor=" + HexString(g_player_actor_vslot28_actor) +
                " active_vslot28_caller=" + HexString(g_player_actor_vslot28_caller));
        }
    }
    original(self, render_case);
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
    bool assigned = false;
    __try {
        string_assign(&native_text, const_cast<char*>(text));
        assigned = true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }

    bool rendered = false;
    __try {
        render(reinterpret_cast<void*>(text_object_address), native_text, x, y);
        rendered = true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        rendered = false;
    }

    if (assigned) {
        DWORD cleanup_exception_code = 0;
        __try {
            string_assign(&native_text, nullptr);
        } __except (CaptureSehCode(GetExceptionInformation(), &cleanup_exception_code)) {
            if (exception_code != nullptr && *exception_code == 0) {
                *exception_code = cleanup_exception_code;
            }
            return false;
        }
    }

    if (rendered) {
        if (exception_code != nullptr) {
            *exception_code = 0;
        }
        return true;
    }
    return false;
}

std::string BuildGameplayNameplateExactText(const std::string& display_name) {
    constexpr char kExactTextCommandPrefix = '_';
    constexpr const char* kHalfScaleCommand = "s(0.5)";

    std::string text;
    text.reserve(display_name.size() + 7);
    text.push_back(kExactTextCommandPrefix);
    text += kHalfScaleCommand;
    text += display_name;
    return text;
}

float EstimateGameplayNameplateTextWidth(std::string_view display_name) {
    constexpr float kHalfScale = 0.5f;
    // ExactText consumes scene coordinates; these advances were measured from
    // live half-scale participant nameplate captures.
    constexpr float kNativeGlyphAdvance = 16.0f;
    constexpr float kNativeSpaceAdvance = 8.0f;

    float width = 0.0f;
    for (const unsigned char ch : display_name) {
        width += std::isspace(ch) ? kNativeSpaceAdvance : kNativeGlyphAdvance;
    }
    return width * kHalfScale;
}

float CalculateGameplayNameplateDrawX(float actor_x, std::string_view display_name) {
    return actor_x - (EstimateGameplayNameplateTextWidth(display_name) * 0.5f);
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
        kGameplayExactTextObjectOffset == 0 ||
        !memory.IsReadableRange(text_object_global_address, sizeof(uintptr_t))) {
        return false;
    }

    uintptr_t text_object_base = 0;
    if (!memory.TryReadValue(text_object_global_address, &text_object_base) ||
        text_object_base == 0) {
        return false;
    }

    const auto text_object_address = text_object_base + kGameplayExactTextObjectOffset;
    if (!memory.IsReadableRange(text_object_address, sizeof(uintptr_t))) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y)) {
        return false;
    }
    y -= 45.0f;
    x = CalculateGameplayNameplateDrawX(x, display_name);
    if (draw_x != nullptr) {
        *draw_x = x;
    }
    if (draw_y != nullptr) {
        *draw_y = y;
    }

    const auto nameplate_text = BuildGameplayNameplateExactText(display_name);
    return CallGameplayExactTextObjectRenderSafe(
        string_assign_address,
        text_object_render_address,
        text_object_address,
        nameplate_text.c_str(),
        x,
        y,
        exception_code);
}
