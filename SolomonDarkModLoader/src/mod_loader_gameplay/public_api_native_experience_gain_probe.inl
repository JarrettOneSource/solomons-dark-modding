bool QueueNativeExperienceGainProbe(
    float amount,
    bool apply_native_scaling,
    std::uint64_t* request_serial,
    std::string* error_message) {
    if (request_serial != nullptr) {
        *request_serial = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized ||
        !std::isfinite(amount) ||
        amount < 0.0f ||
        amount > 1'000'000.0f) {
        if (error_message != nullptr) {
            *error_message = "Native XP probe requires an initialized action pump and amount within 0..1000000.";
        }
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    auto& pending =
        g_gameplay_keyboard_injection.pending_native_experience_gain_probes;
    if (pending.size() >= kQueuedGameplayWorldActionLimit) {
        if (error_message != nullptr) {
            *error_message = "The native XP probe queue is full.";
        }
        return false;
    }

    PendingNativeExperienceGainProbe request{};
    request.request_serial = g_gameplay_keyboard_injection
                                 .next_native_experience_gain_probe_serial++;
    if (g_gameplay_keyboard_injection.next_native_experience_gain_probe_serial == 0) {
        g_gameplay_keyboard_injection.next_native_experience_gain_probe_serial = 1;
    }
    request.amount = amount;
    request.apply_native_scaling = apply_native_scaling;
    pending.push_back(request);
    if (request_serial != nullptr) {
        *request_serial = request.request_serial;
    }
    return true;
}

bool GetNativeExperienceGainProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* xp_before,
    float* xp_after,
    std::uint32_t* exception_code,
    std::string* error_message) {
    if (completed != nullptr) {
        *completed = false;
    }
    if (success != nullptr) {
        *success = false;
    }
    if (xp_before != nullptr) {
        *xp_before = 0.0f;
    }
    if (xp_after != nullptr) {
        *xp_after = 0.0f;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (request_serial == 0) {
        return false;
    }

    std::lock_guard<std::mutex> lock(
        g_gameplay_keyboard_injection.pending_gameplay_world_actions_mutex);
    const auto& result =
        g_gameplay_keyboard_injection.native_experience_gain_probe_result;
    if (result.request_serial != request_serial) {
        return true;
    }
    if (completed != nullptr) {
        *completed = true;
    }
    if (success != nullptr) {
        *success = result.success;
    }
    if (xp_before != nullptr) {
        *xp_before = result.xp_before;
    }
    if (xp_after != nullptr) {
        *xp_after = result.xp_after;
    }
    if (exception_code != nullptr) {
        *exception_code = result.exception_code;
    }
    if (error_message != nullptr) {
        *error_message = result.error;
    }
    return true;
}
