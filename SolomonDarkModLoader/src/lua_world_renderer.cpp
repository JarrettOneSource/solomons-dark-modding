#include "lua_world_render_runtime.h"

#include "binary_layout.h"
#include "logger.h"
#include "lua_draw_internal.h"
#include "lua_draw_runtime.h"
#include "memory_access.h"
#include "mod_loader.h"
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

using NativeRenderQueueFlushFn = void(__thiscall*)(void* queue, int pass);
using NativeRenderQueueInsertFn =
    void(__thiscall*)(void* queue, int reference_y, void* actor, int pass);
using NativePuppetCtorFn = void*(__thiscall*)(void* puppet);
using NativeTextureUploadBgraFn =
    int(__cdecl*)(int width, int height, const void* pixels, int mode);
using NativeTextureReleaseFn =
    void(__thiscall*)(void* renderer, int texture_handle);
using NativeRenderPageRegisterFn =
    void(__thiscall*)(void* renderer, void* page_record);

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
};

struct LuaWorldRendererState {
    bool initialized = false;
    std::size_t arena_render_queue_offset = 0;
    NativeRenderQueueInsertFn render_queue_insert = nullptr;
    NativePuppetCtorFn puppet_ctor = nullptr;
    LuaNativeGlyphDrawFn glyph_draw_at_position = nullptr;
    NativeTextureUploadBgraFn native_texture_upload_bgra = nullptr;
    NativeTextureReleaseFn native_texture_release = nullptr;
    NativeRenderPageRegisterFn native_render_page_register = nullptr;
    uintptr_t native_renderer_global = 0;
    CRITICAL_SECTION* native_texture_critical_section = nullptr;
    std::uint8_t* native_texture_critical_section_initialized = nullptr;
    X86Hook render_queue_flush_hook;
    std::unordered_map<std::string, std::unique_ptr<NativeAtlasTexture>>
        atlas_textures;
    std::vector<std::unique_ptr<NativeWorldCarrier>> carriers;
    std::vector<LuaWorldRenderFrameSnapshot> frame_snapshots;
    std::uint32_t failure_logs_remaining = 16;
    bool logged_native_carrier_draw = false;
    bool logged_custom_stock_geometry_draw = false;
    std::mutex mutex;
};

LuaWorldRendererState g_world_renderer;

template <typename Value>
void WriteNativeField(void* base, std::size_t offset, const Value& value) {
    std::memcpy(
        static_cast<std::uint8_t*>(base) + offset,
        &value,
        sizeof(value));
}

template <typename Value>
Value ReadNativeField(const void* base, std::size_t offset) {
    Value value{};
    std::memcpy(
        &value,
        static_cast<const std::uint8_t*>(base) + offset,
        sizeof(value));
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
    return TryGetBinaryLayoutNumericValue(
        kWorldRenderLayoutSection,
        key,
        value) &&
        value != nullptr && *value != 0;
}

void* TryGetNativeRenderer() {
    if (g_world_renderer.native_renderer_global == 0) {
        return nullptr;
    }
    return *reinterpret_cast<void**>(
        g_world_renderer.native_renderer_global);
}

#include "lua_world_renderer/native_texture_bridge.inl"

void __fastcall DrawWorldCarrierGlyph(
    void* self,
    void* /*unused_edx*/) {
    if (self == nullptr ||
        g_world_renderer.glyph_draw_at_position == nullptr) {
        return;
    }
    auto* carrier = static_cast<NativeWorldCarrier*>(self);
    const float x = ReadNativeField<float>(
        carrier->puppet.data(),
        kPuppetWorldPositionXOffset);
    const float y = ReadNativeField<float>(
        carrier->puppet.data(),
        kPuppetWorldPositionYOffset);
    g_world_renderer.glyph_draw_at_position(
        carrier->glyph.bytes.data(),
        x,
        y);
    if (!g_world_renderer.logged_native_carrier_draw) {
        g_world_renderer.logged_native_carrier_draw = true;
        Log("lua_world_render: native carrier glyph reached stock draw batch");
    }
}

NativeWorldCarrier* GetOrCreateCarrier(std::size_t index) {
    while (g_world_renderer.carriers.size() <= index) {
        if (g_world_renderer.carriers.size() >=
            kLuaWorldRenderMaxGlobalSprites ||
            g_world_renderer.puppet_ctor == nullptr) {
            return nullptr;
        }
        auto carrier = std::make_unique<NativeWorldCarrier>();
        if (g_world_renderer.puppet_ctor(carrier->puppet.data()) == nullptr) {
            return nullptr;
        }
        const auto native_vtable = ReadNativeField<uintptr_t>(
            carrier->puppet.data(),
            0);
        if (native_vtable == 0) {
            return nullptr;
        }
        std::memcpy(
            carrier->vtable.data(),
            reinterpret_cast<const void*>(native_vtable),
            sizeof(carrier->vtable));
        if (carrier->vtable[kPuppetRenderDispatchVtableIndex] == 0) {
            return nullptr;
        }
        carrier->vtable[kPuppetPrimaryDrawVtableIndex] =
            reinterpret_cast<uintptr_t>(&DrawWorldCarrierGlyph);
        carrier->vtable[kPuppetSecondaryDrawVtableIndex] =
            reinterpret_cast<uintptr_t>(&DrawWorldCarrierGlyph);
        WriteNativeField(
            carrier->puppet.data(),
            0,
            reinterpret_cast<uintptr_t>(carrier->vtable.data()));
        g_world_renderer.carriers.push_back(std::move(carrier));
    }
    return g_world_renderer.carriers[index].get();
}

bool PrepareWorldCarrier(
    NativeWorldCarrier* carrier,
    const LuaWorldSpriteCommand& command,
    uintptr_t world_address,
    std::string* error_message) {
    if (carrier == nullptr || world_address == 0 ||
        !BuildNativeWorldGlyph(
            command,
            &carrier->glyph,
            &carrier->bounds,
            error_message)) {
        return false;
    }
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetWorldPositionXOffset,
        command.x);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetWorldPositionYOffset,
        command.y);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetOwnerWorldOffset,
        world_address);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetSortBiasOffset,
        command.sort_bias);
    WriteNativeField(
        carrier->puppet.data(),
        kPuppetBoundsPointerOffset,
        reinterpret_cast<uintptr_t>(carrier->bounds.data()));
    return true;
}

void InsertWorldSpriteCarriers(void* queue, int pass) {
    if (queue == nullptr || pass != 0) {
        return;
    }
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) || !player.valid ||
        player.world_address == 0 || !std::isfinite(player.y)) {
        return;
    }

    std::scoped_lock lock(g_world_renderer.mutex);
    if (!g_world_renderer.initialized ||
        g_world_renderer.render_queue_insert == nullptr ||
        reinterpret_cast<uintptr_t>(queue) !=
            player.world_address + g_world_renderer.arena_render_queue_offset) {
        return;
    }
    PruneNativeAtlasTextures();
    RefreshLuaWorldRenderFrameSnapshots(
        &g_world_renderer.frame_snapshots);

    std::size_t carrier_index = 0;
    const auto reference_y = static_cast<int>(std::floor(player.y));
    for (const auto& frame : g_world_renderer.frame_snapshots) {
        for (const auto& command : frame.commands) {
            if (carrier_index >= kLuaWorldRenderMaxGlobalSprites) {
                return;
            }
            auto* carrier = GetOrCreateCarrier(carrier_index);
            std::string error_message;
            if (carrier == nullptr ||
                !PrepareWorldCarrier(
                    carrier,
                    command,
                    player.world_address,
                    &error_message)) {
                LogWorldRenderFailure(
                    "world sprite skipped. mod=" + frame.mod_id +
                    " atlas=" + command.atlas +
                    " record=" + std::to_string(command.sprite_index) +
                    " error=" + error_message);
                continue;
            }
            g_world_renderer.render_queue_insert(
                queue,
                reference_y,
                carrier->puppet.data(),
                pass);
            ++carrier_index;
        }
    }
}

void __fastcall HookNativeRenderQueueFlush(
    void* self,
    void* /*unused_edx*/,
    int pass) {
    const auto original =
        GetX86HookTrampoline<NativeRenderQueueFlushFn>(
            g_world_renderer.render_queue_flush_hook);
    if (original == nullptr) {
        return;
    }
    InsertWorldSpriteCarriers(self, pass);
    original(self, pass);
}

bool ResolveWorldRendererSeams(
    uintptr_t* render_queue_flush,
    std::string* error_message) {
    if (render_queue_flush == nullptr || error_message == nullptr) {
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
    uintptr_t native_texture_critical_section = 0;
    uintptr_t native_texture_critical_section_initialized = 0;
    uintptr_t configured_render_queue_flush = 0;

    if (!TryGetLayoutValue(
            "arena_render_queue_offset",
            &arena_render_queue_offset) ||
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
            "native_texture_critical_section",
            &native_texture_critical_section) ||
        !TryGetLayoutValue(
            "native_texture_critical_section_initialized",
            &native_texture_critical_section_initialized)) {
        SetError(error_message, "Native world-render layout is incomplete.");
        return false;
    }

    *render_queue_flush =
        memory.ResolveGameAddressOrZero(configured_render_queue_flush);
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

    const std::array<uintptr_t, 7> executable_addresses = {
        *render_queue_flush,
        resolved_render_queue_insert,
        resolved_puppet_ctor,
        resolved_glyph_draw,
        resolved_texture_upload,
        resolved_texture_release,
        resolved_page_register,
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
    g_world_renderer.atlas_textures.clear();
    g_world_renderer.carriers.clear();
    g_world_renderer.frame_snapshots.clear();
    g_world_renderer.initialized = false;
    g_world_renderer.arena_render_queue_offset = 0;
    g_world_renderer.render_queue_insert = nullptr;
    g_world_renderer.puppet_ctor = nullptr;
    g_world_renderer.glyph_draw_at_position = nullptr;
    g_world_renderer.native_texture_upload_bgra = nullptr;
    g_world_renderer.native_texture_release = nullptr;
    g_world_renderer.native_render_page_register = nullptr;
    g_world_renderer.native_renderer_global = 0;
    g_world_renderer.native_texture_critical_section = nullptr;
    g_world_renderer.native_texture_critical_section_initialized = nullptr;
    g_world_renderer.failure_logs_remaining = 16;
    g_world_renderer.logged_native_carrier_draw = false;
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
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (g_world_renderer.initialized) {
            return true;
        }
    }

    uintptr_t render_queue_flush = 0;
    {
        std::scoped_lock lock(g_world_renderer.mutex);
        if (!ResolveWorldRendererSeams(
                &render_queue_flush,
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

    {
        std::scoped_lock lock(g_world_renderer.mutex);
        g_world_renderer.initialized = true;
    }
    Log(
        "Lua native world renderer initialized. queue_flush=" +
        HexString(render_queue_flush));
    return true;
}

void ShutdownLuaWorldRenderer() {
    RemoveX86Hook(&g_world_renderer.render_queue_flush_hook);
    std::scoped_lock lock(g_world_renderer.mutex);
    ClearWorldRendererStateUnlocked();
}

bool IsLuaWorldRendererInitialized() {
    std::scoped_lock lock(g_world_renderer.mutex);
    return g_world_renderer.initialized;
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
