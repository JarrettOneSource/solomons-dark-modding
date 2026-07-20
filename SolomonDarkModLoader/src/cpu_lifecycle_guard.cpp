#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "mod_loader_internal.h"
#include "x86_hook.h"

#include <Windows.h>

#include <array>
#include <cstdint>
#include <string>

namespace sdmod {
namespace {

// CPU::Tick has already called the object's virtual update when execution
// reaches this seam. These are the complete instructions through PUSH EDI,
// immediately before the stock child-manager read at [EBX+0x44]. Keeping the
// whole short-branch target inside the trampoline makes relocation exact.
constexpr std::array<std::uint8_t, 10> kExpectedPostUpdateBytes = {
    0x80, 0x7B, 0x2C, 0x00,  // CMP BYTE PTR [EBX+0x2C],0
    0x75, 0x03,              // JNE +3
    0xFF, 0x43, 0x28,        // INC DWORD PTR [EBX+0x28]
    0x57,                    // PUSH EDI
};

struct CpuLifecycleGuardState {
    X86Hook post_update_hook = {};
    bool initialized = false;
    bool activity_logged = false;
};

CpuLifecycleGuardState g_cpu_lifecycle_guard_state;
void* g_cpu_post_update_trampoline = nullptr;
void* g_cpu_tick_epilogue = nullptr;
volatile LONG g_cpu_pending_remove_guard_hit = 0;

// CPU::Tick pushed EBX at entry and has not pushed EDI yet at this seam. If the
// virtual update just marked the object for removal (+0x05), jump to the
// function's stock epilogue. Otherwise the trampoline replays the exact
// overwritten instructions and resumes the stock function.
__declspec(naked) void DetourCpuPostUpdate() {
    __asm {
        cmp byte ptr [ebx + 5], 0
        jne pending_remove
        jmp dword ptr [g_cpu_post_update_trampoline]

    pending_remove:
        mov dword ptr [g_cpu_pending_remove_guard_hit], 1
        jmp dword ptr [g_cpu_tick_epilogue]
    }
}

}  // namespace

bool InitializeCpuLifecycleGuard(std::string* error_message) {
    if (g_cpu_lifecycle_guard_state.initialized) {
        return true;
    }

    if (!InitializeGameplaySeams(error_message)) {
        return false;
    }

    const auto target = ProcessMemory::Instance().ResolveGameAddressOrZero(kCpuTickPostUpdate);
    const auto epilogue = ProcessMemory::Instance().ResolveGameAddressOrZero(kCpuTickEpilogue);
    if (target == 0 || epilogue == 0) {
        if (error_message != nullptr) {
            *error_message = "Failed to resolve the CPU post-update lifecycle seam or stock epilogue.";
        }
        return false;
    }

    std::array<std::uint8_t, kExpectedPostUpdateBytes.size()> current_bytes = {};
    if (!ProcessMemory::Instance().TryRead(target, current_bytes.data(), current_bytes.size()) ||
        current_bytes != kExpectedPostUpdateBytes) {
        if (error_message != nullptr) {
            *error_message =
                "CPU post-update lifecycle seam does not match the verified Solomon Dark 0.72.5 instruction block.";
        }
        return false;
    }

    std::string hook_error;
    if (!InstallX86Hook(
            reinterpret_cast<void*>(target),
            reinterpret_cast<void*>(&DetourCpuPostUpdate),
            kExpectedPostUpdateBytes.size(),
            &g_cpu_lifecycle_guard_state.post_update_hook,
            &hook_error)) {
        if (error_message != nullptr) {
            *error_message = "Failed to install the CPU post-update lifecycle guard: " + hook_error;
        }
        return false;
    }

    g_cpu_tick_epilogue = reinterpret_cast<void*>(epilogue);
    g_cpu_post_update_trampoline = g_cpu_lifecycle_guard_state.post_update_hook.trampoline;
    if (g_cpu_post_update_trampoline == nullptr) {
        RemoveX86Hook(&g_cpu_lifecycle_guard_state.post_update_hook);
        if (error_message != nullptr) {
            *error_message = "CPU post-update lifecycle guard installed without a trampoline.";
        }
        return false;
    }

    g_cpu_pending_remove_guard_hit = 0;
    g_cpu_lifecycle_guard_state.activity_logged = false;
    g_cpu_lifecycle_guard_state.initialized = true;
    Log(
        "Installed CPU post-update lifecycle guard at " + HexString(target) +
        " patch=" + std::to_string(g_cpu_lifecycle_guard_state.post_update_hook.patch_size) + ".");
    return true;
}

void LogCpuLifecycleGuardActivity() {
    auto& state = g_cpu_lifecycle_guard_state;
    if (!state.initialized || state.activity_logged ||
        InterlockedExchange(&g_cpu_pending_remove_guard_hit, 0) == 0) {
        return;
    }

    state.activity_logged = true;
    Log("CPU lifecycle guard stopped a pending-remove object before its child-manager tick.");
}

void ShutdownCpuLifecycleGuard() {
    auto& state = g_cpu_lifecycle_guard_state;
    if (!state.initialized) {
        return;
    }

    RemoveX86Hook(&state.post_update_hook);
    g_cpu_post_update_trampoline = nullptr;
    g_cpu_tick_epilogue = nullptr;
    g_cpu_pending_remove_guard_hit = 0;
    state.activity_logged = false;
    state.initialized = false;
}

}  // namespace sdmod
