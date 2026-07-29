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

bool CallPlayerActorLightSubmitSafe(
    uintptr_t light_submit_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* light_submit =
        reinterpret_cast<PlayerActorNoArgMethodFn>(light_submit_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (light_submit == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        light_submit(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorInitializeControlBrainSafe(
    uintptr_t initialize_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* initialize_control_brain =
        reinterpret_cast<PlayerActorInitializeControlBrainFn>(initialize_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (initialize_control_brain == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        initialize_control_brain(reinterpret_cast<void*>(actor_address));
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
        uintptr_t progression_handle = 0;
        if (!memory.TryReadField(actor_address, kActorProgressionHandleOffset, &progression_handle)) {
            return false;
        }
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

bool CallSkillsWizardGetPrimaryColorSafe(
    uintptr_t color_address,
    uintptr_t progression_address,
    std::uint32_t primary_entry_arg,
    float out_color[4],
    DWORD* exception_code) {
    auto* get_primary_color = reinterpret_cast<SkillsWizardGetPrimaryColorFn>(color_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (out_color != nullptr) {
        out_color[0] = 0.0f;
        out_color[1] = 0.0f;
        out_color[2] = 0.0f;
        out_color[3] = 0.0f;
    }
    if (get_primary_color == nullptr || progression_address == 0 || out_color == nullptr) {
        return false;
    }

    __try {
        get_primary_color(
            reinterpret_cast<void*>(progression_address),
            out_color,
            primary_entry_arg);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}
