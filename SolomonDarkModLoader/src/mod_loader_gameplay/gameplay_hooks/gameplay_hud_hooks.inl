bool DrawGameplayHudExactTextAt(
    const std::string& display_text,
    float x,
    float y,
    DWORD* exception_code);

void __fastcall HookGameplayHudRenderDispatch(
    void* self,
    void* /*unused_edx*/,
    int render_case,
    uintptr_t arg1,
    uintptr_t arg2) {
    const auto original = GetX86HookTrampoline<GameplayHudRenderDispatchFn>(
        g_gameplay_keyboard_injection.gameplay_hud_render_dispatch_hook);
    if (original != nullptr) {
        original(self, render_case, arg1, arg2);
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

std::string BuildGameplayAllyHudExactText(const std::string& display_name) {
    constexpr char kExactTextCommandPrefix = '_';
    constexpr const char* kQuarterScaleCommand = "s(0.25)";

    std::string text;
    text.reserve(display_name.size() + 8);
    text.push_back(kExactTextCommandPrefix);
    text += kQuarterScaleCommand;
    text += display_name;
    return text;
}

struct GameplayAllyHudRow {
    int gameplay_slot = -1;
    std::uint64_t participant_id = 0;
    std::string display_name;
    float hp_ratio = 0.0f;
};

constexpr float kGameplayAllyHudReservedLabelWidth = 128.0f;
constexpr float kGameplayAllyHudNameHorizontalPadding = 2.0f;
constexpr float kGameplayAllyHudLabelBaselineOffset = 7.0f;
constexpr float kGameplayAllyHudGlyphAdvance = 4.0f;
constexpr float kGameplayAllyHudSpaceAdvance = 2.0f;
static_assert(
    (static_cast<float>(multiplayer::kParticipantDisplayNameBytes - 1) *
        kGameplayAllyHudGlyphAdvance) +
        (kGameplayAllyHudNameHorizontalPadding * 2.0f) <=
        kGameplayAllyHudReservedLabelWidth,
    "The ally HUD reservation must fit the longest protocol display name.");

struct GameplayAllyHudNameLayout {
    float bar_right_x = 0.0f;
    float label_width = 0.0f;
    float label_right_x = 0.0f;
    float name_left_x = 0.0f;
    float name_width = 0.0f;
    float name_right_x = 0.0f;
    bool valid = false;
};

std::vector<GameplayAllyHudRow> BuildGameplayAllyHudRows() {
    std::vector<GameplayAllyHudRow> rows;
    std::unordered_map<std::uint64_t, int> gameplay_slots;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        gameplay_slots.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind)) {
                continue;
            }
            gameplay_slots[binding.bot_id] = binding.gameplay_slot;
        }
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    rows.reserve(runtime_state.participants.size());
    for (const auto& participant : runtime_state.participants) {
        if (!multiplayer::IsRemoteParticipant(participant) ||
            !participant.transport_connected ||
            !participant.runtime.valid ||
            participant.name.empty() ||
            !std::isfinite(participant.runtime.life_current) ||
            !std::isfinite(participant.runtime.life_max) ||
            participant.runtime.life_current <= 0.0f ||
            participant.runtime.life_max <= 0.0f) {
            continue;
        }
        const auto slot_it = gameplay_slots.find(participant.participant_id);
        rows.push_back(GameplayAllyHudRow{
            slot_it == gameplay_slots.end() ? -1 : slot_it->second,
            participant.participant_id,
            participant.name,
            (std::clamp)(
                participant.runtime.life_current /
                    participant.runtime.life_max,
                0.0f,
                1.0f),
        });
    }

    std::sort(
        rows.begin(),
        rows.end(),
        [](const GameplayAllyHudRow& left, const GameplayAllyHudRow& right) {
            return left.participant_id < right.participant_id;
        });
    rows.erase(
        std::unique(
            rows.begin(),
            rows.end(),
            [](const GameplayAllyHudRow& left, const GameplayAllyHudRow& right) {
                return left.participant_id == right.participant_id;
            }),
        rows.end());
    return rows;
}

bool CallGameplayAllyHealthbarAppendSafe(
    uintptr_t append_address,
    uintptr_t gameplay_address,
    uintptr_t label_glyph,
    float hp_ratio,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (append_address == 0 ||
        gameplay_address == 0 ||
        label_glyph == 0) {
        return false;
    }

    auto* append =
        reinterpret_cast<GameplayAllyHealthbarAppendFn>(append_address);
    __try {
        append(
            reinterpret_cast<void*>(gameplay_address),
            label_glyph,
            hp_ratio);
        return true;
    } __except (CaptureSehCode(
        GetExceptionInformation(),
        exception_code)) {
        return false;
    }
}

bool PublishGameplayAllyHudRowsFromParticipantRoster(
    uintptr_t gameplay_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (!multiplayer::IsLocalTransportEnabled() ||
        gameplay_address == 0 ||
        kGameplayUiAllyLabelGlyphOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto append_address =
        memory.ResolveGameAddressOrZero(kGameplayAllyHealthbarAppend);
    const auto bundle_global =
        memory.ResolveGameAddressOrZero(kGameplayUiBundleGlobal);
    uintptr_t bundle_address = 0;
    if (append_address == 0 ||
        bundle_global == 0 ||
        !memory.TryReadValue(bundle_global, &bundle_address) ||
        bundle_address == 0) {
        return false;
    }

    const auto rows = BuildGameplayAllyHudRows();
    const auto label_glyph =
        bundle_address + kGameplayUiAllyLabelGlyphOffset;
    for (const auto& row : rows) {
        if (!CallGameplayAllyHealthbarAppendSafe(
                append_address,
                gameplay_address,
                label_glyph,
                row.hp_ratio,
                exception_code)) {
            return false;
        }
    }
    return true;
}

bool IsGameplayAllyHudLabelGlyphCall(
    uintptr_t glyph_address,
    uintptr_t caller_address) {
    if (glyph_address == 0 || caller_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto bundle_global = memory.ResolveGameAddressOrZero(kGameplayUiBundleGlobal);
    const auto expected_caller =
        memory.ResolveGameAddressOrZero(kGameplayAllyLabelGlyphReturn);
    if (bundle_global == 0 || expected_caller == 0 || kGameplayUiAllyLabelGlyphOffset == 0) {
        return false;
    }

    uintptr_t bundle_address = 0;
    if (!memory.TryReadValue(bundle_global, &bundle_address) || bundle_address == 0) {
        return false;
    }

    return caller_address == expected_caller &&
        glyph_address == bundle_address + kGameplayUiAllyLabelGlyphOffset;
}

std::size_t ResolveGameplayAllyHudRowIndex(float y, std::size_t row_count) {
    if (!std::isfinite(y) || row_count == 0) {
        return row_count;
    }

    thread_local float previous_y = 0.0f;
    thread_local std::size_t next_row_index = 0;
    if (next_row_index >= row_count || y <= previous_y + 0.25f) {
        next_row_index = 0;
    }

    const auto row_index = next_row_index;
    ++next_row_index;
    previous_y = y;
    return row_index;
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

float EstimateGameplayAllyHudTextWidth(std::string_view display_name) {
    float width = 0.0f;
    for (const unsigned char ch : display_name) {
        width += std::isspace(ch)
            ? kGameplayAllyHudSpaceAdvance
            : kGameplayAllyHudGlyphAdvance;
    }
    return width;
}

bool DrawGameplayWorldIndicatorParticipant(
    uintptr_t actor_address,
    std::uint64_t participant_id,
    const std::string& display_name,
    float health_ratio,
    float* drawn_center_x,
    float* drawn_name_y,
    float* drawn_bar_width,
    DWORD* exception_code) {
    if (drawn_center_x != nullptr) {
        *drawn_center_x = 0.0f;
    }
    if (drawn_name_y != nullptr) {
        *drawn_name_y = 0.0f;
    }
    if (drawn_bar_width != nullptr) {
        *drawn_bar_width = 0.0f;
    }
    if (actor_address == 0 ||
        participant_id == 0 ||
        display_name.empty() ||
        !std::isfinite(health_ratio)) {
        return false;
    }

    float world_x = 0.0f;
    float world_y = 0.0f;
    if (!TryReadFiniteFloatField(
            actor_address,
            kActorPositionXOffset,
            &world_x) ||
        !TryReadFiniteFloatField(
            actor_address,
            kActorPositionYOffset,
            &world_y)) {
        return false;
    }
    float center_x = 0.0f;
    float name_y = 0.0f;
    if (!TryProjectNativeWorldIndicatorPoint(
            world_x,
            world_y - 45.0f,
            &center_x,
            &name_y)) {
        return false;
    }

    const auto nameplate_text = BuildGameplayNameplateExactText(display_name);
    const float name_width =
        EstimateGameplayNameplateTextWidth(display_name);
    const float bar_width = (std::max)(64.0f, name_width);
    const bool drew_name = DrawGameplayHudExactTextAt(
        nameplate_text,
        center_x - name_width * 0.5f,
        name_y,
        exception_code);
    const bool drew_health = DrawNativeWorldIndicatorHealthBar(
        center_x,
        name_y + 17.0f,
        bar_width,
        health_ratio);
    if (drew_name && drew_health) {
        if (drawn_center_x != nullptr) {
            *drawn_center_x = center_x;
        }
        if (drawn_name_y != nullptr) {
            *drawn_name_y = name_y;
        }
        if (drawn_bar_width != nullptr) {
            *drawn_bar_width = bar_width;
        }
    }
    return drew_name && drew_health;
}

void RenderGameplayWorldIndicatorsInNativePassImpl() {
    std::vector<uintptr_t> actor_addresses;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        actor_addresses.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (IsWizardParticipantKind(binding.kind) &&
                binding.actor_address != 0) {
                actor_addresses.push_back(binding.actor_address);
            }
        }
    }
    std::sort(actor_addresses.begin(), actor_addresses.end());
    actor_addresses.erase(
        std::unique(actor_addresses.begin(), actor_addresses.end()),
        actor_addresses.end());

    for (const auto actor_address : actor_addresses) {
        if (!IsTrackedWizardParticipantActorForHud(actor_address)) {
            continue;
        }
        std::string display_name;
        std::uint64_t participant_id = 0;
        float health_ratio = 0.0f;
        if (!TryGetGameplayHudParticipantDisplayNameForActor(
                actor_address,
                &display_name,
                &participant_id,
                &health_ratio) ||
            display_name.empty()) {
            continue;
        }

        DWORD exception_code = 0;
        float drawn_center_x = 0.0f;
        float drawn_name_y = 0.0f;
        float drawn_bar_width = 0.0f;
        const bool drawn = DrawGameplayWorldIndicatorParticipant(
            actor_address,
            participant_id,
            display_name,
            health_ratio,
            &drawn_center_x,
            &drawn_name_y,
            &drawn_bar_width,
            &exception_code);
        const int health_percent = std::clamp(
            static_cast<int>(std::lround(health_ratio * 100.0f)),
            0,
            100);
        static std::unordered_map<std::uint64_t, int>
            s_logged_nameplate_health_percent;
        static int s_failed_nameplate_draw_logs_remaining = 8;
        const auto logged =
            s_logged_nameplate_health_percent.find(participant_id);
        const bool health_changed =
            logged == s_logged_nameplate_health_percent.end() ||
            logged->second != health_percent;
        if ((drawn && health_changed) ||
            (!drawn && s_failed_nameplate_draw_logs_remaining > 0)) {
            if (drawn) {
                s_logged_nameplate_health_percent[participant_id] =
                    health_percent;
            } else {
                --s_failed_nameplate_draw_logs_remaining;
            }
            Log(
                "[bots] native gameplay participant name draw. "
                "source=native_world_indicator actor=" +
                HexString(actor_address) +
                " participant=" + std::to_string(participant_id) +
                " name=" + display_name +
                " ok=" + std::string(drawn ? "1" : "0") +
                " health_bar=native" +
                " health_ratio=" + std::to_string(health_ratio) +
                " health_percent=" + std::to_string(health_percent) +
                " center_x=" + std::to_string(drawn_center_x) +
                " name_y=" + std::to_string(drawn_name_y) +
                " bar_top=" + std::to_string(drawn_name_y + 17.0f) +
                " bar_width=" + std::to_string(drawn_bar_width) +
                " exception=" +
                HexString(static_cast<uintptr_t>(exception_code)));
        }
    }
}

bool DrawGameplayHudExactTextAt(
    const std::string& display_text,
    float x,
    float y,
    DWORD* exception_code) {
    if (display_text.empty()) {
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

    return CallGameplayExactTextObjectRenderSafe(
        string_assign_address,
        text_object_render_address,
        text_object_address,
        display_text.c_str(),
        x,
        y,
        exception_code);
}

bool DrawGameplayHudAllyBarParticipantName(
    const GameplayAllyHudRow& row,
    float x,
    float y,
    GameplayAllyHudNameLayout* layout,
    DWORD* exception_code) {
    if (layout != nullptr) {
        *layout = {};
    }
    if (row.display_name.empty() || !std::isfinite(x) || !std::isfinite(y)) {
        return false;
    }

    GameplayAllyHudNameLayout resolved;
    resolved.bar_right_x = x;
    resolved.label_width = kGameplayAllyHudReservedLabelWidth;
    resolved.label_right_x = x + resolved.label_width;
    resolved.name_width = EstimateGameplayAllyHudTextWidth(row.display_name);
    resolved.name_left_x = x + kGameplayAllyHudNameHorizontalPadding;
    resolved.name_right_x = resolved.name_left_x + resolved.name_width;
    resolved.valid =
        resolved.name_width > 0.0f &&
        resolved.name_left_x >=
            resolved.bar_right_x + kGameplayAllyHudNameHorizontalPadding &&
        resolved.name_right_x <=
            resolved.label_right_x - kGameplayAllyHudNameHorizontalPadding;
    if (layout != nullptr) {
        *layout = resolved;
    }
    if (!resolved.valid) {
        return false;
    }

    return DrawGameplayHudExactTextAt(
        BuildGameplayAllyHudExactText(row.display_name),
        resolved.name_left_x,
        y + kGameplayAllyHudLabelBaselineOffset,
        exception_code);
}

void __fastcall HookGameplayUiGlyphDraw(
    void* self,
    void* /*unused_edx*/,
    float x,
    float y) {
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    NativeSceneCaptureBeginSpriteDraw(
        self, "position", x, y, nullptr, caller_address);
    ObserveDebugUiMenuSpritePositionDraw(self, x, y);
    ObserveDebugUiExactTextGlyph(x, y);

    const auto original = GetX86HookTrampoline<GameplayUiGlyphDrawFn>(
        g_gameplay_keyboard_injection.gameplay_ui_glyph_draw_hook);
    if (original == nullptr) {
        NativeSceneCaptureEndSpriteDraw();
        return;
    }

    original(self, x, y);
    NativeSceneCaptureEndSpriteDraw();
}

void __fastcall HookGameplayUiAllyLabelGlyphDraw(
    void* self,
    void* /*unused_edx*/,
    float x,
    float y) {
    const auto original = GetX86HookTrampoline<GameplayUiGlyphDrawFn>(
        g_gameplay_keyboard_injection.gameplay_ui_ally_label_glyph_draw_hook);
    if (original == nullptr) {
        return;
    }

    const auto glyph_address = reinterpret_cast<uintptr_t>(self);
    const auto caller_address = reinterpret_cast<uintptr_t>(_ReturnAddress());
    if (!multiplayer::IsLocalTransportEnabled() ||
        !IsGameplayAllyHudLabelGlyphCall(glyph_address, caller_address)) {
        original(self, x, y);
        return;
    }

    const auto rows = BuildGameplayAllyHudRows();
    const auto row_index = ResolveGameplayAllyHudRowIndex(y, rows.size());
    if (row_index >= rows.size()) {
        return;
    }

    DWORD exception_code = 0;
    GameplayAllyHudNameLayout name_layout;
    const bool drew_name =
        DrawGameplayHudAllyBarParticipantName(
            rows[row_index],
            x,
            y,
            &name_layout,
            &exception_code);

    static std::unordered_set<std::uint64_t> s_logged_ally_hud_participants;
    static int s_failed_ally_hud_name_draw_logs_remaining = 8;
    const bool should_log = drew_name
        ? s_logged_ally_hud_participants.insert(rows[row_index].participant_id).second
        : s_failed_ally_hud_name_draw_logs_remaining > 0;
    if (should_log) {
        if (!drew_name) {
            --s_failed_ally_hud_name_draw_logs_remaining;
        }
        Log(
            "[bots] native gameplay HUD participant name draw. source=ally_healthbar" +
            std::string(" participant=") + std::to_string(rows[row_index].participant_id) +
            " hud_row=" + std::to_string(row_index + 1) +
            " slot=" + std::to_string(rows[row_index].gameplay_slot) +
            " name=" + rows[row_index].display_name +
            " ok=" + std::string(drew_name ? "1" : "0") +
            " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
            " stock_label=0" +
            " layout_ok=" + std::string(name_layout.valid ? "1" : "0") +
            " bar_right_x=" + std::to_string(name_layout.bar_right_x) +
            " label_width=" + std::to_string(name_layout.label_width) +
            " label_right_x=" + std::to_string(name_layout.label_right_x) +
            " name_left_x=" + std::to_string(name_layout.name_left_x) +
            " name_width=" + std::to_string(name_layout.name_width) +
            " name_right_x=" + std::to_string(name_layout.name_right_x) +
            " xy=(" + std::to_string(x) + "," + std::to_string(y) + ")");
    }
}
