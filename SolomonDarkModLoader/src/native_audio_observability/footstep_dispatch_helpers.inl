bool ResolveFootstepDispatchSafe(
    uintptr_t world_address,
    float x,
    float y,
    float gain_scale,
    uintptr_t rng_integer_address,
    uintptr_t rng_state_address,
    float* spatial_gain,
    std::int32_t* footstep_index) {
    if (world_address == 0 ||
        rng_integer_address == 0 ||
        rng_state_address == 0 ||
        spatial_gain == nullptr ||
        footstep_index == nullptr) {
        return false;
    }
    __try {
        const auto world_vtable =
            *reinterpret_cast<uintptr_t*>(world_address);
        if (world_vtable == 0) {
            return false;
        }
        const auto gain_address =
            *reinterpret_cast<uintptr_t*>(
                world_vtable + kWorldPointGainVfuncOffset);
        auto* resolve_gain =
            reinterpret_cast<WorldPointGainFn>(gain_address);
        auto* random_integer =
            reinterpret_cast<NativeRngIntegerFn>(
                rng_integer_address);
        if (resolve_gain == nullptr ||
            random_integer == nullptr) {
            return false;
        }
        *spatial_gain =
            resolve_gain(
                reinterpret_cast<void*>(world_address),
                x,
                y) *
            gain_scale;
        *footstep_index =
            random_integer(
                reinterpret_cast<void*>(rng_state_address),
                static_cast<std::int32_t>(
                    kFootstepCatalog.size()),
                0);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool CallSoundPlaySafe(
    uintptr_t sound_play_address,
    uintptr_t object_address,
    float gain) {
    if (sound_play_address == 0 ||
        object_address == 0 ||
        !std::isfinite(gain)) {
        return false;
    }
    __try {
        auto* play =
            reinterpret_cast<SoundPlayFn>(
                sound_play_address);
        play(
            reinterpret_cast<void*>(object_address),
            gain);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}
