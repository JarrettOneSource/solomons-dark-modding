bool TryExtrapolateParticipantTransform(
    const ParticipantInfo& participant,
    std::uint64_t sample_ms,
    const ParticipantTransformSample& latest,
    ParticipantTransformSample* sample) {
    if (sample == nullptr ||
        sample_ms <= latest.received_ms ||
        participant.transform_history.size() < 2) {
        return false;
    }

    const auto intent_x = participant.runtime.movement_intent_x;
    const auto intent_y = participant.runtime.movement_intent_y;
    const auto intent_magnitude_squared =
        intent_x * intent_x + intent_y * intent_y;
    if (!std::isfinite(intent_magnitude_squared) ||
        intent_magnitude_squared <= 0.000001f) {
        return false;
    }

    const ParticipantTransformSample* previous = nullptr;
    for (auto it = participant.transform_history.rbegin();
         it != participant.transform_history.rend();
         ++it) {
        if (!it->valid ||
            it->received_ms >= latest.received_ms ||
            it->run_nonce != latest.run_nonce ||
            !SameParticipantSceneIntent(
                it->scene_intent,
                latest.scene_intent)) {
            continue;
        }
        previous = &(*it);
        break;
    }
    if (previous == nullptr) {
        return false;
    }

    const auto arrival_interval_ms =
        latest.received_ms - previous->received_ms;
    if (arrival_interval_ms == 0) {
        return false;
    }
    const auto velocity_x =
        (latest.position_x - previous->position_x) /
        static_cast<float>(arrival_interval_ms);
    const auto velocity_y =
        (latest.position_y - previous->position_y) /
        static_cast<float>(arrival_interval_ms);
    if (!std::isfinite(velocity_x) ||
        !std::isfinite(velocity_y) ||
        velocity_x * intent_x + velocity_y * intent_y <= 0.0f) {
        return false;
    }

    const auto extrapolation_ms = (std::min)(
        sample_ms - latest.received_ms,
        arrival_interval_ms);
    *sample = latest;
    sample->position_x +=
        velocity_x * static_cast<float>(extrapolation_ms);
    sample->position_y +=
        velocity_y * static_cast<float>(extrapolation_ms);
    return true;
}
