float NormalizeHeadingDegrees(float heading_degrees) {
    if (!std::isfinite(heading_degrees)) {
        return 0.0f;
    }

    while (heading_degrees < 0.0f) {
        heading_degrees += 360.0f;
    }
    while (heading_degrees >= 360.0f) {
        heading_degrees -= 360.0f;
    }
    return heading_degrees;
}

void DeriveControllerMotionFromTransform(
    PendingBotMovementIntent* intent,
    bool have_transform,
    float current_x,
    float current_y,
    float current_heading) {
    if (intent == nullptr) {
        return;
    }

    intent->direction_x = 0.0f;
    intent->direction_y = 0.0f;
    intent->distance_to_target = 0.0f;
    if (!intent->desired_heading_valid && have_transform) {
        intent->desired_heading_valid = true;
        intent->desired_heading = current_heading;
    }

    if (intent->state == BotControllerState::Moving) {
        if (!intent->has_target) {
            intent->state = BotControllerState::Idle;
            return;
        }
        if (!have_transform) {
            return;
        }

        const auto delta_x = intent->target_x - current_x;
        const auto delta_y = intent->target_y - current_y;
        const auto distance = std::sqrt((delta_x * delta_x) + (delta_y * delta_y));
        intent->distance_to_target = distance;
        if (distance <= kBotArrivalThreshold) {
            intent->state = BotControllerState::Idle;
            intent->has_target = false;
            intent->target_x = current_x;
            intent->target_y = current_y;
            intent->distance_to_target = 0.0f;
            intent->desired_heading_valid = true;
            intent->desired_heading = current_heading;
            return;
        }

        // Final-destination ownership now lives in runtime, but actual path
        // generation and per-step steering live on the gameplay thread.
        // Runtime keeps the destination and the remaining distance current so
        // gameplay can rebuild paths when the intent revision changes.
        intent->direction_x = 0.0f;
        intent->direction_y = 0.0f;
        intent->desired_heading_valid = true;
        intent->desired_heading = current_heading;
        return;
    }

    if (intent->state != BotControllerState::Attacking) {
        intent->state = BotControllerState::Idle;
    }
}
