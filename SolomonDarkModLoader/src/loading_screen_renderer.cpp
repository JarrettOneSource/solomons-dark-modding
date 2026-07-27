#include "loading_screen_internal.h"

#include "d3d9_end_scene_hook.h"
#include "d3d9_font_atlas.h"
#include "loading_screen.h"
#include "logger.h"
#include "lua_draw_internal.h"

#include <Windows.h>
#include <d3d9.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iterator>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod::detail {
namespace {

constexpr float kBottomBandHeightFraction = 0.18f;
constexpr float kProgressBarWidthFraction = 0.60f;
constexpr float kProgressBarTopFraction = 0.925f;

struct ColorVertex {
    float x;
    float y;
    float z;
    float rhw;
    D3DCOLOR color;
};

struct TexturedVertex {
    float x;
    float y;
    float z;
    float rhw;
    D3DCOLOR color;
    float u;
    float v;
};

constexpr DWORD kColorFvf =
    D3DFVF_XYZRHW | D3DFVF_DIFFUSE;
constexpr DWORD kTexturedFvf =
    D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1;

struct LoadingScreenRendererState {
    std::mutex mutex;
    bool started = false;
    bool resources_attempted = false;
    bool render_failure_logged = false;
    IDirect3DDevice9* resource_device = nullptr;
    IDirect3DTexture9* background = nullptr;
    std::uint32_t background_width = 0;
    std::uint32_t background_height = 0;
    D3d9FontAtlas font;
    std::filesystem::path background_path;
    std::uint64_t rendered_sequence = 0;
    LoadingScreenStage rendered_stage =
        LoadingScreenStage::PreparingBoneyard;
};

LoadingScreenRendererState g_renderer;

void ReleaseResourcesUnlocked() {
    if (g_renderer.background != nullptr) {
        g_renderer.background->Release();
        g_renderer.background = nullptr;
    }
    ReleaseD3d9FontAtlas(&g_renderer.font);
    g_renderer.background_width = 0;
    g_renderer.background_height = 0;
    g_renderer.resource_device = nullptr;
    g_renderer.resources_attempted = false;
}

bool ConfigureCommonState(IDirect3DDevice9* device) {
    bool ok = true;
#define SDMOD_LOADING_SET(expression) \
    ok = SUCCEEDED(expression) && ok
    SDMOD_LOADING_SET(device->SetPixelShader(nullptr));
    SDMOD_LOADING_SET(device->SetVertexShader(nullptr));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_ZENABLE, FALSE));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_ZWRITEENABLE, FALSE));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_LIGHTING, FALSE));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_FOGENABLE, FALSE));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_SCISSORTESTENABLE, FALSE));
    SDMOD_LOADING_SET(
        device->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE));
    SDMOD_LOADING_SET(
        device->SetRenderState(
            D3DRS_SRCBLEND,
            D3DBLEND_SRCALPHA));
    SDMOD_LOADING_SET(
        device->SetRenderState(
            D3DRS_DESTBLEND,
            D3DBLEND_INVSRCALPHA));
    SDMOD_LOADING_SET(
        device->SetTextureStageState(
            1,
            D3DTSS_COLOROP,
            D3DTOP_DISABLE));
#undef SDMOD_LOADING_SET
    return ok;
}

bool ConfigureColorStage(IDirect3DDevice9* device) {
    return SUCCEEDED(device->SetTexture(0, nullptr)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_COLOROP,
            D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_COLORARG1,
            D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_ALPHAOP,
            D3DTOP_SELECTARG1)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_ALPHAARG1,
            D3DTA_DIFFUSE));
}

bool ConfigureTextureStage(
    IDirect3DDevice9* device,
    IDirect3DTexture9* texture,
    D3DTEXTUREFILTERTYPE filter) {
    return SUCCEEDED(device->SetTexture(0, texture)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_COLOROP,
            D3DTOP_MODULATE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_COLORARG1,
            D3DTA_TEXTURE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_COLORARG2,
            D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_ALPHAOP,
            D3DTOP_MODULATE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_ALPHAARG1,
            D3DTA_TEXTURE)) &&
        SUCCEEDED(device->SetTextureStageState(
            0,
            D3DTSS_ALPHAARG2,
            D3DTA_DIFFUSE)) &&
        SUCCEEDED(device->SetSamplerState(
            0,
            D3DSAMP_MINFILTER,
            filter)) &&
        SUCCEEDED(device->SetSamplerState(
            0,
            D3DSAMP_MAGFILTER,
            filter)) &&
        SUCCEEDED(device->SetSamplerState(
            0,
            D3DSAMP_MIPFILTER,
            D3DTEXF_NONE)) &&
        SUCCEEDED(device->SetSamplerState(
            0,
            D3DSAMP_ADDRESSU,
            D3DTADDRESS_CLAMP)) &&
        SUCCEEDED(device->SetSamplerState(
            0,
            D3DSAMP_ADDRESSV,
            D3DTADDRESS_CLAMP));
}

bool DrawColorVertices(
    IDirect3DDevice9* device,
    const ColorVertex* vertices,
    std::size_t vertex_count) {
    return vertices != nullptr &&
        vertex_count >= 3 &&
        ConfigureColorStage(device) &&
        SUCCEEDED(device->SetFVF(kColorFvf)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLELIST,
            static_cast<UINT>(vertex_count / 3),
            vertices,
            sizeof(ColorVertex)));
}

bool DrawColorQuad(
    IDirect3DDevice9* device,
    float left,
    float top,
    float right,
    float bottom,
    D3DCOLOR color) {
    const ColorVertex vertices[] = {
        {left, top, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {left, bottom, 0.0f, 1.0f, color},
        {right, top, 0.0f, 1.0f, color},
        {right, bottom, 0.0f, 1.0f, color},
    };
    return DrawColorVertices(
        device,
        vertices,
        std::size(vertices));
}

bool DrawBackground(
    IDirect3DDevice9* device,
    const D3DVIEWPORT9& viewport,
    float* crop_u0,
    float* crop_v0,
    float* crop_u1,
    float* crop_v1) {
    if (g_renderer.background == nullptr ||
        g_renderer.background_width == 0 ||
        g_renderer.background_height == 0) {
        return false;
    }

    const float viewport_width =
        static_cast<float>(viewport.Width);
    const float viewport_height =
        static_cast<float>(viewport.Height);
    const float viewport_aspect =
        viewport_width / viewport_height;
    const float image_aspect =
        static_cast<float>(g_renderer.background_width) /
        static_cast<float>(g_renderer.background_height);
    float u0 = 0.0f;
    float v0 = 0.0f;
    float u1 = 1.0f;
    float v1 = 1.0f;
    if (viewport_aspect > image_aspect) {
        const float visible_height =
            image_aspect / viewport_aspect;
        v0 = (1.0f - visible_height) * 0.5f;
        v1 = 1.0f - v0;
    } else if (viewport_aspect < image_aspect) {
        const float visible_width =
            viewport_aspect / image_aspect;
        u0 = (1.0f - visible_width) * 0.5f;
        u1 = 1.0f - u0;
    }

    *crop_u0 = u0;
    *crop_v0 = v0;
    *crop_u1 = u1;
    *crop_v1 = v1;
    const float left =
        static_cast<float>(viewport.X) - 0.5f;
    const float top =
        static_cast<float>(viewport.Y) - 0.5f;
    const float right = left + viewport_width;
    const float bottom = top + viewport_height;
    const auto white =
        D3DCOLOR_ARGB(255, 255, 255, 255);
    const TexturedVertex vertices[] = {
        {left, top, 0.0f, 1.0f, white, u0, v0},
        {right, top, 0.0f, 1.0f, white, u1, v0},
        {left, bottom, 0.0f, 1.0f, white, u0, v1},
        {left, bottom, 0.0f, 1.0f, white, u0, v1},
        {right, top, 0.0f, 1.0f, white, u1, v0},
        {right, bottom, 0.0f, 1.0f, white, u1, v1},
    };
    return ConfigureTextureStage(
               device,
               g_renderer.background,
               D3DTEXF_LINEAR) &&
        SUCCEEDED(device->SetFVF(kTexturedFvf)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLELIST,
            2,
            vertices,
            sizeof(TexturedVertex)));
}

float MeasureText(std::string_view text, float scale) {
    float width = 0.0f;
    for (unsigned char ch : text) {
        if (ch < kD3d9FontFirstGlyph ||
            ch > kD3d9FontLastGlyph) {
            ch = '?';
        }
        width +=
            (std::max)(
                g_renderer.font.glyphs[
                    ch - kD3d9FontFirstGlyph].width,
                1) *
            scale;
    }
    return width;
}

bool DrawText(
    IDirect3DDevice9* device,
    std::string_view text,
    float x,
    float y,
    float scale,
    D3DCOLOR color) {
    std::vector<TexturedVertex> vertices;
    vertices.reserve(text.size() * 6);
    float cursor_x = x;
    const float height =
        g_renderer.font.line_height * scale;
    for (unsigned char ch : text) {
        if (ch < kD3d9FontFirstGlyph ||
            ch > kD3d9FontLastGlyph) {
            ch = '?';
        }
        const auto& glyph =
            g_renderer.font.glyphs[
                ch - kD3d9FontFirstGlyph];
        const float width =
            (std::max)(glyph.width, 1) * scale;
        const float right = cursor_x + width;
        const float bottom = y + height;
        vertices.insert(
            vertices.end(),
            {
                {cursor_x, y, 0.0f, 1.0f, color,
                 glyph.u0, glyph.v0},
                {right, y, 0.0f, 1.0f, color,
                 glyph.u1, glyph.v0},
                {cursor_x, bottom, 0.0f, 1.0f, color,
                 glyph.u0, glyph.v1},
                {cursor_x, bottom, 0.0f, 1.0f, color,
                 glyph.u0, glyph.v1},
                {right, y, 0.0f, 1.0f, color,
                 glyph.u1, glyph.v0},
                {right, bottom, 0.0f, 1.0f, color,
                 glyph.u1, glyph.v1},
            });
        cursor_x = right;
    }
    return !vertices.empty() &&
        ConfigureTextureStage(
            device,
            g_renderer.font.texture,
            D3DTEXF_LINEAR) &&
        SUCCEEDED(device->SetFVF(kTexturedFvf)) &&
        SUCCEEDED(device->DrawPrimitiveUP(
            D3DPT_TRIANGLELIST,
            static_cast<UINT>(vertices.size() / 3),
            vertices.data(),
            sizeof(TexturedVertex)));
}

bool EnsureResourcesUnlocked(
    IDirect3DDevice9* device,
    std::string* error_message) {
    if (g_renderer.resource_device != device) {
        ReleaseResourcesUnlocked();
        g_renderer.resource_device = device;
    }
    if (g_renderer.resources_attempted) {
        return g_renderer.background != nullptr &&
            g_renderer.font.texture != nullptr;
    }
    g_renderer.resources_attempted = true;

    if (!LoadLuaDrawTexture(
            device,
            g_renderer.background_path,
            &g_renderer.background,
            &g_renderer.background_width,
            &g_renderer.background_height,
            error_message)) {
        return false;
    }

    D3d9FontAtlasSpec font_spec;
    font_spec.font_height = -24;
    font_spec.font_weight = 600;
    font_spec.minimum_line_height = 24;
    font_spec.texture_width = 1024;
    font_spec.texture_height = 256;
    font_spec.cell_width = 48;
    font_spec.cell_height = 40;
    font_spec.face_name = L"Segoe UI";
    if (!InitializeD3d9FontAtlas(
            device,
            font_spec,
            &g_renderer.font,
            error_message)) {
        g_renderer.background->Release();
        g_renderer.background = nullptr;
        return false;
    }
    Log(
        "Loading screen resources ready. background=" +
        std::to_string(g_renderer.background_width) + "x" +
        std::to_string(g_renderer.background_height));
    return true;
}

bool DrawLoadingScreen(
    IDirect3DDevice9* device,
    const LoadingScreenSnapshot& snapshot,
    const D3DVIEWPORT9& viewport,
    float* crop_u0,
    float* crop_v0,
    float* crop_u1,
    float* crop_v1) {
    if (!ConfigureCommonState(device) ||
        !DrawBackground(
            device,
            viewport,
            crop_u0,
            crop_v0,
            crop_u1,
            crop_v1)) {
        return false;
    }

    const float left =
        static_cast<float>(viewport.X) - 0.5f;
    const float top =
        static_cast<float>(viewport.Y) - 0.5f;
    const float width =
        static_cast<float>(viewport.Width);
    const float height =
        static_cast<float>(viewport.Height);
    const float right = left + width;
    const float bottom = top + height;
    const float band_top =
        bottom - height * kBottomBandHeightFraction;
    const auto transparent_black =
        D3DCOLOR_ARGB(0, 0, 0, 0);
    const auto bottom_black =
        D3DCOLOR_ARGB(179, 0, 0, 0);
    const ColorVertex scrim[] = {
        {left, band_top, 0.0f, 1.0f, transparent_black},
        {right, band_top, 0.0f, 1.0f, transparent_black},
        {left, bottom, 0.0f, 1.0f, bottom_black},
        {left, bottom, 0.0f, 1.0f, bottom_black},
        {right, band_top, 0.0f, 1.0f, transparent_black},
        {right, bottom, 0.0f, 1.0f, bottom_black},
    };
    if (!DrawColorVertices(
            device,
            scrim,
            std::size(scrim))) {
        return false;
    }

    const float bar_width =
        width * kProgressBarWidthFraction;
    const float bar_left =
        left + (width - bar_width) * 0.5f;
    const float bar_top =
        top + height * kProgressBarTopFraction;
    const float bar_height =
        (std::clamp)(height * 0.0083f, 8.0f, 10.0f);
    const float bar_right = bar_left + bar_width;
    const float bar_bottom = bar_top + bar_height;
    const auto border =
        D3DCOLOR_ARGB(230, 105, 82, 42);
    const auto track =
        D3DCOLOR_ARGB(235, 20, 17, 13);
    const auto fill =
        D3DCOLOR_ARGB(255, 202, 161, 77);
    if (!DrawColorQuad(
            device,
            bar_left - 1.0f,
            bar_top - 1.0f,
            bar_right + 1.0f,
            bar_bottom + 1.0f,
            border) ||
        !DrawColorQuad(
            device,
            bar_left,
            bar_top,
            bar_right,
            bar_bottom,
            track)) {
        return false;
    }
    const float fill_right =
        bar_left + bar_width *
            (std::clamp)(snapshot.progress, 0.0f, 1.0f);
    if (fill_right > bar_left &&
        !DrawColorQuad(
            device,
            bar_left,
            bar_top,
            fill_right,
            bar_bottom,
            fill)) {
        return false;
    }

    const float text_scale =
        (std::clamp)(height / 1080.0f, 0.70f, 1.50f);
    const float text_width =
        MeasureText(snapshot.label, text_scale);
    const float text_x =
        left + (width - text_width) * 0.5f;
    const float text_y =
        bar_top -
        g_renderer.font.line_height * text_scale -
        (std::max)(12.0f, 14.0f * text_scale);
    return DrawText(
        device,
        snapshot.label,
        text_x,
        text_y,
        text_scale,
        D3DCOLOR_ARGB(255, 242, 229, 199));
}

void RenderLoadingScreen(IDirect3DDevice9* device) {
    const auto snapshot = GetLoadingScreenSnapshot();
    if (!snapshot.active || device == nullptr) {
        return;
    }
    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    if (now_ms < snapshot.started_ms ||
        now_ms - snapshot.started_ms <
            kLoadingScreenPresentationDelayMs) {
        return;
    }

    std::scoped_lock lock(g_renderer.mutex);
    if (!g_renderer.started) {
        return;
    }
    std::string resource_error;
    if (!EnsureResourcesUnlocked(device, &resource_error)) {
        if (!g_renderer.render_failure_logged) {
            g_renderer.render_failure_logged = true;
            Log(
                "Loading screen render resources unavailable. " +
                resource_error);
        }
        return;
    }

    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 ||
        viewport.Height == 0) {
        return;
    }
    float crop_u0 = 0.0f;
    float crop_v0 = 0.0f;
    float crop_u1 = 1.0f;
    float crop_v1 = 1.0f;
    if (!DrawLoadingScreen(
            device,
            snapshot,
            viewport,
            &crop_u0,
            &crop_v0,
            &crop_u1,
            &crop_v1)) {
        if (!g_renderer.render_failure_logged) {
            g_renderer.render_failure_logged = true;
            Log("Loading screen D3D9 draw failed.");
        }
        return;
    }
    g_renderer.render_failure_logged = false;

    if (g_renderer.rendered_sequence != snapshot.sequence ||
        g_renderer.rendered_stage != snapshot.stage) {
        g_renderer.rendered_sequence = snapshot.sequence;
        g_renderer.rendered_stage = snapshot.stage;
        Log(
            "Loading screen rendered. sequence=" +
            std::to_string(snapshot.sequence) +
            " stage=" + snapshot.stage_id +
            " progress=" + std::to_string(snapshot.progress) +
            " viewport=" + std::to_string(viewport.Width) + "x" +
            std::to_string(viewport.Height) +
            " crop=" + std::to_string(crop_u0) + "," +
            std::to_string(crop_v0) + "," +
            std::to_string(crop_u1) + "," +
            std::to_string(crop_v1));
    }
}

}  // namespace

bool StartLoadingScreenRenderer(
    std::uintptr_t device_pointer_global,
    const std::filesystem::path& background_path,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (background_path.empty() ||
        !std::filesystem::is_regular_file(background_path)) {
        if (error_message != nullptr) {
            *error_message =
                "Loading screen background was not found: " +
                background_path.string();
        }
        return false;
    }
    {
        std::scoped_lock lock(g_renderer.mutex);
        if (g_renderer.started) {
            return true;
        }
        g_renderer.background_path = background_path;
    }
    if (!InstallD3d9FrameHook(
            device_pointer_global,
            &RenderLoadingScreen,
            error_message)) {
        std::scoped_lock lock(g_renderer.mutex);
        g_renderer.background_path.clear();
        return false;
    }
    std::scoped_lock lock(g_renderer.mutex);
    g_renderer.started = true;
    return true;
}

void StopLoadingScreenRenderer() {
    RemoveD3d9FrameCallback(&RenderLoadingScreen);
    std::scoped_lock lock(g_renderer.mutex);
    ReleaseResourcesUnlocked();
    g_renderer.started = false;
    g_renderer.render_failure_logged = false;
    g_renderer.background_path.clear();
    g_renderer.rendered_sequence = 0;
    g_renderer.rendered_stage =
        LoadingScreenStage::PreparingBoneyard;
}

}  // namespace sdmod::detail
