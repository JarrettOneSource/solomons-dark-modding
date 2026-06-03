void DrawGameplayHudParticipantNameplates();

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
    if (context_scope.previous_depth == 0) {
        DrawGameplayHudParticipantNameplates();
    }
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

bool TryProjectGameplayHudNameplatePosition(
    uintptr_t actor_address,
    float actor_x,
    float actor_y,
    float* draw_x,
    float* draw_y) {
    if (draw_x == nullptr || draw_y == nullptr || actor_address == 0) {
        return false;
    }

    constexpr float kGameplayHudVirtualWidth = 1600.0f;
    constexpr float kGameplayHudVirtualHeight = 900.0f;
    constexpr float kNameplateVerticalOffset = 45.0f;

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid ||
        scene_state.kind != "arena") {
        *draw_x = actor_x;
        *draw_y = actor_y - kNameplateVerticalOffset;
        return true;
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid ||
        !std::isfinite(player_state.x) || !std::isfinite(player_state.y)) {
        return false;
    }

    // Arena actor coordinates are world-space, while the exact-text HUD render
    // helper consumes virtual screen coordinates. Hub coordinates are already
    // screen-sized, so only arena labels need the local camera-centered projection.
    *draw_x = (kGameplayHudVirtualWidth * 0.5f) + (actor_x - player_state.x);
    *draw_y =
        (kGameplayHudVirtualHeight * 0.5f) +
        (actor_y - player_state.y) -
        kNameplateVerticalOffset;
    return std::isfinite(*draw_x) && std::isfinite(*draw_y);
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

    uintptr_t text_object_base = 0;
    if (!memory.TryReadValue(text_object_global_address, &text_object_base)) {
        return false;
    }
    if (text_object_base == 0) {
        return false;
    }

    const auto text_object_address = text_object_base + kGameplayNameplateTextObjectOffset;
    if (!memory.IsReadableRange(text_object_address, sizeof(uintptr_t))) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y)) {
        return false;
    }
    if (!TryProjectGameplayHudNameplatePosition(actor_address, x, y, &x, &y)) {
        return false;
    }
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

struct NameplateDrawDepthScope {
    int& depth;

    explicit NameplateDrawDepthScope(int& active_depth) : depth(active_depth) {
        ++depth;
    }

    ~NameplateDrawDepthScope() {
        --depth;
    }
};

void DrawGameplayHudParticipantNameplates() {
    static thread_local int s_nameplate_draw_depth = 0;
    if (s_nameplate_draw_depth != 0) {
        return;
    }

    struct NameplateCandidate {
        uintptr_t actor_address = 0;
        std::uint64_t participant_id = 0;
    };

    std::vector<NameplateCandidate> candidates;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        candidates.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind) || binding.actor_address == 0) {
                continue;
            }
            candidates.push_back(NameplateCandidate{binding.actor_address, binding.bot_id});
        }
    }
    if (candidates.empty()) {
        return;
    }

    const auto runtime = multiplayer::SnapshotRuntimeState();
    NameplateDrawDepthScope depth_scope(s_nameplate_draw_depth);
    for (const auto& candidate : candidates) {
        const auto* participant = multiplayer::FindParticipant(runtime, candidate.participant_id);
        if (participant == nullptr ||
            !multiplayer::IsRemoteParticipant(*participant) ||
            participant->name.empty()) {
            continue;
        }

        DWORD exception_code = 0;
        float draw_x = 0.0f;
        float draw_y = 0.0f;
        const bool drew_label =
            DrawGameplayHudParticipantName(
                candidate.actor_address,
                participant->name,
                &draw_x,
                &draw_y,
                &exception_code);
        if constexpr (kEnableWizardBotHotPathDiagnostics) {
            static int s_native_hud_name_draw_logs_remaining = 24;
            if (s_native_hud_name_draw_logs_remaining > 0) {
                --s_native_hud_name_draw_logs_remaining;
                Log(
                    "[bots] native gameplay HUD participant name draw. actor=" +
                    HexString(candidate.actor_address) +
                    " participant=" + std::to_string(candidate.participant_id) +
                    " name=" + participant->name +
                    " ok=" + std::string(drew_label ? "1" : "0") +
                    " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
                    " xy=(" + std::to_string(draw_x) + "," + std::to_string(draw_y) + ")");
            }
        }
    }
}
