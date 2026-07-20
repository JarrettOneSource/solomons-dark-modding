bool QueueHubOpenService(
    std::string_view service_name,
    std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (!g_gameplay_keyboard_injection.initialized) {
        if (error_message != nullptr) {
            *error_message = "Gameplay action pump is not initialized.";
        }
        return false;
    }

    HubServiceKind kind = HubServiceKind::None;
    if (!TryParseHubServiceName(service_name, &kind)) {
        if (error_message != nullptr) {
            *error_message =
                "Unknown hub service. Expected luthacus_storage, fomentius, or hagatha.";
        }
        return false;
    }

    HubServiceDispatchContext context;
    if (!TryBuildHubServiceDispatchContext(kind, &context, error_message)) {
        return false;
    }

    std::uint32_t expected = 0;
    if (!g_gameplay_keyboard_injection.pending_hub_service_request
             .compare_exchange_strong(
                 expected,
                 static_cast<std::uint32_t>(kind),
                 std::memory_order_acq_rel,
                 std::memory_order_acquire)) {
        if (error_message != nullptr) {
            *error_message = "Another hub service request is already pending.";
        }
        return false;
    }
    Log(
        "hub.open_service: queued service=" +
        std::string(HubServiceName(kind)) +
        " gameplay=" + HexString(context.gameplay_address));
    return true;
}

bool TryGetHubSurfaceState(
    SDModHubSurfaceState* state,
    std::string* error_message) {
    return TryReadHubSurfaceStateInternal(state, error_message);
}
