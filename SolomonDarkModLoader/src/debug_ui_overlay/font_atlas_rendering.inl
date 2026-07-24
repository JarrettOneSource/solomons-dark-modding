bool InitializeFontAtlas(IDirect3DDevice9* device, FontAtlas* atlas, std::string* error_message) {
    D3d9FontAtlasSpec spec;
    spec.font_height = -14;
    spec.font_weight = FW_BOLD;
    spec.cell_width = 24;
    spec.cell_height = 24;
    return InitializeD3d9FontAtlas(
        device,
        spec,
        atlas,
        error_message);
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

bool DrawFilledRect(IDirect3DDevice9* device, float left, float top, float right, float bottom, D3DCOLOR color) {
    if (device == nullptr) {
        return false;
    }
    const std::array<ColorVertex, 4> vertices = {{
        {left, top, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {right, bottom, 0.0f, 1.0f, color},
    }};

    return SUCCEEDED(device->SetFVF(kColorVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLESTRIP,
            2,
            vertices.data(),
            sizeof(ColorVertex)));
}

bool DrawRectOutline(IDirect3DDevice9* device, float left, float top, float right, float bottom, D3DCOLOR color) {
    if (device == nullptr) {
        return false;
    }
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

    return SUCCEEDED(device->SetFVF(kColorVertexFvf)) &&
        SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_LINELIST,
            4,
            vertices.data(),
            sizeof(ColorVertex)));
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
