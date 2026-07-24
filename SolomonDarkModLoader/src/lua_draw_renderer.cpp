#include "lua_draw_runtime.h"

#include "d3d9_end_scene_hook.h"
#include "d3d9_font_atlas.h"
#include "logger.h"
#include "lua_draw_internal.h"
#include "lua_item_runtime.h"

#include <Windows.h>
#include <d3d9.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

constexpr float kMinimumPositiveClipW = 0.0001f;

struct LuaDrawColorVertex {
    float x;
    float y;
    float z;
    float rhw;
    D3DCOLOR color;
};

struct LuaDrawTexturedVertex {
    float x;
    float y;
    float z;
    float rhw;
    D3DCOLOR color;
    float u;
    float v;
};

constexpr DWORD kLuaDrawColorVertexFvf =
    D3DFVF_XYZRHW | D3DFVF_DIFFUSE;
constexpr DWORD kLuaDrawTexturedVertexFvf =
    D3DFVF_XYZRHW | D3DFVF_DIFFUSE | D3DFVF_TEX1;

struct LuaDrawFontResource {
    D3d9FontAtlas atlas;
    bool load_attempted = false;
    std::string error_message;
};

struct LuaDrawAtlasTexture {
    IDirect3DTexture9* texture = nullptr;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::filesystem::path source_path;
    std::uint64_t revision = 0;
    bool load_attempted = false;
    std::string error_message;
};

struct LuaDrawProjectionSnapshot {
    D3DVIEWPORT9 viewport{};
    D3DMATRIX world{};
    D3DMATRIX view{};
    D3DMATRIX projection{};
    std::uint64_t generation = 0;
    bool valid = false;
};

struct LuaDrawRendererState {
    bool started = false;
    bool first_frame_logged = false;
    int draw_failure_logs_remaining = 8;
    IDirect3DDevice9* resource_device = nullptr;
    LuaDrawFontResource font;
    std::unordered_map<std::string, LuaDrawAtlasTexture> atlas_textures;
    std::vector<LuaDrawFrameSnapshot> frame_snapshots;
    std::vector<LuaDrawColorVertex> color_batch_vertices;
    std::vector<LuaDrawTexturedVertex> textured_batch_vertices;
    LuaDrawProjectionSnapshot world_projection;
    D3DVIEWPORT9 last_viewport{};
    std::mutex mutex;
};

LuaDrawRendererState g_lua_draw_renderer;

struct LuaDrawHomogeneousPoint {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    float w = 1.0f;
};

LuaDrawHomogeneousPoint TransformRowVector(
    const LuaDrawHomogeneousPoint& point,
    const D3DMATRIX& matrix) {
    return {
        point.x * matrix._11 + point.y * matrix._21 +
            point.z * matrix._31 + point.w * matrix._41,
        point.x * matrix._12 + point.y * matrix._22 +
            point.z * matrix._32 + point.w * matrix._42,
        point.x * matrix._13 + point.y * matrix._23 +
            point.z * matrix._33 + point.w * matrix._43,
        point.x * matrix._14 + point.y * matrix._24 +
            point.z * matrix._34 + point.w * matrix._44,
    };
}

bool IsFiniteMatrix(const D3DMATRIX& matrix) {
    for (int row = 0; row < 4; ++row) {
        for (int column = 0; column < 4; ++column) {
            if (!std::isfinite(matrix.m[row][column])) {
                return false;
            }
        }
    }
    return true;
}

#include "lua_draw_renderer/rendering_helpers.inl"

}  // namespace

bool StartLuaDrawRenderer(
    std::uintptr_t device_pointer_global,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!IsLuaDrawRuntimeInitialized()) {
        if (error_message != nullptr) {
            *error_message = "Lua draw runtime is not initialized.";
        }
        return false;
    }
    {
        std::scoped_lock lock(g_lua_draw_renderer.mutex);
        if (g_lua_draw_renderer.started) {
            return true;
        }
    }
    if (!InstallD3d9FrameHook(
            device_pointer_global,
            &RenderLuaDrawFrame,
            error_message)) {
        return false;
    }
    {
        std::scoped_lock lock(g_lua_draw_renderer.mutex);
        g_lua_draw_renderer.started = true;
    }
    Log("Lua draw renderer subscribed to the D3D9 frame hook.");
    return true;
}

bool IsLuaDrawRendererStarted() {
    std::scoped_lock lock(g_lua_draw_renderer.mutex);
    return g_lua_draw_renderer.started;
}

namespace detail {

void ShutdownLuaDrawRenderer() {
    RemoveD3d9FrameCallback(&RenderLuaDrawFrame);
    std::scoped_lock lock(g_lua_draw_renderer.mutex);
    ReleaseRendererResourcesUnlocked();
    g_lua_draw_renderer.started = false;
    g_lua_draw_renderer.first_frame_logged = false;
    g_lua_draw_renderer.draw_failure_logs_remaining = 8;
    g_lua_draw_renderer.frame_snapshots.clear();
    g_lua_draw_renderer.world_projection = {};
    g_lua_draw_renderer.last_viewport = {};
}

}  // namespace detail

void CaptureLuaDrawWorldProjection(IDirect3DDevice9* device) {
    if (device == nullptr) {
        return;
    }
    LuaDrawProjectionSnapshot snapshot;
    if (FAILED(device->GetViewport(&snapshot.viewport)) ||
        snapshot.viewport.Width == 0 ||
        snapshot.viewport.Height == 0 ||
        FAILED(device->GetTransform(D3DTS_WORLD, &snapshot.world)) ||
        FAILED(device->GetTransform(D3DTS_VIEW, &snapshot.view)) ||
        FAILED(device->GetTransform(D3DTS_PROJECTION, &snapshot.projection)) ||
        !IsFiniteMatrix(snapshot.world) ||
        !IsFiniteMatrix(snapshot.view) ||
        !IsFiniteMatrix(snapshot.projection)) {
        return;
    }
    snapshot.valid = true;

    std::scoped_lock lock(g_lua_draw_renderer.mutex);
    if (!g_lua_draw_renderer.started) {
        return;
    }
    snapshot.generation =
        g_lua_draw_renderer.world_projection.generation + 1;
    g_lua_draw_renderer.world_projection = snapshot;
}

bool TryProjectLuaDrawWorldPoint(
    float world_x,
    float world_y,
    float world_z,
    LuaDrawProjectionResult* result,
    std::string* error_message) {
    if (result != nullptr) {
        *result = {};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (result == nullptr || error_message == nullptr) {
        return false;
    }

    LuaDrawProjectionSnapshot snapshot;
    {
        std::scoped_lock lock(g_lua_draw_renderer.mutex);
        snapshot = g_lua_draw_renderer.world_projection;
    }
    if (!snapshot.valid) {
        *error_message =
            "No gameplay world projection has been captured yet.";
        return false;
    }

    LuaDrawHomogeneousPoint point{world_x, world_y, world_z, 1.0f};
    point = TransformRowVector(point, snapshot.world);
    point = TransformRowVector(point, snapshot.view);
    const auto clip = TransformRowVector(point, snapshot.projection);
    if (!std::isfinite(clip.x) ||
        !std::isfinite(clip.y) ||
        !std::isfinite(clip.z) ||
        !std::isfinite(clip.w) ||
        clip.w <= kMinimumPositiveClipW) {
        *error_message = "World point is behind or outside the gameplay camera.";
        return false;
    }
    const float normalized_x = clip.x / clip.w;
    const float normalized_y = clip.y / clip.w;
    const float normalized_z = clip.z / clip.w;
    result->x = static_cast<float>(snapshot.viewport.X) +
        (normalized_x + 1.0f) * snapshot.viewport.Width * 0.5f;
    result->y = static_cast<float>(snapshot.viewport.Y) +
        (1.0f - normalized_y) * snapshot.viewport.Height * 0.5f;
    result->visible =
        normalized_x >= -1.0f && normalized_x <= 1.0f &&
        normalized_y >= -1.0f && normalized_y <= 1.0f &&
        normalized_z >= 0.0f && normalized_z <= 1.0f;
    result->viewport_width = snapshot.viewport.Width;
    result->viewport_height = snapshot.viewport.Height;
    result->generation = snapshot.generation;
    return std::isfinite(result->x) && std::isfinite(result->y);
}

bool TryGetLuaDrawViewport(
    std::uint32_t* width,
    std::uint32_t* height,
    std::string* error_message) {
    if (width != nullptr) *width = 0;
    if (height != nullptr) *height = 0;
    if (error_message != nullptr) error_message->clear();
    if (width == nullptr || height == nullptr || error_message == nullptr) {
        return false;
    }
    std::scoped_lock lock(g_lua_draw_renderer.mutex);
    if (g_lua_draw_renderer.last_viewport.Width == 0 ||
        g_lua_draw_renderer.last_viewport.Height == 0) {
        *error_message = "No D3D9 viewport has been observed yet.";
        return false;
    }
    *width = g_lua_draw_renderer.last_viewport.Width;
    *height = g_lua_draw_renderer.last_viewport.Height;
    return true;
}

void RenderLuaDrawFrame(IDirect3DDevice9* device) {
    if (device == nullptr) {
        return;
    }
    D3DVIEWPORT9 viewport{};
    if (FAILED(device->GetViewport(&viewport)) ||
        viewport.Width == 0 || viewport.Height == 0) {
        return;
    }
    const auto consumable_quads = TakeLuaConsumableRenderQuads();

    std::scoped_lock lock(g_lua_draw_renderer.mutex);
    if (!g_lua_draw_renderer.started) {
        return;
    }
    g_lua_draw_renderer.last_viewport = viewport;
    if (g_lua_draw_renderer.resource_device != device) {
        ReleaseRendererResourcesUnlocked();
        g_lua_draw_renderer.resource_device = device;
    }
    PruneUnavailableAtlasTextures();
    RefreshLuaDrawFrameSnapshots(&g_lua_draw_renderer.frame_snapshots);
    const auto& frames = g_lua_draw_renderer.frame_snapshots;
    if (frames.empty() && consumable_quads.empty()) {
        return;
    }

    bool render_state_ok = ConfigureRenderState(device);
    LuaDrawBatcher batcher(
        device,
        g_lua_draw_renderer.color_batch_vertices,
        g_lua_draw_renderer.textured_batch_vertices);
    std::size_t command_count = 0;
    for (const auto& frame : frames) {
        for (const auto& command : frame.commands) {
            ++command_count;
            if (!render_state_ok ||
                !QueueCommand(device, &batcher, command)) {
                if (g_lua_draw_renderer.draw_failure_logs_remaining > 0) {
                    --g_lua_draw_renderer.draw_failure_logs_remaining;
                    Log(
                        "Lua draw command failed. mod=" + frame.mod_id +
                        " kind=" +
                        std::to_string(static_cast<int>(command.kind)));
                }
            }
        }
    }
    for (const auto& quad : consumable_quads) {
        ++command_count;
        if ((!render_state_ok ||
             !QueueConsumableQuad(device, &batcher, quad)) &&
            g_lua_draw_renderer.draw_failure_logs_remaining > 0) {
            --g_lua_draw_renderer.draw_failure_logs_remaining;
            Log(
                "Lua consumable icon draw failed. content_id=" +
                std::to_string(quad.content_id));
        }
    }
    batcher.Finish();
    if (batcher.failed_command_count() != 0 &&
        g_lua_draw_renderer.draw_failure_logs_remaining > 0) {
        --g_lua_draw_renderer.draw_failure_logs_remaining;
        Log(
            "Lua draw D3D9 batch submission failed. commands=" +
            std::to_string(batcher.failed_command_count()));
    }
    const auto successful_command_count =
        batcher.successful_command_count();

    if (!g_lua_draw_renderer.first_frame_logged &&
        successful_command_count != 0) {
        g_lua_draw_renderer.first_frame_logged = true;
        Log(
            "Lua draw rendered its first frame. mods=" +
            std::to_string(frames.size()) +
            " commands=" + std::to_string(command_count) +
            " succeeded=" + std::to_string(successful_command_count));
    }
}

}  // namespace sdmod
