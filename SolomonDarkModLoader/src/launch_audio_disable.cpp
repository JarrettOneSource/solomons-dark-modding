#include "launch_audio_disable.h"

#include "binary_layout.h"
#include "logger.h"
#include "memory_access.h"
#include "x86_hook.h"

#include <Windows.h>

#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod {
namespace {

constexpr char kDisableAudioEnvironmentVariable[] = "SDMOD_DISABLE_AUDIO";
constexpr std::size_t kAudioEngineInitializeMinimumPatchSize = 5;

X86Hook g_audio_engine_initialize_hook;

using BassFreeFn = BOOL(WINAPI*)();

bool IsAudioDisableRequested() {
    char value[2] = {};
    return GetEnvironmentVariableA(
               kDisableAudioEnvironmentVariable,
               value,
               static_cast<DWORD>(sizeof(value))) == 1 &&
           value[0] == '1';
}

bool ResolveAudioAddress(
    const char* section,
    const char* key,
    uintptr_t* address) {
    uintptr_t configured_address = 0;
    return address != nullptr &&
           TryGetBinaryLayoutNumericValue(
               section,
               key,
               &configured_address) &&
           configured_address != 0 &&
           ProcessMemory::Instance().TryResolveGameAddress(
               configured_address,
               address);
}

void HookAudioEngineInitialize() {
    Log(
        "Launch audio disable suppressed stock BASS device "
        "initialization.");
}

}  // namespace

bool InitializeLaunchAudioDisable(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!IsAudioDisableRequested() ||
        g_audio_engine_initialize_hook.installed) {
        return true;
    }

    uintptr_t engine_initialize_address = 0;
    uintptr_t engine_free_address = 0;
    uintptr_t engine_enabled_address = 0;
    if (!ResolveAudioAddress(
            "audio.hooks",
            "engine_initialize",
            &engine_initialize_address) ||
        !ResolveAudioAddress(
            "audio.hooks",
            "engine_free",
            &engine_free_address) ||
        !ResolveAudioAddress(
            "audio.globals",
            "engine_enabled",
            &engine_enabled_address)) {
        if (error_message != nullptr) {
            *error_message =
                "Launch audio disable could not resolve the stock BASS "
                "initializer, shutdown thunk, and enabled gate.";
        }
        return false;
    }

    std::string hook_error;
    if (!InstallSafeX86Hook(
            reinterpret_cast<void*>(engine_initialize_address),
            reinterpret_cast<void*>(&HookAudioEngineInitialize),
            kAudioEngineInitializeMinimumPatchSize,
            &g_audio_engine_initialize_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message =
                "Launch audio disable could not install the stock BASS "
                "initializer guard. error=" +
                (hook_error.empty()
                     ? std::string("unresolved native target")
                     : hook_error);
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t engine_enabled = 0;
    if (!memory.TryReadValue(
            engine_enabled_address,
            &engine_enabled)) {
        RemoveX86Hook(&g_audio_engine_initialize_hook);
        if (error_message != nullptr) {
            *error_message =
                "Launch audio disable could not read the stock BASS "
                "enabled gate.";
        }
        return false;
    }

    if (engine_enabled != 0) {
        const std::uint8_t disabled = 0;
        const auto bass_free =
            reinterpret_cast<BassFreeFn>(engine_free_address);
        if (!memory.TryWriteValue(
                engine_enabled_address,
                disabled) ||
            bass_free == nullptr ||
            bass_free() == FALSE) {
            RemoveX86Hook(&g_audio_engine_initialize_hook);
            if (error_message != nullptr) {
                *error_message =
                    "Launch audio disable could not close the active stock "
                    "BASS engine.";
            }
            return false;
        }
        Log(
            "Launch audio disable closed the active stock BASS engine and "
            "audio device.");
    }

    Log("Launch audio disable enabled for this process.");
    return true;
}

void ShutdownLaunchAudioDisable() {
    RemoveX86Hook(&g_audio_engine_initialize_hook);
}

}  // namespace sdmod
