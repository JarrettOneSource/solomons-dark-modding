// Included by lua_world_renderer.cpp inside its anonymous namespace.

void ReleaseNativeAtlasTexture(NativeAtlasTexture* texture) {
    if (texture == nullptr || texture->handle < 0) {
        return;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer != nullptr &&
        g_world_renderer.native_texture_release != nullptr) {
        g_world_renderer.native_texture_release(renderer, texture->handle);
    }
    texture->handle = -1;
    texture->width = 0;
    texture->height = 0;
    texture->page_record = {};
}

void ResetNativeAtlasTexture(
    NativeAtlasTexture* texture,
    std::filesystem::path source_path,
    std::uint64_t revision) {
    if (texture == nullptr) {
        return;
    }
    ReleaseNativeAtlasTexture(texture);
    *texture = {};
    texture->source_path = std::move(source_path);
    texture->revision = revision;
}

void PruneNativeAtlasTextures() {
    for (auto iterator = g_world_renderer.atlas_textures.begin();
         iterator != g_world_renderer.atlas_textures.end();) {
        std::filesystem::path source_path;
        std::uint64_t revision = 0;
        if (TryGetLuaDrawAtlasSource(
                iterator->first,
                &source_path,
                &revision) &&
            source_path == iterator->second->source_path &&
            revision == iterator->second->revision) {
            ++iterator;
            continue;
        }
        ReleaseNativeAtlasTexture(iterator->second.get());
        iterator = g_world_renderer.atlas_textures.erase(iterator);
    }
}

NativeAtlasTexture* GetNativeAtlasTexture(
    const std::string& canonical_atlas) {
    std::filesystem::path source_path;
    std::uint64_t revision = 0;
    if (!TryGetLuaDrawAtlasSource(
            canonical_atlas,
            &source_path,
            &revision) ||
        source_path.empty() || revision == 0) {
        return nullptr;
    }

    auto& texture_slot = g_world_renderer.atlas_textures[canonical_atlas];
    if (texture_slot == nullptr) {
        texture_slot = std::make_unique<NativeAtlasTexture>();
    }
    auto* texture = texture_slot.get();
    if (texture->source_path != source_path ||
        texture->revision != revision) {
        ResetNativeAtlasTexture(texture, source_path, revision);
    }
    if (texture->load_attempted) {
        return texture->handle < 0 ? nullptr : texture;
    }
    texture->load_attempted = true;

    std::vector<std::uint8_t> pixels;
    if (!detail::DecodeLuaDrawTextureBgra(
            texture->source_path,
            &pixels,
            &texture->width,
            &texture->height,
            &texture->error_message)) {
        LogWorldRenderFailure(
            "native atlas decode failed. atlas=" + canonical_atlas +
            " error=" + texture->error_message);
        return nullptr;
    }
    if (texture->width == 0 || texture->height == 0 || pixels.empty() ||
        g_world_renderer.native_texture_upload_bgra == nullptr ||
        g_world_renderer.native_texture_critical_section == nullptr ||
        g_world_renderer.native_texture_critical_section_initialized ==
            nullptr) {
        texture->error_message = "native texture upload seams are unavailable";
        LogWorldRenderFailure(
            "native atlas upload failed. atlas=" + canonical_atlas +
            " error=" + texture->error_message);
        return nullptr;
    }

    if (*g_world_renderer.native_texture_critical_section_initialized == 0) {
        InitializeCriticalSection(
            g_world_renderer.native_texture_critical_section);
        *g_world_renderer.native_texture_critical_section_initialized = 1;
    }
    EnterCriticalSection(g_world_renderer.native_texture_critical_section);
    texture->handle = g_world_renderer.native_texture_upload_bgra(
        static_cast<int>(texture->width),
        static_cast<int>(texture->height),
        pixels.data(),
        0);
    LeaveCriticalSection(g_world_renderer.native_texture_critical_section);
    if (texture->handle < 0) {
        texture->error_message = "stock BGRA uploader returned no texture slot";
        LogWorldRenderFailure(
            "native atlas upload failed. atlas=" + canonical_atlas +
            " error=" + texture->error_message);
        return nullptr;
    }

    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr ||
        g_world_renderer.native_render_page_register == nullptr) {
        texture->error_message = "stock renderer page table is unavailable";
        ReleaseNativeAtlasTexture(texture);
        LogWorldRenderFailure(
            "native atlas registration failed. atlas=" + canonical_atlas +
            " error=" + texture->error_message);
        return nullptr;
    }
    WriteNativeField(
        texture->page_record.data(),
        kNativePageHandleOffset,
        texture->handle);
    g_world_renderer.native_render_page_register(
        renderer,
        texture->page_record.data());
    return texture;
}

bool WriteNativeUv(
    const LuaDrawSpriteInfo& sprite,
    const NativeAtlasTexture& texture,
    NativeWorldGlyph* glyph,
    std::string* error_message) {
    if (glyph == nullptr || texture.width == 0 || texture.height == 0 ||
        sprite.atlas_x < 0.0f || sprite.atlas_y < 0.0f ||
        sprite.packed_width <= 0.0f || sprite.packed_height <= 0.0f ||
        sprite.atlas_x + sprite.packed_width > texture.width ||
        sprite.atlas_y + sprite.packed_height > texture.height) {
        SetError(error_message, "World sprite rectangle is outside its atlas.");
        return false;
    }

    const float u0 =
        (sprite.atlas_x + kNativeUvHalfTexel) / texture.width;
    const float v0 =
        (sprite.atlas_y + kNativeUvHalfTexel) / texture.height;
    const float u1 =
        (sprite.atlas_x + sprite.packed_width - kNativeUvHalfTexel) /
        texture.width;
    const float v1 =
        (sprite.atlas_y + sprite.packed_height - kNativeUvHalfTexel) /
        texture.height;
    const std::array<float, 8> uv = {
        u0, v0,
        u1, v0,
        u0, v1,
        u1, v1,
    };
    WriteNativeField(
        glyph->bytes.data(),
        kNativeSpriteUvOffset,
        uv);
    return true;
}

bool BuildNativeWorldGlyph(
    const LuaWorldSpriteCommand& command,
    NativeWorldGlyph* glyph,
    std::array<float, 4>* bounds,
    std::string* error_message) {
    if (glyph == nullptr || bounds == nullptr || error_message == nullptr) {
        return false;
    }
    LuaDrawSpriteInfo sprite;
    std::string canonical_atlas;
    if (!TryGetLuaDrawSpriteInfo(
            command.atlas,
            command.sprite_index,
            &sprite,
            &canonical_atlas,
            error_message) ||
        sprite.rotated || sprite.logical_width <= 0 ||
        sprite.logical_height == 0) {
        return false;
    }
    auto* texture = GetNativeAtlasTexture(canonical_atlas);
    if (texture == nullptr) {
        SetError(error_message, "Native world atlas texture is unavailable.");
        return false;
    }

    const float logical_width = static_cast<float>(sprite.logical_width);
    const float logical_height = static_cast<float>(sprite.logical_height);
    const float scale_x = command.width / logical_width;
    const float scale_y = command.height / logical_height;
    const float trim_x =
        (logical_width - sprite.content_width) * 0.5f +
        sprite.center_offset_x;
    const float trim_y =
        (logical_height - sprite.content_height) * 0.5f +
        sprite.center_offset_y;
    const float left =
        -command.width * 0.5f + trim_x * scale_x + command.offset_x;
    const float top =
        -command.height * 0.5f + trim_y * scale_y + command.offset_y;
    const float right = left + sprite.packed_width * scale_x;
    const float bottom = top + sprite.packed_height * scale_y;
    if (!std::isfinite(left) || !std::isfinite(top) ||
        !std::isfinite(right) || !std::isfinite(bottom)) {
        SetError(error_message, "World sprite generated non-finite geometry.");
        return false;
    }

    *glyph = {};
    const std::uint8_t valid = 1;
    WriteNativeField(
        glyph->bytes.data(),
        kNativeSpriteValidOffset,
        valid);
    WriteNativeField(
        glyph->bytes.data(),
        kNativeSpriteTextureHandleOffset,
        texture->handle);
    const std::array<float, 8> geometry = {
        left, top,
        right, top,
        left, bottom,
        right, bottom,
    };
    WriteNativeField(
        glyph->bytes.data(),
        kNativeSpriteGeometryOffset,
        geometry);
    if (!WriteNativeUv(sprite, *texture, glyph, error_message)) {
        return false;
    }
    *bounds = {left, top, right, bottom};
    return true;
}
