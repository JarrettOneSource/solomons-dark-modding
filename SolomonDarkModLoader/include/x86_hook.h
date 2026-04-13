#pragma once

#include <Windows.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace sdmod {

struct X86Hook {
    void* target = nullptr;
    void* detour = nullptr;
    void* trampoline = nullptr;
    size_t patch_size = 0;
    bool installed = false;
    std::array<std::uint8_t, 16> original_bytes = {};
};

// Resolves a minimum requested patch size to a whole-instruction x86 prologue
// size that the trampoline can safely copy. Returns 0 on failure.
size_t ResolveX86HookPatchSize(void* target, size_t minimum_patch_size, std::string* error_message);

bool InstallX86Hook(void* target, void* detour, size_t patch_size, X86Hook* hook, std::string* error_message);
bool InstallSafeX86Hook(void* target, void* detour, size_t minimum_patch_size, X86Hook* hook, std::string* error_message);
void RemoveX86Hook(X86Hook* hook);

template <typename T>
T GetX86HookTrampoline(const X86Hook& hook) {
    return reinterpret_cast<T>(hook.trampoline);
}

// ---- Batch hook helpers ----

// Describes a single hook to install. The address field should already be
// resolved to the runtime virtual address (via ProcessMemory).
struct HookSpec {
    void* address;
    size_t patch_size;
    void* detour;
    const char* name;
};

// Install an array of hooks. On failure, all previously installed hooks in
// the set are rolled back automatically. Returns false with a message
// identifying which hook failed.
bool InstallHookSet(const HookSpec* specs, size_t count, X86Hook* hooks, std::string* error_message);

// Remove all hooks in the set (safe to call even if some are not installed).
void RemoveHookSet(X86Hook* hooks, size_t count);

// ---- Mid-function hook macro ----
// Generates a __declspec(naked) detour that saves all registers, calls a
// regular void __cdecl handler(), restores registers, then jumps to the
// trampoline via a void* pointer variable.
//
// Usage:
//   static void* g_my_trampoline = nullptr;   // set after InstallHookSet
//   void __cdecl OnSomeEvent() { /* your code */ }
//   DEFINE_MID_FUNCTION_HOOK(SomeEvent, g_my_trampoline, OnSomeEvent)
//
// This produces a function named MidFunctionDetour_SomeEvent.
// IMPORTANT: trampoline_ptr must be a plain global void* — MSVC inline asm
// cannot handle array indexing or complex expressions.

#define DEFINE_MID_FUNCTION_HOOK(name, trampoline_ptr, handler_fn)  \
    __declspec(naked) void MidFunctionDetour_##name() {             \
        __asm { pushad }                                            \
        __asm { pushfd }                                            \
        __asm { call handler_fn }                                   \
        __asm { popfd }                                             \
        __asm { popad }                                             \
        __asm { jmp dword ptr [trampoline_ptr] }                    \
    }

}  // namespace sdmod
