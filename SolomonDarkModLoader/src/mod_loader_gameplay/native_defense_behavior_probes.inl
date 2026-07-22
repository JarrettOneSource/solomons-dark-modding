bool CallPlayerActorMagicDamageSafe(
    uintptr_t handler_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    auto* handler = reinterpret_cast<PlayerActorMagicDamageFn>(handler_address);
    if (handler == nullptr || actor_address == 0) {
        return false;
    }
    __try {
        handler(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool TryReadNativeMagicHitTargetLife(
    uintptr_t actor_address,
    float* life_current) {
    if (actor_address == 0 || life_current == nullptr) {
        return false;
    }
    uintptr_t progression_address = 0;
    return TryResolveActorProgressionRuntime(
               actor_address,
               &progression_address) &&
           progression_address != 0 &&
           TryReadFiniteFloatField(
               progression_address,
               kProgressionHpOffset,
               life_current);
}

bool ExecuteNativeMagicHitBehaviorProbe(
    const PendingNativeMagicHitBehaviorProbe& request,
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

    SDModPlayerState local_player_state;
    if (!TryGetPlayerState(&local_player_state) ||
        !local_player_state.valid ||
        local_player_state.actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "local player actor is unavailable";
        }
        return false;
    }
    uintptr_t target_actor = local_player_state.actor_address;
    if (request.target_participant_id != 0) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto* binding =
            FindParticipantEntity(request.target_participant_id);
        if (binding == nullptr || binding->actor_address == 0) {
            if (error_message != nullptr) {
                *error_message = "target participant actor is unavailable";
            }
            return false;
        }
        target_actor = binding->actor_address;
    }
    float target_life_before = 0.0f;
    if (!TryReadNativeMagicHitTargetLife(
            target_actor,
            &target_life_before)) {
        if (error_message != nullptr) {
            *error_message = "target participant life is unavailable";
        }
        return false;
    }
    if (hp_before != nullptr) {
        *hp_before = target_life_before;
    }

    auto& memory = ProcessMemory::Instance();
    const auto handler_address =
        memory.ResolveGameAddressOrZero(kPlayerActorMagicDamage);
    const auto target_address =
        memory.ResolveGameAddressOrZero(kDamageContextTargetGlobal);
    const auto source_address =
        memory.ResolveGameAddressOrZero(kDamageContextSourceGlobal);
    const auto flags_address =
        memory.ResolveGameAddressOrZero(kDamageContextFlagsGlobal);
    const auto primary_address =
        memory.ResolveGameAddressOrZero(kDamageContextPrimaryGlobal);
    const auto secondary_address =
        memory.ResolveGameAddressOrZero(kDamageContextSecondaryGlobal);
    if (handler_address == 0 ||
        target_address == 0 ||
        source_address == 0 ||
        flags_address == 0 ||
        primary_address == 0 ||
        secondary_address == 0 ||
        secondary_address != primary_address + sizeof(float)) {
        if (error_message != nullptr) {
            *error_message = "native magic-damage seams are unavailable";
        }
        return false;
    }

    uintptr_t damage_source_actor = local_player_state.actor_address;
    if (damage_source_actor == target_actor) {
        std::lock_guard<std::recursive_mutex> lock(g_participant_entities_mutex);
        const auto source = std::find_if(
            g_participant_entities.begin(),
            g_participant_entities.end(),
            [&](const ParticipantEntityBinding& binding) {
                return binding.actor_address != 0 &&
                       binding.actor_address != target_actor;
            });
        if (source != g_participant_entities.end()) {
            damage_source_actor = source->actor_address;
        }
    }

    uintptr_t saved_target = 0;
    uintptr_t saved_source = 0;
    std::uint32_t saved_flags = 0;
    constexpr std::size_t kDamageLaneCount = 9;
    std::array<float, kDamageLaneCount> saved_damage_lanes{};
    bool context_read =
        memory.TryReadValue(target_address, &saved_target) &&
        memory.TryReadValue(source_address, &saved_source) &&
        memory.TryReadValue(flags_address, &saved_flags);
    for (std::size_t index = 0; index < saved_damage_lanes.size(); ++index) {
        context_read =
            memory.TryReadValue(
                primary_address + index * sizeof(float),
                &saved_damage_lanes[index]) &&
            context_read;
    }
    if (!context_read) {
        if (error_message != nullptr) {
            *error_message = "native damage context could not be captured";
        }
        return false;
    }

    std::uint32_t successful_attempts = 0;
    DWORD exception_code = 0;
    for (std::uint32_t attempt = 0; attempt < request.attempts; ++attempt) {
        bool wrote_context =
            memory.TryWriteValue(target_address, target_actor) &&
            memory.TryWriteValue(source_address, damage_source_actor) &&
            memory.TryWriteValue(flags_address, std::uint32_t{0});
        for (std::size_t index = 0; index < kDamageLaneCount; ++index) {
            const float value =
                index == 0
                    ? request.projectile_damage
                    : (index == 1
                           ? request.magic_damage
                           : (index == 2 ? request.poison_damage : 0.0f));
            wrote_context =
                memory.TryWriteValue(
                    primary_address + index * sizeof(float),
                    value) &&
                wrote_context;
        }
        if (!wrote_context ||
            !CallPlayerActorMagicDamageSafe(
                handler_address,
                target_actor,
                &exception_code)) {
            break;
        }
        ++successful_attempts;
    }

    bool restored =
        memory.TryWriteValue(target_address, saved_target) &&
        memory.TryWriteValue(source_address, saved_source) &&
        memory.TryWriteValue(flags_address, saved_flags);
    for (std::size_t index = 0; index < saved_damage_lanes.size(); ++index) {
        restored =
            memory.TryWriteValue(
                primary_address + index * sizeof(float),
                saved_damage_lanes[index]) &&
            restored;
    }

    float target_life_after = 0.0f;
    const bool final_health_readable = TryReadNativeMagicHitTargetLife(
        target_actor,
        &target_life_after);
    if (final_health_readable && hp_after != nullptr) {
        *hp_after = target_life_after;
    }

    if (successful_attempts != request.attempts ||
        !restored ||
        !final_health_readable) {
        if (error_message != nullptr) {
            std::ostringstream message;
            message << "native magic-damage probe incomplete: successful="
                    << successful_attempts
                    << "/" << request.attempts
                    << " restored=" << (restored ? 1 : 0)
                    << " final_health=" << (final_health_readable ? 1 : 0);
            if (exception_code != 0) {
                message << " exception=" << HexString(exception_code);
            }
            *error_message = message.str();
        }
        return false;
    }
    return true;
}
