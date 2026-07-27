struct PlayerFamilyLocomotionResult {
    bool native_presence_restored = false;
    bool native_step_called = false;
    bool native_step_result = false;
    bool footstep_dispatched = false;
    DWORD exception_code = 0;
    float position_before_x = 0.0f;
    float position_before_y = 0.0f;
    float position_after_x = 0.0f;
    float position_after_y = 0.0f;
    float actual_displacement = 0.0f;
};

bool EnsurePlayerFamilyActorNativePresence(
    uintptr_t actor_address,
    bool* restored,
    DWORD* exception_code) {
    if (restored != nullptr) {
        *restored = false;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 ||
        kActorGridMemberFlagOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t grid_member = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorGridMemberFlagOffset,
            &grid_member)) {
        return false;
    }
    if (grid_member == 1) {
        return true;
    }
    if (!RestoreWizardActorAliveRegistrationState(actor_address) ||
        !TryRebindActorToOwnerWorld(
            actor_address,
            exception_code)) {
        return false;
    }
    if (restored != nullptr) {
        *restored = true;
    }
    return true;
}

bool TeleportPlayerFamilyActorAndRebind(
    uintptr_t actor_address,
    float x,
    float y,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0 ||
        !std::isfinite(x) ||
        !std::isfinite(y)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.TryWriteField(
            actor_address,
            kActorPositionXOffset,
            x) ||
        !memory.TryWriteField(
            actor_address,
            kActorPositionYOffset,
            y)) {
        return false;
    }
    bool restored = false;
    if (!EnsurePlayerFamilyActorNativePresence(
            actor_address,
            &restored,
            exception_code)) {
        return false;
    }
    return restored ||
           TryRebindActorToOwnerWorld(
               actor_address,
               exception_code);
}

bool MovePlayerFamilyActorThroughNativeStep(
    uintptr_t actor_address,
    float move_x,
    float move_y,
    unsigned int flags,
    PlayerFamilyLocomotionResult* result,
    std::string* error_message) {
    if (result != nullptr) {
        *result = PlayerFamilyLocomotionResult{};
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (actor_address == 0 ||
        !std::isfinite(move_x) ||
        !std::isfinite(move_y)) {
        if (error_message != nullptr) {
            *error_message =
                "Player-family locomotion requires a live actor and finite delta.";
        }
        return false;
    }

    PlayerFamilyLocomotionResult local_result;
    auto& memory = ProcessMemory::Instance();
    if (!EnsurePlayerFamilyActorNativePresence(
            actor_address,
            &local_result.native_presence_restored,
            &local_result.exception_code)) {
        if (error_message != nullptr) {
            *error_message =
                local_result.exception_code != 0
                    ? "Player-family native presence restore threw 0x" +
                          HexString(local_result.exception_code) + "."
                    : "Player-family native presence is unavailable.";
        }
        if (result != nullptr) {
            *result = local_result;
        }
        return false;
    }
    uintptr_t world_address = 0;
    if (!TryReadFiniteFloatField(
            actor_address,
            kActorPositionXOffset,
            &local_result.position_before_x) ||
        !TryReadFiniteFloatField(
            actor_address,
            kActorPositionYOffset,
            &local_result.position_before_y) ||
        !memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &world_address) ||
        world_address == 0) {
        if (error_message != nullptr) {
            *error_message =
                "Player-family locomotion could not resolve actor position or world.";
        }
        return false;
    }

    const auto move_step_address =
        memory.ResolveGameAddressOrZero(kPlayerActorMoveStep);
    const auto movement_controller_address =
        world_address + kActorOwnerMovementControllerOffset;
    std::uint32_t native_result = 0;
    if (move_step_address == 0 ||
        kActorOwnerMovementControllerOffset == 0 ||
        !CallPlayerActorMoveStepSafe(
            move_step_address,
            movement_controller_address,
            actor_address,
            move_x,
            move_y,
            flags,
            &local_result.exception_code,
            &native_result)) {
        if (error_message != nullptr) {
            *error_message =
                local_result.exception_code != 0
                    ? "PlayerActor_MoveStep threw 0x" +
                          HexString(local_result.exception_code) + "."
                    : "PlayerActor_MoveStep is unavailable.";
        }
        if (result != nullptr) {
            *result = local_result;
        }
        return false;
    }

    local_result.native_step_called = true;
    local_result.native_step_result = native_result != 0;
    if (!TryReadFiniteFloatField(
            actor_address,
            kActorPositionXOffset,
            &local_result.position_after_x) ||
        !TryReadFiniteFloatField(
            actor_address,
            kActorPositionYOffset,
            &local_result.position_after_y)) {
        if (error_message != nullptr) {
            *error_message =
                "Player-family actor position is unreadable after native movement.";
        }
        if (result != nullptr) {
            *result = local_result;
        }
        return false;
    }

    const auto actual_x =
        local_result.position_after_x - local_result.position_before_x;
    const auto actual_y =
        local_result.position_after_y - local_result.position_before_y;
    local_result.actual_displacement =
        std::sqrt(actual_x * actual_x + actual_y * actual_y);
    if (local_result.actual_displacement > 0.0001f) {
        local_result.footstep_dispatched =
            DispatchNativeWizardFootstep(actor_address);
    }
    if (result != nullptr) {
        *result = local_result;
    }
    return true;
}
