// Host reconciliation for movement applied by accepted enemy-damage claims.

bool TryApplyAcceptedEnemyDamageTargetPosition(
    const EnemyDamageClaimPacket& packet,
    const SDModSceneActorState& target_actor) {
    if (target_actor.actor_address == 0 ||
        !std::isfinite(packet.target_position_x) ||
        !std::isfinite(packet.target_position_y) ||
        !std::isfinite(target_actor.x) ||
        !std::isfinite(target_actor.y)) {
        return false;
    }

    constexpr float kPositionWriteEpsilon = 0.5f;
    const float displacement_sq = DistanceSquared(
        packet.target_position_x,
        packet.target_position_y,
        target_actor.x,
        target_actor.y);
    const float target_drift_limit_sq =
        kEnemyDamageClaimMaxTargetDrift * kEnemyDamageClaimMaxTargetDrift;
    if (displacement_sq > target_drift_limit_sq) {
        return false;
    }
    if (displacement_sq <= kPositionWriteEpsilon * kPositionWriteEpsilon) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote_x = memory.TryWriteField(
        target_actor.actor_address,
        kActorPositionXOffset,
        packet.target_position_x);
    const bool wrote_y = memory.TryWriteField(
        target_actor.actor_address,
        kActorPositionYOffset,
        packet.target_position_y);
    if (!wrote_x || !wrote_y) {
        // Avoid leaving a half-written transform if one field unexpectedly
        // fails even though the actor was readable during validation.
        (void)memory.TryWriteField(
            target_actor.actor_address,
            kActorPositionXOffset,
            target_actor.x);
        (void)memory.TryWriteField(
            target_actor.actor_address,
            kActorPositionYOffset,
            target_actor.y);
        return false;
    }

    std::string rebind_error;
    if (!sdmod::RebindSceneActorCell(target_actor.actor_address, &rebind_error)) {
        Log(
            "Multiplayer accepted enemy damage target position rebind failed. actor=" +
            HexString(target_actor.actor_address) +
            " error=" + rebind_error);
    }
    return true;
}
