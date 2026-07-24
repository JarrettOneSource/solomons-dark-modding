#include "d3d9_font_atlas.h"

#include <Windows.h>
#include <d3d9.h>

#include <algorithm>
#include <cstdint>
#include <cstring>

namespace sdmod {
namespace {

bool IsValidSpec(const D3d9FontAtlasSpec& spec) {
    if (spec.font_height == 0 ||
        spec.minimum_line_height <= 0 ||
        spec.texture_width <= 0 ||
        spec.texture_height <= 0 ||
        spec.cell_width <= 0 ||
        spec.cell_height <= 0 ||
        spec.columns <= 0 ||
        spec.face_name.empty()) {
        return false;
    }
    const int rows =
        (kD3d9FontGlyphCount + spec.columns - 1) / spec.columns;
    return spec.columns * spec.cell_width <= spec.texture_width &&
        rows * spec.cell_height <= spec.texture_height;
}

}  // namespace

bool InitializeD3d9FontAtlas(
    IDirect3DDevice9* device,
    const D3d9FontAtlasSpec& spec,
    D3d9FontAtlas* atlas,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (device == nullptr || atlas == nullptr || error_message == nullptr) {
        return false;
    }
    if (atlas->texture != nullptr) {
        return true;
    }
    if (!IsValidSpec(spec)) {
        *error_message = "D3D9 font atlas specification is invalid.";
        return false;
    }

    BITMAPINFO bitmap_info{};
    bitmap_info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bitmap_info.bmiHeader.biWidth = spec.texture_width;
    bitmap_info.bmiHeader.biHeight = -spec.texture_height;
    bitmap_info.bmiHeader.biPlanes = 1;
    bitmap_info.bmiHeader.biBitCount = 32;
    bitmap_info.bmiHeader.biCompression = BI_RGB;

    void* dib_pixels = nullptr;
    HDC screen_dc = GetDC(nullptr);
    if (screen_dc == nullptr) {
        *error_message = "GetDC failed while creating a D3D9 font atlas.";
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
        spec.font_height,
        0,
        0,
        0,
        spec.font_weight,
        FALSE,
        FALSE,
        FALSE,
        ANSI_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        ANTIALIASED_QUALITY,
        FF_DONTCARE,
        spec.face_name.c_str());
    if (memory_dc == nullptr || bitmap == nullptr ||
        dib_pixels == nullptr || font == nullptr) {
        if (font != nullptr) {
            DeleteObject(font);
        }
        if (bitmap != nullptr) {
            DeleteObject(bitmap);
        }
        if (memory_dc != nullptr) {
            DeleteDC(memory_dc);
        }
        *error_message = "GDI failed while creating a D3D9 font atlas.";
        return false;
    }

    const HGDIOBJ old_bitmap = SelectObject(memory_dc, bitmap);
    const HGDIOBJ old_font = SelectObject(memory_dc, font);
    auto CleanupGdi = [&]() {
        SelectObject(memory_dc, old_font);
        SelectObject(memory_dc, old_bitmap);
        DeleteObject(font);
        DeleteObject(bitmap);
        DeleteDC(memory_dc);
    };
    SetBkMode(memory_dc, TRANSPARENT);
    SetTextColor(memory_dc, RGB(255, 255, 255));
    std::memset(
        dib_pixels,
        0,
        static_cast<std::size_t>(spec.texture_width) *
            static_cast<std::size_t>(spec.texture_height) * 4u);

    D3d9FontAtlas candidate;
    candidate.line_height = spec.minimum_line_height;
    for (int index = 0; index < kD3d9FontGlyphCount; ++index) {
        const wchar_t glyph =
            static_cast<wchar_t>(kD3d9FontFirstGlyph + index);
        const int x = (index % spec.columns) * spec.cell_width + 2;
        const int y = (index / spec.columns) * spec.cell_height + 2;
        SIZE size{};
        if (!GetTextExtentPoint32W(memory_dc, &glyph, 1, &size) ||
            size.cx <= 0 || size.cy <= 0) {
            size.cx = spec.cell_width / 2;
            size.cy = spec.minimum_line_height;
        }
        if (!TextOutW(memory_dc, x, y, &glyph, 1)) {
            CleanupGdi();
            *error_message = "GDI failed while rasterizing a D3D9 font atlas.";
            return false;
        }
        auto& target = candidate.glyphs[index];
        target.u0 = static_cast<float>(x) / spec.texture_width;
        target.v0 = static_cast<float>(y) / spec.texture_height;
        target.u1 = static_cast<float>(x + size.cx) / spec.texture_width;
        target.v1 = static_cast<float>(y + size.cy) / spec.texture_height;
        target.width = size.cx;
        candidate.line_height =
            (std::max)(candidate.line_height, static_cast<int>(size.cy));
    }

    HRESULT result = device->CreateTexture(
        spec.texture_width,
        spec.texture_height,
        1,
        0,
        D3DFMT_A8R8G8B8,
        D3DPOOL_MANAGED,
        &candidate.texture,
        nullptr);
    if (FAILED(result) || candidate.texture == nullptr) {
        CleanupGdi();
        *error_message = "D3D9 failed to create a managed font texture.";
        return false;
    }
    D3DLOCKED_RECT locked{};
    if (FAILED(candidate.texture->LockRect(0, &locked, nullptr, 0))) {
        candidate.texture->Release();
        candidate.texture = nullptr;
        CleanupGdi();
        *error_message = "D3D9 failed to lock a managed font texture.";
        return false;
    }
    const auto* source = static_cast<const std::uint8_t*>(dib_pixels);
    for (int y = 0; y < spec.texture_height; ++y) {
        auto* destination = reinterpret_cast<std::uint32_t*>(
            static_cast<std::uint8_t*>(locked.pBits) + y * locked.Pitch);
        const auto* source_row =
            source + static_cast<std::size_t>(y) * spec.texture_width * 4u;
        for (int x = 0; x < spec.texture_width; ++x) {
            const auto blue = source_row[x * 4 + 0];
            const auto green = source_row[x * 4 + 1];
            const auto red = source_row[x * 4 + 2];
            const auto alpha = (std::max)(red, (std::max)(green, blue));
            destination[x] = D3DCOLOR_ARGB(alpha, 255, 255, 255);
        }
    }
    candidate.texture->UnlockRect(0);
    CleanupGdi();
    *atlas = candidate;
    return true;
}

void ReleaseD3d9FontAtlas(D3d9FontAtlas* atlas) {
    if (atlas == nullptr) {
        return;
    }
    if (atlas->texture != nullptr) {
        atlas->texture->Release();
    }
    *atlas = {};
}

}  // namespace sdmod
