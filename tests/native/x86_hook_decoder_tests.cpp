#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>

// The decoder is byte-oriented and remains testable on a 64-bit CI host. Its
// production translation unit is intentionally enabled only for the x86
// loader, so opt this one test translation unit into that implementation.
#if !defined(_M_IX86) && !defined(__i386__)
#define __i386__ 1
#define SDMOD_TEST_DEFINED_I386 1
#endif
#include "../../SolomonDarkModLoader/src/runtime_debug/hde32_impl.inl"
#if defined(SDMOD_TEST_DEFINED_I386)
#undef __i386__
#undef SDMOD_TEST_DEFINED_I386
#endif

namespace {

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

bool UnprefixedRelativeInstructionsDecodeOnce() {
    const std::uint8_t call[] = {0xE8, 0x68, 0x4A, 0x04, 0x00};
    const std::uint8_t jump[] = {0xE9, 0x78, 0x56, 0x34, 0x12};
    const std::uint8_t conditional[] = {
        0x0F, 0x84, 0x78, 0x56, 0x34, 0x12};

    hde32s decoded = {};
    if (!Require(hde32_disasm(call, &decoded) == sizeof(call),
                 "CALL rel32 was not decoded as five bytes") ||
        !Require((decoded.flags & (F_IMM32 | F_RELATIVE)) ==
                     (F_IMM32 | F_RELATIVE),
                 "CALL rel32 lost its immediate or relative flag") ||
        !Require(decoded.imm.imm32 == 0x00044A68,
                 "CALL rel32 immediate was read from the wrong offset")) {
        return false;
    }

    decoded = {};
    if (!Require(hde32_disasm(jump, &decoded) == sizeof(jump),
                 "JMP rel32 was not decoded as five bytes") ||
        !Require((decoded.flags & (F_IMM32 | F_RELATIVE)) ==
                     (F_IMM32 | F_RELATIVE),
                 "JMP rel32 lost its immediate or relative flag")) {
        return false;
    }

    decoded = {};
    return Require(
               hde32_disasm(conditional, &decoded) == sizeof(conditional),
               "Jcc rel32 was not decoded as six bytes") &&
           Require(
               (decoded.flags & (F_IMM32 | F_RELATIVE)) ==
                   (F_IMM32 | F_RELATIVE),
               "Jcc rel32 lost its immediate or relative flag");
}

bool OperandSizeRelativeCallConsumesItsImmediateOnce() {
    const std::uint8_t prefixed_call[] = {0x66, 0xE8, 0x34, 0x12};
    hde32s decoded = {};
    return Require(
               hde32_disasm(prefixed_call, &decoded) ==
                   sizeof(prefixed_call),
               "operand-size CALL rel16 was not decoded as four bytes") &&
           Require(
               (decoded.flags & (F_IMM16 | F_RELATIVE)) ==
                   (F_IMM16 | F_RELATIVE),
               "operand-size CALL rel16 lost its immediate or relative flag") &&
           Require(
               (decoded.flags & F_IMM32) == 0,
               "operand-size CALL rel16 was also classified as rel32") &&
           Require(
               decoded.imm.imm16 == 0x1234,
               "operand-size CALL rel16 immediate was read from the wrong offset");
}

bool GoodiePrologueUsesWholeInstructions() {
    const std::uint8_t prologue[] = {
        0x56,                         // push esi
        0x8B, 0xF1,                   // mov esi, ecx
        0xE8, 0x68, 0x4A, 0x04, 0x00 // call 0x006287D0
    };

    std::size_t offset = 0;
    while (offset < 5) {
        hde32s decoded = {};
        const auto length = hde32_disasm(prologue + offset, &decoded);
        if (!Require(length != 0 && (decoded.flags & F_ERROR) == 0,
                     "Goodie constructor prologue failed to decode")) {
            return false;
        }
        offset += length;
    }
    return Require(
        offset == sizeof(prologue),
        "safe hook patch size did not end after the Goodie constructor CALL");
}

bool RelocatedGoodieCallKeepsItsAbsoluteTarget() {
    constexpr std::uintptr_t source_instruction = 0x005E3D63;
    constexpr std::uintptr_t native_target = 0x006287D0;
    constexpr std::uintptr_t trampoline_instruction = 0x048B0003;
    std::uint8_t call[] = {0xE8, 0x68, 0x4A, 0x04, 0x00};

    hde32s decoded = {};
    if (!Require(
            hde32_disasm(call, &decoded) == sizeof(call),
            "Goodie base-constructor CALL length is invalid")) {
        return false;
    }

    const auto relative_offset =
        static_cast<std::size_t>(decoded.len) - sizeof(std::int32_t);
    std::int32_t original_relative = 0;
    std::memcpy(
        &original_relative,
        call + relative_offset,
        sizeof(original_relative));
    const auto original_target = static_cast<std::uintptr_t>(
        static_cast<std::intptr_t>(source_instruction + decoded.len) +
        original_relative);
    if (!Require(
            original_target == native_target,
            "Goodie base-constructor CALL source target is invalid")) {
        return false;
    }

    const auto relocated_delta =
        static_cast<std::int64_t>(native_target) -
        static_cast<std::int64_t>(
            trampoline_instruction + decoded.len);
    if (!Require(
            relocated_delta >=
                    (std::numeric_limits<std::int32_t>::min)() &&
                relocated_delta <=
                    (std::numeric_limits<std::int32_t>::max)(),
            "Goodie base-constructor CALL cannot be relocated as rel32")) {
        return false;
    }
    const auto relocated_relative =
        static_cast<std::int32_t>(relocated_delta);
    std::memcpy(
        call + relative_offset,
        &relocated_relative,
        sizeof(relocated_relative));

    std::int32_t stored_relative = 0;
    std::memcpy(
        &stored_relative,
        call + relative_offset,
        sizeof(stored_relative));
    const auto relocated_target = static_cast<std::uintptr_t>(
        static_cast<std::intptr_t>(
            trampoline_instruction + decoded.len) +
        stored_relative);
    return Require(
               relocated_target == native_target,
               "relocated Goodie CALL no longer reaches the native base constructor") &&
           Require(
               call[1] == 0xC8 && call[2] == 0x87 &&
                   call[3] == 0xD7 && call[4] == 0xFB,
               "relocated Goodie CALL bytes do not match the dump-derived target");
}

}  // namespace

int main() {
    if (!UnprefixedRelativeInstructionsDecodeOnce() ||
        !OperandSizeRelativeCallConsumesItsImmediateOnce() ||
        !GoodiePrologueUsesWholeInstructions() ||
        !RelocatedGoodieCallKeepsItsAbsoluteTarget()) {
        return 1;
    }
    std::cout << "x86 hook decoder tests passed\n";
    return 0;
}
