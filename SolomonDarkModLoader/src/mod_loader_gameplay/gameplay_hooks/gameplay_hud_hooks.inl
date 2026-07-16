bool DrawGameplayHudParticipantName(
    uintptr_t actor_address,
    const std::string& display_name,
    float* draw_x,
    float* draw_y,
    DWORD* exception_code);
bool DrawGameplayParticipantHealthBar(
    uintptr_t actor_address,
    float nameplate_y,
    float* health_ratio,
    int* filled_segment_count,
    DWORD* exception_code);
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
};

constexpr std::size_t kGameplayAllyHudNativeSlotCount = 5;
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
    const auto runtime = multiplayer::SnapshotRuntimeState();
    std::vector<GameplayAllyHudRow> rows;
    {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        rows.reserve(g_participant_entities.size());
        for (const auto& binding : g_participant_entities) {
            if (!IsWizardParticipantKind(binding.kind) ||
                binding.actor_address == 0 ||
                binding.gameplay_slot <= 0 ||
                binding.gameplay_slot >= static_cast<int>(kGameplayPlayerSlotCount)) {
                continue;
            }

            const auto* participant = multiplayer::FindParticipant(runtime, binding.bot_id);
            if (participant == nullptr ||
                !multiplayer::IsRemoteParticipant(*participant) ||
                !participant->transport_connected ||
                participant->name.empty()) {
                continue;
            }
            rows.push_back(GameplayAllyHudRow{
                binding.gameplay_slot,
                binding.bot_id,
                participant->name,
            });
        }
    }

    std::sort(
        rows.begin(),
        rows.end(),
        [](const GameplayAllyHudRow& left, const GameplayAllyHudRow& right) {
            if (left.gameplay_slot != right.gameplay_slot) {
                return left.gameplay_slot < right.gameplay_slot;
            }
            return left.participant_id < right.participant_id;
        });
    rows.erase(
        std::unique(
            rows.begin(),
            rows.end(),
            [](const GameplayAllyHudRow& left, const GameplayAllyHudRow& right) {
                return left.gameplay_slot == right.gameplay_slot;
            }),
        rows.end());
    return rows;
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

bool DrawGameplayParticipantHealthBar(
    uintptr_t actor_address,
    float nameplate_y,
    float* health_ratio,
    int* filled_segment_count,
    DWORD* exception_code) {
    if (health_ratio != nullptr) {
        *health_ratio = 0.0f;
    }
    if (filled_segment_count != nullptr) {
        *filled_segment_count = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 || !std::isfinite(nameplate_y)) {
        return false;
    }

    ActorHealthRuntime health;
    if (!TryReadActorProgressionHealth(actor_address, &health)) {
        return false;
    }
    const float ratio = std::clamp(health.hp / health.max_hp, 0.0f, 1.0f);

    float actor_x = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &actor_x)) {
        return false;
    }

    constexpr int kBarSegments = 12;
    constexpr float kQuarterScaleGlyphWidth = 4.0f;
    constexpr int kBarBoundaryGlyphs = 2;
    constexpr float kBarVerticalGap = 12.0f;
    const int filled_segments = std::clamp(
        static_cast<int>(std::lround(ratio * static_cast<float>(kBarSegments))),
        0,
        kBarSegments);

    std::string bar_text = "_s(0.25)[";
    bar_text.append(static_cast<std::size_t>(filled_segments), '=');
    bar_text.append(static_cast<std::size_t>(kBarSegments - filled_segments), '-');
    bar_text.push_back(']');

    const float bar_width =
        static_cast<float>(kBarSegments + kBarBoundaryGlyphs) * kQuarterScaleGlyphWidth;
    const float bar_x = actor_x - (bar_width * 0.5f);
    const float bar_y = nameplate_y + kBarVerticalGap;
    if (health_ratio != nullptr) {
        *health_ratio = ratio;
    }
    if (filled_segment_count != nullptr) {
        *filled_segment_count = filled_segments;
    }
    return DrawGameplayHudExactTextAt(bar_text, bar_x, bar_y, exception_code);
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

void DrawGameplayHudLevelUpWaitStatusForHudPass() {
    std::string wait_text;
    if (!multiplayer::TryBuildLevelUpWaitStatusText(&wait_text) || wait_text.empty()) {
        return;
    }

    const auto exact_text = BuildGameplayNameplateExactText(wait_text);
    DWORD exception_code = 0;
    const bool drew_label =
        DrawGameplayHudExactTextAt(exact_text, 250.0f, 110.0f, &exception_code);
    static int s_level_up_wait_status_draw_logs_remaining = 12;
    if (s_level_up_wait_status_draw_logs_remaining > 0) {
        --s_level_up_wait_status_draw_logs_remaining;
        Log(
            "Multiplayer level-up wait HUD draw. ok=" +
            std::string(drew_label ? "1" : "0") +
            " exception=" + HexString(static_cast<uintptr_t>(exception_code)) +
            " text=\"" + wait_text + "\"");
    }
}

void __fastcall HookGameplayUiGlyphDraw(
    void* self,
    void* /*unused_edx*/,
    float x,
    float y) {
    ObserveDebugUiExactTextGlyph(x, y);

    const auto original = GetX86HookTrampoline<GameplayUiGlyphDrawFn>(
        g_gameplay_keyboard_injection.gameplay_ui_glyph_draw_hook);
    if (original == nullptr) {
        return;
    }

    original(self, x, y);
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
        original(self, x, y);
        return;
    }

    if (row_index == 0) {
        DrawGameplayHudLevelUpWaitStatusForHudPass();
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
    if (!drew_name) {
        original(self, x, y);
    }

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
            " stock_label=" + std::string(drew_name ? "0" : "1") +
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
