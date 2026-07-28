using NativeInclusiveRandomIntegerFn =
    std::int32_t(__thiscall*)(
        void* self,
        std::int32_t minimum,
        std::int32_t maximum);
using NativeRangeRandomIntegerFn =
    std::int32_t(__thiscall*)(
        void* self,
        std::int32_t range,
        char sign_mode);
using PlayerHitPresentationBlockedFn =
    std::uint8_t(__thiscall*)(void* self);

bool HasNativeActorHitReactionLayout() {
    return kActorHitReactionPrimaryAlphaOffset != 0 &&
           kActorHitReactionIntensityOffset ==
               kActorHitReactionPrimaryAlphaOffset + sizeof(float) &&
           kActorHitReactionSecondaryAlphaOffset ==
               kActorHitReactionIntensityOffset + sizeof(float) &&
           kActorHitReactionColorRedOffset ==
               kActorHitReactionSecondaryAlphaOffset + sizeof(float) &&
           kActorHitReactionColorGreenOffset ==
               kActorHitReactionColorRedOffset + sizeof(float) &&
           kActorHitReactionColorBlueOffset ==
               kActorHitReactionColorGreenOffset + sizeof(float) &&
           kActorHitReactionColorAlphaOffset ==
               kActorHitReactionColorBlueOffset + sizeof(float);
}

bool TryReadNativeActorHitReactionState(
    uintptr_t actor_address,
    multiplayer::ParticipantHitReactionState* state) {
    if (state == nullptr) {
        return false;
    }
    *state = {};
    return actor_address != 0 &&
           HasNativeActorHitReactionLayout() &&
           ProcessMemory::Instance().TryRead(
               actor_address +
                   kActorHitReactionPrimaryAlphaOffset,
               state,
               sizeof(*state)) &&
           multiplayer::IsValidParticipantHitReactionState(
               *state);
}

bool TryWriteNativeActorHitReactionState(
    uintptr_t actor_address,
    const multiplayer::ParticipantHitReactionState& state) {
    return actor_address != 0 &&
           HasNativeActorHitReactionLayout() &&
           multiplayer::IsValidParticipantHitReactionState(state) &&
           ProcessMemory::Instance().TryWrite(
               actor_address +
                   kActorHitReactionPrimaryAlphaOffset,
               &state,
               sizeof(state));
}

bool TryResolveNativeHitFeedbackRng(
    uintptr_t* rng_state_address) {
    if (rng_state_address == nullptr) {
        return false;
    }
    *rng_state_address = 0;
    auto& memory = ProcessMemory::Instance();
    const auto rng_global_address =
        memory.ResolveGameAddressOrZero(
            kNativeGlobalRngStateGlobal);
    return rng_global_address != 0 &&
           memory.TryReadValue(
               rng_global_address,
               rng_state_address) &&
           *rng_state_address != 0;
}

bool TryNativeHitFeedbackInclusiveRandom(
    std::int32_t minimum,
    std::int32_t maximum,
    std::int32_t* value) {
    if (value == nullptr ||
        minimum > maximum ||
        kNativeInclusiveRandomInteger == 0) {
        return false;
    }
    uintptr_t rng_state_address = 0;
    const auto random_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kNativeInclusiveRandomInteger);
    if (random_address == 0 ||
        !TryResolveNativeHitFeedbackRng(&rng_state_address)) {
        return false;
    }
    __try {
        const auto random_integer =
            reinterpret_cast<NativeInclusiveRandomIntegerFn>(
                random_address);
        *value = random_integer(
            reinterpret_cast<void*>(rng_state_address),
            minimum,
            maximum);
        return *value >= minimum && *value <= maximum;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryNativeHitFeedbackRangeRandom(
    std::int32_t range,
    std::int32_t* value) {
    if (value == nullptr ||
        range <= 0 ||
        kNativeRngInteger == 0) {
        return false;
    }
    uintptr_t rng_state_address = 0;
    const auto random_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kNativeRngInteger);
    if (random_address == 0 ||
        !TryResolveNativeHitFeedbackRng(&rng_state_address)) {
        return false;
    }
    __try {
        const auto random_integer =
            reinterpret_cast<NativeRangeRandomIntegerFn>(
                random_address);
        *value = random_integer(
            reinterpret_cast<void*>(rng_state_address),
            range,
            0);
        return *value >= 0 && *value < range;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool TryReadNativeHitFeedbackTiming(
    std::int32_t* current_tick,
    std::int32_t* deadline) {
    if (current_tick == nullptr ||
        deadline == nullptr) {
        return false;
    }
    auto& memory = ProcessMemory::Instance();
    const auto frame_counter_address =
        memory.ResolveGameAddressOrZero(
            kHitFeedbackFrameCounterGlobal);
    const auto deadline_address =
        memory.ResolveGameAddressOrZero(
            kHitFeedbackDeadlineGlobal);
    return frame_counter_address != 0 &&
           deadline_address != 0 &&
           memory.TryReadValue(
               frame_counter_address,
               current_tick) &&
           memory.TryReadValue(
               deadline_address,
               deadline);
}

bool TryWriteNativeHitFeedbackDeadline(
    std::int32_t deadline) {
    const auto deadline_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kHitFeedbackDeadlineGlobal);
    return deadline_address != 0 &&
           ProcessMemory::Instance().TryWriteValue(
               deadline_address,
               deadline);
}

bool TryIsNativeHitFeedbackPresentationBlocked(
    bool* blocked) {
    if (blocked == nullptr ||
        kPlayerHitPresentationBlocked == 0 ||
        kHitFeedbackPresentationStateGlobal == 0) {
        return false;
    }
    const auto function_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kPlayerHitPresentationBlocked);
    const auto state_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kHitFeedbackPresentationStateGlobal);
    if (function_address == 0 || state_address == 0) {
        return false;
    }
    __try {
        const auto predicate =
            reinterpret_cast<PlayerHitPresentationBlockedFn>(
                function_address);
        *blocked = predicate(
            reinterpret_cast<void*>(state_address)) != 0;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool RequeueLocalPlayerHitFeedback(
    const PendingLocalPlayerHitFeedback& request,
    std::string* error_message) {
    return QueueLocalPlayerHitFeedback(
        request.authority_participant_id,
        request.target_participant_id,
        request.run_nonce,
        request.event_sequence,
        request.health_before,
        request.health_after,
        request.health_maximum,
        request.hit_reaction,
        request.feedback_flags,
        error_message);
}

void ExecuteQueuedLocalHitFeedbackActions(
    const std::vector<PendingLocalPlayerHitFeedback>& requests) {
    for (const auto& request : requests) {
        const auto runtime_state =
            multiplayer::SnapshotRuntimeState();
        const auto* local =
            multiplayer::FindLocalParticipant(runtime_state);
        const auto local_transport_participant_id =
            multiplayer::GetLocalTransportParticipantId();
        if (local == nullptr ||
            local_transport_participant_id == 0 ||
            local_transport_participant_id !=
                request.target_participant_id ||
            !local->runtime.valid ||
            !local->runtime.in_run ||
            local->runtime.run_nonce != request.run_nonce) {
            Log(
                "[hit-feedback] event=discard "
                "event_sequence=" +
                std::to_string(request.event_sequence) +
                " reason=target_run_changed "
                "request_target_participant_id=" +
                std::to_string(request.target_participant_id) +
                " request_run_nonce=" +
                std::to_string(request.run_nonce) +
                " local_transport_participant_id=" +
                std::to_string(local_transport_participant_id) +
                " local_found=" +
                std::to_string(local != nullptr ? 1 : 0) +
                " local_runtime_slot_id=" +
                std::to_string(
                    local == nullptr ? 0 : local->participant_id) +
                " local_runtime_valid=" +
                std::to_string(
                    local != nullptr && local->runtime.valid ? 1 : 0) +
                " local_in_run=" +
                std::to_string(
                    local != nullptr && local->runtime.in_run ? 1 : 0) +
                " local_run_nonce=" +
                std::to_string(
                    local == nullptr ? 0 : local->runtime.run_nonce));
            continue;
        }

        SDModPlayerState player_state;
        if (!TryGetPlayerState(&player_state) ||
            !player_state.valid ||
            player_state.actor_address == 0) {
            std::string requeue_error;
            const bool requeued =
                RequeueLocalPlayerHitFeedback(
                    request,
                    &requeue_error);
            Log(
                "[hit-feedback] event=owner_actor_pending "
                "event_sequence=" +
                std::to_string(request.event_sequence) +
                " requeued=" +
                std::to_string(requeued ? 1 : 0) +
                (requeue_error.empty()
                     ? std::string{}
                     : " error=" + requeue_error));
            continue;
        }

        auto& memory = ProcessMemory::Instance();
        std::uint8_t terminal_state = 0;
        const bool actor_live =
            kActorTerminalDispatchPendingOffset != 0 &&
            memory.TryReadField(
                player_state.actor_address,
                kActorTerminalDispatchPendingOffset,
                &terminal_state) &&
            terminal_state == 0;

        const bool actor_reaction_written =
            actor_live &&
            TryWriteNativeActorHitReactionState(
                player_state.actor_address,
                request.hit_reaction);

        bool ouch_requested = false;
        std::int32_t ouch_index = -1;
        float ouch_gain = 0.0f;
        std::int32_t current_tick = 0;
        std::int32_t deadline = 0;
        const bool ouch_lane_eligible =
            (request.feedback_flags &
             multiplayer::
                 ParticipantHitFeedbackFlagOuchEligible) != 0;
        bool presentation_blocked = true;
        if (actor_live &&
            ouch_lane_eligible &&
            TryReadNativeHitFeedbackTiming(
                &current_tick,
                &deadline) &&
            current_tick > deadline &&
            TryIsNativeHitFeedbackPresentationBlocked(
                &presentation_blocked) &&
            !presentation_blocked) {
            std::int32_t delay = 0;
            if (TryNativeHitFeedbackInclusiveRandom(
                    20,
                    60,
                    &delay)) {
                const float health_factor = (std::clamp)(
                    (request.health_after - 25.0f) / 20.0f,
                    0.0f,
                    1.0f);
                const auto initial_deadline =
                    current_tick + delay;
                const auto scaled_deadline =
                    static_cast<std::int32_t>(
                        std::lround(
                            health_factor *
                            static_cast<float>(
                                initial_deadline)));
                (void)TryWriteNativeHitFeedbackDeadline(
                    scaled_deadline);
                ouch_requested =
                    TryDispatchNativeWizardOuchSound(
                        player_state.actor_address,
                        request.health_after,
                        request.target_participant_id,
                        request.event_sequence,
                        &ouch_index,
                        &ouch_gain);
            }
        }

        bool red_written = false;
        float red_value = 0.0f;
        if (actor_live &&
            request.health_after < 30.0f &&
            kArenaHitFeedbackAlphaOffset != 0) {
            uintptr_t arena_address = 0;
            if (memory.TryReadField(
                    player_state.actor_address,
                    kActorOwnerOffset,
                    &arena_address) &&
                arena_address != 0) {
                red_value =
                    (1.0f -
                     (request.health_after / 40.0f)) *
                    0.7f;
                red_written = memory.TryWriteField(
                    arena_address,
                    kArenaHitFeedbackAlphaOffset,
                    red_value);
                if (red_written) {
                    std::int32_t jitter = 0;
                    if (TryNativeHitFeedbackRangeRandom(
                            11,
                            &jitter)) {
                        if (!TryReadNativeHitFeedbackTiming(
                                &current_tick,
                                &deadline)) {
                            current_tick = 0;
                        }
                        (void)TryWriteNativeHitFeedbackDeadline(
                            current_tick + 20 + jitter);
                    }
                }
            }
        }

        Log(
            "[hit-feedback] event=replay "
            "authority_participant_id=" +
            std::to_string(request.authority_participant_id) +
            " target_participant_id=" +
            std::to_string(request.target_participant_id) +
            " run_nonce=" +
            std::to_string(request.run_nonce) +
            " event_sequence=" +
            std::to_string(request.event_sequence) +
            " health_before=" +
            std::to_string(request.health_before) +
            " health_after=" +
            std::to_string(request.health_after) +
            " health_maximum=" +
            std::to_string(request.health_maximum) +
            " actor_live=" +
            std::to_string(actor_live ? 1 : 0) +
            " actor_reaction_written=" +
            std::to_string(
                actor_reaction_written ? 1 : 0) +
            " hit_primary_alpha=" +
            std::to_string(
                request.hit_reaction.primary_alpha) +
            " hit_intensity=" +
            std::to_string(request.hit_reaction.intensity) +
            " hit_secondary_alpha=" +
            std::to_string(
                request.hit_reaction.secondary_alpha) +
            " hit_color_red=" +
            std::to_string(request.hit_reaction.color_red) +
            " hit_color_green=" +
            std::to_string(request.hit_reaction.color_green) +
            " hit_color_blue=" +
            std::to_string(request.hit_reaction.color_blue) +
            " hit_color_alpha=" +
            std::to_string(request.hit_reaction.color_alpha) +
            " ouch_eligible=" +
            std::to_string(ouch_lane_eligible ? 1 : 0) +
            " ouch_requested=" +
            std::to_string(ouch_requested ? 1 : 0) +
            " ouch_index=" +
            std::to_string(ouch_index) +
            " ouch_gain=" +
            std::to_string(ouch_gain) +
            " red_written=" +
            std::to_string(red_written ? 1 : 0) +
            " red_value=" +
            std::to_string(red_value));
    }
}
