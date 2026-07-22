D3DCOLOR PackColor(const LuaDrawColor& color) {
    return D3DCOLOR_ARGB(
        color.alpha,
        color.red,
        color.green,
        color.blue);
}

void ReleaseRendererResourcesUnlocked() {
    if (g_lua_draw_renderer.font.texture != nullptr) {
        g_lua_draw_renderer.font.texture->Release();
    }
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

bool InitializeFontAtlas(
    IDirect3DDevice9* device,
    LuaDrawFontAtlas* atlas,
    std::string* error_message) {
    if (device == nullptr || atlas == nullptr || error_message == nullptr) {
        return false;
    }
    if (atlas->texture != nullptr) {
        return true;
    }

    BITMAPINFO bitmap_info{};
    bitmap_info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bitmap_info.bmiHeader.biWidth = kFontTextureWidth;
    bitmap_info.bmiHeader.biHeight = -kFontTextureHeight;
    bitmap_info.bmiHeader.biPlanes = 1;
    bitmap_info.bmiHeader.biBitCount = 32;
    bitmap_info.bmiHeader.biCompression = BI_RGB;

    void* dib_pixels = nullptr;
    HDC screen_dc = GetDC(nullptr);
    if (screen_dc == nullptr) {
        *error_message = "GetDC failed while creating the Lua draw font atlas.";
        return false;
    }
    HDC memory_dc = CreateCompatibleDC(screen_dc);
    HBITMAP bitmap = CreateDIBSection(
        screen_dc,
        &bitmap_info,
        DIB_RGB_COLORS,
        &dib_pixels,
        nullptr,
        0);
    ReleaseDC(nullptr, screen_dc);
    HFONT font = CreateFontW(
        -16,
        0,
        0,
        0,
        FW_NORMAL,
        FALSE,
        FALSE,
        FALSE,
        ANSI_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY,
        FF_DONTCARE,
        L"Consolas");
    if (memory_dc == nullptr || bitmap == nullptr || dib_pixels == nullptr || font == nullptr) {
        if (font != nullptr) DeleteObject(font);
        if (bitmap != nullptr) DeleteObject(bitmap);
        if (memory_dc != nullptr) DeleteDC(memory_dc);
        *error_message = "GDI failed while creating the Lua draw font atlas.";
        return false;
    }

    HGDIOBJ old_bitmap = SelectObject(memory_dc, bitmap);
    HGDIOBJ old_font = SelectObject(memory_dc, font);
    auto CleanupGdi = [&]() {
        SelectObject(memory_dc, old_font);
        SelectObject(memory_dc, old_bitmap);
        DeleteObject(font);
        DeleteObject(bitmap);
        DeleteDC(memory_dc);
    };
    SetBkMode(memory_dc, TRANSPARENT);
    SetTextColor(memory_dc, RGB(255, 255, 255));
    std::memset(dib_pixels, 0, kFontTextureWidth * kFontTextureHeight * 4);

    atlas->line_height = 16;
    for (int index = 0; index < kFontGlyphCount; ++index) {
        const wchar_t glyph = static_cast<wchar_t>(kFirstFontGlyph + index);
        const int x = (index % kFontColumns) * kFontCellWidth + 2;
        const int y = (index / kFontColumns) * kFontCellHeight + 2;
        SIZE size{};
        if (!GetTextExtentPoint32W(memory_dc, &glyph, 1, &size) || size.cx <= 0 || size.cy <= 0) {
            size.cx = 8;
            size.cy = 16;
        }
        TextOutW(memory_dc, x, y, &glyph, 1);
        auto& target = atlas->glyphs[index];
        target.u0 = static_cast<float>(x) / kFontTextureWidth;
        target.v0 = static_cast<float>(y) / kFontTextureHeight;
        target.u1 = static_cast<float>(x + size.cx) / kFontTextureWidth;
        target.v1 = static_cast<float>(y + size.cy) / kFontTextureHeight;
        target.width = size.cx;
        atlas->line_height = (std::max)(
            atlas->line_height,
            static_cast<int>(size.cy));
    }

    IDirect3DTexture9* texture = nullptr;
    HRESULT result = device->CreateTexture(
        kFontTextureWidth,
        kFontTextureHeight,
        1,
        0,
        D3DFMT_A8R8G8B8,
        D3DPOOL_MANAGED,
        &texture,
        nullptr);
    if (FAILED(result) || texture == nullptr) {
        CleanupGdi();
        *error_message = "D3D9 failed to create the Lua draw font texture.";
        return false;
    }
    D3DLOCKED_RECT locked{};
    if (FAILED(texture->LockRect(0, &locked, nullptr, 0))) {
        texture->Release();
        CleanupGdi();
        *error_message = "D3D9 failed to lock the Lua draw font texture.";
        return false;
    }
    const auto* source = static_cast<const std::uint8_t*>(dib_pixels);
    for (int y = 0; y < kFontTextureHeight; ++y) {
        auto* destination = reinterpret_cast<std::uint32_t*>(
            static_cast<std::uint8_t*>(locked.pBits) + y * locked.Pitch);
        const auto* source_row = source + y * kFontTextureWidth * 4;
        for (int x = 0; x < kFontTextureWidth; ++x) {
            const auto blue = source_row[x * 4 + 0];
            const auto green = source_row[x * 4 + 1];
            const auto red = source_row[x * 4 + 2];
            const auto alpha = (std::max)(red, (std::max)(green, blue));
            destination[x] = D3DCOLOR_ARGB(alpha, 255, 255, 255);
        }
    }
    texture->UnlockRect(0);
    CleanupGdi();
    atlas->texture = texture;
    return true;
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
    SDMOD_SET_D3D_STATE(device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_POINT));
    SDMOD_SET_D3D_STATE(device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_POINT));
    SDMOD_SET_D3D_STATE(device->SetSamplerState(0, D3DSAMP_MIPFILTER, D3DTEXF_NONE));
#undef SDMOD_SET_D3D_STATE
    return ok;
}

bool ConfigureUntexturedStage(IDirect3DDevice9* device) {
    return SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE));
}

bool ConfigureTexturedStage(IDirect3DDevice9* device) {
    return SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE)) &&
        SUCCEEDED(device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE));
}

bool DrawColorQuad(
    IDirect3DDevice9* device,
    float left,
    float top,
    float right,
    float bottom,
    D3DCOLOR color) {
    const std::array<LuaDrawColorVertex, 4> vertices = {{
        {left, top, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {right, bottom, 0.0f, 1.0f, color},
    }};
    return ConfigureUntexturedStage(device) &&
        SUCCEEDED(device->SetFVF(kLuaDrawColorVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLESTRIP,
            2,
            vertices.data(),
            sizeof(LuaDrawColorVertex)));
}

bool DrawLineCommand(IDirect3DDevice9* device, const LuaDrawCommand& command) {
    const float dx = command.x2 - command.x;
    const float dy = command.y2 - command.y;
    const float length = std::sqrt(dx * dx + dy * dy);
    if (!std::isfinite(length) || length < 0.0001f) {
        const float half = command.thickness * 0.5f;
        return DrawColorQuad(
            device,
            command.x - half,
            command.y - half,
            command.x + half,
            command.y + half,
            PackColor(command.color));
    }
    const float half = command.thickness * 0.5f;
    const float perpendicular_x = -dy / length * half;
    const float perpendicular_y = dx / length * half;
    const auto color = PackColor(command.color);
    const std::array<LuaDrawColorVertex, 4> vertices = {{
        {command.x + perpendicular_x, command.y + perpendicular_y, 0.0f, 1.0f, color},
        {command.x2 + perpendicular_x, command.y2 + perpendicular_y, 0.0f, 1.0f, color},
        {command.x - perpendicular_x, command.y - perpendicular_y, 0.0f, 1.0f, color},
        {command.x2 - perpendicular_x, command.y2 - perpendicular_y, 0.0f, 1.0f, color},
    }};
    return ConfigureUntexturedStage(device) &&
        SUCCEEDED(device->SetFVF(kLuaDrawColorVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLESTRIP,
            2,
            vertices.data(),
            sizeof(LuaDrawColorVertex)));
}

bool DrawRectCommand(IDirect3DDevice9* device, const LuaDrawCommand& command) {
    const auto color = PackColor(command.color);
    if (command.kind == LuaDrawCommandKind::FilledRect) {
        return DrawColorQuad(
            device,
            command.x,
            command.y,
            command.x + command.width,
            command.y + command.height,
            color);
    }
    const float thickness = (std::min)(
        command.thickness,
        (std::min)(command.width, command.height) * 0.5f);
    return DrawColorQuad(device, command.x, command.y, command.x + command.width, command.y + thickness, color) &&
        DrawColorQuad(device, command.x, command.y + command.height - thickness, command.x + command.width, command.y + command.height, color) &&
        DrawColorQuad(device, command.x, command.y + thickness, command.x + thickness, command.y + command.height - thickness, color) &&
        DrawColorQuad(device, command.x + command.width - thickness, command.y + thickness, command.x + command.width, command.y + command.height - thickness, color);
}

bool DrawTextCommand(IDirect3DDevice9* device, const LuaDrawCommand& command) {
    auto& font = g_lua_draw_renderer.font;
    if (!font.load_attempted) {
        font.load_attempted = true;
        if (!InitializeFontAtlas(device, &font, &font.error_message)) {
            Log("Lua draw text renderer unavailable. " + font.error_message);
        }
    }
    if (font.texture == nullptr) {
        return false;
    }
    std::vector<LuaDrawTexturedVertex> vertices;
    vertices.reserve(command.text.size() * 6);
    const auto color = PackColor(command.color);
    float cursor_x = command.x;
    float cursor_y = command.y;
    for (unsigned char ch : command.text) {
        if (ch == '\n') {
            cursor_x = command.x;
            cursor_y += font.line_height * command.scale;
            continue;
        }
        if (ch == '\t') {
            cursor_x += font.glyphs[' ' - kFirstFontGlyph].width * command.scale * 4.0f;
            continue;
        }
        if (ch < kFirstFontGlyph || ch > kLastFontGlyph) {
            ch = '?';
        }
        const auto& glyph = font.glyphs[ch - kFirstFontGlyph];
        const float width = (std::max)(glyph.width, 1) * command.scale;
        const float height = font.line_height * command.scale;
        const float right = cursor_x + width;
        const float bottom = cursor_y + height;
        vertices.push_back({cursor_x, cursor_y, 0.0f, 1.0f, color, glyph.u0, glyph.v0});
        vertices.push_back({right, cursor_y, 0.0f, 1.0f, color, glyph.u1, glyph.v0});
        vertices.push_back({cursor_x, bottom, 0.0f, 1.0f, color, glyph.u0, glyph.v1});
        vertices.push_back({cursor_x, bottom, 0.0f, 1.0f, color, glyph.u0, glyph.v1});
        vertices.push_back({right, cursor_y, 0.0f, 1.0f, color, glyph.u1, glyph.v0});
        vertices.push_back({right, bottom, 0.0f, 1.0f, color, glyph.u1, glyph.v1});
        cursor_x = right;
    }
    if (vertices.empty()) {
        return true;
    }
    return ConfigureTexturedStage(device) &&
        SUCCEEDED(device->SetFVF(kLuaDrawTexturedVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, font.texture)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLELIST,
            static_cast<UINT>(vertices.size() / 3),
            vertices.data(),
            sizeof(LuaDrawTexturedVertex)));
}

LuaDrawAtlasTexture* GetAtlasTexture(
    IDirect3DDevice9* device,
    const std::string& atlas) {
    auto& cached = g_lua_draw_renderer.atlas_textures[atlas];
    if (!cached.load_attempted) {
        cached.load_attempted = true;
        const auto image_path = GetLuaDrawAtlasImagePath(atlas);
        if (!detail::LoadLuaDrawTexture(
                device,
                image_path,
                &cached.texture,
                &cached.width,
                &cached.height,
                &cached.error_message)) {
            Log(
                "Lua draw failed to load stock atlas " + atlas + ". " +
                cached.error_message);
        }
    }
    return cached.texture == nullptr ? nullptr : &cached;
}

bool DrawSpriteCommand(IDirect3DDevice9* device, const LuaDrawCommand& command) {
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
    if (texture == nullptr || texture->width == 0 || texture->height == 0) {
        return false;
    }
    if (sprite.atlas_x + sprite.packed_width > texture->width ||
        sprite.atlas_y + sprite.packed_height > texture->height) {
        return false;
    }

    const float logical_width = static_cast<float>(sprite.logical_width);
    const float logical_height = static_cast<float>(sprite.logical_height);
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
    const float u1 = (sprite.atlas_x + sprite.packed_width) / texture->width;
    const float v1 = (sprite.atlas_y + sprite.packed_height) / texture->height;
    const auto color = PackColor(command.color);
    const std::array<LuaDrawTexturedVertex, 4> vertices = {{
        {left, top, 0.0f, 1.0f, color, u0, v0},
        {right, top, 0.0f, 1.0f, color, u1, v0},
        {left, bottom, 0.0f, 1.0f, color, u0, v1},
        {right, bottom, 0.0f, 1.0f, color, u1, v1},
    }};
    return ConfigureTexturedStage(device) &&
        SUCCEEDED(device->SetFVF(kLuaDrawTexturedVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, texture->texture)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLESTRIP,
            2,
            vertices.data(),
            sizeof(LuaDrawTexturedVertex)));
}

bool DrawCommand(IDirect3DDevice9* device, const LuaDrawCommand& command) {
    switch (command.kind) {
    case LuaDrawCommandKind::Text:
        return DrawTextCommand(device, command);
    case LuaDrawCommandKind::FilledRect:
    case LuaDrawCommandKind::OutlinedRect:
        return DrawRectCommand(device, command);
    case LuaDrawCommandKind::Line:
        return DrawLineCommand(device, command);
    case LuaDrawCommandKind::Sprite:
        return DrawSpriteCommand(device, command);
    }
    return false;
}
