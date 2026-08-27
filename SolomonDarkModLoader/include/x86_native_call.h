#pragma once

#include <cstdint>

namespace sdmod::detail {

static_assert(sizeof(void*) == 4, "Native call helpers require an x86 build.");

struct X86NativeCallResult {
    std::uint32_t result = 0;
    std::int32_t stack_delta_bytes = 0;
};

__declspec(noinline) inline X86NativeCallResult InvokeX86Thiscall(
    std::uintptr_t function_address,
    std::uintptr_t this_ptr) noexcept {
    std::uintptr_t stack_before = 0;
    std::uintptr_t stack_after = 0;
    std::uint32_t result = 0;
    __asm {
        mov esi, esp
        mov stack_before, esi
        mov ecx, this_ptr
        mov eax, function_address
        call eax
        mov edx, esp
        mov esp, esi
        mov result, eax
        mov stack_after, edx
    }
    return {
        result,
        static_cast<std::int32_t>(stack_after - stack_before),
    };
}

__declspec(noinline) inline X86NativeCallResult InvokeX86ThiscallU32(
    std::uintptr_t function_address,
    std::uintptr_t this_ptr,
    std::uint32_t arg0) noexcept {
    std::uintptr_t stack_before = 0;
    std::uintptr_t stack_after = 0;
    std::uint32_t result = 0;
    __asm {
        mov esi, esp
        mov stack_before, esi
        push arg0
        mov ecx, this_ptr
        mov eax, function_address
        call eax
        mov edx, esp
        mov esp, esi
        mov result, eax
        mov stack_after, edx
    }
    return {
        result,
        static_cast<std::int32_t>(stack_after - stack_before),
    };
}

__declspec(noinline) inline X86NativeCallResult InvokeX86ThiscallU32U32(
    std::uintptr_t function_address,
    std::uintptr_t this_ptr,
    std::uint32_t arg0,
    std::uint32_t arg1) noexcept {
    std::uintptr_t stack_before = 0;
    std::uintptr_t stack_after = 0;
    std::uint32_t result = 0;
    __asm {
        mov esi, esp
        mov stack_before, esi
        push arg1
        push arg0
        mov ecx, this_ptr
        mov eax, function_address
        call eax
        mov edx, esp
        mov esp, esi
        mov result, eax
        mov stack_after, edx
    }
    return {
        result,
        static_cast<std::int32_t>(stack_after - stack_before),
    };
}

__declspec(noinline) inline X86NativeCallResult InvokeX86CdeclU32(
    std::uintptr_t function_address,
    std::uint32_t arg0) noexcept {
    std::uintptr_t stack_before = 0;
    std::uintptr_t stack_after = 0;
    std::uint32_t result = 0;
    __asm {
        mov esi, esp
        mov stack_before, esi
        push arg0
        mov eax, function_address
        call eax
        mov edx, esp
        mov esp, esi
        mov result, eax
        mov stack_after, edx
    }
    return {
        result,
        static_cast<std::int32_t>(
            stack_after - stack_before + sizeof(std::uint32_t)),
    };
}

__declspec(noinline) inline X86NativeCallResult InvokeX86CdeclU32U32(
    std::uintptr_t function_address,
    std::uint32_t arg0,
    std::uint32_t arg1) noexcept {
    std::uintptr_t stack_before = 0;
    std::uintptr_t stack_after = 0;
    std::uint32_t result = 0;
    __asm {
        mov esi, esp
        mov stack_before, esi
        push arg1
        push arg0
        mov eax, function_address
        call eax
        mov edx, esp
        mov esp, esi
        mov result, eax
        mov stack_after, edx
    }
    return {
        result,
        static_cast<std::int32_t>(
            stack_after - stack_before + 2 * sizeof(std::uint32_t)),
    };
}

__declspec(noinline) inline X86NativeCallResult InvokeX86StdcallU32U32(
    std::uintptr_t function_address,
    std::uint32_t arg0,
    std::uint32_t arg1) noexcept {
    std::uintptr_t stack_before = 0;
    std::uintptr_t stack_after = 0;
    std::uint32_t result = 0;
    __asm {
        mov esi, esp
        mov stack_before, esi
        push arg1
        push arg0
        mov eax, function_address
        call eax
        mov edx, esp
        mov esp, esi
        mov result, eax
        mov stack_after, edx
    }
    return {
        result,
        static_cast<std::int32_t>(stack_after - stack_before),
    };
}

}  // namespace sdmod::detail
