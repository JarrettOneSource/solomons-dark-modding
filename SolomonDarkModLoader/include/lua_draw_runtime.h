#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

struct IDirect3DDevice9;

namespace sdmod {

inline constexpr std::size_t kLuaDrawMaxCommandsPerMod = 512;
inline constexpr std::size_t kLuaDrawMaxTextBytesPerMod = 16 * 1024;
inline constexpr std::size_t kLuaDrawMaxTextCommandBytes = 1024;
inline constexpr std::size_t kLuaDrawMaxAtlasNameBytes = 32;

enum class LuaDrawCommandKind : std::uint8_t {
    Text,
    FilledRect,
    OutlinedRect,
    Line,
    Sprite,
};

struct LuaDrawColor {
    std::uint8_t red = 255;
    std::uint8_t green = 255;
    std::uint8_t blue = 255;
    std::uint8_t alpha = 255;
};

struct LuaDrawCommand {
    LuaDrawCommandKind kind = LuaDrawCommandKind::Text;
    float x = 0.0f;
    float y = 0.0f;
    float width = 0.0f;
    float height = 0.0f;
    float x2 = 0.0f;
    float y2 = 0.0f;
    float thickness = 1.0f;
    float scale = 1.0f;
    LuaDrawColor color;
    std::string text;
    std::string atlas;
    std::uint32_t sprite_index = 0;
    bool centered = false;
};

struct LuaDrawFrameSnapshot {
    std::string mod_id;
    std::uint64_t generation = 0;
    std::vector<LuaDrawCommand> commands;
};

struct LuaDrawSpriteInfo {
    float atlas_x = 0.0f;
    float atlas_y = 0.0f;
    float packed_width = 0.0f;
    float packed_height = 0.0f;
    std::int32_t logical_width = 0;
    std::uint32_t logical_height = 0;
    float content_width = 0.0f;
    float content_height = 0.0f;
    float center_offset_x = 0.0f;
    float center_offset_y = 0.0f;
    bool rotated = false;
};

struct LuaDrawProjectionResult {
    float x = 0.0f;
    float y = 0.0f;
    bool visible = false;
    std::uint32_t viewport_width = 0;
    std::uint32_t viewport_height = 0;
    std::uint64_t generation = 0;
};

bool InitializeLuaDrawRuntime(
    const std::filesystem::path& stage_root,
    std::string* error_message);
bool StartLuaDrawRenderer(
    std::uintptr_t device_pointer_global,
    std::string* error_message);
void ShutdownLuaDrawRuntime();
bool IsLuaDrawRuntimeInitialized();
bool IsLuaDrawRendererStarted();

void BeginLuaDrawFrame(std::string_view mod_id);
void CommitLuaDrawFrame(std::string_view mod_id);
bool SubmitLuaDrawCommand(
    std::string_view mod_id,
    LuaDrawCommand command,
    std::string* error_message);
std::vector<LuaDrawFrameSnapshot> SnapshotLuaDrawFrames();

bool TryGetLuaDrawSpriteInfo(
    std::string_view atlas,
    std::uint32_t sprite_index,
    LuaDrawSpriteInfo* info,
    std::string* canonical_atlas,
    std::string* error_message);
std::filesystem::path GetLuaDrawAtlasImagePath(std::string_view canonical_atlas);

void CaptureLuaDrawWorldProjection(IDirect3DDevice9* device);
bool TryProjectLuaDrawWorldPoint(
    float world_x,
    float world_y,
    float world_z,
    LuaDrawProjectionResult* result,
    std::string* error_message);
bool TryGetLuaDrawViewport(
    std::uint32_t* width,
    std::uint32_t* height,
    std::string* error_message);
void RenderLuaDrawFrame(IDirect3DDevice9* device);

}  // namespace sdmod
