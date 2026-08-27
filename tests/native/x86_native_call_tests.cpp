#include "x86_native_call.h"

#include <cstdint>
#include <iostream>

namespace {

__declspec(naked) std::uint32_t NoArgumentTarget() {
    __asm {
        mov eax, 12345678h
        ret
    }
}

__declspec(naked) std::uint32_t OneArgumentTarget() {
    __asm {
        mov eax, dword ptr [esp + 4]
        ret 4
    }
}

__declspec(naked) std::uint32_t TwoArgumentCalleeCleanupTarget() {
    __asm {
        mov eax, dword ptr [esp + 4]
        add eax, dword ptr [esp + 8]
        ret 8
    }
}

__declspec(naked) std::uint32_t OneArgumentCallerCleanupTarget() {
    __asm {
        mov eax, dword ptr [esp + 4]
        ret
    }
}

__declspec(naked) std::uint32_t TwoArgumentCallerCleanupTarget() {
    __asm {
        mov eax, dword ptr [esp + 4]
        add eax, dword ptr [esp + 8]
        ret
    }
}

bool Require(bool condition, const char* message) {
    if (condition) {
        return true;
    }
    std::cerr << message << '\n';
    return false;
}

}  // namespace

int main() {
    const auto no_argument_address =
        reinterpret_cast<std::uintptr_t>(&NoArgumentTarget);
    const auto one_argument_address =
        reinterpret_cast<std::uintptr_t>(&OneArgumentTarget);
    const auto two_argument_callee_cleanup_address =
        reinterpret_cast<std::uintptr_t>(&TwoArgumentCalleeCleanupTarget);
    const auto one_argument_caller_cleanup_address =
        reinterpret_cast<std::uintptr_t>(&OneArgumentCallerCleanupTarget);
    const auto two_argument_caller_cleanup_address =
        reinterpret_cast<std::uintptr_t>(&TwoArgumentCallerCleanupTarget);

    const auto no_argument = sdmod::detail::InvokeX86Thiscall(
        no_argument_address,
        0x11223344u);
    const auto one_argument = sdmod::detail::InvokeX86ThiscallU32(
        one_argument_address,
        0x11223344u,
        0x89ABCDEFu);
    const auto missing_argument = sdmod::detail::InvokeX86Thiscall(
        one_argument_address,
        0x11223344u);
    const auto extra_argument = sdmod::detail::InvokeX86ThiscallU32(
        no_argument_address,
        0x11223344u,
        0x89ABCDEFu);
    const auto two_argument_thiscall =
        sdmod::detail::InvokeX86ThiscallU32U32(
            two_argument_callee_cleanup_address,
            0x11223344u,
            20u,
            22u);
    const auto one_argument_cdecl = sdmod::detail::InvokeX86CdeclU32(
        one_argument_caller_cleanup_address,
        0x89ABCDEFu);
    const auto two_argument_cdecl = sdmod::detail::InvokeX86CdeclU32U32(
        two_argument_caller_cleanup_address,
        20u,
        22u);
    const auto two_argument_stdcall = sdmod::detail::InvokeX86StdcallU32U32(
        two_argument_callee_cleanup_address,
        20u,
        22u);
    const auto cdecl_called_as_stdcall = sdmod::detail::InvokeX86StdcallU32U32(
        two_argument_caller_cleanup_address,
        20u,
        22u);
    const auto stdcall_called_as_cdecl = sdmod::detail::InvokeX86CdeclU32U32(
        two_argument_callee_cleanup_address,
        20u,
        22u);

    if (!Require(no_argument.stack_delta_bytes == 0,
                 "balanced no-argument thiscall changed ESP") ||
        !Require(no_argument.result == 0x12345678u,
                 "no-argument thiscall lost EAX") ||
        !Require(one_argument.stack_delta_bytes == 0,
                 "balanced one-argument thiscall changed ESP") ||
        !Require(one_argument.result == 0x89ABCDEFu,
                 "one-argument thiscall lost its argument") ||
        !Require(missing_argument.stack_delta_bytes == 4,
                 "missing thiscall argument was not detected") ||
        !Require(extra_argument.stack_delta_bytes == -4,
                 "extra thiscall argument was not detected") ||
        !Require(two_argument_thiscall.stack_delta_bytes == 0 &&
                     two_argument_thiscall.result == 42u,
                 "two-argument thiscall contract failed") ||
        !Require(one_argument_cdecl.stack_delta_bytes == 0 &&
                     one_argument_cdecl.result == 0x89ABCDEFu,
                 "one-argument cdecl contract failed") ||
        !Require(two_argument_cdecl.stack_delta_bytes == 0 &&
                     two_argument_cdecl.result == 42u,
                 "two-argument cdecl contract failed") ||
        !Require(two_argument_stdcall.stack_delta_bytes == 0 &&
                     two_argument_stdcall.result == 42u,
                 "two-argument stdcall contract failed") ||
        !Require(cdecl_called_as_stdcall.stack_delta_bytes == -8,
                 "cdecl target passed as stdcall was not detected") ||
        !Require(stdcall_called_as_cdecl.stack_delta_bytes == 8,
                 "stdcall target passed as cdecl was not detected")) {
        return 1;
    }

    const auto after_mismatch = sdmod::detail::InvokeX86Thiscall(
        no_argument_address,
        0x11223344u);
    if (!Require(after_mismatch.stack_delta_bytes == 0,
                 "mismatched call corrupted the caller stack") ||
        !Require(after_mismatch.result == 0x12345678u,
                 "caller did not continue after a mismatched call")) {
        return 1;
    }

    std::cout << "x86 native call tests passed\n";
    return 0;
}
