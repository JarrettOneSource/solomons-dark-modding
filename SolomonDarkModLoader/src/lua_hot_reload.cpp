#include "lua_engine_internal.h"

#include "logger.h"
#include "lua_source_loader.h"

extern "C" {
#include "lauxlib.h"
#include "lua.h"
}

#include <array>
#include <filesystem>
#include <fstream>
#include <string>
#include <system_error>

namespace sdmod::detail {
namespace {

constexpr std::uint64_t kLuaHotReloadPollIntervalMs = 250;
constexpr std::uint64_t kLuaHotReloadStableIntervalMs = 300;
constexpr std::uint64_t kLuaHotReloadMaximumSourceBytes = 1024 * 1024;
constexpr std::uint64_t kFnvOffsetBasis = 14695981039346656037ull;
constexpr std::uint64_t kFnvPrime = 1099511628211ull;

std::uint64_t& NextLuaHotReloadPollMs() {
    static std::uint64_t value = 0;
    return value;
}

bool& LuaHotReloadDeferredLogEmitted() {
    static bool value = false;
    return value;
}

bool SameFingerprint(
    const LuaSourceFingerprint& left,
    const LuaSourceFingerprint& right) {
    return left.exists == right.exists &&
        left.size == right.size &&
        left.hash == right.hash;
}

bool TryReadFingerprint(
    const std::filesystem::path& path,
    LuaSourceFingerprint* fingerprint,
    std::string* error_message) {
    if (fingerprint == nullptr || error_message == nullptr) {
        return false;
    }
    *fingerprint = LuaSourceFingerprint{};
    error_message->clear();

    std::error_code filesystem_error;
    const bool regular_file = std::filesystem::is_regular_file(path, filesystem_error);
    if (filesystem_error) {
        *error_message =
            "could not inspect source entry script: " + filesystem_error.message();
        return false;
    }
    if (!regular_file) {
        return true;
    }

    fingerprint->exists = true;
    fingerprint->size = std::filesystem::file_size(path, filesystem_error);
    if (filesystem_error) {
        *error_message =
            "could not measure source entry script: " + filesystem_error.message();
        return false;
    }
    if (fingerprint->size > kLuaHotReloadMaximumSourceBytes) {
        return true;
    }

    std::ifstream stream(path, std::ios::binary);
    if (!stream.is_open()) {
        *error_message = "could not open source entry script.";
        return false;
    }

    std::uint64_t hash = kFnvOffsetBasis;
    std::array<char, 4096> buffer = {};
    while (stream.good()) {
        stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto bytes_read = stream.gcount();
        for (std::streamsize index = 0; index < bytes_read; ++index) {
            hash ^= static_cast<unsigned char>(buffer[static_cast<std::size_t>(index)]);
            hash *= kFnvPrime;
        }
    }
    if (!stream.eof()) {
        *error_message = "could not read source entry script.";
        return false;
    }
    fingerprint->hash = hash;
    return true;
}

bool PreflightLuaSource(
    const LoadedLuaMod& mod,
    const LuaSourceFingerprint& fingerprint,
    std::string* error_message) {
    if (error_message == nullptr) {
        return false;
    }
    error_message->clear();
    if (!fingerprint.exists) {
        *error_message = "source entry script does not exist.";
        return false;
    }
    if (fingerprint.size > kLuaHotReloadMaximumSourceBytes) {
        *error_message =
            "source entry script exceeds the 1 MiB hot-reload limit.";
        return false;
    }

    auto* preflight_state = luaL_newstate();
    if (preflight_state == nullptr) {
        *error_message = "luaL_newstate failed during syntax preflight.";
        return false;
    }
    if (!LoadLuaSourceFile(
            preflight_state,
            mod.descriptor.source_entry_script_path,
            error_message)) {
        lua_close(preflight_state);
        return false;
    }
    lua_close(preflight_state);
    return true;
}

void ResetPendingCandidate(LoadedLuaMod* mod) {
    if (mod == nullptr) {
        return;
    }
    mod->hot_reload.pending = false;
    mod->hot_reload.pending_fingerprint = LuaSourceFingerprint{};
    mod->hot_reload.pending_since_ms = 0;
}

bool HasEnabledHotReloadMod() {
    for (const auto& mod : LoadedLuaModsStorage()) {
        if (mod != nullptr && mod->descriptor.hot_reload && mod->hot_reload.initialized) {
            return true;
        }
    }
    return false;
}

}  // namespace

void InitializeLuaHotReloadState(LoadedLuaMod* mod) {
    if (mod == nullptr || !mod->descriptor.hot_reload) {
        return;
    }
    if (mod->descriptor.source_entry_script_path.empty()) {
        LogLuaMessage(*mod, "hot reload disabled: source entry script path is empty.");
        mod->descriptor.hot_reload = false;
        return;
    }

    std::string read_error;
    LuaSourceFingerprint fingerprint;
    if (!TryReadFingerprint(
            mod->descriptor.source_entry_script_path,
            &fingerprint,
            &read_error)) {
        LogLuaMessage(*mod, "hot reload disabled: " + read_error);
        mod->descriptor.hot_reload = false;
        return;
    }

    mod->hot_reload = LuaHotReloadState{};
    mod->hot_reload.initialized = true;
    mod->hot_reload.accepted = fingerprint;
    LogLuaMessage(
        *mod,
        "hot reload watching source entry script: " +
            mod->descriptor.source_entry_script_path.string());
}

void ResetLuaHotReloadRuntime() {
    NextLuaHotReloadPollMs() = 0;
    LuaHotReloadDeferredLogEmitted() = false;
}

void PollLuaHotReloadsOnLockedThread(
    bool multiplayer_transport_enabled,
    std::uint64_t now_ms) {
    if (now_ms < NextLuaHotReloadPollMs()) {
        return;
    }
    NextLuaHotReloadPollMs() = now_ms + kLuaHotReloadPollIntervalMs;
    if (!HasEnabledHotReloadMod()) {
        return;
    }

    if (multiplayer_transport_enabled) {
        for (const auto& mod : LoadedLuaModsStorage()) {
            ResetPendingCandidate(mod.get());
        }
        if (!LuaHotReloadDeferredLogEmitted()) {
            Log("[lua] hot reload deferred for this multiplayer transport session.");
            LuaHotReloadDeferredLogEmitted() = true;
        }
        return;
    }
    if (LuaHotReloadDeferredLogEmitted()) {
        Log("[lua] hot reload resumed after the multiplayer transport stopped.");
        LuaHotReloadDeferredLogEmitted() = false;
    }

    for (const auto& loaded_mod : LoadedLuaModsStorage()) {
        auto* mod = loaded_mod.get();
        if (mod == nullptr || !mod->descriptor.hot_reload || !mod->hot_reload.initialized) {
            continue;
        }

        LuaSourceFingerprint observed;
        std::string read_error;
        if (!TryReadFingerprint(
                mod->descriptor.source_entry_script_path,
                &observed,
                &read_error)) {
            if (!mod->hot_reload.read_error_logged) {
                LogLuaMessage(*mod, "hot reload read failed: " + read_error);
                mod->hot_reload.read_error_logged = true;
            }
            ResetPendingCandidate(mod);
            continue;
        }
        mod->hot_reload.read_error_logged = false;

        if (SameFingerprint(observed, mod->hot_reload.accepted)) {
            ResetPendingCandidate(mod);
            continue;
        }
        if (!mod->hot_reload.pending ||
            !SameFingerprint(observed, mod->hot_reload.pending_fingerprint)) {
            mod->hot_reload.pending = true;
            mod->hot_reload.pending_fingerprint = observed;
            mod->hot_reload.pending_since_ms = now_ms;
            continue;
        }
        if (now_ms - mod->hot_reload.pending_since_ms <
            kLuaHotReloadStableIntervalMs) {
            continue;
        }

        const auto candidate = mod->hot_reload.pending_fingerprint;
        mod->hot_reload.accepted = candidate;
        ResetPendingCandidate(mod);

        std::string reload_error;
        if (!PreflightLuaSource(*mod, candidate, &reload_error)) {
            LogLuaMessage(
                *mod,
                "hot reload rejected; existing state preserved: " + reload_error);
            continue;
        }

        CloseLuaStateForMod(mod);
        if (!CreateLuaStateForMod(
                mod,
                mod->descriptor.source_entry_script_path,
                &reload_error)) {
            CloseLuaStateForMod(mod);
            LogLuaMessage(
                *mod,
                "hot reload execution failed; edit the source to retry: " + reload_error);
            continue;
        }
        LogLuaMessage(
            *mod,
            "hot reloaded source entry script: " +
                mod->descriptor.source_entry_script_path.string());
    }
}

}  // namespace sdmod::detail
