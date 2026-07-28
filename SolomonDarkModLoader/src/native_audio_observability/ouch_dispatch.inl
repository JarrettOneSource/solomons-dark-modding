bool TryDispatchNativeWizardOuchSound(
    uintptr_t actor_address,
    float health_after,
    std::uint64_t participant_id,
    std::uint32_t event_sequence,
    std::int32_t* sound_index,
    float* gain) {
    if (sound_index != nullptr) {
        *sound_index = -1;
    }
    if (gain != nullptr) {
        *gain = 0.0f;
    }
    if (actor_address == 0 ||
        !std::isfinite(health_after) ||
        g_sound_play_address == 0 ||
        g_compiled_registry_global == 0 ||
        kActorOwnerOffset == 0 ||
        kActorPositionXOffset == 0 ||
        kActorPositionYOffset == 0 ||
        kNativeRngInteger == 0 ||
        kNativeGlobalRngStateGlobal == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t world_address = 0;
    uintptr_t registry_address = 0;
    uintptr_t rng_state_address = 0;
    float x = 0.0f;
    float y = 0.0f;
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
    std::int32_t selected_index = -1;
    if (!ResolveOuchDispatchSafe(
            world_address,
            x,
            y,
            memory.ResolveGameAddressOrZero(kNativeRngInteger),
            rng_state_address,
            &spatial_gain,
            &selected_index) ||
        !std::isfinite(spatial_gain) ||
        selected_index < 0 ||
        selected_index >=
            static_cast<std::int32_t>(kOuchCatalog.size())) {
        return false;
    }

    const float health_factor = (std::clamp)(
        (health_after - 25.0f) / 20.0f,
        0.0f,
        1.0f);
    const float health_gain =
        (1.0f - health_factor) * 0.75f + 0.25f;
    const float final_gain = spatial_gain * health_gain;
    if (!std::isfinite(final_gain)) {
        return false;
    }

    ScopedNativeAudioAttribution attribution(actor_address);
    attribution.SetParticipantCast(
        participant_id,
        false,
        -1,
        event_sequence);
    const auto object_address =
        registry_address +
        kOuchCatalog[
            static_cast<std::size_t>(selected_index)]
            .object_offset;
    if (!CallSoundPlaySafe(
            g_sound_play_address,
            object_address,
            final_gain)) {
        return false;
    }

    if (sound_index != nullptr) {
        *sound_index = selected_index;
    }
    if (gain != nullptr) {
        *gain = final_gain;
    }
    return true;
}
