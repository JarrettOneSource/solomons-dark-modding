struct NativeRemotePlaybackResult {
    bool applicable = false;
    bool moving = false;
    bool wrote_position = false;
};

bool IsNativeRemoteParticipantBinding(const ParticipantEntityBinding* binding) {
    return binding != nullptr &&
           binding->controller_kind == multiplayer::ParticipantControllerKind::Native;
}

float ShortestHeadingDeltaDegrees(float from_degrees, float to_degrees) {
    const float from = NormalizeWizardActorHeadingForWrite(from_degrees);
    const float to = NormalizeWizardActorHeadingForWrite(to_degrees);
    float delta = to - from;
    while (delta > 180.0f) {
        delta -= 360.0f;
    }
    while (delta < -180.0f) {
        delta += 360.0f;
    }
    return delta;
}

bool RefreshNativeRemoteParticipantTransformTarget(ParticipantEntityBinding* binding) {
    if (binding == nullptr || binding->bot_id == 0) {
        return false;
    }

    const auto runtime_state = multiplayer::SnapshotRuntimeState();
    const auto* participant = multiplayer::FindParticipant(runtime_state, binding->bot_id);
    if (participant == nullptr || !multiplayer::IsRemoteParticipant(*participant)) {
        binding->replicated_transform_valid = false;
        return false;
    }

    binding->controller_kind = participant->controller_kind;
    if (!multiplayer::IsNativeControlledParticipant(*participant) ||
        !participant->runtime.transform_valid ||
        !std::isfinite(participant->runtime.position_x) ||
        !std::isfinite(participant->runtime.position_y) ||
        !std::isfinite(participant->runtime.heading)) {
        binding->replicated_transform_valid = false;
        return false;
    }

    binding->replicated_transform_valid = true;
    binding->replicated_target_x = participant->runtime.position_x;
    binding->replicated_target_y = participant->runtime.position_y;
    binding->replicated_target_heading =
        NormalizeWizardActorHeadingForWrite(participant->runtime.heading);
    binding->replicated_transform_packet_ms = participant->last_packet_ms;
    return true;
}

bool NativeRemoteParticipantPlaybackTargetIsMoving(
    const ParticipantEntityBinding* binding,
    uintptr_t actor_address) {
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_transform_valid) {
        return false;
    }

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return false;
    }

    const float dx = binding->replicated_target_x - x;
    const float dy = binding->replicated_target_y - y;
    const float heading_delta =
        ShortestHeadingDeltaDegrees(heading, binding->replicated_target_heading);
    return dx * dx + dy * dy > 2.25f || std::fabs(heading_delta) > 2.0f;
}

NativeRemotePlaybackResult ApplyNativeRemoteParticipantPlayback(
    ParticipantEntityBinding* binding,
    uintptr_t actor_address,
    std::uint64_t now_ms) {
    NativeRemotePlaybackResult result;
    if (!IsNativeRemoteParticipantBinding(binding) ||
        actor_address == 0 ||
        !binding->replicated_transform_valid) {
        return result;
    }
    result.applicable = true;

    float x = 0.0f;
    float y = 0.0f;
    float heading = 0.0f;
    if (!TryReadFiniteFloatField(actor_address, kActorPositionXOffset, &x) ||
        !TryReadFiniteFloatField(actor_address, kActorPositionYOffset, &y) ||
        !TryReadFiniteFloatField(actor_address, kActorHeadingOffset, &heading)) {
        return result;
    }

    const float dx = binding->replicated_target_x - x;
    const float dy = binding->replicated_target_y - y;
    const float distance_sq = dx * dx + dy * dy;
    const float distance = std::sqrt(distance_sq);
    const float heading_delta =
        ShortestHeadingDeltaDegrees(heading, binding->replicated_target_heading);
    result.moving = distance > 1.5f || std::fabs(heading_delta) > 2.0f;

    constexpr float kRemoteSnapDistance = 360.0f;
    constexpr float kRemoteSettleDistance = 0.75f;

    float next_x = binding->replicated_target_x;
    float next_y = binding->replicated_target_y;
    float next_heading = binding->replicated_target_heading;
    if (distance > kRemoteSettleDistance && distance < kRemoteSnapDistance) {
        std::uint64_t elapsed_ms = 50;
        if (binding->replicated_transform_playback_ms != 0 &&
            now_ms >= binding->replicated_transform_playback_ms) {
            elapsed_ms = now_ms - binding->replicated_transform_playback_ms;
        }
        elapsed_ms = (std::min<std::uint64_t>)(elapsed_ms, 100);

        float alpha = static_cast<float>(elapsed_ms) / 50.0f * 0.45f;
        alpha = (std::clamp)(alpha, 0.25f, distance > 120.0f ? 0.85f : 0.65f);
        next_x = x + dx * alpha;
        next_y = y + dy * alpha;
    }

    auto& memory = ProcessMemory::Instance();
    if (std::fabs(next_x - x) > 0.01f || std::fabs(next_y - y) > 0.01f) {
        result.wrote_position =
            memory.TryWriteField(actor_address, kActorPositionXOffset, next_x) &&
            memory.TryWriteField(actor_address, kActorPositionYOffset, next_y);
        if (result.wrote_position) {
            const auto rebind_actor_address = memory.ResolveGameAddressOrZero(kWorldCellGridRebindActor);
            uintptr_t world_address = 0;
            if (rebind_actor_address != 0 &&
                memory.TryReadField(actor_address, kActorOwnerOffset, &world_address) &&
                world_address != 0) {
                DWORD rebind_exception_code = 0;
                (void)CallWorldCellGridRebindActorSafe(
                    rebind_actor_address,
                    world_address,
                    actor_address,
                    &rebind_exception_code);
            }
        }
    }
    ApplyWizardActorFacingState(actor_address, next_heading);
    binding->replicated_transform_playback_ms = now_ms;
    PublishParticipantGameplaySnapshot(*binding);
    return result;
}
