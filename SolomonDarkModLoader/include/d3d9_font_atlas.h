#pragma once

#include <array>
#include <string>

struct IDirect3DDevice9;
struct IDirect3DTexture9;

namespace sdmod {

inline constexpr int kD3d9FontFirstGlyph = 32;
inline constexpr int kD3d9FontLastGlyph = 126;
inline constexpr int kD3d9FontGlyphCount =
    kD3d9FontLastGlyph - kD3d9FontFirstGlyph + 1;

struct D3d9FontGlyph {
    float u0 = 0.0f;
    float v0 = 0.0f;
    float u1 = 0.0f;
    float v1 = 0.0f;
    int width = 0;
};

struct D3d9FontAtlas {
    IDirect3DTexture9* texture = nullptr;
    std::array<D3d9FontGlyph, kD3d9FontGlyphCount> glyphs{};
    int line_height = 16;
};

struct D3d9FontAtlasSpec {
    int font_height = -16;
    int font_weight = 400;
    int minimum_line_height = 16;
    int texture_width = 512;
    int texture_height = 256;
    int cell_width = 32;
    int cell_height = 32;
    int columns = 16;
    std::wstring face_name = L"Consolas";
};

bool InitializeD3d9FontAtlas(
    IDirect3DDevice9* device,
    const D3d9FontAtlasSpec& spec,
    D3d9FontAtlas* atlas,
    std::string* error_message);
void ReleaseD3d9FontAtlas(D3d9FontAtlas* atlas);

}  // namespace sdmod
