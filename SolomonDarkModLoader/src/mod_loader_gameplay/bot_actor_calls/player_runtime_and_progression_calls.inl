bool CallPlayerActorEnsureProgressionHandleSafe(
    uintptr_t ensure_progression_handle_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* ensure_progression_handle =
        reinterpret_cast<PlayerActorNoArgMethodFn>(ensure_progression_handle_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (ensure_progression_handle == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        ensure_progression_handle(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorRefreshRuntimeHandlesSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_runtime_handles = reinterpret_cast<PlayerActorRefreshRuntimeHandlesFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_runtime_handles == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        refresh_runtime_handles(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorProgressionRefreshSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_progression = reinterpret_cast<ActorProgressionRefreshFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_progression == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        auto& memory = ProcessMemory::Instance();
        const auto progression_handle =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        const auto progression_runtime =
            progression_handle != 0 ? ReadSmartPointerInnerObject(progression_handle) : 0;
        if (progression_runtime == 0) {
            return false;
        }

        refresh_progression(reinterpret_cast<void*>(progression_runtime));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallSkillsWizardBuildPrimarySpellSafe(
    uintptr_t build_address,
    uintptr_t progression_address,
    std::uint32_t primary_entry_arg,
    std::uint32_t combo_entry_arg,
    DWORD* exception_code) {
    auto* build_primary_spell =
        reinterpret_cast<SkillsWizardBuildPrimarySpellFn>(build_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_primary_spell == nullptr || progression_address == 0) {
        return false;
    }

    __try {
        build_primary_spell(
            reinterpret_cast<void*>(progression_address),
            primary_entry_arg,
            combo_entry_arg,
            0,
            0,
            0,
            0);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerAppearanceApplyChoiceSafe(
    uintptr_t apply_choice_address,
    uintptr_t progression_address,
    int choice_id,
    int ensure_assets,
    DWORD* exception_code) {
    auto* apply_choice = reinterpret_cast<PlayerAppearanceApplyChoiceFn>(apply_choice_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (apply_choice == nullptr || progression_address == 0 || choice_id < 0) {
        return false;
    }

    __try {
        apply_choice(reinterpret_cast<void*>(progression_address), choice_id, ensure_assets);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
