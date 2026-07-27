bool DispatchNativeWizardFootstep(uintptr_t actor_address) {
    if (actor_address == 0 ||
        g_sound_play_address == 0 ||
        g_compiled_registry_global == 0 ||
        g_footstep_frame_counter == 0 ||
        g_footstep_gain_scale == 0 ||
        kActorOwnerOffset == 0 ||
        kActorPositionXOffset == 0 ||
        kActorPositionYOffset == 0 ||
        kNativeRngInteger == 0 ||
        kNativeGlobalRngStateGlobal == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint32_t frame_counter = 0;
    if (!memory.TryReadValue(
            g_footstep_frame_counter,
            &frame_counter) ||
        frame_counter % kNativeFootstepCadenceFrames != 0) {
        return false;
    }
    {
        std::lock_guard<std::mutex> lock(g_native_audio_mutex);
        const auto found =
            g_last_footstep_frame_by_actor.find(actor_address);
        if (found != g_last_footstep_frame_by_actor.end() &&
            found->second == frame_counter) {
            return false;
        }
        if (g_last_footstep_frame_by_actor.size() >=
                kMaximumObservedFootstepActors &&
            found == g_last_footstep_frame_by_actor.end()) {
            g_last_footstep_frame_by_actor.erase(
                g_last_footstep_frame_by_actor.begin());
        }
        g_last_footstep_frame_by_actor[actor_address] =
            frame_counter;
    }

    uintptr_t world_address = 0;
    float x = 0.0f;
    float y = 0.0f;
    double gain_scale = 0.0;
    uintptr_t registry_address = 0;
    uintptr_t rng_state_address = 0;
    if (!memory.TryReadField(
            actor_address,
            kActorOwnerOffset,
            &world_address) ||
        world_address == 0 ||
        !memory.TryReadField(
            actor_address,
            kActorPositionXOffset,
            &x) ||
        !memory.TryReadField(
            actor_address,
            kActorPositionYOffset,
            &y) ||
        !std::isfinite(x) ||
        !std::isfinite(y) ||
        !memory.TryReadValue(
            g_footstep_gain_scale,
            &gain_scale) ||
        !std::isfinite(gain_scale) ||
        gain_scale < 0.0 ||
        !memory.TryReadValue(
            g_compiled_registry_global,
            &registry_address) ||
        registry_address == 0 ||
        !memory.TryReadValue(
            memory.ResolveGameAddressOrZero(
                kNativeGlobalRngStateGlobal),
            &rng_state_address) ||
        rng_state_address == 0) {
        return false;
    }

    float spatial_gain = 0.0f;
    std::int32_t footstep_index = 0;
    if (!ResolveFootstepDispatchSafe(
            world_address,
            x,
            y,
            static_cast<float>(gain_scale),
            memory.ResolveGameAddressOrZero(
                kNativeRngInteger),
            rng_state_address,
            &spatial_gain,
            &footstep_index)) {
        return false;
    }
    if (!std::isfinite(spatial_gain) ||
        footstep_index < 0 ||
        footstep_index >=
            static_cast<std::int32_t>(
                kFootstepCatalog.size())) {
        return false;
    }

    const auto object_address =
        registry_address +
        kFootstepCatalog[
            static_cast<std::size_t>(footstep_index)]
            .object_offset;
    return CallSoundPlaySafe(
        g_sound_play_address,
        object_address,
        spatial_gain);
}
