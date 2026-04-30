bool CallActorWorldUnregisterSafe(
    uintptr_t actor_world_unregister_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    char remove_from_container,
    DWORD* exception_code) {
    auto* actor_world_unregister = reinterpret_cast<ActorWorldUnregisterFn>(actor_world_unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_unregister == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        actor_world_unregister(
            reinterpret_cast<void*>(world_address),
            reinterpret_cast<void*>(actor_address),
            remove_from_container);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldUnregisterGameplaySlotActorSafe(
    uintptr_t unregister_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code) {
    auto* unregister_slot_actor =
        reinterpret_cast<ActorWorldUnregisterGameplaySlotActorFn>(unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (unregister_slot_actor == nullptr || world_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        unregister_slot_actor(reinterpret_cast<void*>(world_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorSafe(
    uintptr_t object_address,
    int flags,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorDetailedSafe(
    uintptr_t object_address,
    int flags,
    SehExceptionDetails* exception_details) {
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehDetails(GetExceptionInformation(), exception_details)) {
        return false;
    }
}

bool CallActorGetProfileSafe(
    uintptr_t fn_address,
    uintptr_t actor_address,
    DWORD* exception_code,
    uintptr_t* out_profile) {
    auto* get_profile = reinterpret_cast<ActorGetProfileFn>(fn_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_profile != nullptr) {
        *out_profile = 0;
    }
    if (get_profile == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        auto* profile = get_profile(reinterpret_cast<void*>(actor_address));
        if (out_profile != nullptr) {
            *out_profile = reinterpret_cast<uintptr_t>(profile);
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallProfileResolveStatEntrySafe(
    uintptr_t fn_address,
    uintptr_t container_address,
    int stat_index,
    DWORD* exception_code,
    uintptr_t* out_entry) {
    auto* resolve_stat_entry = reinterpret_cast<ProfileResolveStatEntryFn>(fn_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_entry != nullptr) {
        *out_entry = 0;
    }
    if (resolve_stat_entry == nullptr || container_address == 0) {
        return false;
    }

    __try {
        auto* entry = resolve_stat_entry(reinterpret_cast<void*>(container_address), stat_index);
        if (out_entry != nullptr) {
            *out_entry = reinterpret_cast<uintptr_t>(entry);
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallStatBookComputeValueSafe(
    uintptr_t fn_address,
    uintptr_t stat_book_address,
    float base_value,
    int entry_idx,
    char apply_modifier,
    DWORD* exception_code,
    float* out_value) {
    auto* compute_value = reinterpret_cast<StatBookComputeValueFn>(fn_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_value != nullptr) {
        *out_value = 0.0f;
    }
    if (compute_value == nullptr || stat_book_address == 0) {
        return false;
    }

    __try {
        const auto value = compute_value(
            reinterpret_cast<void*>(stat_book_address), base_value, entry_idx, apply_modifier);
        if (out_value != nullptr) {
            *out_value = value;
        }
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
