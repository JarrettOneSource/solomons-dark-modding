uintptr_t ReadSmartPointerInnerObject(uintptr_t wrapper_address) {
    if (wrapper_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto direct_inner = memory.ReadValueOr<uintptr_t>(wrapper_address, 0);
    if (direct_inner != 0 && memory.IsReadableRange(direct_inner, 1)) {
        return direct_inner;
    }

    // Gameplay-slot wrappers are not the loader-owned 8-byte clone wrappers.
    // Their live object pointer sits at +0x0C, so support both contracts here.
    const auto gameplay_inner = memory.ReadValueOr<uintptr_t>(wrapper_address + 0x0C, 0);
    if (gameplay_inner != 0 && memory.IsReadableRange(gameplay_inner, 1)) {
        return gameplay_inner;
    }

    return direct_inner;
}

bool RetainSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (wrapper_address == 0) {
        return true;
    }

    __try {
        auto* wrapper = reinterpret_cast<std::int32_t*>(wrapper_address);
        ++wrapper[1];
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ReleaseSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (wrapper_address == 0) {
        return true;
    }

    const auto free_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameFree);
    if (free_address == 0) {
        return false;
    }

    __try {
        auto* wrapper = reinterpret_cast<std::int32_t*>(wrapper_address);
        --wrapper[1];
        if (wrapper[1] > 0) {
            return true;
        }

        auto* inner_object = reinterpret_cast<void*>(static_cast<uintptr_t>(wrapper[0]));
        if (inner_object != nullptr) {
            const auto vtable = *reinterpret_cast<uintptr_t*>(inner_object);
            const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
            auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
            destructor(inner_object, 1);
        }

        auto* free_memory = reinterpret_cast<GameFreeFn>(free_address);
        free_memory(reinterpret_cast<void*>(wrapper_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool AssignActorSmartPointerWrapperSafe(
    uintptr_t actor_address,
    std::size_t wrapper_offset,
    std::size_t runtime_state_offset,
    uintptr_t source_wrapper_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto existing_wrapper_address = memory.ReadFieldOr<uintptr_t>(actor_address, wrapper_offset, 0);
    if (existing_wrapper_address == source_wrapper_address) {
        const auto inner_object = ReadSmartPointerInnerObject(source_wrapper_address);
        return memory.TryWriteField(actor_address, runtime_state_offset, inner_object);
    }

    if (source_wrapper_address != 0 &&
        !RetainSmartPointerWrapperSafe(source_wrapper_address, exception_code)) {
        return false;
    }

    if (!memory.TryWriteField(actor_address, wrapper_offset, source_wrapper_address)) {
        if (source_wrapper_address != 0) {
            DWORD release_exception = 0;
            (void)ReleaseSmartPointerWrapperSafe(source_wrapper_address, &release_exception);
        }
        return false;
    }

    const auto inner_object = ReadSmartPointerInnerObject(source_wrapper_address);
    if (!memory.TryWriteField(actor_address, runtime_state_offset, inner_object)) {
        return false;
    }

    if (existing_wrapper_address != 0) {
        DWORD release_exception = 0;
        if (!ReleaseSmartPointerWrapperSafe(existing_wrapper_address, &release_exception) &&
            exception_code != nullptr &&
            *exception_code == 0) {
            *exception_code = release_exception;
        }
    }

    return true;
}

