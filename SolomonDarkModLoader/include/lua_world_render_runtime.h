#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace sdmod {

inline constexpr std::size_t kLuaWorldRenderMaxSpritesPerMod = 256;
inline constexpr std::size_t kLuaWorldRenderMaxGlobalSprites = 2048;
inline constexpr float kLuaWorldRenderMaximumCoordinate = 1000000.0f;
inline constexpr float kLuaWorldRenderMaximumDimension = 16384.0f;
inline constexpr float kLuaWorldRenderMaximumSortBias = 16384.0f;

struct LuaWorldSpriteCommand {
    std::string atlas;
    std::uint32_t sprite_index = 0;
    float x = 0.0f;
    float y = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
    float offset_x = 0.0f;
    float offset_y = 0.0f;
    float sort_bias = 0.0f;
};

struct LuaWorldRenderFrameSnapshot {
    std::string mod_id;
    std::uint64_t generation = 0;
    std::vector<LuaWorldSpriteCommand> commands;
};

using LuaNativeGlyphDrawFn =
    void(__thiscall*)(void* sprite, float x, float y);

void InitializeLuaWorldRenderRuntime();
void ResetLuaWorldRenderRuntime();
bool IsLuaWorldRenderRuntimeInitialized();

void BeginLuaWorldRenderFrame(std::string_view mod_id);
void CommitLuaWorldRenderFrame(std::string_view mod_id);
void ClearLuaWorldRenderFrameForMod(std::string_view mod_id);
bool SubmitLuaWorldSpriteCommand(
    std::string_view mod_id,
    LuaWorldSpriteCommand command,
    std::string* error_message);
void RefreshLuaWorldRenderFrameSnapshots(
    std::vector<LuaWorldRenderFrameSnapshot>* snapshots);

bool InitializeLuaWorldRenderer(std::string* error_message);
void ShutdownLuaWorldRenderer();
bool IsLuaWorldRendererInitialized();

bool DrawLuaSpriteWithStockGeometry(
    std::string_view atlas,
    std::uint32_t sprite_index,
    const void* stock_sprite,
    float x,
    float y,
    LuaNativeGlyphDrawFn draw,
    std::string* error_message);

}  // namespace sdmod
