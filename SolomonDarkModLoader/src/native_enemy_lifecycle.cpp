#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <Windows.h>

#include "native_enemy_lifecycle.h"

#include "gameplay_seams.h"
#include "memory_access.h"

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

bool CallEnemyDeathSafe(uintptr_t actor_address, std::uint32_t* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    const auto enemy_death_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kEnemyDeath);
    auto* enemy_death = reinterpret_cast<EnemyDeathNativeFn>(enemy_death_address);
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

}  // namespace

bool TryTriggerRunEnemyDeath(uintptr_t actor_address, std::uint32_t* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 || kEnemyDeathHandledOffset == 0) {
        return false;
    }

    std::uint8_t death_handled = 0;
    if (ProcessMemory::Instance().TryReadField(actor_address, kEnemyDeathHandledOffset, &death_handled) &&
        death_handled != 0) {
        return true;
    }

    return CallEnemyDeathSafe(actor_address, exception_code);
}

}  // namespace sdmod
