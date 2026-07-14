bool CallNativeStaffEffectResolverSafe(
    uintptr_t resolver_address,
    uintptr_t source_actor,
    std::uint32_t variant,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* resolver =
        reinterpret_cast<StaffEffectResolverFn>(resolver_address);
    if (resolver == nullptr || source_actor == 0) {
        return false;
    }
    __try {
        resolver(reinterpret_cast<void*>(source_actor), variant);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ExecuteNativeStaffEffectProbe(
    const PendingNativeStaffEffectProbe& request,
    float* hp_before,
    float* hp_after,
    std::string* error_message) {
    if (hp_before != nullptr) {
        *hp_before = 0.0f;
    }
    if (hp_after != nullptr) {
        *hp_after = 0.0f;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolver_address =
        memory.ResolveGameAddressOrZero(kStaffEffectResolver);
    uintptr_t source_vtable = 0;
    uintptr_t source_first_method = 0;
    const bool source_valid =
        request.source_actor != 0 &&
        memory.TryReadValue(request.source_actor, &source_vtable) &&
        source_vtable != 0 &&
        memory.TryReadValue(source_vtable, &source_first_method) &&
        source_first_method != 0 &&
        memory.IsExecutableRange(source_first_method, 1);
    float captured_hp_before = 0.0f;
    const bool target_valid =
        request.target_actor != 0 &&
        kEnemyCurrentHpOffset != 0 &&
        memory.TryReadField(
            request.target_actor,
            kEnemyCurrentHpOffset,
            &captured_hp_before) &&
        std::isfinite(captured_hp_before);
    if (resolver_address == 0 ||
        !memory.IsExecutableRange(resolver_address, 1) ||
        !source_valid ||
        !target_valid ||
        request.variant > 4) {
        if (error_message != nullptr) {
            *error_message = "native staff-effect probe seams are unavailable";
        }
        return false;
    }
    if (hp_before != nullptr) {
        *hp_before = captured_hp_before;
    }

    DWORD exception_code = 0;
    if (!CallNativeStaffEffectResolverSafe(
            resolver_address,
            request.source_actor,
            request.variant,
            &exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                "native staff-effect resolver failed" +
                (exception_code == 0
                     ? std::string{}
                     : " exception=" + HexString(exception_code));
        }
        return false;
    }
    float captured_hp_after = 0.0f;
    if (!memory.TryReadField(
            request.target_actor,
            kEnemyCurrentHpOffset,
            &captured_hp_after) ||
        !std::isfinite(captured_hp_after)) {
        if (error_message != nullptr) {
            *error_message = "native staff-effect target health is unavailable";
        }
        return false;
    }
    if (hp_after != nullptr) {
        *hp_after = captured_hp_after;
    }
    return true;
}
