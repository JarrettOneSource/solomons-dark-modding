int CaptureSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
        if (exception_pointers != nullptr && exception_pointers->ExceptionRecord != nullptr) {
            *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

int CaptureSehDetails(
    EXCEPTION_POINTERS* exception_pointers,
    SehExceptionDetails* exception_details) {
    if (exception_details != nullptr) {
        *exception_details = {};
        if (exception_pointers != nullptr) {
            if (exception_pointers->ExceptionRecord != nullptr) {
                const auto* record = exception_pointers->ExceptionRecord;
                exception_details->code = record->ExceptionCode;
                exception_details->exception_address =
                    reinterpret_cast<uintptr_t>(record->ExceptionAddress);
                if (record->NumberParameters >= 2 &&
                    (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION ||
                     record->ExceptionCode == EXCEPTION_IN_PAGE_ERROR)) {
                    exception_details->access_type =
                        static_cast<DWORD>(record->ExceptionInformation[0]);
                    exception_details->access_address =
                        static_cast<uintptr_t>(record->ExceptionInformation[1]);
                }
            }
            if (exception_pointers->ContextRecord != nullptr) {
                exception_details->eip =
                    static_cast<uintptr_t>(exception_pointers->ContextRecord->Eip);
            }
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

std::string FormatSehExceptionDetails(const SehExceptionDetails& details) {
    std::ostringstream out;
    out << "code=0x" << HexString(details.code)
        << " exception_address=0x" << HexString(details.exception_address)
        << " eip=0x" << HexString(details.eip);
    if (details.access_address != 0 || details.access_type != 0) {
        out << " access_type=" << details.access_type
            << " access_address=0x" << HexString(details.access_address);
    }
    return out.str();
}

bool CallGameplayCreatePlayerSlotSafe(
    uintptr_t create_player_slot_address,
    uintptr_t gameplay_address,
    int slot_index,
    DWORD* exception_code) {
    auto* create_player_slot = reinterpret_cast<GameplayCreatePlayerSlotFn>(create_player_slot_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (create_player_slot == nullptr || gameplay_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        create_player_slot(reinterpret_cast<void*>(gameplay_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPuppetManagerDeletePuppetSafe(
    uintptr_t delete_puppet_address,
    uintptr_t manager_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* delete_puppet = reinterpret_cast<PuppetManagerDeletePuppetFn>(delete_puppet_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (delete_puppet == nullptr || manager_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        delete_puppet(reinterpret_cast<void*>(manager_address), reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallObjectDeleteSafe(
    uintptr_t object_delete_address,
    uintptr_t object_address,
    DWORD* exception_code) {
    auto* object_delete = reinterpret_cast<ObjectDeleteFn>(object_delete_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (object_delete == nullptr || object_address == 0) {
        return false;
    }

    __try {
        object_delete(reinterpret_cast<void*>(object_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldRegisterSafe(
    uintptr_t actor_world_register_address,
    uintptr_t world_address,
    int actor_group,
    uintptr_t actor_address,
    int slot_index,
    char use_alt_list,
    DWORD* exception_code) {
    auto* actor_world_register = reinterpret_cast<ActorWorldRegisterFn>(actor_world_register_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_register == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        return actor_world_register(
                   reinterpret_cast<void*>(world_address),
                   actor_group,
                   reinterpret_cast<void*>(actor_address),
                   slot_index,
                   use_alt_list) != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameObjectFactorySafe(
    uintptr_t factory_address,
    uintptr_t factory_context_address,
    int type_id,
    uintptr_t* object_address,
    DWORD* exception_code) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* factory = reinterpret_cast<GameObjectFactoryFn>(factory_address);
    if (factory == nullptr || factory_context_address == 0) {
        return false;
    }

    __try {
        const auto object_address_value =
            factory(reinterpret_cast<void*>(factory_context_address), type_id);
        if (object_address != nullptr) {
            *object_address = object_address_value;
        }
        return object_address_value != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameOperatorNewSafe(
    uintptr_t operator_new_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code) {
    if (allocation_address != nullptr) {
        *allocation_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* operator_new_fn = reinterpret_cast<GameOperatorNewFn>(operator_new_address);
    if (operator_new_fn == nullptr) {
        return false;
    }

    __try {
        const auto allocation = operator_new_fn(allocation_size);
        if (allocation_address != nullptr) {
            *allocation_address = reinterpret_cast<uintptr_t>(allocation);
        }
        return allocation != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameObjectAllocateSafe(
    uintptr_t object_allocate_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code) {
    if (allocation_address != nullptr) {
        *allocation_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* object_allocate_fn = reinterpret_cast<GameObjectAllocateFn>(object_allocate_address);
    if (object_allocate_fn == nullptr) {
        return false;
    }

    __try {
        const auto allocation = object_allocate_fn(allocation_size);
        if (allocation_address != nullptr) {
            *allocation_address = reinterpret_cast<uintptr_t>(allocation);
        }
        return allocation != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameFreeSafe(
    uintptr_t free_address,
    uintptr_t allocation_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (allocation_address == 0) {
        return true;
    }

    auto* free_fn = reinterpret_cast<GameFreeFn>(free_address);
    if (free_fn == nullptr) {
        return false;
    }

    __try {
        free_fn(reinterpret_cast<void*>(allocation_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallRawObjectCtorSafe(
    uintptr_t ctor_address,
    void* object_memory,
    uintptr_t* object_address,
    DWORD* exception_code) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* ctor = reinterpret_cast<RawObjectCtorFn>(ctor_address);
    if (ctor == nullptr || object_memory == nullptr) {
        return false;
    }

    __try {
        auto* object = ctor(object_memory);
        if (object_address != nullptr) {
            *object_address = reinterpret_cast<uintptr_t>(object);
        }
        return object != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorCtorSafe(
    uintptr_t ctor_address,
    void* actor_memory,
    uintptr_t* actor_address,
    DWORD* exception_code) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* ctor = reinterpret_cast<PlayerActorCtorFn>(ctor_address);
    if (ctor == nullptr || actor_memory == nullptr) {
        return false;
    }

    __try {
        auto* actor = ctor(actor_memory);
        if (actor_address != nullptr) {
            *actor_address = reinterpret_cast<uintptr_t>(actor);
        }
        return actor != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

