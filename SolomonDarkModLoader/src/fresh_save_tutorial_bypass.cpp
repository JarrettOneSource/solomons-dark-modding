#include "fresh_save_tutorial_bypass.h"

#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "x86_hook.h"

#include <Windows.h>

#include <cstddef>
#include <string>

namespace sdmod {
namespace {

constexpr char kSkipFreshSaveTutorialEnvironmentVariable[] =
    "SDMOD_SKIP_FRESH_SAVE_TUTORIAL";
constexpr std::size_t kTutorialGameplayBootstrapMinimumPatchSize = 5;

X86Hook g_tutorial_gameplay_bootstrap_hook;

using TutorialGameplayBootstrapFn = void(__thiscall*)(void* app);
using StartStandardGameplayFn = void(__thiscall*)(void* app);

StartStandardGameplayFn g_start_standard_gameplay = nullptr;

bool IsTutorialBypassRequested() {
    char value[2] = {};
    return GetEnvironmentVariableA(
               kSkipFreshSaveTutorialEnvironmentVariable,
               value,
               static_cast<DWORD>(sizeof(value))) == 1 &&
           value[0] == '1';
}

void __fastcall HookTutorialGameplayBootstrap(
    void* app,
    void* /*unused_edx*/) {
    if (g_start_standard_gameplay == nullptr) {
        const auto original =
            GetX86HookTrampoline<TutorialGameplayBootstrapFn>(
                g_tutorial_gameplay_bootstrap_hook);
        if (original != nullptr) {
            original(app);
        }
        return;
    }

    Log(
        "Fresh-save tutorial bypass redirected the stock tutorial bootstrap "
        "to standard gameplay before construction.");
    g_start_standard_gameplay(app);
}

}  // namespace

bool InitializeFreshSaveTutorialBypass(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!IsTutorialBypassRequested()) {
        return true;
    }

    const auto tutorial_bootstrap_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kTutorialGameplayBootstrap);
    const auto standard_gameplay_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kStartStandardGameplay);
    std::string hook_error;
    if (tutorial_bootstrap_address == 0 ||
        standard_gameplay_address == 0 ||
        !InstallSafeX86Hook(
            reinterpret_cast<void*>(tutorial_bootstrap_address),
            reinterpret_cast<void*>(&HookTutorialGameplayBootstrap),
            kTutorialGameplayBootstrapMinimumPatchSize,
            &g_tutorial_gameplay_bootstrap_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message =
                "Fresh-save tutorial bypass could not install the stock "
                "tutorial bootstrap guard. error=" +
                (hook_error.empty()
                     ? std::string("unresolved native target")
                     : hook_error);
        }
        return false;
    }

    g_start_standard_gameplay =
        reinterpret_cast<StartStandardGameplayFn>(
            standard_gameplay_address);
    Log("Fresh-save tutorial bypass enabled.");
    return true;
}

void ShutdownFreshSaveTutorialBypass() {
    RemoveX86Hook(&g_tutorial_gameplay_bootstrap_hook);
    g_start_standard_gameplay = nullptr;
}

}  // namespace sdmod
