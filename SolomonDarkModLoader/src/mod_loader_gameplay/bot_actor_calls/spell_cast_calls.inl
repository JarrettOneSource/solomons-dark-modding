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

bool CallActorWorldLookupObjectByHandleSafe(
    uintptr_t lookup_address,
    uintptr_t world_address,
    std::uint8_t group,
    std::uint16_t slot,
    uintptr_t* object_address,
    DWORD* exception_code) {
    auto* lookup = reinterpret_cast<ActorWorldLookupObjectByHandleFn>(lookup_address);
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (lookup == nullptr || world_address == 0 || object_address == nullptr) {
        return false;
    }

    struct NativeObjectHandle {
        std::uint8_t group = 0;
        std::uint8_t reserved = 0;
        std::uint16_t slot = 0;
    };
    NativeObjectHandle handle{};
    handle.group = group;
    handle.slot = slot;

    __try {
        *object_address =
            lookup(reinterpret_cast<void*>(world_address), reinterpret_cast<void*>(&handle));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
