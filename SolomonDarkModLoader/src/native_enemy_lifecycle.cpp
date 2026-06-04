#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <Windows.h>

#include "native_enemy_lifecycle.h"

#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"

namespace sdmod {
namespace {

using EnemyDeathNativeFn = int(__fastcall*)(void* self, void* unused_edx);

int CaptureNativeEnemyLifecycleSehCode(
    EXCEPTION_POINTERS* exception_pointers,
    std::uint32_t* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
        if (exception_pointers != nullptr && exception_pointers->ExceptionRecord != nullptr) {
            *exception_code =
                static_cast<std::uint32_t>(exception_pointers->ExceptionRecord->ExceptionCode);
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

bool CallEnemyDeathFunctionSafe(
    uintptr_t function_address,
    uintptr_t actor_address,
    std::uint32_t* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (function_address == 0 || actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsExecutableRange(function_address, 1)) {
        return false;
    }

    auto* enemy_death = reinterpret_cast<EnemyDeathNativeFn>(function_address);
    if (enemy_death == nullptr) {
        return false;
    }

    __try {
        enemy_death(reinterpret_cast<void*>(actor_address), nullptr);
        return true;
    } __except (CaptureNativeEnemyLifecycleSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallEnemyDeathSafe(uintptr_t actor_address, std::uint32_t* exception_code) {
    const auto enemy_death_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kEnemyDeath);
    return CallEnemyDeathFunctionSafe(enemy_death_address, actor_address, exception_code);
}

bool CallEnemyDeathPresenterVirtualSafe(uintptr_t actor_address, std::uint32_t* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 || kEnemyDeathPresenterVtableSlotOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t vtable_address = 0;
    uintptr_t presenter_address = 0;
    if (!memory.TryReadValue(actor_address, &vtable_address) ||
        vtable_address == 0 ||
        !memory.TryReadValue(
            vtable_address + kEnemyDeathPresenterVtableSlotOffset,
            &presenter_address) ||
        presenter_address == 0) {
        return false;
    }

    const bool called = CallEnemyDeathFunctionSafe(presenter_address, actor_address, exception_code);
    Log(
        "native enemy death presenter invoked. actor=" + HexString(actor_address) +
        " vtable=" + HexString(vtable_address) +
        " slot=" + HexString(static_cast<uintptr_t>(kEnemyDeathPresenterVtableSlotOffset)) +
        " presenter=" + HexString(presenter_address) +
        " called=" + std::to_string(called ? 1 : 0) +
        " seh=" + HexString(exception_code != nullptr ? static_cast<uintptr_t>(*exception_code) : 0));
    return called;
}

bool IsEnemyDeathHandled(uintptr_t actor_address) {
    if (actor_address == 0 || kEnemyDeathHandledOffset == 0) {
        return false;
    }

    std::uint8_t death_handled = 0;
    return ProcessMemory::Instance().TryReadField(
               actor_address,
               kEnemyDeathHandledOffset,
               &death_handled) &&
           death_handled != 0;
}

bool TryReadActorNativeTypeId(uintptr_t actor_address, std::uint32_t* native_type_id) {
    if (actor_address == 0 || native_type_id == nullptr || kGameObjectTypeIdOffset == 0) {
        return false;
    }

    return ProcessMemory::Instance().TryReadField(
        actor_address,
        kGameObjectTypeIdOffset,
        native_type_id);
}

bool IsSameNativeActor(uintptr_t actor_address, std::uint32_t expected_native_type_id) {
    std::uint32_t current_native_type_id = 0;
    return expected_native_type_id != 0 &&
           TryReadActorNativeTypeId(actor_address, &current_native_type_id) &&
           current_native_type_id == expected_native_type_id;
}

void LogNativeEnemyDeathTriggerResult(
    uintptr_t actor_address,
    bool presenter_called,
    std::uint32_t presenter_exception_code,
    bool fallback_called,
    std::uint32_t fallback_exception_code,
    bool death_handled,
    bool actor_still_same) {
    Log(
        "native enemy death trigger result. actor=" + HexString(actor_address) +
        " presenter_called=" + std::to_string(presenter_called ? 1 : 0) +
        " presenter_seh=" + HexString(static_cast<uintptr_t>(presenter_exception_code)) +
        " fallback_called=" + std::to_string(fallback_called ? 1 : 0) +
        " fallback_seh=" + HexString(static_cast<uintptr_t>(fallback_exception_code)) +
        " death_handled=" + std::to_string(death_handled ? 1 : 0) +
        " actor_still_same=" + std::to_string(actor_still_same ? 1 : 0));
}

}  // namespace

bool TryTriggerRunEnemyDeath(uintptr_t actor_address, std::uint32_t* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 || kEnemyDeathHandledOffset == 0) {
        return false;
    }

    if (IsEnemyDeathHandled(actor_address)) {
        return true;
    }

    std::uint32_t original_native_type_id = 0;
    const bool have_original_native_type =
        TryReadActorNativeTypeId(actor_address, &original_native_type_id);
    std::uint32_t presenter_exception_code = 0;
    const bool presenter_called =
        CallEnemyDeathPresenterVirtualSafe(actor_address, &presenter_exception_code);
    if (IsEnemyDeathHandled(actor_address)) {
        if (exception_code != nullptr) {
            *exception_code = presenter_exception_code;
        }
        LogNativeEnemyDeathTriggerResult(
            actor_address,
            presenter_called,
            presenter_exception_code,
            false,
            0,
            true,
            true);
        return true;
    }

    const bool actor_still_same =
        !have_original_native_type || IsSameNativeActor(actor_address, original_native_type_id);
    if (presenter_called && !actor_still_same) {
        if (exception_code != nullptr) {
            *exception_code = presenter_exception_code;
        }
        LogNativeEnemyDeathTriggerResult(
            actor_address,
            true,
            presenter_exception_code,
            false,
            0,
            false,
            false);
        return true;
    }

    std::uint32_t death_exception_code = 0;
    const bool death_called = CallEnemyDeathSafe(actor_address, &death_exception_code);
    const bool death_handled = IsEnemyDeathHandled(actor_address);
    if (exception_code != nullptr) {
        *exception_code = death_called ? death_exception_code : presenter_exception_code;
    }
    LogNativeEnemyDeathTriggerResult(
        actor_address,
        presenter_called,
        presenter_exception_code,
        death_called,
        death_exception_code,
        death_handled,
        actor_still_same);
    return death_handled;
}

}  // namespace sdmod
