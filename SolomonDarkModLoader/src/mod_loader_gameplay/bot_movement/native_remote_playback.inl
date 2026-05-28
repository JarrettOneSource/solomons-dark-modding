struct NativeRemotePlaybackResult {
    bool applicable = false;
    bool moving = false;
    bool wrote_position = false;
};

constexpr std::uint64_t kRemoteTransformInterpolationDelayMs = 120;

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

bool RefreshNativeRemoteParticipantTransformTarget(
    ParticipantEntityBinding* binding,
    std::uint64_t now_ms) {
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
        !participant->runtime.transform_valid) {
        binding->replicated_transform_valid = false;
        return false;
    }

    multiplayer::ParticipantTransformSample transform_sample;
    if (!multiplayer::TrySampleParticipantTransform(
            *participant,
            now_ms,
            kRemoteTransformInterpolationDelayMs,
            &transform_sample)) {
        binding->replicated_transform_valid = false;
        return false;
    }

    binding->replicated_transform_valid = true;
    binding->replicated_target_x = transform_sample.position_x;
    binding->replicated_target_y = transform_sample.position_y;
    binding->replicated_target_heading =
        NormalizeWizardActorHeadingForWrite(transform_sample.heading);
    binding->replicated_transform_packet_ms = transform_sample.received_ms;
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
    constexpr float kRemoteSettleDistance = 0.05f;

    const bool large_discontinuity = distance > kRemoteSnapDistance;
    const float position_write_distance = large_discontinuity ? 0.0f : kRemoteSettleDistance;
    const float next_x = binding->replicated_target_x;
    const float next_y = binding->replicated_target_y;
    const float next_heading = binding->replicated_target_heading;

    auto& memory = ProcessMemory::Instance();
    if (distance > position_write_distance) {
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
