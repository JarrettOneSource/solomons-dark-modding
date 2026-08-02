#include "lua_world_render_runtime.h"

#include "lua_draw_runtime.h"

#include <algorithm>
#include <cmath>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

struct LuaWorldRenderModFrame {
    std::uint64_t generation = 0;
    bool accepting_commands = false;
    std::vector<LuaWorldSpriteCommand> pending_commands;
    std::vector<LuaWorldSpriteCommand> active_commands;
};

struct LuaWorldRenderRuntimeState {
    bool initialized = false;
    std::vector<std::string> mod_order;
    std::unordered_map<std::string, LuaWorldRenderModFrame> mod_frames;
    std::mutex mutex;
};

LuaWorldRenderRuntimeState g_lua_world_render_runtime;

LuaWorldRenderModFrame& FindOrCreateWorldFrame(std::string_view mod_id) {
    const std::string owned_mod_id(mod_id);
    const auto [frame, inserted] =
        g_lua_world_render_runtime.mod_frames.try_emplace(owned_mod_id);
    if (inserted) {
        frame->second.pending_commands.reserve(
            kLuaWorldRenderMaxSpritesPerMod);
        frame->second.active_commands.reserve(
            kLuaWorldRenderMaxSpritesPerMod);
        g_lua_world_render_runtime.mod_order.push_back(owned_mod_id);
    }
    return frame->second;
}

bool IsBoundedFinite(float value, float maximum_magnitude) {
    return std::isfinite(value) &&
        value >= -maximum_magnitude &&
        value <= maximum_magnitude;
}

std::size_t CountOtherActiveCommands(std::string_view owner) {
    std::size_t count = 0;
    for (const auto& [mod_id, frame] :
         g_lua_world_render_runtime.mod_frames) {
        if (mod_id != owner) {
            count += frame.active_commands.size();
        }
    }
    return count;
}

void SetError(std::string* error_message, std::string message) {
    if (error_message != nullptr) {
        *error_message = std::move(message);
    }
}

}  // namespace

void InitializeLuaWorldRenderRuntime() {
    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    g_lua_world_render_runtime.mod_order.clear();
    g_lua_world_render_runtime.mod_frames.clear();
    g_lua_world_render_runtime.initialized = true;
}

void ResetLuaWorldRenderRuntime() {
    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    g_lua_world_render_runtime.initialized = false;
    g_lua_world_render_runtime.mod_order.clear();
    g_lua_world_render_runtime.mod_frames.clear();
}

bool IsLuaWorldRenderRuntimeInitialized() {
    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    return g_lua_world_render_runtime.initialized;
}

void BeginLuaWorldRenderFrame(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }
    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    if (!g_lua_world_render_runtime.initialized) {
        return;
    }
    auto& frame = FindOrCreateWorldFrame(mod_id);
    frame.pending_commands.clear();
    frame.accepting_commands = true;
}

void CommitLuaWorldRenderFrame(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }
    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    const auto frame =
        g_lua_world_render_runtime.mod_frames.find(std::string(mod_id));
    if (!g_lua_world_render_runtime.initialized ||
        frame == g_lua_world_render_runtime.mod_frames.end() ||
        !frame->second.accepting_commands) {
        return;
    }
    frame->second.accepting_commands = false;
    frame->second.active_commands.swap(frame->second.pending_commands);
    frame->second.pending_commands.clear();
    ++frame->second.generation;
}

void ClearLuaWorldRenderFrameForMod(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }
    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    const std::string owner(mod_id);
    g_lua_world_render_runtime.mod_frames.erase(owner);
    g_lua_world_render_runtime.mod_order.erase(
        std::remove(
            g_lua_world_render_runtime.mod_order.begin(),
            g_lua_world_render_runtime.mod_order.end(),
            owner),
        g_lua_world_render_runtime.mod_order.end());
}

bool SubmitLuaWorldSpriteCommand(
    std::string_view mod_id,
    LuaWorldSpriteCommand command,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (mod_id.empty() || error_message == nullptr) {
        return false;
    }
    if (command.atlas.empty()) {
        SetError(error_message, "World sprite atlas must not be empty.");
        return false;
    }
    if (!IsBoundedFinite(command.x, kLuaWorldRenderMaximumCoordinate) ||
        !IsBoundedFinite(command.y, kLuaWorldRenderMaximumCoordinate) ||
        !IsBoundedFinite(
            command.offset_x,
            kLuaWorldRenderMaximumCoordinate) ||
        !IsBoundedFinite(
            command.offset_y,
            kLuaWorldRenderMaximumCoordinate) ||
        !std::isfinite(command.width) || command.width <= 0.0f ||
        command.width > kLuaWorldRenderMaximumDimension ||
        !std::isfinite(command.height) || command.height <= 0.0f ||
        command.height > kLuaWorldRenderMaximumDimension ||
        !IsBoundedFinite(
            command.sort_bias,
            kLuaWorldRenderMaximumSortBias)) {
        SetError(error_message, "World sprite geometry is outside its bound.");
        return false;
    }

    LuaDrawSpriteInfo sprite;
    std::string canonical_atlas;
    if (!TryGetLuaDrawSpriteInfo(
            command.atlas,
            command.sprite_index,
            &sprite,
            &canonical_atlas,
            error_message)) {
        return false;
    }
    if (sprite.rotated) {
        SetError(error_message, "Rotated world sprite records are unsupported.");
        return false;
    }
    command.atlas = std::move(canonical_atlas);

    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    if (!g_lua_world_render_runtime.initialized) {
        SetError(error_message, "Native world rendering is not initialized.");
        return false;
    }
    const auto found =
        g_lua_world_render_runtime.mod_frames.find(std::string(mod_id));
    if (found == g_lua_world_render_runtime.mod_frames.end() ||
        !found->second.accepting_commands) {
        SetError(
            error_message,
            "World sprites may only be submitted during runtime.tick.");
        return false;
    }
    auto& pending = found->second.pending_commands;
    if (pending.size() >= kLuaWorldRenderMaxSpritesPerMod) {
        SetError(error_message, "Per-mod world sprite frame limit exceeded.");
        return false;
    }
    const auto other_active = CountOtherActiveCommands(mod_id);
    if (other_active + pending.size() + 1 >
        kLuaWorldRenderMaxGlobalSprites) {
        SetError(error_message, "Global world sprite frame limit exceeded.");
        return false;
    }
    pending.push_back(std::move(command));
    return true;
}

void RefreshLuaWorldRenderFrameSnapshots(
    std::vector<LuaWorldRenderFrameSnapshot>* snapshots) {
    if (snapshots == nullptr) {
        return;
    }
    std::vector<LuaWorldRenderFrameSnapshot> previous;
    previous.swap(*snapshots);

    std::scoped_lock lock(g_lua_world_render_runtime.mutex);
    if (!g_lua_world_render_runtime.initialized) {
        return;
    }
    snapshots->reserve(g_lua_world_render_runtime.mod_order.size());
    for (const auto& mod_id : g_lua_world_render_runtime.mod_order) {
        const auto frame =
            g_lua_world_render_runtime.mod_frames.find(mod_id);
        if (frame == g_lua_world_render_runtime.mod_frames.end() ||
            frame->second.active_commands.empty()) {
            continue;
        }
        const auto cached = std::find_if(
            previous.begin(),
            previous.end(),
            [&](const LuaWorldRenderFrameSnapshot& snapshot) {
                return snapshot.mod_id == mod_id &&
                    snapshot.generation == frame->second.generation;
            });
        if (cached != previous.end()) {
            snapshots->push_back(std::move(*cached));
            continue;
        }
        snapshots->push_back(LuaWorldRenderFrameSnapshot{
            mod_id,
            frame->second.generation,
            frame->second.active_commands,
        });
    }
}

}  // namespace sdmod
