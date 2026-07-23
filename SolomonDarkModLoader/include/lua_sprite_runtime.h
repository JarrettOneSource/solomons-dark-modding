#pragma once

#include "lua_content_registry.h"
#include "lua_draw_runtime.h"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

inline constexpr std::size_t kLuaSpriteMaximumAtlasesPerMod = 32;
inline constexpr std::size_t kLuaSpriteMaximumGlobalAtlases = 128;
inline constexpr std::size_t kLuaSpriteMaximumFramesPerAtlas = 4096;
inline constexpr std::size_t kLuaSpriteMaximumGlobalFrames = 32768;
inline constexpr std::size_t kLuaSpriteMaximumRelativePathBytes = 512;
inline constexpr std::size_t kLuaSpriteMaximumAtlasIdBytes =
    kLuaContentMaximumIdentifierLength * 2 + 1;
inline constexpr std::uintmax_t kLuaSpriteMaximumImageBytes =
    64ULL * 1024ULL * 1024ULL;
inline constexpr std::uintmax_t kLuaSpriteMaximumBundleBytes =
    16ULL * 1024ULL * 1024ULL;
inline constexpr std::uint32_t kLuaSpriteMaximumImageDimension = 4096;
inline constexpr float kLuaSpriteMaximumFrameGeometry = 16384.0f;

struct LuaSpriteAtlasSnapshot {
    std::string id;
    std::string mod_id;
    std::string key;
    std::string image_path;
    std::string bundle_path;
    std::size_t frame_count = 0;
    std::uint32_t image_width = 0;
    std::uint32_t image_height = 0;
    std::uint64_t revision = 0;
};

bool RegisterLuaSpriteAtlas(
    std::string_view mod_id,
    const std::filesystem::path& mod_root,
    std::string_view key,
    std::string_view image_path,
    std::string_view bundle_path,
    LuaSpriteAtlasSnapshot* snapshot,
    std::string* error_message);
bool UnregisterLuaSpriteAtlas(
    std::string_view mod_id,
    std::string_view key);
std::optional<LuaSpriteAtlasSnapshot> FindLuaSpriteAtlas(
    std::string_view mod_id,
    std::string_view key);
std::vector<LuaSpriteAtlasSnapshot> ListLuaSpriteAtlases(
    std::string_view mod_id);
void ClearLuaSpriteAtlasesForMod(std::string_view mod_id);
void ResetLuaSpriteRegistry();

bool TryGetLuaRegisteredSpriteInfo(
    std::string_view atlas_id,
    std::uint32_t sprite_index,
    LuaDrawSpriteInfo* info,
    std::string* canonical_atlas,
    std::string* error_message);
bool TryGetLuaRegisteredSpriteSource(
    std::string_view atlas_id,
    std::filesystem::path* image_path,
    std::uint64_t* revision);

}  // namespace sdmod
