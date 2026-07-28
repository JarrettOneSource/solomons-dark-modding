struct RemoteParticipantHitFeedbackCapture {
    bool applicable = false;
    std::uint64_t participant_id = 0;
    std::uint32_t run_nonce = 0;
    uintptr_t actor_address = 0;
    uintptr_t progression_address = 0;
    float health_before = 0.0f;
    float health_maximum = 0.0f;
    multiplayer::ParticipantHitReactionState hit_reaction{};
    bool ouch_eligible = false;
};

thread_local std::uint32_t g_player_damage_resolver_depth = 0;

bool TryPrepareRemoteParticipantHitFeedback(
    uintptr_t actor_address,
    RemoteParticipantHitFeedbackCapture* capture) {
    if (capture == nullptr) {
        return false;
    }
    *capture = RemoteParticipantHitFeedbackCapture{};
    if (!multiplayer::IsLocalTransportHost() ||
        actor_address == 0) {
        return true;
    }

    std::uint64_t participant_id = 0;
    {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        const auto* binding =
            FindParticipantEntityForActor(actor_address);
        if (binding == nullptr ||
            !IsNativeRemoteParticipantBinding(binding) ||
            binding->bot_id == 0) {
            return true;
        }
        participant_id = binding->bot_id;
    }

    const auto runtime_state =
        multiplayer::SnapshotRuntimeState();
    const auto* participant =
        multiplayer::FindParticipant(
            runtime_state,
            participant_id);
    if (participant == nullptr ||
        !multiplayer::IsRemoteParticipant(*participant) ||
        !multiplayer::IsNativeControlledParticipant(*participant) ||
        !participant->runtime.valid ||
        !participant->runtime.in_run ||
        participant->runtime.run_nonce == 0) {
        return true;
    }

    uintptr_t progression_address = 0;
    float health_before = 0.0f;
    float health_maximum = 0.0f;
    if (!TryResolveActorProgressionRuntime(
            actor_address,
            &progression_address) ||
        progression_address == 0 ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionHpOffset,
            &health_before) ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxHpOffset,
            &health_maximum) ||
        health_before <= 0.0f ||
        health_maximum <= 0.0f ||
        health_before > health_maximum) {
        return false;
    }

    capture->applicable = true;
    capture->participant_id = participant_id;
    capture->run_nonce = participant->runtime.run_nonce;
    capture->actor_address = actor_address;
    capture->progression_address = progression_address;
    capture->health_before = health_before;
    capture->health_maximum = health_maximum;
    return true;
}

void PublishRemoteParticipantHitFeedback(
    const RemoteParticipantHitFeedbackCapture& capture) {
    if (!capture.applicable ||
        capture.participant_id == 0 ||
        capture.actor_address == 0 ||
        capture.progression_address == 0) {
        return;
    }

    {
        std::lock_guard<std::recursive_mutex> lock(
            g_participant_entities_mutex);
        const auto* binding =
            FindParticipantEntityForActor(
                capture.actor_address);
        if (binding == nullptr ||
            binding->bot_id != capture.participant_id ||
            !IsNativeRemoteParticipantBinding(binding)) {
            return;
        }
    }

    uintptr_t progression_address = 0;
    float health_after = 0.0f;
    float health_maximum = 0.0f;
    if (!TryResolveActorProgressionRuntime(
            capture.actor_address,
            &progression_address) ||
        progression_address != capture.progression_address ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionHpOffset,
            &health_after) ||
        !TryReadFiniteFloatField(
            progression_address,
            kProgressionMaxHpOffset,
            &health_maximum) ||
        health_after >= capture.health_before ||
        health_after <= 0.0f ||
        health_maximum <= 0.0f) {
        return;
    }

    if (!multiplayer::QueueHostParticipantHitFeedback(
        capture.participant_id,
        capture.run_nonce,
        capture.health_before,
            health_after,
            health_maximum,
            capture.hit_reaction,
            capture.ouch_eligible)) {
        Log(
            "[hit-feedback] event=authority_queue_failed "
            "target_participant_id=" +
            std::to_string(capture.participant_id) +
            " health_before=" +
            std::to_string(capture.health_before) +
            " health_after=" +
            std::to_string(health_after));
    }
}

bool TryReadResolvedHitFeedbackLanes(
    std::array<float, 3>* lanes) {
    if (lanes == nullptr) {
        return false;
    }
    *lanes = {};
    const auto primary_address =
        g_gameplay_keyboard_injection.damage_context_primary_address;
    if (primary_address == 0 ||
        g_gameplay_keyboard_injection.damage_context_secondary_address !=
            primary_address + sizeof(float)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    for (std::size_t index = 0; index < lanes->size(); ++index) {
        if (!memory.TryReadValue(
                primary_address + index * sizeof(float),
                &(*lanes)[index]) ||
            !std::isfinite((*lanes)[index])) {
            return false;
        }
    }
    return true;
}

std::uint32_t __fastcall HookPlayerActorDamageResolver(
    void* self,
    void* /*unused_edx*/) {
    const auto original =
        GetX86HookTrampoline<PlayerActorMagicDamageFn>(
            g_gameplay_keyboard_injection
                .player_actor_damage_resolver_hook);
    if (original == nullptr) {
        return 0;
    }

    const auto actor_address =
        reinterpret_cast<uintptr_t>(self);
    RemoteParticipantHitFeedbackCapture hit_feedback;
    const bool owns_event_boundary =
        g_player_damage_resolver_depth == 0;
    g_player_damage_resolver_depth += 1;
    if (owns_event_boundary &&
        !TryPrepareRemoteParticipantHitFeedback(
            actor_address,
            &hit_feedback)) {
        Log(
            "[hit-feedback] event=authority_capture_failed "
            "actor=" + HexString(actor_address));
    }

    const auto result = original(self);
    g_player_damage_resolver_depth -= 1;
    if (!owns_event_boundary ||
        !hit_feedback.applicable) {
        return result;
    }

    std::array<float, 3> lanes{};
    if (!TryReadResolvedHitFeedbackLanes(&lanes) ||
        lanes[2] != 0.0f) {
        return result;
    }
    hit_feedback.ouch_eligible =
        lanes[0] + lanes[1] > 0.0f;
    if (!TryReadNativeActorHitReactionState(
            actor_address,
            &hit_feedback.hit_reaction)) {
        Log(
            "[hit-feedback] "
            "event=authority_hit_reaction_capture_failed "
            "actor=" + HexString(actor_address));
        return result;
    }
    PublishRemoteParticipantHitFeedback(hit_feedback);
    return result;
}
