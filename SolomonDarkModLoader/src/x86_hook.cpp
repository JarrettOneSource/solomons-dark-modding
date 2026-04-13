#include "x86_hook.h"
#include "third_party/hde32.h"

#include <cstring>
#include <sstream>

namespace sdmod {
namespace {

bool WriteRelativeJump(void* location, const void* destination, std::string* error_message) {
    if (location == nullptr || destination == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Hook patch location or destination was null.";
        }
        return false;
    }

    auto* bytes = static_cast<std::uint8_t*>(location);
    const auto source = reinterpret_cast<std::uintptr_t>(location);
    const auto target = reinterpret_cast<std::uintptr_t>(destination);
    const auto next_instruction = source + 5;
    const auto relative = static_cast<std::intptr_t>(target) - static_cast<std::intptr_t>(next_instruction);
    if (relative < static_cast<std::intptr_t>(INT32_MIN) || relative > static_cast<std::intptr_t>(INT32_MAX)) {
        if (error_message != nullptr) {
            *error_message = "Hook target was out of range for an x86 relative jump.";
        }
        return false;
    }

    bytes[0] = 0xE9;
    *reinterpret_cast<std::int32_t*>(bytes + 1) = static_cast<std::int32_t>(relative);
    return true;
}

std::string FormatProtectFlags(DWORD protect) {
    std::ostringstream out;
    out << "0x" << std::hex << std::uppercase << protect;
    return out.str();
}

std::string BuildVirtualProtectFailureDetail(void* target, size_t patch_size, DWORD last_error) {
    MEMORY_BASIC_INFORMATION info = {};
    std::ostringstream out;
    out << "VirtualProtect failed while patching the target function."
        << " gle=" << last_error
        << " target=0x" << std::hex << std::uppercase << reinterpret_cast<std::uintptr_t>(target)
        << " size=0x" << patch_size;
    if (VirtualQuery(target, &info, sizeof(info)) == sizeof(info)) {
        out << " region_base=0x" << reinterpret_cast<std::uintptr_t>(info.BaseAddress)
            << " region_size=0x" << info.RegionSize
            << " state=" << FormatProtectFlags(info.State)
            << " protect=" << FormatProtectFlags(info.Protect)
            << " alloc_protect=" << FormatProtectFlags(info.AllocationProtect)
            << " type=" << FormatProtectFlags(info.Type);
    } else {
        out << " region_query_failed";
    }
    return out.str();
}

bool InstallX86HookResolved(void* target, void* detour, size_t patch_size, X86Hook* hook, std::string* error_message) {
    if (hook == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Hook destination was null.";
        }
        return false;
    }

    if (target == nullptr || detour == nullptr) {
        if (error_message != nullptr) {
            *error_message = "Hook target or detour was null.";
        }
        return false;
    }

    if (patch_size < 5 || patch_size > hook->original_bytes.size()) {
        if (error_message != nullptr) {
            *error_message = "Hook patch size must be between 5 and 16 bytes.";
        }
        return false;
    }

    *hook = X86Hook{};
    hook->target = target;
    hook->detour = detour;
    hook->patch_size = patch_size;

    std::memcpy(hook->original_bytes.data(), target, hook->patch_size);

    const auto trampoline_size = hook->patch_size + 5;
    auto* trampoline = static_cast<std::uint8_t*>(
        VirtualAlloc(nullptr, trampoline_size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (trampoline == nullptr) {
        if (error_message != nullptr) {
            *error_message = "VirtualAlloc failed while creating the hook trampoline.";
        }
        return false;
    }

    std::memcpy(trampoline, hook->original_bytes.data(), hook->patch_size);
    if (!WriteRelativeJump(
            trampoline + hook->patch_size,
            static_cast<std::uint8_t*>(target) + hook->patch_size,
            error_message)) {
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }
    hook->trampoline = trampoline;

    DWORD old_protection = 0;
    if (!VirtualProtect(target, hook->patch_size, PAGE_EXECUTE_READWRITE, &old_protection)) {
        hook->trampoline = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        if (error_message != nullptr) {
            *error_message = BuildVirtualProtectFailureDetail(target, hook->patch_size, GetLastError());
        }
        return false;
    }

    auto* target_bytes = static_cast<std::uint8_t*>(target);
    const auto restore_protection = [&]() {
        DWORD ignored = 0;
        VirtualProtect(target, hook->patch_size, old_protection, &ignored);
        FlushInstructionCache(GetCurrentProcess(), target, hook->patch_size);
    };

    if (!WriteRelativeJump(target, detour, error_message)) {
        std::memcpy(target_bytes, hook->original_bytes.data(), hook->patch_size);
        restore_protection();
        hook->trampoline = nullptr;
        VirtualFree(trampoline, 0, MEM_RELEASE);
        return false;
    }

    for (size_t index = 5; index < hook->patch_size; ++index) {
        target_bytes[index] = 0x90;
    }

    restore_protection();
    hook->installed = true;
    return true;
}

}  // namespace

size_t ResolveX86HookPatchSize(void* target, size_t minimum_patch_size, std::string* error_message) {
    if (target == nullptr || minimum_patch_size < 5 || minimum_patch_size > 16) {
        if (error_message != nullptr) {
            *error_message = "Hook patch size must be between 5 and 16 bytes.";
        }
        return 0;
    }

    auto* const bytes = static_cast<const std::uint8_t*>(target);
    size_t total_size = 0;
    while (total_size < minimum_patch_size) {
        hde32s hs = {};
        const auto length = static_cast<size_t>(hde32_disasm(bytes + total_size, &hs));
        if (length == 0 || (hs.flags & F_ERROR) != 0) {
            if (error_message != nullptr) {
                std::ostringstream out;
                out << "Instruction decode failed at +0x" << std::hex << std::uppercase << total_size
                    << " flags=0x" << hs.flags;
                *error_message = out.str();
            }
            return 0;
        }

        if ((hs.flags & F_RELATIVE) != 0) {
            if (error_message != nullptr) {
                std::ostringstream out;
                out << "Relative control-flow instruction in hook prologue at +0x"
                    << std::hex << std::uppercase << total_size;
                *error_message = out.str();
            }
            return 0;
        }

        total_size += length;
        if (total_size > 16) {
            if (error_message != nullptr) {
                *error_message = "Hook patch would exceed the 16-byte trampoline buffer.";
            }
            return 0;
        }
    }

    return total_size;
}

bool InstallX86Hook(void* target, void* detour, size_t patch_size, X86Hook* hook, std::string* error_message) {
    return InstallX86HookResolved(target, detour, patch_size, hook, error_message);
}

bool InstallSafeX86Hook(void* target, void* detour, size_t minimum_patch_size, X86Hook* hook, std::string* error_message) {
    const auto safe_patch_size = ResolveX86HookPatchSize(target, minimum_patch_size, error_message);
    if (safe_patch_size == 0) {
        return false;
    }
    return InstallX86HookResolved(target, detour, safe_patch_size, hook, error_message);
}

void RemoveX86Hook(X86Hook* hook) {
    if (hook == nullptr || !hook->installed || hook->target == nullptr) {
        return;
    }

    DWORD old_protection = 0;
    if (VirtualProtect(hook->target, hook->patch_size, PAGE_EXECUTE_READWRITE, &old_protection)) {
        std::memcpy(hook->target, hook->original_bytes.data(), hook->patch_size);
        DWORD ignored = 0;
        VirtualProtect(hook->target, hook->patch_size, old_protection, &ignored);
        FlushInstructionCache(GetCurrentProcess(), hook->target, hook->patch_size);
    }

    if (hook->trampoline != nullptr) {
        VirtualFree(hook->trampoline, 0, MEM_RELEASE);
    }

    *hook = X86Hook{};
}

bool InstallHookSet(const HookSpec* specs, size_t count, X86Hook* hooks, std::string* error_message) {
    std::string hook_error;
    for (size_t i = 0; i < count; ++i) {
        if (!InstallX86Hook(specs[i].address, specs[i].detour, specs[i].patch_size, &hooks[i], &hook_error)) {
            // Roll back all previously installed hooks in this set.
            for (size_t j = i; j > 0; --j) {
                RemoveX86Hook(&hooks[j - 1]);
            }
            if (error_message != nullptr) {
                *error_message = "Failed to install " + std::string(specs[i].name) + " hook: " + hook_error;
            }
            return false;
        }
    }
    return true;
}

void RemoveHookSet(X86Hook* hooks, size_t count) {
    for (size_t i = count; i > 0; --i) {
        RemoveX86Hook(&hooks[i - 1]);
    }
}

}  // namespace sdmod
