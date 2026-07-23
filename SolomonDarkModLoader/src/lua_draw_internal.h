#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

#include "lua_draw_runtime.h"

struct IDirect3DDevice9;
struct IDirect3DTexture9;

namespace sdmod::detail {

void ConfigureLuaDrawAssets(const std::filesystem::path& images_directory);
void ResetLuaDrawAssets();
bool TryParseLuaDrawSpriteBundle(
    const std::filesystem::path& path,
    std::vector<LuaDrawSpriteInfo>* sprites,
    std::string* error_message);
bool LoadLuaDrawTexture(
    IDirect3DDevice9* device,
    const std::filesystem::path& path,
    IDirect3DTexture9** texture,
    std::uint32_t* width,
    std::uint32_t* height,
    std::string* error_message);
void ShutdownLuaDrawRenderer();

}  // namespace sdmod::detail
