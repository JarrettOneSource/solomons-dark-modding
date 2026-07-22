bool CallNativeExperienceGainSafe(
    uintptr_t function_address,
    uintptr_t progression_address,
    float amount,
    bool apply_native_scaling,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (function_address == 0 || progression_address == 0) {
        return false;
    }

    const auto function =
        reinterpret_cast<ExperienceGainProbeFn>(function_address);
    __try {
        function(
            reinterpret_cast<void*>(progression_address),
            amount,
            apply_native_scaling ? 1 : 0);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteNativeExperienceGainProbe(
    const PendingNativeExperienceGainProbe& request,
    float* xp_before,
    float* xp_after,
    std::uint32_t* exception_code,
    std::string* error_message) {
    if (xp_before != nullptr) {
        *xp_before = 0.0f;
    }
    if (xp_after != nullptr) {
        *xp_after = 0.0f;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) ||
        !player_state.valid ||
        player_state.progression_address == 0) {
        if (error_message != nullptr) {
            *error_message = "local progression or native XP seam is unavailable";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto experience_gain_address =
        memory.ResolveGameAddressOrZero(kExperienceGain);
    if (experience_gain_address == 0) {
        if (error_message != nullptr) {
            *error_message = "native XP seam is unavailable";
        }
        return false;
    }

    float before = 0.0f;
    if (!memory.TryReadField(
            player_state.progression_address,
            kProgressionXpOffset,
            &before) ||
        !std::isfinite(before)) {
        if (error_message != nullptr) {
            *error_message = "native XP total could not be read before the probe";
        }
        return false;
    }

    DWORD seh_code = 0;
    const bool called = CallNativeExperienceGainSafe(
        experience_gain_address,
        player_state.progression_address,
        request.amount,
        request.apply_native_scaling,
        &seh_code);
    float after = before;
    const bool read_after = memory.TryReadField(
        player_state.progression_address,
        kProgressionXpOffset,
        &after) &&
        std::isfinite(after);
    if (xp_before != nullptr) {
        *xp_before = before;
    }
    if (xp_after != nullptr) {
        *xp_after = after;
    }
    if (exception_code != nullptr) {
        *exception_code = static_cast<std::uint32_t>(seh_code);
    }
    if (!called) {
        if (error_message != nullptr) {
            *error_message = "native XP seam raised " +
                HexString(static_cast<uintptr_t>(seh_code));
        }
        return false;
    }
    if (!read_after) {
        if (error_message != nullptr) {
            *error_message = "native XP total could not be read after the probe";
        }
        return false;
    }
    return true;
}
