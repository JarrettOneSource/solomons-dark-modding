#include "native_scene_capture.h"

#include "binary_layout.h"
#include "d3d9_end_scene_hook.h"
#include "logger.h"
#include "memory_access.h"
#include "x86_hook.h"

#include <Windows.h>
#include <d3d9.h>
#include <intrin.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <exception>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

constexpr const char* kLayoutSection = "native_scene_capture";
constexpr const char* kCaptureDirectoryEnvironment =
    "SDMOD_NATIVE_SCENE_CAPTURE_DIRECTORY";
constexpr const char* kInstanceEnvironment = "SDMOD_LUA_EXEC_PIPE_NAME";
constexpr std::size_t kMaximumDrawsPerFrame = 32768;
constexpr std::size_t kNativeSpriteStride = 0xC4;
constexpr std::size_t kNativeSpriteTextureHandleOffset = 0x08;
constexpr std::size_t kNativeSpriteUvOffset = 0x4C;
constexpr std::size_t kNativeSpriteLogicalWidthOffset = 0x94;
constexpr std::size_t kNativeSpriteLogicalHeightOffset = 0x98;
constexpr std::size_t kRendererBaseXOffset = 0x68;
constexpr std::size_t kRendererBaseYOffset = 0x6C;
constexpr std::size_t kRendererRedOffset = 0x1EC;
constexpr std::size_t kRendererGreenOffset = 0x1F0;
constexpr std::size_t kRendererBlueOffset = 0x1F4;
constexpr std::size_t kRendererAlphaOffset = 0x1F8;
constexpr std::size_t kObjectPendingRemoveOffset = 0x05;
constexpr std::size_t kObjectTypeOffset = 0x08;
constexpr std::size_t kObjectWorldXOffset = 0x18;
constexpr std::size_t kObjectWorldYOffset = 0x1C;
constexpr std::size_t kObjectSortBiasOffset = 0xA0;
constexpr std::size_t kObjectLightingScalarOffset = 0xCC;
constexpr std::size_t kRegionScaleOffset = 0x80;
constexpr std::size_t kRegionWorldBoundsOffset = 0x8BBC;
constexpr std::size_t kRegionPrimaryViewOffset = 0x8BCC;
constexpr std::size_t kRegionExpandedViewOffset = 0x8BDC;
constexpr std::size_t kRegionCullingViewOffset = 0x8BEC;
constexpr std::size_t kRegionShakeMagnitudeOffset = 0x8E04;
constexpr std::size_t kRegionShakeAccumulatorOffset = 0x8E08;
constexpr uintptr_t kPreferredImageBase = 0x00400000;

enum class NativeSceneAtlasSpanKind {
    Inline,
    Array,
};

struct NativeSceneAtlasSpan {
    const char* atlas = nullptr;
    uintptr_t singleton_global = 0;
    NativeSceneAtlasSpanKind kind = NativeSceneAtlasSpanKind::Inline;
    std::size_t object_field = 0;
    std::uint32_t first_record = 0;
    std::uint32_t record_count = 0;
};

#include "native_scene_capture/generated_atlas_spans.inl"

struct NativeSpriteSignature {
    std::uint32_t texture_handle = 0;
    std::array<std::uint32_t, 8> uv_bits = {};
    std::int32_t logical_width = 0;
    std::int32_t logical_height = 0;
};

struct ResolvedNativeArt {
    std::string id;
    std::string atlas;
    std::string resolution;
    std::vector<std::string> candidates;
    std::int32_t sprite_index = -1;
    std::uint32_t texture_handle = 0;
};

enum class CapturePhase {
    PreQueue,
    SortedQueue,
    PostQueue,
};

struct CameraCapture {
    std::array<float, 4> world_bounds = {};
    std::array<float, 4> primary_view = {};
    std::array<float, 4> expanded_view = {};
    std::array<float, 4> culling_view = {};
    float scale = 0.0f;
    float shake_magnitude = 0.0f;
    float shake_accumulator = 0.0f;
};

struct SortCapture {
    bool present = false;
    std::string lane;
    std::uint32_t gather_index = 0;
    std::int32_t pass = 0;
    std::int32_t queue_origin = 0;
    std::int32_t queue_bucket_count = 0;
    std::int32_t reference_y = 0;
    std::int32_t floor_world_y = 0;
    std::int32_t floor_sort_bias = 0;
    std::int32_t relative = 0;
    std::int32_t bucket_offset = 0;
    std::int32_t bucket_index = 0;
    float world_y = 0.0f;
    float sort_bias = 0.0f;
};

struct BlendCapture {
    bool available = false;
    DWORD enabled = FALSE;
    DWORD source = 0;
    DWORD destination = 0;
    DWORD operation = 0;
};

struct DrawCapture {
    std::uint32_t order = 0;
    std::string layer;
    std::string semantic_role;
    std::string phase;
    std::string draw_kind;
    std::uintptr_t caller_preferred_address = 0;
    ResolvedNativeArt art;
    std::array<float, 4> tint = {1.0f, 1.0f, 1.0f, 1.0f};
    BlendCapture blend;
    bool has_lighting_scalar = false;
    float lighting_scalar = 0.0f;
    bool visible = false;
    std::array<float, 8> screen_quad = {};
    std::array<float, 4> screen_rect = {};
    std::array<float, 4> clipped_screen_rect = {};
    std::string transform_kind;
    std::array<float, 2> submitted_position = {};
    std::array<float, 16> submitted_matrix = {};
    std::array<float, 8> inverse_projected_world_quad = {};
    SortCapture sort;
    std::uint32_t object_type = 0;
    float object_world_x = 0.0f;
    float object_world_y = 0.0f;
};

struct PendingSpriteDraw {
    uintptr_t sprite_address = 0;
    uintptr_t caller_address = 0;
    std::string draw_kind;
    float x = 0.0f;
    float y = 0.0f;
    bool has_transform = false;
    std::array<float, 16> transform = {};
};

struct SceneFrameCapture {
    std::string label;
    std::string scene_kind;
    std::string instance;
    uintptr_t region = 0;
    CameraCapture camera;
    std::vector<SortCapture> insertions;
    std::vector<uintptr_t> insertion_objects;
    std::vector<DrawCapture> draws;
};

using RegionRenderFn = void(__thiscall*)(void* region);
using RenderQueueInsertFn =
    void(__thiscall*)(void* queue, int reference_y, void* object, int pass);
using NativeMeshDrawFn = void(__thiscall*)(
    void* renderer,
    float primitive_count,
    int vertex_count,
    int index_count,
    const float* vertices,
    const std::int16_t* indices);
using NativeUntexturedQuadFn = void(__thiscall*)(
    void* renderer,
    float x,
    float y,
    float width,
    float height);
using NativeClearFn = void(__thiscall*)(
    void* renderer,
    float red,
    float green,
    float blue,
    float alpha);
using NativeObjectRenderFn = void(__thiscall*)(void* object);

struct NativeSceneCaptureState {
    bool requested = false;
    bool initialized = false;
    bool frame_active = false;
    CapturePhase phase = CapturePhase::PreQueue;
    std::filesystem::path directory;
    std::string status = "unavailable";
    std::string pending_label;
    std::string active_label;
    std::string output_path;
    std::string error_message;
    uintptr_t runtime_image_base = 0;
    uintptr_t native_renderer_global = 0;
    std::size_t native_renderer_draw_state_offset = 0;
    std::array<X86Hook, 5> fixed_region_hooks;
    X86Hook render_queue_insert_hook;
    X86Hook mesh_draw_hook;
    X86Hook untextured_quad_hook;
    X86Hook clear_hook;
    X86Hook road_render_hook;
    X86Hook terrain_render_hook;
    std::unordered_map<uintptr_t, std::vector<std::string>> art_by_address;
    std::unordered_map<std::string, std::vector<std::string>>
        art_by_signature;
    SceneFrameCapture frame;
};

NativeSceneCaptureState g_scene_capture;
thread_local std::vector<PendingSpriteDraw> g_pending_sprite_draws;
thread_local std::vector<uintptr_t> g_scene_capture_callers;
thread_local std::vector<uintptr_t> g_scene_capture_objects;

struct MeshObjectContext {
    const char* kind = nullptr;
    uintptr_t object = 0;
};

thread_local std::vector<MeshObjectContext> g_scene_capture_mesh_objects;

constexpr std::array<uintptr_t, 5> kFixedRegionRenderPreferredAddresses = {
    0x0051EB60,
    0x0050EAC0,
    0x00519070,
    0x00511320,
    0x00519E40,
};

constexpr std::array<const char*, 5> kFixedRegionNames = {
    "courtyard",
    "mortuary",
    "storeroom",
    "library",
    "office",
};

#include "native_scene_capture/atlas_resolver.inl"
#include "native_scene_capture/observation.inl"
#include "native_scene_capture/serialization.inl"
#include "native_scene_capture/hooks.inl"

}  // namespace

#include "native_scene_capture/public_api.inl"

}  // namespace sdmod
