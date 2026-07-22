#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

struct IDirect3DDevice9;
struct IDirect3DTexture9;

namespace sdmod::detail {

void ConfigureLuaDrawAssets(const std::filesystem::path& images_directory);
void ResetLuaDrawAssets();
bool LoadLuaDrawTexture(
    IDirect3DDevice9* device,
    const std::filesystem::path& path,
    IDirect3DTexture9** texture,
    std::uint32_t* width,
    std::uint32_t* height,
    std::string* error_message);
void ShutdownLuaDrawRenderer();

}  // namespace sdmod::detail
