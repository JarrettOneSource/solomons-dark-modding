bool ExecuteNativeEnemyDeathProbe(
    const PendingNativeEnemyDeathProbe& request,
    std::uint32_t* exception_code,
    bool* config_restored,
    std::string* error_message) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (config_restored != nullptr) {
        *config_restored = false;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t current_config_address = 0;
    const bool fixture_still_attached = memory.TryReadField(
        request.actor_address,
        kEnemyConfigOffset,
        &current_config_address) &&
        current_config_address == request.expected_config_address;
    if (!fixture_still_attached) {
        if (error_message != nullptr) {
            *error_message = "enemy config fixture changed before dispatch";
        }
        return false;
    }

    std::uint32_t death_exception_code = 0;
    const bool triggered = TryTriggerRunEnemyDeath(
        request.actor_address,
        &death_exception_code);
    uintptr_t config_after_death = 0;
    const bool restored = memory.TryReadField(
        request.actor_address,
        kEnemyConfigOffset,
        &config_after_death) &&
        config_after_death == request.expected_config_address &&
        memory.TryWriteField(
            request.actor_address,
            kEnemyConfigOffset,
            request.restore_config_address);
    if (exception_code != nullptr) {
        *exception_code = death_exception_code;
    }
    if (config_restored != nullptr) {
        *config_restored = restored;
    }
    if (!triggered) {
        if (error_message != nullptr) {
            *error_message = "native enemy death was not handled";
        }
        return false;
    }
    if (death_exception_code != 0) {
        if (error_message != nullptr) {
            *error_message = "native enemy death raised " +
                HexString(static_cast<uintptr_t>(death_exception_code));
        }
        return false;
    }
    if (!restored) {
        if (error_message != nullptr) {
            *error_message = "enemy config fixture was not restored";
        }
        return false;
    }
    return true;
}
