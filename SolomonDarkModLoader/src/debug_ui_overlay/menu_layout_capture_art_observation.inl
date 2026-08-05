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

std::vector<CapturedMenuArtElement> TakeCapturedMenuArtFrame() {
    std::scoped_lock lock(g_debug_ui_overlay_state.mutex);
    auto result = std::move(
        g_debug_ui_overlay_state.frame_menu_art_elements);
    g_debug_ui_overlay_state.frame_menu_art_elements.clear();
    g_native_menu_art_draw_order = 0;
    return result;
}

