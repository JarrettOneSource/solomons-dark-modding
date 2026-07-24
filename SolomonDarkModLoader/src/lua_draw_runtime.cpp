#include "lua_draw_runtime.h"

#include "lua_draw_internal.h"
#include "lua_sprite_runtime.h"

#include <algorithm>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

struct LuaDrawModFrame {
    std::uint64_t generation = 0;
    std::size_t pending_text_bytes = 0;
    bool accepting_commands = false;
    std::vector<LuaDrawCommand> pending_commands;
    std::vector<LuaDrawCommand> active_commands;
};

struct LuaDrawRuntimeState {
    bool initialized = false;
    std::vector<std::string> mod_order;
    std::unordered_map<std::string, LuaDrawModFrame> mod_frames;
    std::mutex mutex;
};

LuaDrawRuntimeState g_lua_draw_runtime;

LuaDrawModFrame& FindOrCreateModFrame(std::string_view mod_id) {
    const std::string owned_mod_id(mod_id);
    const auto [frame, inserted] =
        g_lua_draw_runtime.mod_frames.try_emplace(owned_mod_id);
    if (inserted) {
        frame->second.pending_commands.reserve(kLuaDrawMaxCommandsPerMod);
        frame->second.active_commands.reserve(kLuaDrawMaxCommandsPerMod);
        g_lua_draw_runtime.mod_order.push_back(owned_mod_id);
    }
    return frame->second;
}

}  // namespace

bool InitializeLuaDrawRuntime(
    const std::filesystem::path& stage_root,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (stage_root.empty()) {
        if (error_message != nullptr) {
            *error_message = "Lua draw stage root was empty.";
        }
        return false;
    }

    {
        std::scoped_lock lock(g_lua_draw_runtime.mutex);
        g_lua_draw_runtime.mod_order.clear();
        g_lua_draw_runtime.mod_frames.clear();
        g_lua_draw_runtime.initialized = true;
    }
    ResetLuaSpriteRegistry();
    detail::ConfigureLuaDrawAssets(stage_root / "images");
    return true;
}

void ShutdownLuaDrawRuntime() {
    detail::ShutdownLuaDrawRenderer();
    detail::ResetLuaDrawAssets();
    ResetLuaSpriteRegistry();

    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    g_lua_draw_runtime.initialized = false;
    g_lua_draw_runtime.mod_order.clear();
    g_lua_draw_runtime.mod_frames.clear();
}

bool IsLuaDrawRuntimeInitialized() {
    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    return g_lua_draw_runtime.initialized;
}

void BeginLuaDrawFrame(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }

    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    if (!g_lua_draw_runtime.initialized) {
        return;
    }
    auto& frame = FindOrCreateModFrame(mod_id);
    frame.pending_commands.clear();
    frame.pending_text_bytes = 0;
    frame.accepting_commands = true;
}

void CommitLuaDrawFrame(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }

    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    const auto frame = g_lua_draw_runtime.mod_frames.find(std::string(mod_id));
    if (!g_lua_draw_runtime.initialized ||
        frame == g_lua_draw_runtime.mod_frames.end() ||
        !frame->second.accepting_commands) {
        return;
    }

    frame->second.accepting_commands = false;
    frame->second.active_commands.swap(frame->second.pending_commands);
    frame->second.pending_commands.clear();
    frame->second.pending_text_bytes = 0;
    ++frame->second.generation;
}

void ClearLuaDrawFrameForMod(std::string_view mod_id) {
    if (mod_id.empty()) {
        return;
    }
    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    const std::string owner(mod_id);
    g_lua_draw_runtime.mod_frames.erase(owner);
    g_lua_draw_runtime.mod_order.erase(
        std::remove(
            g_lua_draw_runtime.mod_order.begin(),
            g_lua_draw_runtime.mod_order.end(),
            owner),
        g_lua_draw_runtime.mod_order.end());
}

bool SubmitLuaDrawCommand(
    std::string_view mod_id,
    LuaDrawCommand command,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (mod_id.empty()) {
        if (error_message != nullptr) {
            *error_message = "Lua draw command did not have a mod owner.";
        }
        return false;
    }

    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    if (!g_lua_draw_runtime.initialized) {
        if (error_message != nullptr) {
            *error_message = "Lua draw runtime is not initialized.";
        }
        return false;
    }

    const auto frame = g_lua_draw_runtime.mod_frames.find(std::string(mod_id));
    if (frame == g_lua_draw_runtime.mod_frames.end() ||
        !frame->second.accepting_commands) {
        if (error_message != nullptr) {
            *error_message =
                "sd.draw commands may only be submitted from a runtime.tick handler.";
        }
        return false;
    }
    if (frame->second.pending_commands.size() >= kLuaDrawMaxCommandsPerMod) {
        if (error_message != nullptr) {
            *error_message = "Lua draw command limit exceeded for this mod frame.";
        }
        return false;
    }
    if (command.text.size() >
        kLuaDrawMaxTextBytesPerMod - frame->second.pending_text_bytes) {
        if (error_message != nullptr) {
            *error_message = "Lua draw text-byte limit exceeded for this mod frame.";
        }
        return false;
    }

    frame->second.pending_text_bytes += command.text.size();
    frame->second.pending_commands.push_back(std::move(command));
    return true;
}

void RefreshLuaDrawFrameSnapshots(
    std::vector<LuaDrawFrameSnapshot>* snapshots) {
    if (snapshots == nullptr) {
        return;
    }
    std::scoped_lock lock(g_lua_draw_runtime.mutex);
    std::vector<LuaDrawFrameSnapshot> previous = std::move(*snapshots);
    snapshots->clear();
    if (!g_lua_draw_runtime.initialized) {
        return;
    }

    snapshots->reserve(g_lua_draw_runtime.mod_order.size());
    for (const auto& mod_id : g_lua_draw_runtime.mod_order) {
        const auto frame = g_lua_draw_runtime.mod_frames.find(mod_id);
        if (frame == g_lua_draw_runtime.mod_frames.end() ||
            frame->second.active_commands.empty()) {
            continue;
        }
        const auto cached = std::find_if(
            previous.begin(),
            previous.end(),
            [&](const LuaDrawFrameSnapshot& snapshot) {
                return snapshot.mod_id == mod_id &&
                    snapshot.generation == frame->second.generation;
            });
        if (cached != previous.end()) {
            snapshots->push_back(std::move(*cached));
            continue;
        }
        snapshots->push_back(LuaDrawFrameSnapshot{
            mod_id,
            frame->second.generation,
            frame->second.active_commands,
        });
    }
}

}  // namespace sdmod
