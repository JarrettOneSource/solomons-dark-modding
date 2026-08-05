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
constexpr uintptr_t kSettingsSectionRowAddress = 0x00436750;
constexpr uintptr_t kSettingsSingleStringRowAddress = 0x004A5A70;
constexpr uintptr_t kSettingsDualStringRowAddress = 0x004A5B60;
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

bool TryReadMenuRenderBase(float* base_x, float* base_y) {
    if (base_x == nullptr || base_y == nullptr) {
        return false;
    }
    uintptr_t render_context = 0;
    if (!TryReadUiRenderContext(
            g_debug_ui_overlay_state.config,
            &render_context) ||
        render_context == 0) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               render_context,
               g_debug_ui_overlay_state.config.ui_render_context_base_x_offset,
               base_x) &&
        memory.TryReadField(
            render_context,
            g_debug_ui_overlay_state.config.ui_render_context_base_y_offset,
            base_y) &&
        std::isfinite(*base_x) && std::isfinite(*base_y);
}

bool TryReadNativeSpriteVertices(
    uintptr_t sprite_address,
    std::array<float, 8>* vertices) {
    return vertices != nullptr &&
        ProcessMemory::Instance().TryRead(
            sprite_address + kNativeSpriteVertexOffset,
            vertices->data(),
            sizeof(*vertices));
}

void ClipCapturedMenuArt(CapturedMenuArtElement* element) {
    if (element == nullptr) {
        return;
    }
    element->unclipped_left = element->left;
    element->unclipped_top = element->top;
    element->unclipped_right = element->right;
    element->unclipped_bottom = element->bottom;

    auto* device = GetLastSeenD3d9Device();
    if (device != nullptr) {
        D3DVIEWPORT9 viewport = {};
        if (SUCCEEDED(device->GetViewport(&viewport))) {
            element->left = (std::max)(
                element->left,
                static_cast<float>(viewport.X));
            element->top = (std::max)(
                element->top,
                static_cast<float>(viewport.Y));
            element->right = (std::min)(
                element->right,
                static_cast<float>(viewport.X + viewport.Width));
            element->bottom = (std::min)(
                element->bottom,
                static_cast<float>(viewport.Y + viewport.Height));
        }

        DWORD scissor_enabled = FALSE;
        RECT scissor = {};
        if (SUCCEEDED(device->GetRenderState(
                D3DRS_SCISSORTESTENABLE,
                &scissor_enabled)) &&
            scissor_enabled != FALSE &&
            SUCCEEDED(device->GetScissorRect(&scissor))) {
            element->left = (std::max)(
                element->left,
                static_cast<float>(scissor.left));
            element->top = (std::max)(
                element->top,
                static_cast<float>(scissor.top));
            element->right = (std::min)(
                element->right,
                static_cast<float>(scissor.right));
            element->bottom = (std::min)(
                element->bottom,
                static_cast<float>(scissor.bottom));
        }
    }

    element->visible =
        element->right > element->left &&
        element->bottom > element->top;
}

void StoreCapturedMenuArt(CapturedMenuArtElement element) {
    if (element.art_id.empty()) {
        return;
    }
    ClipCapturedMenuArt(&element);
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    if (g_debug_ui_overlay_state.frame_menu_art_elements.size() >=
        kMaximumCapturedMenuArtPerFrame) {
        return;
    }
    const auto same_layout_element = [&](const CapturedMenuArtElement& other) {
        const auto nearly_equal = [](float left, float right) {
            return std::fabs(left - right) <= 0.001f;
        };
        return other.art_id == element.art_id &&
            other.draw_kind == element.draw_kind &&
            other.source_object_ptr == element.source_object_ptr &&
            other.visible == element.visible &&
            nearly_equal(other.left, element.left) &&
            nearly_equal(other.top, element.top) &&
            nearly_equal(other.right, element.right) &&
            nearly_equal(other.bottom, element.bottom) &&
            nearly_equal(other.unclipped_left, element.unclipped_left) &&
            nearly_equal(other.unclipped_top, element.unclipped_top) &&
            nearly_equal(other.unclipped_right, element.unclipped_right) &&
            nearly_equal(other.unclipped_bottom, element.unclipped_bottom);
    };
    if (std::any_of(
            g_debug_ui_overlay_state.frame_menu_art_elements.begin(),
            g_debug_ui_overlay_state.frame_menu_art_elements.end(),
            same_layout_element)) {
        return;
    }
    element.draw_order = ++g_native_menu_art_draw_order;
    if (g_native_loader_render_active &&
        element.art_id.rfind("Loader.", 0) == 0) {
        g_native_loader_frame_art.push_back(element);
    }
    g_debug_ui_overlay_state.frame_menu_art_elements.push_back(
        std::move(element));
}

void ObserveMenuSpritePositionDraw(
    void* self,
    float x,
    float y,
    bool centered) {
    if (!g_debug_ui_overlay_state.menu_layout_capture_enabled ||
        self == nullptr) {
        return;
    }
    const auto sprite_address = reinterpret_cast<uintptr_t>(self);
    const auto art_id = ResolveNativeMenuArtId(sprite_address);
    if (art_id.empty() && g_active_settings_row_captures.empty()) {
        return;
    }

    std::array<float, 8> vertices = {};
    if (!TryReadNativeSpriteVertices(sprite_address, &vertices)) {
        return;
    }
    float base_x = 0.0f;
    float base_y = 0.0f;
    (void)TryReadMenuRenderBase(&base_x, &base_y);
    if (centered) {
        std::int32_t logical_width = 0;
        std::int32_t logical_height = 0;
        auto& memory = ProcessMemory::Instance();
        if (!memory.TryReadField(
                sprite_address,
                kNativeSpriteLogicalWidthOffset,
                &logical_width) ||
            !memory.TryReadField(
                sprite_address,
                kNativeSpriteLogicalHeightOffset,
                &logical_height)) {
            return;
        }
        x += static_cast<float>(logical_width / 2);
        y += static_cast<float>(logical_height / 2);
    }

    CapturedMenuArtElement element;
    element.art_id = art_id;
    element.draw_kind = centered ? "centered" : "position";
    element.source_object_ptr = sprite_address;
    element.left = (std::numeric_limits<float>::max)();
    element.top = (std::numeric_limits<float>::max)();
    element.right = (std::numeric_limits<float>::lowest)();
    element.bottom = (std::numeric_limits<float>::lowest)();
    for (std::size_t index = 0; index < 4; ++index) {
        const auto px = vertices[index * 2] + x + base_x;
        const auto py = vertices[index * 2 + 1] + y + base_y;
        element.left = (std::min)(element.left, px);
        element.top = (std::min)(element.top, py);
        element.right = (std::max)(element.right, px);
        element.bottom = (std::max)(element.bottom, py);
    }
    if (element.right <= element.left || element.bottom <= element.top) {
        return;
    }
    ObserveActiveSettingsRowBounds(
        element.left,
        element.top,
        element.right,
        element.bottom,
        sprite_address);
    if (art_id.empty()) {
        return;
    }
    StoreCapturedMenuArt(std::move(element));
}

void ObserveMenuSpriteTransformDraw(void* self, const float* transform) {
    if (!g_debug_ui_overlay_state.menu_layout_capture_enabled ||
        self == nullptr || transform == nullptr) {
        return;
    }
    const auto sprite_address = reinterpret_cast<uintptr_t>(self);
    const auto art_id = ResolveNativeMenuArtId(sprite_address);
    if (art_id.empty() && g_active_settings_row_captures.empty()) {
        return;
    }

    std::array<float, 8> vertices = {};
    if (!TryReadNativeSpriteVertices(sprite_address, &vertices)) {
        return;
    }
    std::array<float, 16> matrix = {};
    if (!ProcessMemory::Instance().TryRead(
            reinterpret_cast<uintptr_t>(transform),
            matrix.data(),
            sizeof(matrix))) {
        return;
    }

    CapturedMenuArtElement element;
    element.art_id = art_id;
    element.draw_kind = "transform";
    element.source_object_ptr = sprite_address;
    element.left = (std::numeric_limits<float>::max)();
    element.top = (std::numeric_limits<float>::max)();
    element.right = (std::numeric_limits<float>::lowest)();
    element.bottom = (std::numeric_limits<float>::lowest)();
    float base_x = 0.0f;
    float base_y = 0.0f;
    (void)TryReadMenuRenderBase(&base_x, &base_y);
    for (std::size_t index = 0; index < 4; ++index) {
        const auto vx = vertices[index * 2];
        const auto vy = vertices[index * 2 + 1];
        const auto px = vx * matrix[0] + vy * matrix[4] + matrix[12] +
            base_x;
        const auto py = vx * matrix[1] + vy * matrix[5] + matrix[13] +
            base_y;
        element.left = (std::min)(element.left, px);
        element.top = (std::min)(element.top, py);
        element.right = (std::max)(element.right, px);
        element.bottom = (std::max)(element.bottom, py);
    }
    if (element.right <= element.left || element.bottom <= element.top) {
        return;
    }
    ObserveActiveSettingsRowBounds(
        element.left,
        element.top,
        element.right,
        element.bottom,
        sprite_address);
    if (art_id.empty()) {
        return;
    }
    StoreCapturedMenuArt(std::move(element));
}

void __fastcall HookMenuSpriteCenteredDraw(
    void* self,
    void* /*unused_edx*/,
    float x,
    float y) {
    ObserveMenuSpritePositionDraw(self, x, y, true);
    const auto original = GetX86HookTrampoline<SpritePositionDrawFn>(
        g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
    if (original != nullptr) {
        original(self, x, y);
    }
}

void __fastcall HookMenuSpriteTransformDraw(
    void* self,
    void* /*unused_edx*/,
    const float* transform) {
    ObserveMenuSpriteTransformDraw(self, transform);
    const auto original = GetX86HookTrampoline<SpriteTransformDrawFn>(
        g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
    if (original != nullptr) {
        original(self, transform);
    }
}

void __fastcall HookSettingsScalarRow(
    void* self,
    void* /*unused_edx*/,
    NativeUiString label,
    void* value) {
    BeginSettingsRowCapture(
        label,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original = GetX86HookTrampoline<SettingsValueRowFn>(
        g_debug_ui_overlay_state.settings_scalar_row_hook);
    if (original != nullptr) {
        original(self, label, value);
    }
    EndSettingsRowCapture();
}

void __fastcall HookSettingsToggleRow(
    void* self,
    void* /*unused_edx*/,
    NativeUiString label,
    void* value) {
    BeginSettingsRowCapture(
        label,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original = GetX86HookTrampoline<SettingsValueRowFn>(
        g_debug_ui_overlay_state.settings_toggle_row_hook);
    if (original != nullptr) {
        original(self, label, value);
    }
    EndSettingsRowCapture();
}

uintptr_t __fastcall HookSettingsSectionRow(
    void* self,
    void* /*unused_edx*/,
    NativeUiString label,
    uintptr_t arg3,
    uintptr_t arg4,
    uintptr_t arg5) {
    BeginSettingsRowCapture(
        label,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original = GetX86HookTrampoline<SettingsSectionRowFn>(
        g_debug_ui_overlay_state.settings_section_row_hook);
    const auto result = original == nullptr
        ? uintptr_t{0}
        : original(self, label, arg3, arg4, arg5);
    EndSettingsRowCapture();
    return result;
}

uintptr_t __fastcall HookSettingsSingleStringRow(
    void* self,
    void* /*unused_edx*/,
    NativeUiString label) {
    BeginSettingsRowCapture(
        label,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original =
        GetX86HookTrampoline<SettingsSingleStringRowFn>(
            g_debug_ui_overlay_state.settings_single_string_row_hook);
    const auto result = original == nullptr
        ? uintptr_t{0}
        : original(self, label);
    EndSettingsRowCapture();
    return result;
}

uintptr_t __fastcall HookSettingsDualStringRow(
    void* self,
    void* /*unused_edx*/,
    NativeUiString label,
    NativeUiString detail,
    void* value) {
    BeginSettingsRowCapture(
        label,
        reinterpret_cast<uintptr_t>(_ReturnAddress()));
    const auto original =
        GetX86HookTrampoline<SettingsDualStringRowFn>(
            g_debug_ui_overlay_state.settings_dual_string_row_hook);
    const auto result = original == nullptr
        ? uintptr_t{0}
        : original(self, label, detail, value);
    EndSettingsRowCapture();
    return result;
}

std::vector<CapturedMenuArtElement> TakeCapturedMenuArtFrame() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto result = std::move(
        g_debug_ui_overlay_state.frame_menu_art_elements);
    g_debug_ui_overlay_state.frame_menu_art_elements.clear();
    g_native_menu_art_draw_order = 0;
    return result;
}

std::string LowerAsciiCopy(std::string_view value) {
    std::string result(value);
    std::transform(
        result.begin(),
        result.end(),
        result.begin(),
        [](unsigned char character) {
            return static_cast<char>(std::tolower(character));
        });
    return result;
}

bool ContainsObservedText(
    const std::vector<ObservedUiElement>& elements,
    std::string_view expected) {
    const auto normalized_expected = LowerAsciiCopy(expected);
    return std::any_of(
        elements.begin(),
        elements.end(),
        [&](const ObservedUiElement& element) {
            return LowerAsciiCopy(element.label).find(normalized_expected) !=
                std::string::npos;
        });
}

std::string ResolveCapturedLayoutScreenId(
    const std::vector<OverlayRenderElement>& semantic_elements,
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<CapturedMenuArtElement>& art_elements) {
    const auto semantic_root = semantic_elements.empty()
        ? std::string{}
        : GetOverlaySurfaceRootId(semantic_elements.front().surface_id);
    if (semantic_root == "dialog" &&
        ContainsObservedText(exact_text_elements, "beta version v.0.72")) {
        return "beta_notice";
    }
    struct TextScreen {
        const char* text;
        const char* screen_id;
    };
    constexpr TextScreen kTextScreens[] = {
        {"select a control scheme", "control_scheme_picker"},
        {"search cloud for boneyards", "dark_cloud_search"},
        {"sort levels by", "dark_cloud_sort"},
        {"level options", "dark_cloud_options"},
        {"dark cloud settings", "dark_cloud_settings"},
        {"customize keyboard", "controls"},
        {"tweak performance", "performance"},
        {"hall of fame", "hall_of_fame"},
        {"game over", "game_over"},
    };
    for (const auto& candidate : kTextScreens) {
        if (ContainsObservedText(exact_text_elements, candidate.text)) {
            return candidate.screen_id;
        }
    }
    if (semantic_root == "create") {
        const auto has_art = [&](std::string_view art_id) {
            return std::any_of(
                art_elements.begin(),
                art_elements.end(),
                [&](const CapturedMenuArtElement& element) {
                    return element.visible && element.art_id == art_id;
                });
        };
        if (has_art("Create.9")) {
            return "create_element";
        }
        if (has_art("Create.16")) {
            return "create_discipline";
        }
    }
    if (std::any_of(
            semantic_elements.begin(),
            semantic_elements.end(),
            [](const OverlayRenderElement& element) {
                return element.action_id.rfind("pause_menu.", 0) == 0;
            })) {
        return "pause_menu";
    }
    if (!semantic_root.empty()) {
        return semantic_root;
    }
    return {};
}

std::string SlugifyLayoutToken(std::string_view token) {
    std::string result;
    bool previous_separator = false;
    for (const auto character : token) {
        const auto byte = static_cast<unsigned char>(character);
        if (std::isalnum(byte) != 0) {
            result.push_back(static_cast<char>(std::tolower(byte)));
            previous_separator = false;
        } else if (!result.empty() && !previous_separator) {
            result.push_back('_');
            previous_separator = true;
        }
    }
    while (!result.empty() && result.back() == '_') {
        result.pop_back();
    }
    return result.empty() ? std::string("element") : result;
}

void StoreLatestMenuLayoutSnapshotUnlocked(
    DebugUiOverlayState* state,
    const std::vector<OverlayRenderElement>& semantic_elements,
    const std::vector<ObservedUiElement>& exact_text_elements,
    const std::vector<CapturedMenuArtElement>& art_elements) {
    if (state == nullptr || !state->menu_layout_capture_enabled) {
        return;
    }

    DebugUiLayoutSnapshot snapshot;
    snapshot.generation = state->latest_surface_snapshot_generation;
    snapshot.captured_at_milliseconds = GetTickCount64();
    snapshot.screen_id = ResolveCapturedLayoutScreenId(
        semantic_elements,
        exact_text_elements,
        art_elements);
    if (!semantic_elements.empty()) {
        snapshot.screen_title = semantic_elements.front().surface_title;
    }
    snapshot.capture_method =
        "live native UI tree + exact text/font hooks + native Sprite draw hooks";
    snapshot.elements.reserve(
        semantic_elements.size() + exact_text_elements.size() +
        art_elements.size());

    for (const auto& source : semantic_elements) {
        DebugUiLayoutElement element;
        const auto lowered_surface = LowerAsciiCopy(source.surface_id);
        element.kind =
            lowered_surface.size() >= 6 &&
                lowered_surface.compare(
                    lowered_surface.size() - 6,
                    6,
                    ".panel") == 0
            ? "panel"
            : (!source.action_id.empty() ? "control" : "text");
        element.text = source.label;
        element.action_id = source.action_id;
        element.source_object_ptr = source.source_object_ptr;
        element.interactive = !source.action_id.empty();
        element.left = source.left;
        element.top = source.top;
        element.right = source.right;
        element.bottom = source.bottom;
        element.unclipped_left = source.left;
        element.unclipped_top = source.top;
        element.unclipped_right = source.right;
        element.unclipped_bottom = source.bottom;
        snapshot.elements.push_back(std::move(element));
    }

    for (const auto& source : exact_text_elements) {
        if (source.label.empty() ||
            source.max_x <= source.min_x ||
            source.max_y <= source.min_y) {
            continue;
        }
        DebugUiLayoutElement element;
        if (source.surface_id == "settings") {
            element.action_id = ResolveConfiguredUiActionId(
                "settings",
                source.label);
        }
        element.kind = element.action_id.empty() ? "text" : "control";
        element.text = source.label;
        element.font_id = source.font_id;
        element.text_style = source.font_id.empty()
            ? "native_atlas_text"
            : "native_atlas_text:" + source.font_id;
        element.source_object_ptr = source.object_ptr;
        element.interactive = !element.action_id.empty();
        element.left = source.min_x;
        element.top = source.min_y;
        element.right = source.max_x;
        element.bottom = source.max_y;
        element.unclipped_left = source.min_x;
        element.unclipped_top = source.min_y;
        element.unclipped_right = source.max_x;
        element.unclipped_bottom = source.max_y;
        snapshot.elements.push_back(std::move(element));
    }

    for (const auto& source : art_elements) {
        DebugUiLayoutElement element;
        element.kind = "art";
        element.art_id = source.art_id;
        element.text_style = source.draw_kind;
        element.source_object_ptr = source.source_object_ptr;
        element.visible = source.visible;
        element.draw_order = source.draw_order;
        element.left = source.left;
        element.top = source.top;
        element.right = source.right;
        element.bottom = source.bottom;
        element.unclipped_left = source.unclipped_left;
        element.unclipped_top = source.unclipped_top;
        element.unclipped_right = source.unclipped_right;
        element.unclipped_bottom = source.unclipped_bottom;
        snapshot.elements.push_back(std::move(element));
    }

    std::stable_sort(
        snapshot.elements.begin(),
        snapshot.elements.end(),
        [](const DebugUiLayoutElement& left,
           const DebugUiLayoutElement& right) {
            if (left.kind != right.kind) {
                return left.kind < right.kind;
            }
            if (left.top != right.top) {
                return left.top < right.top;
            }
            if (left.left != right.left) {
                return left.left < right.left;
            }
            if (left.art_id != right.art_id) {
                return left.art_id < right.art_id;
            }
            return left.text < right.text;
        });

    std::unordered_map<std::string, std::uint32_t> id_counts;
    for (auto& element : snapshot.elements) {
        const auto token = !element.art_id.empty()
            ? element.art_id
            : (!element.action_id.empty() ? element.action_id : element.text);
        const auto id_base =
            SlugifyLayoutToken(snapshot.screen_id) + "." + element.kind +
            "." + SlugifyLayoutToken(token);
        const auto ordinal = ++id_counts[id_base];
        element.id = id_base + "." + std::to_string(ordinal);
    }

    if (!snapshot.screen_id.empty() && !snapshot.elements.empty()) {
        state->layout_snapshots_by_screen[snapshot.screen_id] = snapshot;
    }
    state->latest_layout_snapshot = std::move(snapshot);
}

std::string JsonEscapeMenuCapture(std::string_view value) {
    std::ostringstream output;
    for (const auto character : value) {
        switch (character) {
            case '\\': output << "\\\\"; break;
            case '"': output << "\\\""; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default: output << character; break;
        }
    }
    return output.str();
}

void WriteNativeBootCaptureJson() {
    if (g_native_boot_capture_directory.empty()) {
        return;
    }
    std::error_code error;
    std::filesystem::create_directories(
        g_native_boot_capture_directory,
        error);
    if (error) {
        return;
    }

    const auto output_path =
        g_native_boot_capture_directory / "native-loader-layout.json";
    std::ofstream output(output_path, std::ios::trunc);
    if (!output) {
        return;
    }

    char pipe_name[512] = {};
    GetEnvironmentVariableA(
        "SDMOD_LUA_EXEC_PIPE_NAME",
        pipe_name,
        static_cast<DWORD>(sizeof(pipe_name)));
    output << "{\n"
           << "  \"schema\": \"solomon-dark-native-loader-capture-v1\",\n"
           << "  \"instance\": \"" << JsonEscapeMenuCapture(pipe_name) << "\",\n"
           << "  \"process_id\": " << GetCurrentProcessId() << ",\n"
           << "  \"capture_method\": \"MyLoader render detour + live loader globals + native Sprite draw hooks + D3D9 backbuffer\",\n"
           << "  \"samples\": [\n";
    for (std::size_t sample_index = 0;
         sample_index < g_native_boot_capture_samples.size();
         ++sample_index) {
        const auto& sample = g_native_boot_capture_samples[sample_index];
        output << "    {\"elapsed_milliseconds\": "
               << sample.elapsed_milliseconds
               << ", \"numerator\": " << sample.numerator
               << ", \"denominator\": " << sample.denominator
               << ", \"complete\": " << (sample.complete ? "true" : "false")
               << ", \"progress\": " << std::fixed << std::setprecision(6)
               << sample.progress
               << ", \"reference_capture\": \""
               << JsonEscapeMenuCapture(sample.reference_capture)
               << "\", \"elements\": [";
        for (std::size_t element_index = 0;
             element_index < sample.elements.size();
             ++element_index) {
            const auto& element = sample.elements[element_index];
            if (element_index != 0) {
                output << ',';
            }
            output << "{\"art_id\": \""
                   << JsonEscapeMenuCapture(element.art_id)
                   << "\", \"draw_kind\": \""
                   << JsonEscapeMenuCapture(element.draw_kind)
                   << "\", \"rect\": ["
                   << element.left << ',' << element.top << ','
                   << element.right << ',' << element.bottom
                   << "], \"unclipped_rect\": ["
                   << element.unclipped_left << ','
                   << element.unclipped_top << ','
                   << element.unclipped_right << ','
                   << element.unclipped_bottom << "]}";
        }
        output << "]}";
        if (sample_index + 1 != g_native_boot_capture_samples.size()) {
            output << ',';
        }
        output << '\n';
    }
    output << "  ]\n}\n";
}

void CaptureNativeLoaderSample() {
    if (g_native_boot_capture_directory.empty()) {
        return;
    }
    auto& memory = ProcessMemory::Instance();
    const auto numerator_address =
        memory.ResolveGameAddressOrZero(kNativeLoaderProgressNumerator);
    const auto denominator_address =
        memory.ResolveGameAddressOrZero(kNativeLoaderProgressDenominator);
    const auto complete_address =
        memory.ResolveGameAddressOrZero(kNativeLoaderCompleteFlag);
    NativeBootCaptureSample sample;
    std::uint8_t complete = 0;
    if (numerator_address == 0 || denominator_address == 0 ||
        complete_address == 0 ||
        !memory.TryReadValue(numerator_address, &sample.numerator) ||
        !memory.TryReadValue(denominator_address, &sample.denominator) ||
        !memory.TryReadValue(complete_address, &complete)) {
        return;
    }
    if (g_native_boot_capture_started_at == 0) {
        g_native_boot_capture_started_at = GetTickCount64();
    }
    sample.elapsed_milliseconds =
        GetTickCount64() - g_native_boot_capture_started_at;
    sample.complete = complete != 0;
    sample.progress = sample.complete
        ? 1.0
        : (sample.denominator == 0
               ? 0.0
               : (std::min)(
                     1.0,
                     static_cast<double>(sample.numerator) /
                         static_cast<double>(sample.denominator)));

    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        sample.elements = g_native_loader_frame_art;
    }

    const auto progress_bucket =
        static_cast<int>(std::lround(sample.progress * 1000.0));
    const auto should_capture_reference =
        g_native_boot_last_reference_bucket < 0 ||
        progress_bucket >= g_native_boot_last_reference_bucket + 50 ||
        (sample.complete && g_native_boot_last_reference_bucket < 1000);
    if (should_capture_reference &&
        g_native_boot_capture_samples.size() < 128) {
        std::ostringstream filename;
        filename << "native-loader-" << std::setw(3) << std::setfill('0')
                 << g_native_boot_capture_samples.size() << "-p"
                 << std::setw(4) << progress_bucket << ".bmp";
        const auto path = g_native_boot_capture_directory / filename.str();
        std::string capture_error;
        if (CaptureD3d9BackBufferBmp(path.wstring(), &capture_error)) {
            sample.reference_capture = filename.str();
            g_native_boot_last_reference_bucket = progress_bucket;
        }
    }
    g_native_boot_capture_samples.push_back(std::move(sample));
    WriteNativeBootCaptureJson();
}

void __fastcall HookNativeLoaderRender(
    void* self,
    void* /*unused_edx*/) {
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_native_loader_frame_art.clear();
        g_native_loader_render_active = true;
    }
    RebuildNativeMenuArtResolver();
    const auto original = GetX86HookTrampoline<MyLoaderRenderFn>(
        g_debug_ui_overlay_state.native_loader_render_hook);
    if (original != nullptr) {
        original(self);
    }
    {
        std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
        g_native_loader_render_active = false;
    }
    CaptureNativeLoaderSample();
}

bool IsTruthyMenuCaptureEnvironment(const char* name) {
    char value[16] = {};
    const auto length = GetEnvironmentVariableA(
        name,
        value,
        static_cast<DWORD>(sizeof(value)));
    if (length == 0 || length >= sizeof(value)) {
        return false;
    }
    const auto normalized = LowerAsciiCopy(value);
    return normalized == "1" || normalized == "true" ||
        normalized == "yes" || normalized == "on";
}

bool InstallMenuLayoutCaptureHooks(std::string* error_message) {
    char boot_directory[32768] = {};
    const auto boot_directory_length = GetEnvironmentVariableA(
        "SDMOD_NATIVE_BOOT_CAPTURE_DIRECTORY",
        boot_directory,
        static_cast<DWORD>(sizeof(boot_directory)));
    if (boot_directory_length > 0 &&
        boot_directory_length < sizeof(boot_directory)) {
        g_native_boot_capture_directory = boot_directory;
    }
    const auto requested =
        IsTruthyMenuCaptureEnvironment(
            "SDMOD_NATIVE_MENU_LAYOUT_CAPTURE") ||
        !g_native_boot_capture_directory.empty();
    g_debug_ui_overlay_state.menu_layout_capture_enabled = requested;
    if (!requested) {
        return true;
    }

    auto& memory = ProcessMemory::Instance();
    const auto centered = memory.ResolveGameAddressOrZero(
        kNativeSpriteCenteredDrawAddress);
    const auto transformed = memory.ResolveGameAddressOrZero(
        kNativeSpriteTransformDrawAddress);
    const auto loader = memory.ResolveGameAddressOrZero(
        kNativeLoaderRenderAddress);
    const auto settings_scalar = memory.ResolveGameAddressOrZero(
        kSettingsScalarRowAddress);
    const auto settings_toggle = memory.ResolveGameAddressOrZero(
        kSettingsToggleRowAddress);
    const auto settings_section = memory.ResolveGameAddressOrZero(
        kSettingsSectionRowAddress);
    const auto settings_single = memory.ResolveGameAddressOrZero(
        kSettingsSingleStringRowAddress);
    const auto settings_dual = memory.ResolveGameAddressOrZero(
        kSettingsDualStringRowAddress);
    if (centered == 0 || transformed == 0 || loader == 0 ||
        settings_scalar == 0 || settings_toggle == 0 ||
        settings_section == 0 || settings_single == 0 ||
        settings_dual == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Could not resolve native menu-layout capture targets.";
        }
        return false;
    }

    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(centered),
            reinterpret_cast<void*>(&HookMenuSpriteCenteredDraw),
            5,
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook,
            error_message)) {
        return false;
    }
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(transformed),
            reinterpret_cast<void*>(&HookMenuSpriteTransformDraw),
            5,
            &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook,
            error_message)) {
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
        return false;
    }
    if (!g_native_boot_capture_directory.empty() &&
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(loader),
            reinterpret_cast<void*>(&HookNativeLoaderRender),
            5,
            &g_debug_ui_overlay_state.native_loader_render_hook,
            error_message)) {
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
        return false;
    }
    const auto remove_capture_hooks = []() {
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_dual_string_row_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_single_string_row_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_section_row_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_toggle_row_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.settings_scalar_row_hook);
        RemoveX86Hook(&g_debug_ui_overlay_state.native_loader_render_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
        RemoveX86Hook(
            &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
    };
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_scalar),
            reinterpret_cast<void*>(&HookSettingsScalarRow),
            5,
            &g_debug_ui_overlay_state.settings_scalar_row_hook,
            error_message) ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_toggle),
            reinterpret_cast<void*>(&HookSettingsToggleRow),
            5,
            &g_debug_ui_overlay_state.settings_toggle_row_hook,
            error_message) ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_section),
            reinterpret_cast<void*>(&HookSettingsSectionRow),
            5,
            &g_debug_ui_overlay_state.settings_section_row_hook,
            error_message) ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_single),
            reinterpret_cast<void*>(&HookSettingsSingleStringRow),
            5,
            &g_debug_ui_overlay_state.settings_single_string_row_hook,
            error_message) ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(settings_dual),
            reinterpret_cast<void*>(&HookSettingsDualStringRow),
            5,
            &g_debug_ui_overlay_state.settings_dual_string_row_hook,
            error_message)) {
        remove_capture_hooks();
        return false;
    }
    RebuildNativeMenuArtResolver();
    return true;
}

void RemoveMenuLayoutCaptureHooks() {
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_dual_string_row_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_single_string_row_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_section_row_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_toggle_row_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.settings_scalar_row_hook);
    RemoveX86Hook(&g_debug_ui_overlay_state.native_loader_render_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.menu_sprite_transform_draw_hook);
    RemoveX86Hook(
        &g_debug_ui_overlay_state.menu_sprite_centered_draw_hook);
}

void ResetMenuLayoutCaptureStateUnlocked(DebugUiOverlayState* state) {
    if (state == nullptr) {
        return;
    }
    state->menu_sprite_centered_draw_hook = X86Hook{};
    state->menu_sprite_transform_draw_hook = X86Hook{};
    state->native_loader_render_hook = X86Hook{};
    state->settings_scalar_row_hook = X86Hook{};
    state->settings_toggle_row_hook = X86Hook{};
    state->settings_section_row_hook = X86Hook{};
    state->settings_single_string_row_hook = X86Hook{};
    state->settings_dual_string_row_hook = X86Hook{};
    state->menu_layout_capture_enabled = false;
    state->frame_menu_art_elements.clear();
    state->latest_layout_snapshot = DebugUiLayoutSnapshot{};
    state->layout_snapshots_by_screen.clear();
    g_native_menu_art_by_address.clear();
    g_native_menu_art_by_signature.clear();
    g_native_menu_art_cache_built_at = 0;
    g_native_menu_art_draw_order = 0;
    g_native_boot_capture_directory.clear();
    g_native_boot_capture_samples.clear();
    g_native_boot_capture_started_at = 0;
    g_native_boot_last_reference_bucket = -1;
    g_native_loader_render_active = false;
    g_native_loader_frame_art.clear();
    g_active_settings_row_captures.clear();
}
