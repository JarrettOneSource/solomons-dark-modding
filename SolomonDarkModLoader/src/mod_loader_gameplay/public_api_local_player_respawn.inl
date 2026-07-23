bool TryRespawnLocalPlayerAt(
    float world_x,
    float world_y,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    constexpr float kMaximumRespawnCoordinateMagnitude = 1000000.0f;
    if (!std::isfinite(world_x) ||
        !std::isfinite(world_y) ||
        std::abs(world_x) > kMaximumRespawnCoordinateMagnitude ||
        std::abs(world_y) > kMaximumRespawnCoordinateMagnitude) {
        if (error_message != nullptr) {
            *error_message = "Respawn coordinates are invalid.";
        }
        return false;
    }

    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        player.actor_address == 0 ||
        player.world_address == 0 ||
        player.progression_address == 0 ||
        !std::isfinite(player.max_hp) ||
        !std::isfinite(player.max_mp) ||
        player.max_hp <= 0.0f ||
        player.max_mp <= 0.0f ||
        kProgressionHpOffset == 0 ||
        kProgressionMpOffset == 0 ||
        kActorPositionXOffset == 0 ||
        kActorPositionYOffset == 0 ||
        kActorAnimationDriveStateByteOffset == 0) {
        if (error_message != nullptr) {
            *error_message =
                "A live local run player with valid progression is required.";
        }
        return false;
    }

    std::string cast_error;
    if (!ClearLocalPlayerGameplayCastState(&cast_error)) {
        if (error_message != nullptr) {
            *error_message =
                "The local cast state could not be cleared: " +
                cast_error;
        }
        return false;
    }

    g_gameplay_keyboard_injection.pending_movement_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.pending_movement_frames.store(
        0,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_x.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_y.store(
        0.0f,
        std::memory_order_release);
    g_gameplay_keyboard_injection.local_movement_intent_observed_ms.store(
        0,
        std::memory_order_release);

    auto& memory = ProcessMemory::Instance();
    const bool wrote =
        memory.TryWriteField(
            player.progression_address,
            kProgressionHpOffset,
            player.max_hp) &&
        memory.TryWriteField(
            player.progression_address,
            kProgressionMpOffset,
            player.max_mp) &&
        memory.TryWriteField(
            player.actor_address,
            kActorPositionXOffset,
            world_x) &&
        memory.TryWriteField(
            player.actor_address,
            kActorPositionYOffset,
            world_y) &&
        memory.TryWriteField<float>(
            player.actor_address,
            kActorAnimationConfigBlockOffset,
            0.0f) &&
        memory.TryWriteField<float>(
            player.actor_address,
            kActorAnimationDriveParameterOffset,
            0.0f) &&
        memory.TryWriteField<std::int32_t>(
            player.actor_address,
            kActorAnimationMoveDurationTicksOffset,
            0);
    if (!wrote) {
        if (error_message != nullptr) {
            *error_message =
                "One or more native respawn fields could not be written.";
        }
        return false;
    }

    ClearLiveWizardActorAnimationDriveState(player.actor_address);
    std::string rebind_error;
    if (!RebindSceneActorCell(
            player.actor_address,
            &rebind_error)) {
        if (error_message != nullptr) {
            *error_message =
                "The respawn position could not be rebound to the world grid: " +
                rebind_error;
        }
        return false;
    }

    SDModPlayerState verified;
    constexpr float kRespawnReadbackTolerance = 0.05f;
    if (!TryGetPlayerState(&verified) ||
        !verified.valid ||
        verified.actor_address != player.actor_address ||
        std::abs(verified.hp - verified.max_hp) >
            kRespawnReadbackTolerance ||
        std::abs(verified.mp - verified.max_mp) >
            kRespawnReadbackTolerance ||
        std::abs(verified.x - world_x) >
            kRespawnReadbackTolerance ||
        std::abs(verified.y - world_y) >
            kRespawnReadbackTolerance ||
        verified.anim_drive_state != 0) {
        if (error_message != nullptr) {
            *error_message =
                "Native respawn fields did not converge after writeback.";
        }
        return false;
    }

    Log(
        "Respawned local multiplayer player. actor=" +
        HexString(player.actor_address) +
        " position=(" + std::to_string(world_x) + "," +
        std::to_string(world_y) + ")" +
        " hp=" + std::to_string(verified.hp) +
        " mp=" + std::to_string(verified.mp));
    return true;
}
