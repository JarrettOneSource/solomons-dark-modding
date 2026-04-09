bool InitializeFontAtlas(IDirect3DDevice9* device, FontAtlas* atlas, std::string* error_message) {
    if (device == nullptr || atlas == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Font atlas device or destination was null.";
        }
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
    const auto screen_dc = GetDC(nullptr);
    if (screen_dc == nullptr) {
        if (error_message != nullptr) {
            *error_message = "GetDC failed while building the debug UI font atlas.";
        }
        return false;
    }

    const auto memory_dc = CreateCompatibleDC(screen_dc);
    const auto dib_bitmap = CreateDIBSection(screen_dc, &bitmap_info, DIB_RGB_COLORS, &dib_pixels, nullptr, 0);
    ReleaseDC(nullptr, screen_dc);

    if (memory_dc == nullptr || dib_bitmap == nullptr || dib_pixels == nullptr) {
        if (memory_dc != nullptr) {
            DeleteDC(memory_dc);
        }
        if (dib_bitmap != nullptr) {
            DeleteObject(dib_bitmap);
        }
        if (error_message != nullptr) {
            *error_message = "Failed to allocate the debug UI font atlas bitmap.";
        }
        return false;
    }

    const auto old_bitmap = SelectObject(memory_dc, dib_bitmap);
    const auto font = CreateFontW(
        -14,
        0,
        0,
        0,
        FW_BOLD,
        FALSE,
        FALSE,
        FALSE,
        ANSI_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY,
        FF_DONTCARE,
        L"Consolas");
    const auto old_font = SelectObject(memory_dc, font);
    const auto cleanup_gdi = [&]() {
        SelectObject(memory_dc, old_font);
        SelectObject(memory_dc, old_bitmap);
        DeleteObject(font);
        DeleteObject(dib_bitmap);
        DeleteDC(memory_dc);
    };

    SetBkMode(memory_dc, TRANSPARENT);
    SetTextColor(memory_dc, RGB(255, 255, 255));

    std::memset(dib_pixels, 0, kFontTextureWidth * kFontTextureHeight * 4);

    atlas->line_height = 16;
    for (int glyph_index = 0; glyph_index < kGlyphCount; ++glyph_index) {
        const wchar_t glyph = static_cast<wchar_t>(kFirstGlyph + glyph_index);
        const int column = glyph_index % kFontColumns;
        const int row = glyph_index / kFontColumns;
        const int x = column * kFontCellWidth + 2;
        const int y = row * kFontCellHeight + 2;

        SIZE glyph_size{};
        GetTextExtentPoint32W(memory_dc, &glyph, 1, &glyph_size);
        if (glyph_size.cx <= 0) {
            glyph_size.cx = 6;
        }
        if (glyph_size.cy <= 0) {
            glyph_size.cy = atlas->line_height;
        }

        TextOutW(memory_dc, x, y, &glyph, 1);

        auto& info = atlas->glyphs[glyph_index];
        info.u0 = static_cast<float>(x) / static_cast<float>(kFontTextureWidth);
        info.v0 = static_cast<float>(y) / static_cast<float>(kFontTextureHeight);
        info.u1 = static_cast<float>(x + glyph_size.cx) / static_cast<float>(kFontTextureWidth);
        info.v1 = static_cast<float>(y + glyph_size.cy) / static_cast<float>(kFontTextureHeight);
        info.width = glyph_size.cx;
        atlas->line_height = (std::max)(atlas->line_height, static_cast<int>(glyph_size.cy));
    }

    IDirect3DTexture9* texture = nullptr;
    const auto texture_result = device->CreateTexture(
        kFontTextureWidth,
        kFontTextureHeight,
        1,
        0,
        D3DFMT_A8R8G8B8,
        D3DPOOL_MANAGED,
        &texture,
        nullptr);
    if (FAILED(texture_result) || texture == nullptr) {
        cleanup_gdi();
        if (error_message != nullptr) {
            *error_message = "CreateTexture failed while building the debug UI font atlas.";
        }
        return false;
    }

    D3DLOCKED_RECT locked_rect{};
    if (FAILED(texture->LockRect(0, &locked_rect, nullptr, 0))) {
        texture->Release();
        cleanup_gdi();
        if (error_message != nullptr) {
            *error_message = "LockRect failed while populating the debug UI font atlas.";
        }
        return false;
    }

    const auto* source_pixels = static_cast<const std::uint8_t*>(dib_pixels);
    for (int y = 0; y < kFontTextureHeight; ++y) {
        auto* destination_row = reinterpret_cast<std::uint32_t*>(static_cast<std::uint8_t*>(locked_rect.pBits) + y * locked_rect.Pitch);
        const auto* source_row = source_pixels + (y * kFontTextureWidth * 4);
        for (int x = 0; x < kFontTextureWidth; ++x) {
            const auto blue = source_row[x * 4 + 0];
            const auto green = source_row[x * 4 + 1];
            const auto red = source_row[x * 4 + 2];
            const auto alpha = static_cast<std::uint8_t>((std::max)((std::max)(blue, green), red));
            destination_row[x] = D3DCOLOR_ARGB(alpha, 255, 255, 255);
        }
    }

    texture->UnlockRect(0);
    cleanup_gdi();
    atlas->texture = texture;
    return true;
}

int MeasureLabelWidth(const FontAtlas& atlas, std::string_view label) {
    int width = 0;
    for (unsigned char ch : label) {
        if (ch < kFirstGlyph || ch > kLastGlyph) {
            width += atlas.line_height / 2;
            continue;
        }

        width += atlas.glyphs[ch - kFirstGlyph].width;
    }
    return width;
}

void DrawFilledRect(IDirect3DDevice9* device, float left, float top, float right, float bottom, D3DCOLOR color) {
    const std::array<ColorVertex, 4> vertices = {{
        {left, top, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {right, bottom, 0.0f, 1.0f, color},
    }};

    device->SetFVF(kColorVertexFvf);
    device->SetTexture(0, nullptr);
    device->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP, 2, vertices.data(), sizeof(ColorVertex));
}

void DrawRectOutline(IDirect3DDevice9* device, float left, float top, float right, float bottom, D3DCOLOR color) {
    const std::array<ColorVertex, 8> vertices = {{
        {left, top, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {right, bottom, 0.0f, 1.0f, color},
        {right, bottom, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {left, top, 0.0f, 1.0f, color},
    }};

    device->SetFVF(kColorVertexFvf);
    device->SetTexture(0, nullptr);
    device->DrawPrimitiveUP(D3DPT_LINELIST, 4, vertices.data(), sizeof(ColorVertex));
}

void DrawLabelText(IDirect3DDevice9* device, const FontAtlas& atlas, float left, float top, std::string_view label, D3DCOLOR color) {
    if (atlas.texture == nullptr || label.empty()) {
        return;
    }

    std::vector<TexturedVertex> vertices;
    vertices.reserve(label.size() * 6);

    float cursor_x = left;
    for (unsigned char ch : label) {
        if (ch < kFirstGlyph || ch > kLastGlyph) {
            cursor_x += static_cast<float>(atlas.line_height / 2);
            continue;
        }

        const auto& glyph = atlas.glyphs[ch - kFirstGlyph];
        const auto width = static_cast<float>((std::max)(glyph.width, 1));
        const auto height = static_cast<float>(atlas.line_height);

        const float right = cursor_x + width;
        const float bottom = top + height;

        vertices.push_back({cursor_x, top, 0.0f, 1.0f, color, glyph.u0, glyph.v0});
        vertices.push_back({right, top, 0.0f, 1.0f, color, glyph.u1, glyph.v0});
        vertices.push_back({cursor_x, bottom, 0.0f, 1.0f, color, glyph.u0, glyph.v1});
        vertices.push_back({cursor_x, bottom, 0.0f, 1.0f, color, glyph.u0, glyph.v1});
        vertices.push_back({right, top, 0.0f, 1.0f, color, glyph.u1, glyph.v0});
        vertices.push_back({right, bottom, 0.0f, 1.0f, color, glyph.u1, glyph.v1});

        cursor_x = right;
    }

    if (vertices.empty()) {
        return;
    }

    device->SetFVF(kTexturedVertexFvf);
    device->SetTexture(0, atlas.texture);
    device->DrawPrimitiveUP(
        D3DPT_TRIANGLELIST,
        static_cast<UINT>(vertices.size() / 3),
        vertices.data(),
        sizeof(TexturedVertex));
}

void ConfigureOverlayRenderState(IDirect3DDevice9* device) {
    device->SetPixelShader(nullptr);
    device->SetVertexShader(nullptr);
    device->SetRenderState(D3DRS_ZENABLE, FALSE);
    device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE);
    device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    device->SetRenderState(D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    device->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_FOGENABLE, FALSE);
    device->SetTextureStageState(0, D3DTSS_COLOROP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_COLORARG2, D3DTA_DIFFUSE);
    device->SetTextureStageState(0, D3DTSS_ALPHAOP, D3DTOP_MODULATE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG1, D3DTA_TEXTURE);
    device->SetTextureStageState(0, D3DTSS_ALPHAARG2, D3DTA_DIFFUSE);
    device->SetSamplerState(0, D3DSAMP_MINFILTER, D3DTEXF_LINEAR);
    device->SetSamplerState(0, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR);
}

