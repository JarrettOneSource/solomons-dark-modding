#include "lua_world_render_runtime.h"

#include "binary_layout.h"
#include "logger.h"
#include "lua_camera_runtime.h"
#include "lua_draw_internal.h"
#include "lua_draw_runtime.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "native_world_render.h"
#include "x86_hook.h"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace sdmod {
namespace {

constexpr const char* kWorldRenderLayoutSection = "lua_world_render";
constexpr std::size_t kNativeSpriteSize = 0xC4;
constexpr std::size_t kNativeSpriteValidOffset = 0x04;
constexpr std::size_t kNativeSpriteTextureHandleOffset = 0x08;
constexpr std::size_t kNativeSpriteGeometryOffset = 0x2C;
constexpr std::size_t kNativeSpriteUvOffset = 0x4C;
constexpr std::size_t kNativePageHandleOffset = 0x08;
constexpr std::size_t kNativePageRecordSize = 0x0C;
constexpr std::size_t kPuppetStorageSize = 0x140;
constexpr std::size_t kPuppetVtableEntryCount = 9;
constexpr std::size_t kPuppetWorldPositionXOffset = 0x18;
constexpr std::size_t kPuppetWorldPositionYOffset = 0x1C;
constexpr std::size_t kPuppetOwnerWorldOffset = 0x58;
constexpr std::size_t kPuppetSortBiasOffset = 0xA0;
constexpr std::size_t kPuppetBoundsPointerOffset = 0xC8;
constexpr std::size_t kPuppetRenderDispatchVtableIndex = 3;
constexpr std::size_t kPuppetPrimaryDrawVtableIndex = 7;
constexpr std::size_t kPuppetSecondaryDrawVtableIndex = 8;
constexpr float kNativeUvHalfTexel = 0.5f;
constexpr std::size_t kNativeRendererBaseRedOffset = 0x1EC;
constexpr std::size_t kNativeRendererBaseGreenOffset = 0x1F0;
constexpr std::size_t kNativeRendererBaseBlueOffset = 0x1F4;
constexpr std::size_t kNativeRendererBaseAlphaOffset = 0x1F8;
constexpr ULONGLONG kDampenPresentationDurationMilliseconds = 900;
constexpr float kDampenInitialRadius = 18.0f;
constexpr float kDampenFinalRadius = 96.0f;
constexpr std::size_t kDampenPresentationLimit = 8;
constexpr std::size_t kDampenTextureSize = 128;

using NativeRenderQueueFlushFn = void(__thiscall*)(void* queue, int pass);
using NativeArenaRenderFn = void(__thiscall*)(void* arena);
using NativeRenderQueueInsertFn =
    void(__thiscall*)(void* queue, int reference_y, void* actor, int pass);
using NativePuppetCtorFn = void*(__thiscall*)(void* puppet);
using NativeTextureUploadBgraFn =
    int(__cdecl*)(int width, int height, const void* pixels, int mode);
using NativeTextureReleaseFn = void(__thiscall*)(
    void* renderer, int texture_handle);
using NativeRenderPageRegisterFn = void(__thiscall*)(
    void* renderer, void* page_record);
using NativeRendererSetColorFn = void(__thiscall*)(
    void* renderer,
    float red,
    float green,
    float blue,
    float alpha);
using NativeUntexturedQuadFn = void(__thiscall*)(
    void* renderer,
    float x,
    float y,
    float width,
    float height);

struct NativeWorldGlyph {
    std::array<std::uint8_t, kNativeSpriteSize> bytes{};
};

struct NativeAtlasTexture {
    std::filesystem::path source_path;
    std::uint64_t revision = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    int handle = -1;
    bool load_attempted = false;
    std::string error_message;
    std::array<std::uint8_t, kNativePageRecordSize> page_record{};
};

struct NativeWorldCarrier {
    std::array<std::uint8_t, kPuppetStorageSize> puppet{};
    std::array<uintptr_t, kPuppetVtableEntryCount> vtable{};
    NativeWorldGlyph glyph;
    std::array<float, 4> bounds{};
    float opacity = 1.0f;
};

struct NativeWorldDampenPresentation {
    std::uint64_t owner_participant_id = 0;
    std::uint32_t cast_sequence = 0;
    float x = 0.0f;
    float y = 0.0f;
    ULONGLONG started_at_milliseconds = 0;
    bool draw_logged = false;
};

struct LuaWorldRendererState {
    bool initialized = false;
    std::size_t arena_render_queue_offset = 0;
    NativeRenderQueueInsertFn render_queue_insert = nullptr;
    NativeRendererSetColorFn native_renderer_set_color = nullptr;
    NativeUntexturedQuadFn native_untextured_quad = nullptr;
    NativePuppetCtorFn puppet_ctor = nullptr;
    LuaNativeGlyphDrawFn glyph_draw_at_position = nullptr;
    NativeTextureUploadBgraFn native_texture_upload_bgra = nullptr;
    NativeTextureReleaseFn native_texture_release = nullptr;
    NativeRenderPageRegisterFn native_render_page_register = nullptr;
    uintptr_t native_renderer_global = 0;
    std::size_t native_renderer_draw_state_offset = 0;
    CRITICAL_SECTION* native_texture_critical_section = nullptr;
    std::uint8_t* native_texture_critical_section_initialized = nullptr;
    X86Hook render_queue_flush_hook;
    X86Hook arena_render_hook;
    std::unordered_map<std::string, std::unique_ptr<NativeAtlasTexture>> atlas_textures;
    std::vector<std::unique_ptr<NativeWorldCarrier>> carriers;
    std::vector<LuaWorldRenderFrameSnapshot> frame_snapshots;
    NativeAtlasTexture dampen_texture;
    std::vector<NativeWorldDampenPresentation> dampen_presentations;
    std::uint32_t failure_logs_remaining = 16;
    bool logged_native_carrier_draw = false;
    bool logged_native_marker_draw = false;
    bool logged_custom_stock_geometry_draw = false;
    std::mutex mutex;
};

LuaWorldRendererState g_world_renderer;

template <typename Value>
void WriteNativeField(void* base, std::size_t offset, const Value& value) {
    std::memcpy(static_cast<std::uint8_t*>(base) + offset, &value, sizeof(value));
}

template <typename Value>
Value ReadNativeField(const void* base, std::size_t offset) {
    Value value{};
    std::memcpy(
        &value, static_cast<const std::uint8_t*>(base) + offset, sizeof(value));
    return value;
}

void SetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

void LogWorldRenderFailure(const std::string& message) {
    if (g_world_renderer.failure_logs_remaining == 0) {
        return;
    }
    --g_world_renderer.failure_logs_remaining;
    Log("lua_world_render: " + message);
}

bool TryGetLayoutValue(const char* key, uintptr_t* value) {
    return TryGetBinaryLayoutNumericValue(kWorldRenderLayoutSection, key, value) &&
        value != nullptr && *value != 0;
}

void* TryGetNativeRenderer() {
    if (g_world_renderer.native_renderer_global == 0 ||
        g_world_renderer.native_renderer_draw_state_offset == 0) {
        return nullptr;
    }
    const auto renderer = *reinterpret_cast<uintptr_t*>(
        g_world_renderer.native_renderer_global);
    if (renderer == 0) {
        return nullptr;
    }
    return reinterpret_cast<void*>(
        renderer + g_world_renderer.native_renderer_draw_state_offset);
}

#include "lua_world_renderer/native_texture_bridge.inl"

#include "lua_world_renderer/native_carrier_queue.inl"

#include "lua_world_renderer/native_indicator_lane.inl"

bool ResolveWorldRendererSeams(
    uintptr_t* render_queue_flush,
    uintptr_t* arena_render,
    std::string* error_message) {
    if (render_queue_flush == nullptr || arena_render == nullptr ||
        error_message == nullptr) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    uintptr_t arena_render_queue_offset = 0;
    uintptr_t render_queue_insert = 0;
    uintptr_t puppet_ctor = 0;
    uintptr_t glyph_draw_at_position = 0;
    uintptr_t native_texture_upload_bgra = 0;
    uintptr_t native_texture_release = 0;
    uintptr_t native_render_page_register = 0;
    uintptr_t native_renderer_global = 0;
    uintptr_t native_renderer_draw_state_offset = 0;
    uintptr_t native_texture_critical_section = 0;
    uintptr_t native_texture_critical_section_initialized = 0;
    uintptr_t configured_render_queue_flush = 0;
    uintptr_t configured_arena_render = 0;
    uintptr_t native_renderer_set_color = 0;
    uintptr_t native_untextured_quad = 0;

    if (!TryGetLayoutValue(
            "arena_render_queue_offset",
            &arena_render_queue_offset) ||
        !TryGetLayoutValue("arena_render", &configured_arena_render) ||
        !TryGetLayoutValue(
            "render_queue_flush",
            &configured_render_queue_flush) ||
        !TryGetLayoutValue(
            "render_queue_insert",
            &render_queue_insert) ||
        !TryGetLayoutValue("puppet_ctor", &puppet_ctor) ||
        !TryGetLayoutValue(
            "glyph_draw_at_position",
            &glyph_draw_at_position) ||
        !TryGetLayoutValue(
            "native_texture_upload_bgra",
            &native_texture_upload_bgra) ||
        !TryGetLayoutValue(
            "native_texture_release",
            &native_texture_release) ||
        !TryGetLayoutValue(
            "native_render_page_register",
            &native_render_page_register) ||
        !TryGetLayoutValue(
            "native_renderer_global",
            &native_renderer_global) ||
        !TryGetLayoutValue(
            "native_renderer_draw_state_offset",
            &native_renderer_draw_state_offset) ||
        !TryGetLayoutValue(
            "native_texture_critical_section",
            &native_texture_critical_section) ||
        !TryGetLayoutValue(
            "native_texture_critical_section_initialized",
            &native_texture_critical_section_initialized) ||
        !TryGetLayoutValue(
            "native_renderer_set_color",
            &native_renderer_set_color) ||
        !TryGetLayoutValue(
            "native_untextured_quad",
            &native_untextured_quad)) {
        SetError(error_message, "Native world-render layout is incomplete.");
        return false;
    }

    *render_queue_flush =
        memory.ResolveGameAddressOrZero(configured_render_queue_flush);
    *arena_render =
        memory.ResolveGameAddressOrZero(configured_arena_render);
    const auto resolved_render_queue_insert =
        memory.ResolveGameAddressOrZero(render_queue_insert);
    const auto resolved_puppet_ctor =
        memory.ResolveGameAddressOrZero(puppet_ctor);
    const auto resolved_glyph_draw =
        memory.ResolveGameAddressOrZero(glyph_draw_at_position);
    const auto resolved_texture_upload =
        memory.ResolveGameAddressOrZero(native_texture_upload_bgra);
    const auto resolved_texture_release =
        memory.ResolveGameAddressOrZero(native_texture_release);
    const auto resolved_page_register =
        memory.ResolveGameAddressOrZero(native_render_page_register);
    const auto resolved_renderer_global =
        memory.ResolveGameAddressOrZero(native_renderer_global);
    const auto resolved_texture_critical_section =
        memory.ResolveGameAddressOrZero(native_texture_critical_section);
    const auto resolved_texture_critical_section_initialized =
        memory.ResolveGameAddressOrZero(
            native_texture_critical_section_initialized);
    const auto resolved_renderer_set_color =
        memory.ResolveGameAddressOrZero(native_renderer_set_color);
    const auto resolved_untextured_quad =
        memory.ResolveGameAddressOrZero(native_untextured_quad);

    const std::array<uintptr_t, 10> executable_addresses = {
        *render_queue_flush,
        *arena_render,
        resolved_render_queue_insert,
        resolved_puppet_ctor,
        resolved_glyph_draw,
        resolved_texture_upload,
        resolved_texture_release,
        resolved_page_register,
        resolved_renderer_set_color,
        resolved_untextured_quad,
    };
    if (std::any_of(
            executable_addresses.begin(),
            executable_addresses.end(),
            [&](uintptr_t address) {
                return address == 0 ||
                    !memory.IsExecutableRange(address, 1);
            }) ||
        resolved_renderer_global == 0 ||
        resolved_texture_critical_section == 0 ||
        resolved_texture_critical_section_initialized == 0 ||
        !memory.IsReadableRange(resolved_renderer_global, sizeof(uintptr_t)) ||
        !memory.IsWritableRange(
            resolved_texture_critical_section,
            sizeof(CRITICAL_SECTION)) ||
        !memory.IsWritableRange(
            resolved_texture_critical_section_initialized,
            sizeof(std::uint8_t))) {
        SetError(error_message, "Native world-render seams failed validation.");
        return false;
    }

    g_world_renderer.arena_render_queue_offset =
        static_cast<std::size_t>(arena_render_queue_offset);
    g_world_renderer.render_queue_insert =
        reinterpret_cast<NativeRenderQueueInsertFn>(
            resolved_render_queue_insert);
    g_world_renderer.native_renderer_set_color =
        reinterpret_cast<NativeRendererSetColorFn>(
            resolved_renderer_set_color);
    g_world_renderer.native_untextured_quad =
        reinterpret_cast<NativeUntexturedQuadFn>(
            resolved_untextured_quad);
    g_world_renderer.puppet_ctor =
        reinterpret_cast<NativePuppetCtorFn>(resolved_puppet_ctor);
    g_world_renderer.glyph_draw_at_position =
        reinterpret_cast<LuaNativeGlyphDrawFn>(resolved_glyph_draw);
    g_world_renderer.native_texture_upload_bgra =
        reinterpret_cast<NativeTextureUploadBgraFn>(
            resolved_texture_upload);
    g_world_renderer.native_texture_release =
        reinterpret_cast<NativeTextureReleaseFn>(
            resolved_texture_release);
    g_world_renderer.native_render_page_register =
        reinterpret_cast<NativeRenderPageRegisterFn>(
            resolved_page_register);
    g_world_renderer.native_renderer_global = resolved_renderer_global;
    g_world_renderer.native_renderer_draw_state_offset =
        static_cast<std::size_t>(native_renderer_draw_state_offset);
    g_world_renderer.native_texture_critical_section =
        reinterpret_cast<CRITICAL_SECTION*>(
            resolved_texture_critical_section);
    g_world_renderer.native_texture_critical_section_initialized =
        reinterpret_cast<std::uint8_t*>(
            resolved_texture_critical_section_initialized);
    return true;
}

void ClearWorldRendererStateUnlocked() {
    for (auto& [atlas, texture] : g_world_renderer.atlas_textures) {
        (void)atlas;
        ReleaseNativeAtlasTexture(texture.get());
    }
    ReleaseNativeAtlasTexture(&g_world_renderer.dampen_texture);
    g_world_renderer.dampen_texture = {};
    g_world_renderer.atlas_textures.clear();
    g_world_renderer.carriers.clear();
    g_world_renderer.frame_snapshots.clear();
    g_world_renderer.dampen_presentations.clear();
    g_world_renderer.initialized = false;
    g_world_renderer.arena_render_queue_offset = 0;
    g_world_renderer.render_queue_insert = nullptr;
    g_world_renderer.native_renderer_set_color = nullptr;
    g_world_renderer.native_untextured_quad = nullptr;
    g_world_renderer.puppet_ctor = nullptr;
    g_world_renderer.glyph_draw_at_position = nullptr;
    g_world_renderer.native_texture_upload_bgra = nullptr;
    g_world_renderer.native_texture_release = nullptr;
    g_world_renderer.native_render_page_register = nullptr;
    g_world_renderer.native_renderer_global = 0;
    g_world_renderer.native_renderer_draw_state_offset = 0;
    g_world_renderer.native_texture_critical_section = nullptr;
    g_world_renderer.native_texture_critical_section_initialized = nullptr;
    g_world_renderer.failure_logs_remaining = 16;
    g_world_renderer.logged_native_carrier_draw = false;
    g_world_renderer.logged_native_marker_draw = false;
    g_world_renderer.logged_custom_stock_geometry_draw = false;
}

}  // namespace

bool InitializeLuaWorldRenderer(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (error_message == nullptr ||
        !IsLuaWorldRenderRuntimeInitialized()) {
        SetError(
            error_message,
            "Lua world-render command runtime is not initialized.");
        return false;
    }
    if (!IsLuaCameraRuntimeAvailable()) {
        SetError(
            error_message,
            "Lua native world renderer requires the Region camera runtime.");
        return false;
    }
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (g_world_renderer.initialized) {
            return true;
        }
    }

    uintptr_t render_queue_flush = 0;
    uintptr_t arena_render = 0;
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (!ResolveWorldRendererSeams(
                &render_queue_flush,
                &arena_render,
                error_message)) {
            ClearWorldRendererStateUnlocked();
            return false;
        }
    }

    std::string hook_error;
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(render_queue_flush),
            reinterpret_cast<void*>(&HookNativeRenderQueueFlush),
            5,
            &g_world_renderer.render_queue_flush_hook,
            &hook_error)) {
        std::scoped_lock lock(g_world_renderer.mutex);
        ClearWorldRendererStateUnlocked();
        SetError(
            error_message,
            "Failed to install native world render-queue hook: " +
                hook_error);
        return false;
    }

    hook_error.clear();
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(arena_render),
            reinterpret_cast<void*>(&HookNativeArenaRender),
            5,
            &g_world_renderer.arena_render_hook,
            &hook_error)) {
        RemoveX86Hook(&g_world_renderer.render_queue_flush_hook);
        std::scoped_lock lock(g_world_renderer.mutex);
        ClearWorldRendererStateUnlocked();
        SetError(
            error_message,
            "Failed to install native Arena render hook: " + hook_error);
        return false;
    }

    {
        std::scoped_lock lock(g_world_renderer.mutex);
        g_world_renderer.initialized = true;
    }
    Log(
        "Lua native world renderer initialized. queue_flush=" +
        HexString(render_queue_flush) +
        " arena_render=" + HexString(arena_render));
    return true;
}

void ShutdownLuaWorldRenderer() {
    RemoveX86Hook(&g_world_renderer.arena_render_hook);
    RemoveX86Hook(&g_world_renderer.render_queue_flush_hook);
    std::scoped_lock lock(g_world_renderer.mutex);
    ClearWorldRendererStateUnlocked();
}

bool IsLuaWorldRendererInitialized() {
    std::scoped_lock lock(g_world_renderer.mutex);
    return g_world_renderer.initialized;
}

bool TryProjectNativeWorldIndicatorPoint(
    float world_x,
    float world_y,
    float* screen_x,
    float* screen_y) {
    if (screen_x != nullptr) {
        *screen_x = 0.0f;
    }
    if (screen_y != nullptr) {
        *screen_y = 0.0f;
    }
    if (screen_x == nullptr || screen_y == nullptr) {
        return false;
    }
    LuaCameraSnapshot camera;
    if (!TryGetLuaCameraSnapshot({}, &camera) ||
        !camera.scene_available) {
        return false;
    }
    const float projected_x = (world_x - camera.origin_x) * camera.scale;
    const float projected_y = (world_y - camera.origin_y) * camera.scale;
    const float viewport_width = camera.width * camera.scale;
    const float viewport_height = camera.height * camera.scale;
    if (projected_x < 0.0f || projected_x > viewport_width ||
        projected_y < 0.0f || projected_y > viewport_height) {
        return false;
    }
    *screen_x = projected_x;
    *screen_y = projected_y;
    return true;
}

bool DrawNativeWorldIndicatorHealthBar(
    float center_x,
    float top,
    float width,
    float health_ratio) {
    if (!std::isfinite(center_x) || !std::isfinite(top) ||
        !std::isfinite(width) || width < 4.0f ||
        !std::isfinite(health_ratio)) {
        return false;
    }
    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.native_renderer_set_color == nullptr ||
        g_world_renderer.native_untextured_quad == nullptr) {
        return false;
    }
    void* renderer = TryGetNativeRenderer();
    if (renderer == nullptr) {
        return false;
    }

    constexpr float kHeight = 7.0f;
    constexpr float kInset = 1.0f;
    constexpr NativeWorldIndicatorColor kBorder{12, 6, 6, 235};
    constexpr NativeWorldIndicatorColor kEmpty{54, 13, 13, 220};
    constexpr NativeWorldIndicatorColor kHealth{190, 31, 24, 240};
    constexpr NativeWorldIndicatorColor kHighlight{255, 105, 78, 210};
    const float left = center_x - width * 0.5f;
    const float inner_width = width - kInset * 2.0f;
    const float fill_width = inner_width *
        std::clamp(health_ratio, 0.0f, 1.0f);
    const auto previous_color = ReadNativeRendererBaseColor(renderer);
    DrawNativeIndicatorQuadUnlocked(
        renderer, left, top, width, kHeight, kBorder);
    DrawNativeIndicatorQuadUnlocked(
        renderer,
        left + kInset,
        top + kInset,
        inner_width,
        kHeight - kInset * 2.0f,
        kEmpty);
    if (fill_width > 0.0f) {
        DrawNativeIndicatorQuadUnlocked(
            renderer,
            left + kInset,
            top + kInset,
            fill_width,
            kHeight - kInset * 2.0f,
            kHealth);
        DrawNativeIndicatorQuadUnlocked(
            renderer,
            left + kInset,
            top + kInset,
            fill_width,
            1.0f,
            kHighlight);
    }
    RestoreNativeRendererColor(renderer, previous_color);
    return true;
}

void QueueNativeWorldDampenPresentation(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence,
    float x,
    float y) {
    if (owner_participant_id == 0 || cast_sequence == 0 ||
        !std::isfinite(x) || !std::isfinite(y)) {
        return;
    }
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (!g_world_renderer.initialized) {
            return;
        }
        auto& presentations = g_world_renderer.dampen_presentations;
        const auto duplicate = std::find_if(
            presentations.begin(),
            presentations.end(),
            [&](const NativeWorldDampenPresentation& presentation) {
                return presentation.owner_participant_id ==
                           owner_participant_id &&
                    presentation.cast_sequence == cast_sequence;
            });
        if (duplicate != presentations.end()) {
            return;
        }
        if (presentations.size() == kDampenPresentationLimit) {
            presentations.erase(presentations.begin());
        }
        presentations.push_back(NativeWorldDampenPresentation{
            owner_participant_id,
            cast_sequence,
            x,
            y,
            GetTickCount64(),
            false,
        });
    }
    Log(
        "Multiplayer Dampen native world presentation queued. "
        "owner_participant_id=" +
        std::to_string(owner_participant_id) +
        " cast_sequence=" + std::to_string(cast_sequence) +
        " xy=(" + std::to_string(x) + "," + std::to_string(y) + ")");
}

bool DrawLuaSpriteWithStockGeometry(
    std::string_view atlas,
    std::uint32_t sprite_index,
    const void* stock_sprite,
    float x,
    float y,
    LuaNativeGlyphDrawFn draw,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (atlas.empty() || stock_sprite == nullptr || draw == nullptr ||
        error_message == nullptr || !std::isfinite(x) || !std::isfinite(y)) {
        return false;
    }

    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized) {
        SetError(error_message, "Native world renderer is not initialized.");
        return false;
    }
    LuaDrawSpriteInfo sprite;
    std::string canonical_atlas;
    if (!TryGetLuaDrawSpriteInfo(
            atlas,
            sprite_index,
            &sprite,
            &canonical_atlas,
            error_message) ||
        sprite.rotated) {
        return false;
    }
    auto* texture = GetNativeAtlasTexture(canonical_atlas);
    if (texture == nullptr) {
        SetError(error_message, "Native potion atlas texture is unavailable.");
        return false;
    }

    NativeWorldGlyph glyph;
    std::memcpy(
        glyph.bytes.data(),
        stock_sprite,
        glyph.bytes.size());
    const std::uint8_t valid = 1;
    WriteNativeField(
        glyph.bytes.data(),
        kNativeSpriteValidOffset,
        valid);
    WriteNativeField(
        glyph.bytes.data(),
        kNativeSpriteTextureHandleOffset,
        texture->handle);
    if (!WriteNativeUv(sprite, *texture, &glyph, error_message)) {
        return false;
    }
    draw(glyph.bytes.data(), x, y);
    if (!g_world_renderer.logged_custom_stock_geometry_draw) {
        g_world_renderer.logged_custom_stock_geometry_draw = true;
        Log(
            "lua_world_render: custom glyph reached stock carrier draw batch. "
            "atlas=" + canonical_atlas +
            " record=" + std::to_string(sprite_index));
    }
    return true;
}

}  // namespace sdmod
