// Opt-in native menu layout capture.
//
// Contract:
// - Existing sd.ui.get_snapshot()/get_state() behavior is unchanged.
// - Native sprite detours are installed only when
//   SDMOD_NATIVE_MENU_LAYOUT_CAPTURE=1 or
//   SDMOD_NATIVE_BOOT_CAPTURE_DIRECTORY is set.
// - Reported art ids are resolved from live atlas singleton/destination
//   objects. Rectangles come from the submitted native Sprite quad and the
//   active D3D9 viewport/scissor state; screenshots are not measured.

enum class NativeAtlasSpanKind {
    Inline,
    Array,
};

struct NativeAtlasSpan {
    const char* atlas = nullptr;
    uintptr_t singleton_global = 0;
    NativeAtlasSpanKind kind = NativeAtlasSpanKind::Inline;
    std::size_t object_field = 0;
    std::uint32_t first_record = 0;
    std::uint32_t record_count = 0;
};

// Generated from docs/reverse-engineering/native-asset-object-map.json. The
// omitted ControlPanel Fonts auxiliary destination is text, not menu art.
constexpr NativeAtlasSpan kNativeMenuAtlasSpans[] = {
    {"Loader",       0x008199BC, NativeAtlasSpanKind::Inline, 0x0038, 0,   5},
    {"Controls",     0x0081998C, NativeAtlasSpanKind::Inline, 0x0038, 0,   4},
    {"GameOver",     0x008199A4, NativeAtlasSpanKind::Inline, 0x0038, 0,   3},
    {"LevelPicker",  0x008199B4, NativeAtlasSpanKind::Inline, 0x0038, 0,   8},
    {"Title",        0x008199E0, NativeAtlasSpanKind::Inline, 0x0038, 0,  11},
    {"Title",        0x008199E0, NativeAtlasSpanKind::Array,  0x08A8, 11,  5},
    {"Title",        0x008199E0, NativeAtlasSpanKind::Array,  0x08B8, 16,  9},
    {"Create",       0x00819990, NativeAtlasSpanKind::Inline, 0x0038, 0,   9},
    {"Create",       0x00819990, NativeAtlasSpanKind::Array,  0x0720, 9,   5},
    {"Create",       0x00819990, NativeAtlasSpanKind::Array,  0x0730, 14,  2},
    {"Create",       0x00819990, NativeAtlasSpanKind::Array,  0x0740, 16,  4},
    {"Create",       0x00819990, NativeAtlasSpanKind::Array,  0x0750, 20,  4},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Inline, 0x0038, 0,   8},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x065C, 8,   2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x066C, 10,  2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x067C, 12,  2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x068C, 14,  2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x069C, 16,  2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x06AC, 18,  2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x06BC, 20,  2},
    {"ControlPanel", 0x00819988, NativeAtlasSpanKind::Array,  0x06CC, 22,  2},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Inline, 0x0038, 0,  19},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0EC8, 19,  8},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0ED8, 27, 96},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0EE8, 123, 2},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0EF8, 125, 2},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0F08, 127, 29},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0F18, 156, 8},
    {"Skills",       0x008199CC, NativeAtlasSpanKind::Array,  0x0F28, 164, 2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Inline, 0x0038, 0,  84},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x408C, 84,  2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x409C, 86,  2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x40AC, 88,  2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x40BC, 90,  8},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x40CC, 98,  3},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x40DC, 101, 2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x40EC, 103, 2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x40FC, 105, 2},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x410C, 107, 4},
    {"UI",           0x008199E4, NativeAtlasSpanKind::Array,  0x411C, 111, 2},
};

constexpr std::size_t kNativeSpriteStride = 0xC4;
constexpr std::size_t kNativeSpriteTextureHandleOffset = 0x08;
constexpr std::size_t kNativeSpriteVertexOffset = 0x2C;
constexpr std::size_t kNativeSpriteUvOffset = 0x4C;
constexpr std::size_t kNativeSpriteLogicalWidthOffset = 0x94;
constexpr std::size_t kNativeSpriteLogicalHeightOffset = 0x98;
constexpr uintptr_t kNativeLoaderRenderAddress = 0x005BCA40;
constexpr uintptr_t kNativeSpriteCenteredDrawAddress = 0x004142E0;
constexpr uintptr_t kNativeSpriteTransformDrawAddress = 0x00414540;
constexpr uintptr_t kSettingsScalarRowAddress = 0x00436160;
constexpr uintptr_t kSettingsToggleRowAddress = 0x00435DE0;
constexpr uintptr_t kNativeLoaderProgressNumerator = 0x0081F6A8;
constexpr uintptr_t kNativeLoaderProgressDenominator = 0x0081F6AC;
constexpr uintptr_t kNativeLoaderCompleteFlag = 0x0081F6B0;
constexpr std::size_t kMaximumCapturedMenuArtPerFrame = 2048;

struct NativeSpriteSignature {
    std::uint32_t texture_handle = 0;
    std::array<std::uint32_t, 8> uv_bits = {};
    std::int32_t logical_width = 0;
    std::int32_t logical_height = 0;
};

struct NativeBootCaptureSample {
    std::uint64_t elapsed_milliseconds = 0;
    std::uint32_t numerator = 0;
    std::uint32_t denominator = 0;
    bool complete = false;
    double progress = 0.0;
    std::string reference_capture;
    std::vector<CapturedMenuArtElement> elements;
};

std::unordered_map<uintptr_t, std::string> g_native_menu_art_by_address;
std::unordered_map<std::string, std::string> g_native_menu_art_by_signature;
ULONGLONG g_native_menu_art_cache_built_at = 0;
std::uint32_t g_native_menu_art_draw_order = 0;
std::filesystem::path g_native_boot_capture_directory;
std::vector<NativeBootCaptureSample> g_native_boot_capture_samples;
ULONGLONG g_native_boot_capture_started_at = 0;
int g_native_boot_last_reference_bucket = -1;
bool g_native_loader_render_active = false;
std::vector<CapturedMenuArtElement> g_native_loader_frame_art;

struct ActiveSettingsRowCapture {
    std::string label;
    std::string font_id;
    uintptr_t caller_address = 0;
    float left = (std::numeric_limits<float>::max)();
    float top = (std::numeric_limits<float>::max)();
    float right = (std::numeric_limits<float>::lowest)();
    float bottom = (std::numeric_limits<float>::lowest)();
    std::uint32_t sample_count = 0;
};

thread_local std::vector<ActiveSettingsRowCapture>
    g_active_settings_row_captures;

bool HasDrawableNativeSpriteSignature(
    const NativeSpriteSignature& signature) {
    return signature.texture_handle != 0 &&
        signature.logical_width > 0 &&
        signature.logical_height > 0;
}

std::string NativeSpriteSignatureKey(const NativeSpriteSignature& signature) {
    return std::string(
        reinterpret_cast<const char*>(&signature),
        sizeof(signature));
}

bool TryReadNativeSpriteSignature(
    uintptr_t sprite_address,
    NativeSpriteSignature* signature) {
    if (sprite_address == 0 || signature == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               sprite_address,
               kNativeSpriteTextureHandleOffset,
               &signature->texture_handle) &&
        memory.TryRead(
            sprite_address + kNativeSpriteUvOffset,
            signature->uv_bits.data(),
            sizeof(signature->uv_bits)) &&
        memory.TryReadField(
            sprite_address,
            kNativeSpriteLogicalWidthOffset,
            &signature->logical_width) &&
        memory.TryReadField(
            sprite_address,
            kNativeSpriteLogicalHeightOffset,
            &signature->logical_height);
}

void RebuildNativeMenuArtResolver() {
    std::unordered_map<uintptr_t, std::string> by_address;
    std::unordered_map<std::string, std::string> by_signature;
    auto& memory = ProcessMemory::Instance();

    for (const auto& span : kNativeMenuAtlasSpans) {
        const auto resolved_global =
            memory.ResolveGameAddressOrZero(span.singleton_global);
        std::uint32_t object_pointer = 0;
        if (resolved_global == 0 ||
            !memory.TryReadValue(resolved_global, &object_pointer) ||
            object_pointer == 0) {
            continue;
        }

        uintptr_t records =
            static_cast<uintptr_t>(object_pointer) + span.object_field;
        if (span.kind == NativeAtlasSpanKind::Array) {
            std::uint32_t array_pointer = 0;
            std::uint32_t live_count = 0;
            if (!memory.TryReadValue(records, &array_pointer) ||
                !memory.TryReadValue(records + sizeof(std::uint32_t), &live_count) ||
                array_pointer == 0 || live_count < span.record_count) {
                continue;
            }
            records = static_cast<uintptr_t>(array_pointer);
        }

        for (std::uint32_t index = 0; index < span.record_count; ++index) {
            const auto record_address =
                records + static_cast<uintptr_t>(index) * kNativeSpriteStride;
            const auto record_id =
                std::string(span.atlas) + "." +
                std::to_string(span.first_record + index);
            by_address.emplace(record_address, record_id);

            NativeSpriteSignature signature;
            if (TryReadNativeSpriteSignature(record_address, &signature) &&
                HasDrawableNativeSpriteSignature(signature)) {
                by_signature.emplace(
                    NativeSpriteSignatureKey(signature),
                    record_id);
            }
        }
    }

    g_native_menu_art_by_address = std::move(by_address);
    g_native_menu_art_by_signature = std::move(by_signature);
    g_native_menu_art_cache_built_at = GetTickCount64();
}

std::string ResolveNativeMenuArtId(uintptr_t sprite_address) {
    if (!g_debug_ui_overlay_state.menu_layout_capture_enabled ||
        sprite_address == 0) {
        return {};
    }

    const auto now = GetTickCount64();
    if (g_native_menu_art_by_address.empty() ||
        (now >= g_native_menu_art_cache_built_at &&
         now - g_native_menu_art_cache_built_at > 1000)) {
        RebuildNativeMenuArtResolver();
    }

    if (const auto direct = g_native_menu_art_by_address.find(sprite_address);
        direct != g_native_menu_art_by_address.end()) {
        return direct->second;
    }

    NativeSpriteSignature signature;
    if (!TryReadNativeSpriteSignature(sprite_address, &signature) ||
        !HasDrawableNativeSpriteSignature(signature)) {
        return {};
    }
    const auto copied = g_native_menu_art_by_signature.find(
        NativeSpriteSignatureKey(signature));
    return copied != g_native_menu_art_by_signature.end()
        ? copied->second
        : std::string{};
}

std::string ResolveNativeFontId(uintptr_t font_object_address) {
    constexpr std::pair<std::size_t, const char*> kFontGroups[] = {
        {0x00FC, "Fonts.1-92"},
        {0x4D530, "Fonts.93-184"},
        {0x9A964, "Fonts.185-215"},
        {0xE7D98, "Fonts.216-307"},
        {0x1351CC, "Fonts.308-349"},
        {0x182600, "Fonts.350-375"},
        {0x1CFA34, "Fonts.376-442"},
        {0x21CE68, "Fonts.443-534"},
        {0x26A29C, "Fonts.535-626"},
    };

    auto& memory = ProcessMemory::Instance();
    const auto resolved_global = memory.ResolveGameAddressOrZero(0x008199A0);
    std::uint32_t fonts_object = 0;
    if (resolved_global == 0 ||
        !memory.TryReadValue(resolved_global, &fonts_object) ||
        fonts_object == 0) {
        return {};
    }

    for (const auto& group : kFontGroups) {
        if (font_object_address ==
            static_cast<uintptr_t>(fonts_object) + group.first) {
            return group.second;
        }
    }
    return {};
}

bool TryReadMenuRenderBase(float* base_x, float* base_y);

std::string ResolveNativeFontIdForGlyphSprite(
    uintptr_t glyph_sprite_address) {
    constexpr std::pair<std::size_t, const char*> kFontGroups[] = {
        {0x00FC, "Fonts.1-92"},
        {0x4D530, "Fonts.93-184"},
        {0x9A964, "Fonts.185-215"},
        {0xE7D98, "Fonts.216-307"},
        {0x1351CC, "Fonts.308-349"},
        {0x182600, "Fonts.350-375"},
        {0x1CFA34, "Fonts.376-442"},
        {0x21CE68, "Fonts.443-534"},
        {0x26A29C, "Fonts.535-626"},
    };
    constexpr std::size_t kFontGroupSpan = 0x4D434;

    auto& memory = ProcessMemory::Instance();
    const auto resolved_global =
        memory.ResolveGameAddressOrZero(0x008199A0);
    std::uint32_t fonts_object = 0;
    if (resolved_global == 0 ||
        !memory.TryReadValue(resolved_global, &fonts_object) ||
        fonts_object == 0) {
        return {};
    }

    for (const auto& group : kFontGroups) {
        const auto start =
            static_cast<uintptr_t>(fonts_object) + group.first;
        if (glyph_sprite_address >= start &&
            glyph_sprite_address < start + kFontGroupSpan) {
            return group.second;
        }
    }
    return {};
}

std::string ReadSettingsRowCaptureLabel(
    const NativeUiString& native_label) {
    std::string label;
    if (!TryReadStringObject(
            reinterpret_cast<uintptr_t>(&native_label),
            &label)) {
        return {};
    }
    return TrimAsciiWhitespace(label);
}

void BeginSettingsRowCapture(
    const NativeUiString& native_label,
    uintptr_t caller_address) {
    if (!g_debug_ui_overlay_state.menu_layout_capture_enabled) {
        return;
    }
    uintptr_t settings_address = 0;
    if (!TryGetLiveSettingsRender(&settings_address) ||
        settings_address == 0) {
        return;
    }
    auto label = ReadSettingsRowCaptureLabel(native_label);
    if (label.empty()) {
        return;
    }
    ActiveSettingsRowCapture capture;
    capture.label = std::move(label);
    capture.caller_address = caller_address;
    g_active_settings_row_captures.push_back(std::move(capture));
}

void ObserveActiveSettingsRowBounds(
    float left,
    float top,
    float right,
    float bottom,
    uintptr_t glyph_sprite_address = 0) {
    if (g_active_settings_row_captures.empty() ||
        !std::isfinite(left) || !std::isfinite(top) ||
        !std::isfinite(right) || !std::isfinite(bottom) ||
        right <= left || bottom <= top) {
        return;
    }
    auto& capture = g_active_settings_row_captures.back();
    capture.left = (std::min)(capture.left, left);
    capture.top = (std::min)(capture.top, top);
    capture.right = (std::max)(capture.right, right);
    capture.bottom = (std::max)(capture.bottom, bottom);
    ++capture.sample_count;
    if (capture.font_id.empty() && glyph_sprite_address != 0) {
        capture.font_id = ResolveNativeFontIdForGlyphSprite(
            glyph_sprite_address);
    }
}

void ObserveActiveSettingsRowTextQuad(
    const float* destination_vertices) {
    if (destination_vertices == nullptr ||
        g_active_settings_row_captures.empty()) {
        return;
    }
    float base_x = 0.0f;
    float base_y = 0.0f;
    (void)TryReadMenuRenderBase(&base_x, &base_y);
    float left = (std::numeric_limits<float>::max)();
    float top = (std::numeric_limits<float>::max)();
    float right = (std::numeric_limits<float>::lowest)();
    float bottom = (std::numeric_limits<float>::lowest)();
    for (std::size_t index = 0; index < 4; ++index) {
        const auto x = destination_vertices[index * 2] + base_x;
        const auto y = destination_vertices[index * 2 + 1] + base_y;
        left = (std::min)(left, x);
        top = (std::min)(top, y);
        right = (std::max)(right, x);
        bottom = (std::max)(bottom, y);
    }
    ObserveActiveSettingsRowBounds(left, top, right, bottom);
}

void EndSettingsRowCapture() {
    if (g_active_settings_row_captures.empty()) {
        return;
    }
    auto capture = std::move(g_active_settings_row_captures.back());
    g_active_settings_row_captures.pop_back();
    if (capture.sample_count == 0 || capture.label.empty() ||
        capture.right <= capture.left || capture.bottom <= capture.top) {
        return;
    }

    ObservedUiElement element;
    element.surface_id = "settings";
    element.surface_title = "Game Settings";
    // The return address is a stable identity for an immediate-mode row: the
    // native control itself is transient, while every row has a unique call
    // site in Settings_Render.
    element.object_ptr = capture.caller_address;
    element.caller_address = capture.caller_address;
    element.min_x = capture.left;
    element.min_y = capture.top;
    element.max_x = capture.right;
    element.max_y = capture.bottom;
    element.sample_count = capture.sample_count;
    element.label = std::move(capture.label);
    element.font_id = std::move(capture.font_id);

    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto& elements =
        g_debug_ui_overlay_state.frame_exact_text_elements;
    const auto existing = std::find_if(
        elements.begin(),
        elements.end(),
        [&](const ObservedUiElement& candidate) {
            return candidate.surface_id == element.surface_id &&
                candidate.object_ptr == element.object_ptr &&
                candidate.label == element.label;
        });
    if (existing != elements.end()) {
        existing->min_x = (std::min)(existing->min_x, element.min_x);
        existing->min_y = (std::min)(existing->min_y, element.min_y);
        existing->max_x = (std::max)(existing->max_x, element.max_x);
        existing->max_y = (std::max)(existing->max_y, element.max_y);
        existing->sample_count += element.sample_count;
        if (existing->font_id.empty()) {
            existing->font_id = std::move(element.font_id);
        }
        return;
    }
    elements.push_back(std::move(element));
}

