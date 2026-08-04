// Included by lua_world_renderer.cpp inside namespace sdmod.
// Public presentation API backed by the stock native renderer and world queue.

bool DrawNativeWorldIndicatorHealthBar(
    float center_x,
    float top,
    float width,
    float health_ratio) {
    if (!std::isfinite(center_x) || !std::isfinite(top) ||
        !std::isfinite(width) || width < 4.0f ||
        !std::isfinite(health_ratio)) {
        return false;
    }
    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.native_renderer_set_color == nullptr ||
        g_world_renderer.native_untextured_quad == nullptr) {
        return false;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr) {
        return false;
    }

    constexpr float kHeight = 7.0f;
    constexpr float kInset = 1.0f;
    constexpr NativeWorldIndicatorColor kBorder{12, 6, 6, 235};
    constexpr NativeWorldIndicatorColor kEmpty{54, 13, 13, 220};
    constexpr NativeWorldIndicatorColor kHealth{190, 31, 24, 240};
    constexpr NativeWorldIndicatorColor kHighlight{255, 105, 78, 210};
    const float left = center_x - width * 0.5f;
    const float inner_width = width - kInset * 2.0f;
    const float fill_width = inner_width *
        std::clamp(health_ratio, 0.0f, 1.0f);
    const auto previous_color = ReadNativeRendererBaseColor(renderer);
    DrawNativeIndicatorQuadUnlocked(
        renderer, left, top, width, kHeight, kBorder);
    DrawNativeIndicatorQuadUnlocked(
        renderer,
        left + kInset,
        top + kInset,
        inner_width,
        kHeight - kInset * 2.0f,
        kEmpty);
    if (fill_width > 0.0f) {
        DrawNativeIndicatorQuadUnlocked(
            renderer,
            left + kInset,
            top + kInset,
            fill_width,
            kHeight - kInset * 2.0f,
            kHealth);
        DrawNativeIndicatorQuadUnlocked(
            renderer,
            left + kInset,
            top + kInset,
            fill_width,
            1.0f,
            kHighlight);
    }
    RestoreNativeRendererColor(renderer, previous_color);
    return true;
}

bool DrawNativeScreenQuad(
    float left,
    float top,
    float width,
    float height,
    const NativeWorldIndicatorColor& color) {
    if (!std::isfinite(left) || !std::isfinite(top) ||
        !std::isfinite(width) || !std::isfinite(height) ||
        width <= 0.0f || height <= 0.0f) {
        return false;
    }
    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.native_renderer_set_color == nullptr ||
        g_world_renderer.native_untextured_quad == nullptr) {
        return false;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr) {
        return false;
    }
    const auto previous_color = ReadNativeRendererBaseColor(renderer);
    DrawNativeIndicatorQuadUnlocked(renderer, left, top, width, height, color);
    RestoreNativeRendererColor(renderer, previous_color);
    return true;
}

void QueueNativeWorldDampenPresentation(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence,
    float x,
    float y) {
    if (owner_participant_id == 0 || cast_sequence == 0 ||
        !std::isfinite(x) || !std::isfinite(y)) {
        return;
    }
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (!g_world_renderer.initialized) {
            return;
        }
        auto& presentations = g_world_renderer.dampen_presentations;
        const auto duplicate = std::find_if(
            presentations.begin(),
            presentations.end(),
            [&](const NativeWorldDampenPresentation& presentation) {
                return presentation.owner_participant_id ==
                           owner_participant_id &&
                    presentation.cast_sequence == cast_sequence;
            });
        if (duplicate != presentations.end()) {
            return;
        }
        if (presentations.size() == kDampenPresentationLimit) {
            presentations.erase(presentations.begin());
        }
        presentations.push_back(NativeWorldDampenPresentation{
            owner_participant_id,
            cast_sequence,
            x,
            y,
            GetTickCount64(),
            false,
        });
    }
    Log(
        "Multiplayer Dampen native world presentation queued. "
        "owner_participant_id=" +
        std::to_string(owner_participant_id) +
        " cast_sequence=" + std::to_string(cast_sequence) +
        " xy=(" + std::to_string(x) + "," + std::to_string(y) + ")");
}

bool QueueNativeWorldConsumableVfxPresentation(
    std::string_view mod_id,
    std::uint64_t content_id,
    std::uint64_t participant_id,
    std::uint64_t use_id,
    std::uint32_t duration_ms,
    const std::array<float, 4>& color) {
    if (mod_id.empty() || content_id == 0 || participant_id == 0 ||
        use_id == 0 || duration_ms == 0 ||
        !std::all_of(
            color.begin(),
            color.end(),
            [](float component) {
                return std::isfinite(component) &&
                    component >= 0.0f && component <= 1.0f;
            })) {
        return false;
    }
    const auto started_at = GetTickCount64();
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (!g_world_renderer.initialized) {
            return false;
        }
        auto& presentations =
            g_world_renderer.consumable_vfx_presentations;
        const auto duplicate = std::find_if(
            presentations.begin(),
            presentations.end(),
            [&](const NativeWorldConsumableVfxPresentation& presentation) {
                return presentation.participant_id == participant_id &&
                    presentation.use_id == use_id;
            });
        if (duplicate != presentations.end()) {
            return true;
        }
        if (presentations.size() >= kConsumableVfxPresentationLimit) {
            return false;
        }
        presentations.push_back(NativeWorldConsumableVfxPresentation{
            std::string(mod_id),
            content_id,
            participant_id,
            use_id,
            color,
            started_at,
            started_at + duration_ms,
            false,
        });
    }
    Log(
        "lua_items: consumable VFX native carrier queued. content_id=" +
        std::to_string(content_id) +
        " participant_id=" + std::to_string(participant_id) +
        " use_id=" + std::to_string(use_id) +
        " duration_ms=" + std::to_string(duration_ms));
    return true;
}

void ClearNativeWorldConsumableVfxPresentationsForMod(
    std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }
    std::scoped_lock lock(g_world_renderer.mutex);
    auto& presentations = g_world_renderer.consumable_vfx_presentations;
    presentations.erase(
        std::remove_if(
            presentations.begin(),
            presentations.end(),
            [&](const NativeWorldConsumableVfxPresentation& presentation) {
                return presentation.mod_id == mod_id;
            }),
        presentations.end());
}

void ClearNativeWorldConsumableVfxPresentations() {
    std::scoped_lock lock(g_world_renderer.mutex);
    g_world_renderer.consumable_vfx_presentations.clear();
}

bool DrawLuaSpriteWithStockGeometry(
    std::string_view atlas,
    std::uint32_t sprite_index,
    const void* stock_sprite,
    float x,
    float y,
    LuaNativeGlyphDrawFn draw,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (atlas.empty() || stock_sprite == nullptr || draw == nullptr ||
        error_message == nullptr || !std::isfinite(x) || !std::isfinite(y)) {
        return false;
    }

    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized) {
        SetError(error_message, "Native world renderer is not initialized.");
        return false;
    }
    std::string canonical_atlas;
    NativeWorldGlyph glyph;
    if (!PrepareLuaSpriteWithStockGeometry(
            atlas,
            sprite_index,
            stock_sprite,
            &glyph,
            &canonical_atlas,
            error_message)) {
        return false;
    }
    draw(glyph.bytes.data(), x, y);
    if (!g_world_renderer.logged_custom_stock_geometry_draw) {
        g_world_renderer.logged_custom_stock_geometry_draw = true;
        Log(
            "lua_world_render: custom glyph reached stock carrier draw batch. "
            "atlas=" + canonical_atlas +
            " record=" + std::to_string(sprite_index));
    }
    return true;
}

bool DrawLuaSpriteWithStockGeometryScaled(
    std::string_view atlas,
    std::uint32_t sprite_index,
    const void* stock_sprite,
    float x,
    float y,
    float scale,
    LuaNativeScaledGlyphDrawFn draw,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (atlas.empty() || stock_sprite == nullptr || draw == nullptr ||
        error_message == nullptr || !std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(scale)) {
        return false;
    }

    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized) {
        SetError(error_message, "Native world renderer is not initialized.");
        return false;
    }
    std::string canonical_atlas;
    NativeWorldGlyph glyph;
    if (!PrepareLuaSpriteWithStockGeometry(
            atlas,
            sprite_index,
            stock_sprite,
            &glyph,
            &canonical_atlas,
            error_message)) {
        return false;
    }
    draw(glyph.bytes.data(), x, y, scale);
    if (!g_world_renderer.logged_custom_inventory_draw) {
        g_world_renderer.logged_custom_inventory_draw = true;
        Log(
            "lua_world_render: custom inventory glyph reached stock scaled draw. "
            "atlas=" + canonical_atlas +
            " record=" + std::to_string(sprite_index));
    }
    return true;
}
