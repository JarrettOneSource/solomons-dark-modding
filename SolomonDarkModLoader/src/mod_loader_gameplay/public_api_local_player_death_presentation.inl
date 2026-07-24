bool HoldLocalPlayerMultiplayerDeathPresentation(
    bool presentation_active,
    std::uint64_t presentation_elapsed_ms) {
    SDModPlayerState player;
    if (!TryGetPlayerState(&player) ||
        !player.valid ||
        player.actor_address == 0 ||
        kActorTerminalDispatchPendingOffset == 0 ||
        kActorTerminalDispatchCountdownOffset == 0 ||
        kActorAnimationDriveStateByteOffset == 0 ||
        kActorAnimationMoveDurationTicksOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const bool wrote =
        memory.TryWriteField<std::uint8_t>(
            player.actor_address,
            kActorTerminalDispatchPendingOffset,
            0) &&
        memory.TryWriteField<std::int32_t>(
            player.actor_address,
            kActorTerminalDispatchCountdownOffset,
            0) &&
        memory.TryWriteField<std::uint8_t>(
            player.actor_address,
            kActorAnimationDriveStateByteOffset,
            1) &&
        memory.TryWriteField<std::int32_t>(
            player.actor_address,
            kActorAnimationMoveDurationTicksOffset,
            presentation_active
                ? multiplayer::ResolveParticipantDeathPresentationTick(
                      presentation_elapsed_ms)
                : 0);
    return wrote;
}
