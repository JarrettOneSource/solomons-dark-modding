D3DCOLOR PackColor(const LuaDrawColor& color) {
    return D3DCOLOR_ARGB(
        color.alpha,
        color.red,
        color.green,
        color.blue);
}

void ReleaseRendererResourcesUnlocked() {
    ReleaseD3d9FontAtlas(&g_lua_draw_renderer.font.atlas);
    g_lua_draw_renderer.font = {};
    for (auto& [atlas, texture] : g_lua_draw_renderer.atlas_textures) {
        (void)atlas;
        if (texture.texture != nullptr) {
            texture.texture->Release();
        }
    }
    g_lua_draw_renderer.atlas_textures.clear();
    g_lua_draw_renderer.resource_device = nullptr;
}

void PruneUnavailableAtlasTextures() {
    for (auto iterator = g_lua_draw_renderer.atlas_textures.begin();
         iterator != g_lua_draw_renderer.atlas_textures.end();) {
        std::filesystem::path image_path;
        std::uint64_t revision = 0;
        if (TryGetLuaDrawAtlasSource(
                iterator->first,
                &image_path,
                &revision)) {
            ++iterator;
            continue;
        }
        if (iterator->second.texture != nullptr) {
            iterator->second.texture->Release();
        }
        iterator = g_lua_draw_renderer.atlas_textures.erase(iterator);
    }
}

bool ConfigureRenderState(IDirect3DDevice9* device) {
    bool ok = true;
#define SDMOD_SET_D3D_STATE(expression) ok = SUCCEEDED(expression) && ok
    SDMOD_SET_D3D_STATE(device->SetPixelShader(nullptr));
    SDMOD_SET_D3D_STATE(device->SetVertexShader(nullptr));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_ZENABLE, FALSE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_LIGHTING, FALSE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_FOGENABLE, FALSE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA));
    SDMOD_SET_D3D_STATE(device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA));
    SDMOD_SET_D3D_STATE(device->SetTextureStageState(1, D3DTSS_COLOROP, D3DTOP_DISABLE));
#undef SDMOD_SET_D3D_STATE
    return ok;
}

bool ConfigureUntexturedStage(IDirect3DDevice9* device) {
    return SUCCEEDED(device->SetTextureStageState(
               0, D3DTSS_COLOROP, D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_COLORARG1, D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE));
}

bool ConfigureTexturedStage(
    IDirect3DDevice9* device,
    D3DTEXTUREFILTERTYPE min_filter,
    D3DTEXTUREFILTERTYPE mag_filter) {
    return SUCCEEDED(device->SetTextureStageState(
               0, D3DTSS_COLOROP, D3DTOP_MODULATE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_COLORARG1, D3DTA_TEXTURE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_COLORARG2, D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_ALPHAOP, D3DTOP_MODULATE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetSamplerState(
            0, D3DSAMP_MINFILTER, min_filter)) &&
        SUCCEEDED(device->SetSamplerState(
            0, D3DSAMP_MAGFILTER, mag_filter)) &&
        SUCCEEDED(device->SetSamplerState(
            0, D3DSAMP_MIPFILTER, D3DTEXF_NONE));
}

enum class LuaDrawBatchMode {
    None,
    Color,
    PointText,
    LinearSprite,
};

class LuaDrawBatcher {
public:
    LuaDrawBatcher(
        IDirect3DDevice9* device,
        std::vector<LuaDrawColorVertex>& color_vertices,
        std::vector<LuaDrawTexturedVertex>& textured_vertices)
        : device_(device),
          color_vertices_(color_vertices),
          textured_vertices_(textured_vertices) {
        color_vertices_.clear();
        textured_vertices_.clear();
    }

    void BeginRun(
        LuaDrawBatchMode mode,
        IDirect3DTexture9* texture) {
        if (mode_ == mode && texture_ == texture) {
            return;
        }
        Flush();
        mode_ = mode;
        texture_ = texture;
    }

    void AppendColorQuad(
        float left,
        float top,
        float right,
        float bottom,
        D3DCOLOR color) {
        AppendColorQuad(
            {left, top, 0.0f, 1.0f, color},
            {right, top, 0.0f, 1.0f, color},
            {left, bottom, 0.0f, 1.0f, color},
            {right, bottom, 0.0f, 1.0f, color});
    }

    void AppendColorQuad(
        const LuaDrawColorVertex& top_left,
        const LuaDrawColorVertex& top_right,
        const LuaDrawColorVertex& bottom_left,
        const LuaDrawColorVertex& bottom_right) {
        color_vertices_.push_back(top_left);
        color_vertices_.push_back(top_right);
        color_vertices_.push_back(bottom_left);
        color_vertices_.push_back(bottom_left);
        color_vertices_.push_back(top_right);
        color_vertices_.push_back(bottom_right);
    }

    void AppendTexturedQuad(
        const LuaDrawTexturedVertex& top_left,
        const LuaDrawTexturedVertex& top_right,
        const LuaDrawTexturedVertex& bottom_left,
        const LuaDrawTexturedVertex& bottom_right) {
        textured_vertices_.push_back(top_left);
        textured_vertices_.push_back(top_right);
        textured_vertices_.push_back(bottom_left);
        textured_vertices_.push_back(bottom_left);
        textured_vertices_.push_back(top_right);
        textured_vertices_.push_back(bottom_right);
    }

    void CompleteCommand() {
        ++current_command_count_;
    }

    void RecordImmediateSuccess() {
        ++successful_command_count_;
    }

    bool Finish() {
        return Flush();
    }

    std::size_t successful_command_count() const {
        return successful_command_count_;
    }

    std::size_t failed_command_count() const {
        return failed_command_count_;
    }

private:
    bool Flush() {
        if (current_command_count_ == 0) {
            color_vertices_.clear();
            textured_vertices_.clear();
            mode_ = LuaDrawBatchMode::None;
            texture_ = nullptr;
            return true;
        }

        bool succeeded = false;
        if (mode_ == LuaDrawBatchMode::Color) {
            succeeded =
                ConfigureUntexturedStage(device_) &&
                SUCCEEDED(device_->SetFVF(kLuaDrawColorVertexFvf)) &&
                SUCCEEDED(device_->SetTexture(0, nullptr)) &&
                SUCCEEDED(device_->DrawPrimitiveUP(
                    D3DPT_TRIANGLELIST,
                    static_cast<UINT>(color_vertices_.size() / 3),
                    color_vertices_.data(),
                    sizeof(LuaDrawColorVertex)));
        } else {
            const bool point_text =
                mode_ == LuaDrawBatchMode::PointText;
            succeeded =
                ConfigureTexturedStage(
                    device_,
                    D3DTEXF_POINT,
                    point_text ? D3DTEXF_POINT : D3DTEXF_LINEAR) &&
                SUCCEEDED(device_->SetFVF(kLuaDrawTexturedVertexFvf)) &&
                SUCCEEDED(device_->SetTexture(0, texture_)) &&
                SUCCEEDED(device_->DrawPrimitiveUP(
                    D3DPT_TRIANGLELIST,
                    static_cast<UINT>(textured_vertices_.size() / 3),
                    textured_vertices_.data(),
                    sizeof(LuaDrawTexturedVertex)));
        }

        if (succeeded) {
            successful_command_count_ += current_command_count_;
        } else {
            failed_command_count_ += current_command_count_;
        }
        current_command_count_ = 0;
        color_vertices_.clear();
        textured_vertices_.clear();
        mode_ = LuaDrawBatchMode::None;
        texture_ = nullptr;
        return succeeded;
    }

    IDirect3DDevice9* device_ = nullptr;
    LuaDrawBatchMode mode_ = LuaDrawBatchMode::None;
    IDirect3DTexture9* texture_ = nullptr;
    std::vector<LuaDrawColorVertex>& color_vertices_;
    std::vector<LuaDrawTexturedVertex>& textured_vertices_;
    std::size_t current_command_count_ = 0;
    std::size_t successful_command_count_ = 0;
    std::size_t failed_command_count_ = 0;
};

void QueueColorQuad(
    LuaDrawBatcher* batcher,
    float left,
    float top,
    float right,
    float bottom,
    D3DCOLOR color) {
    batcher->BeginRun(LuaDrawBatchMode::Color, nullptr);
    batcher->AppendColorQuad(left, top, right, bottom, color);
}

bool QueueLineCommand(
    LuaDrawBatcher* batcher,
    const LuaDrawCommand& command) {
    const float dx = command.x2 - command.x;
    const float dy = command.y2 - command.y;
    const float length = std::sqrt(dx * dx + dy * dy);
    const float half = command.thickness * 0.5f;
    if (!std::isfinite(length)) {
        return false;
    }
    if (length < 0.0001f) {
        QueueColorQuad(
            batcher,
            command.x - half,
            command.y - half,
            command.x + half,
            command.y + half,
            PackColor(command.color));
        batcher->CompleteCommand();
        return true;
    }

    const float perpendicular_x = -dy / length * half;
    const float perpendicular_y = dx / length * half;
    const auto color = PackColor(command.color);
    batcher->BeginRun(LuaDrawBatchMode::Color, nullptr);
    batcher->AppendColorQuad(
        {command.x + perpendicular_x, command.y + perpendicular_y,
         0.0f, 1.0f, color},
        {command.x2 + perpendicular_x, command.y2 + perpendicular_y,
         0.0f, 1.0f, color},
        {command.x - perpendicular_x, command.y - perpendicular_y,
         0.0f, 1.0f, color},
        {command.x2 - perpendicular_x, command.y2 - perpendicular_y,
         0.0f, 1.0f, color});
    batcher->CompleteCommand();
    return true;
}

bool QueueRectCommand(
    LuaDrawBatcher* batcher,
    const LuaDrawCommand& command) {
    const auto color = PackColor(command.color);
    if (command.kind == LuaDrawCommandKind::FilledRect) {
        QueueColorQuad(
            batcher,
            command.x,
            command.y,
            command.x + command.width,
            command.y + command.height,
            color);
        batcher->CompleteCommand();
        return true;
    }

    const float thickness = (std::min)(
        command.thickness,
        (std::min)(command.width, command.height) * 0.5f);
    QueueColorQuad(
        batcher,
        command.x,
        command.y,
        command.x + command.width,
        command.y + thickness,
        color);
    QueueColorQuad(
        batcher,
        command.x,
        command.y + command.height - thickness,
        command.x + command.width,
        command.y + command.height,
        color);
    QueueColorQuad(
        batcher,
        command.x,
        command.y + thickness,
        command.x + thickness,
        command.y + command.height - thickness,
        color);
    QueueColorQuad(
        batcher,
        command.x + command.width - thickness,
        command.y + thickness,
        command.x + command.width,
        command.y + command.height - thickness,
        color);
    batcher->CompleteCommand();
    return true;
}

bool QueueTextCommand(
    IDirect3DDevice9* device,
    LuaDrawBatcher* batcher,
    const LuaDrawCommand& command) {
    auto& font = g_lua_draw_renderer.font;
    if (!font.load_attempted) {
        font.load_attempted = true;
        D3d9FontAtlasSpec spec;
        if (!InitializeD3d9FontAtlas(
                device,
                spec,
                &font.atlas,
                &font.error_message)) {
            Log("Lua draw text renderer unavailable. " + font.error_message);
        }
    }
    if (font.atlas.texture == nullptr) {
        return false;
    }

    batcher->BeginRun(
        LuaDrawBatchMode::PointText,
        font.atlas.texture);
    const auto color = PackColor(command.color);
    float cursor_x = command.x;
    float cursor_y = command.y;
    bool appended = false;
    for (unsigned char ch : command.text) {
        if (ch == '\n') {
            cursor_x = command.x;
            cursor_y += font.atlas.line_height * command.scale;
            continue;
        }
        if (ch == '\t') {
            cursor_x +=
                font.atlas.glyphs[
                    ' ' - kD3d9FontFirstGlyph].width *
                command.scale * 4.0f;
            continue;
        }
        if (ch < kD3d9FontFirstGlyph ||
            ch > kD3d9FontLastGlyph) {
            ch = '?';
        }
        const auto& glyph =
            font.atlas.glyphs[ch - kD3d9FontFirstGlyph];
        const float width =
            (std::max)(glyph.width, 1) * command.scale;
        const float height =
            font.atlas.line_height * command.scale;
        const float right = cursor_x + width;
        const float bottom = cursor_y + height;
        batcher->AppendTexturedQuad(
            {cursor_x, cursor_y, 0.0f, 1.0f, color, glyph.u0, glyph.v0},
            {right, cursor_y, 0.0f, 1.0f, color, glyph.u1, glyph.v0},
            {cursor_x, bottom, 0.0f, 1.0f, color, glyph.u0, glyph.v1},
            {right, bottom, 0.0f, 1.0f, color, glyph.u1, glyph.v1});
        appended = true;
        cursor_x = right;
    }
    if (appended) {
        batcher->CompleteCommand();
    } else {
        batcher->RecordImmediateSuccess();
    }
    return true;
}

LuaDrawAtlasTexture* GetAtlasTexture(
    IDirect3DDevice9* device,
    const std::string& atlas) {
    std::filesystem::path image_path;
    std::uint64_t revision = 0;
    if (!TryGetLuaDrawAtlasSource(atlas, &image_path, &revision)) {
        return nullptr;
    }
    auto& cached = g_lua_draw_renderer.atlas_textures[atlas];
    if (cached.source_path != image_path || cached.revision != revision) {
        if (cached.texture != nullptr) {
            cached.texture->Release();
        }
        cached = {};
        cached.source_path = image_path;
        cached.revision = revision;
    }
    if (cached.source_path.empty() || cached.revision == 0) {
        return nullptr;
    }
    if (!cached.load_attempted) {
        cached.load_attempted = true;
        if (!detail::LoadLuaDrawTexture(
                device,
                cached.source_path,
                &cached.texture,
                &cached.width,
                &cached.height,
                &cached.error_message)) {
            Log(
                "Lua draw failed to load atlas " + atlas + ". " +
                cached.error_message);
        }
    }
    return cached.texture == nullptr ? nullptr : &cached;
}

bool QueueSpriteCommand(
    IDirect3DDevice9* device,
    LuaDrawBatcher* batcher,
    const LuaDrawCommand& command) {
    LuaDrawSpriteInfo sprite;
    std::string canonical_atlas;
    std::string sprite_error;
    if (!TryGetLuaDrawSpriteInfo(
            command.atlas,
            command.sprite_index,
            &sprite,
            &canonical_atlas,
            &sprite_error)) {
        return false;
    }
    auto* texture = GetAtlasTexture(device, canonical_atlas);
    if (texture == nullptr ||
        texture->width == 0 ||
        texture->height == 0 ||
        sprite.logical_width == 0 ||
        sprite.logical_height == 0 ||
        sprite.atlas_x + sprite.packed_width > texture->width ||
        sprite.atlas_y + sprite.packed_height > texture->height) {
        return false;
    }

    const float logical_width =
        static_cast<float>(sprite.logical_width);
    const float logical_height =
        static_cast<float>(sprite.logical_height);
    const float scale_x = command.width / logical_width;
    const float scale_y = command.height / logical_height;
    const float logical_left = command.centered
        ? command.x - command.width * 0.5f
        : command.x;
    const float logical_top = command.centered
        ? command.y - command.height * 0.5f
        : command.y;
    const float trim_x =
        (logical_width - sprite.content_width) * 0.5f +
        sprite.center_offset_x;
    const float trim_y =
        (logical_height - sprite.content_height) * 0.5f +
        sprite.center_offset_y;
    const float left = logical_left + trim_x * scale_x;
    const float top = logical_top + trim_y * scale_y;
    const float right = left + sprite.packed_width * scale_x;
    const float bottom = top + sprite.packed_height * scale_y;
    const float u0 = sprite.atlas_x / texture->width;
    const float v0 = sprite.atlas_y / texture->height;
    const float u1 =
        (sprite.atlas_x + sprite.packed_width) / texture->width;
    const float v1 =
        (sprite.atlas_y + sprite.packed_height) / texture->height;
    const auto color = PackColor(command.color);
    batcher->BeginRun(
        LuaDrawBatchMode::LinearSprite,
        texture->texture);
    batcher->AppendTexturedQuad(
        {left, top, 0.0f, 1.0f, color, u0, v0},
        {right, top, 0.0f, 1.0f, color, u1, v0},
        {left, bottom, 0.0f, 1.0f, color, u0, v1},
        {right, bottom, 0.0f, 1.0f, color, u1, v1});
    batcher->CompleteCommand();
    return true;
}

bool QueueConsumableQuad(
    IDirect3DDevice9* device,
    LuaDrawBatcher* batcher,
    const LuaConsumableRenderQuad& quad) {
    LuaDrawSpriteInfo sprite;
    std::string canonical_atlas;
    std::string sprite_error;
    if (!TryGetLuaDrawSpriteInfo(
            quad.icon_atlas,
            quad.icon_frame,
            &sprite,
            &canonical_atlas,
            &sprite_error)) {
        return false;
    }
    auto* texture = GetAtlasTexture(device, canonical_atlas);
    if (texture == nullptr ||
        texture->width == 0 ||
        texture->height == 0 ||
        sprite.logical_width == 0 ||
        sprite.logical_height == 0 ||
        sprite.atlas_x + sprite.packed_width > texture->width ||
        sprite.atlas_y + sprite.packed_height > texture->height) {
        return false;
    }

    const float logical_width =
        static_cast<float>(sprite.logical_width);
    const float logical_height =
        static_cast<float>(sprite.logical_height);
    const float trim_x =
        (logical_width - sprite.content_width) * 0.5f +
        sprite.center_offset_x;
    const float trim_y =
        (logical_height - sprite.content_height) * 0.5f +
        sprite.center_offset_y;
    const float left_fraction = trim_x / logical_width;
    const float top_fraction = trim_y / logical_height;
    const float right_fraction =
        (trim_x + sprite.packed_width) / logical_width;
    const float bottom_fraction =
        (trim_y + sprite.packed_height) / logical_height;

    auto Interpolate = [&](float horizontal, float vertical) {
        const float top_x =
            quad.vertices[0] +
            (quad.vertices[2] - quad.vertices[0]) * horizontal;
        const float top_y =
            quad.vertices[1] +
            (quad.vertices[3] - quad.vertices[1]) * horizontal;
        const float bottom_x =
            quad.vertices[4] +
            (quad.vertices[6] - quad.vertices[4]) * horizontal;
        const float bottom_y =
            quad.vertices[5] +
            (quad.vertices[7] - quad.vertices[5]) * horizontal;
        return std::array<float, 2>{
            top_x + (bottom_x - top_x) * vertical,
            top_y + (bottom_y - top_y) * vertical,
        };
    };
    const auto top_left =
        Interpolate(left_fraction, top_fraction);
    const auto top_right =
        Interpolate(right_fraction, top_fraction);
    const auto bottom_left =
        Interpolate(left_fraction, bottom_fraction);
    const auto bottom_right =
        Interpolate(right_fraction, bottom_fraction);

    const float u0 = sprite.atlas_x / texture->width;
    const float v0 = sprite.atlas_y / texture->height;
    const float u1 =
        (sprite.atlas_x + sprite.packed_width) / texture->width;
    const float v1 =
        (sprite.atlas_y + sprite.packed_height) / texture->height;
    const auto color = D3DCOLOR_ARGB(255, 255, 255, 255);
    batcher->BeginRun(
        LuaDrawBatchMode::LinearSprite,
        texture->texture);
    batcher->AppendTexturedQuad(
        {top_left[0], top_left[1], 0.0f, 1.0f, color, u0, v0},
        {top_right[0], top_right[1], 0.0f, 1.0f, color, u1, v0},
        {bottom_left[0], bottom_left[1], 0.0f, 1.0f, color, u0, v1},
        {bottom_right[0], bottom_right[1], 0.0f, 1.0f, color, u1, v1});
    batcher->CompleteCommand();
    return true;
}

bool QueueCommand(
    IDirect3DDevice9* device,
    LuaDrawBatcher* batcher,
    const LuaDrawCommand& command) {
    switch (command.kind) {
    case LuaDrawCommandKind::Text:
        return QueueTextCommand(
            device,
            batcher,
            command);
    case LuaDrawCommandKind::FilledRect:
    case LuaDrawCommandKind::OutlinedRect:
        return QueueRectCommand(batcher, command);
    case LuaDrawCommandKind::Line:
        return QueueLineCommand(batcher, command);
    case LuaDrawCommandKind::Sprite:
        return QueueSpriteCommand(
            device,
            batcher,
            command);
    }
    return false;
}
