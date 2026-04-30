bool CallSpellCastDispatcherSafe(
    uintptr_t dispatcher_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* dispatcher = reinterpret_cast<SpellCastDispatcherFn>(dispatcher_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (dispatcher == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        dispatcher(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPurePrimarySpellStartSafe(
    uintptr_t startup_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* startup = reinterpret_cast<PurePrimarySpellStartFn>(startup_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (startup == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        startup(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallCastActiveHandleCleanupSafe(
    uintptr_t cleanup_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* cleanup = reinterpret_cast<CastActiveHandleCleanupFn>(cleanup_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (cleanup == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        cleanup(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallNativeTwoFloatGetterSafe(
    uintptr_t getter_address,
    uintptr_t object_address,
    float x,
    float y,
    float* result,
    DWORD* exception_code) {
    auto* getter = reinterpret_cast<NativeTwoFloatGetterFn>(getter_address);
    if (result != nullptr) {
        *result = 0.0f;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (getter == nullptr || object_address == 0 || result == nullptr) {
        return false;
    }

    __try {
        *result = getter(reinterpret_cast<void*>(object_address), x, y);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
