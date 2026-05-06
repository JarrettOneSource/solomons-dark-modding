void LogLocalPlayerAnimationProbe() {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) ||
        actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    (void)memory;
    float current_x = 0.0f;
    float current_y = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &current_x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &current_y)) {
        return;
    }

    bool moving_now = false;
    if (g_local_player_animation_probe_has_last_position) {
        const auto delta_x = current_x - g_local_player_animation_probe_last_x;
        const auto delta_y = current_y - g_local_player_animation_probe_last_y;
        moving_now = std::sqrt((delta_x * delta_x) + (delta_y * delta_y)) > 0.01f;
    }

    g_local_player_animation_probe_last_x = current_x;
    g_local_player_animation_probe_last_y = current_y;
    g_local_player_animation_probe_has_last_position = true;
    CaptureObservedPlayerAnimationDriveProfile(actor_address, moving_now);
}
