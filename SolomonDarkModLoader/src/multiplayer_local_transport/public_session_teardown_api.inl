bool IsLocalTransportEnabled() {
    return g_local_transport_enabled.load(
        std::memory_order_acquire);
}

bool IsLocalTransportHost() {
    return g_local_transport_host.load(
        std::memory_order_acquire);
}

bool IsLocalTransportClient() {
    return g_local_transport.initialized &&
        !g_local_transport.is_host;
}

void RequestImmediateRunWorldSnapshot() {
    if (!g_local_transport_host.load(std::memory_order_acquire)) {
        return;
    }
    g_immediate_run_world_snapshot_requested.store(
        true,
        std::memory_order_release);
    SendWorldSnapshot(
        static_cast<std::uint64_t>(GetTickCount64()));
}

void RequestLocalTransportTeardown(
    SessionGoodbyeReason reason,
    bool notify_peers) {
    if (!g_local_transport_enabled.load(
            std::memory_order_acquire) ||
        !g_local_transport_is_udp.load(
            std::memory_order_acquire)) {
        g_local_transport_teardown_complete.store(
            true,
            std::memory_order_release);
        return;
    }

    g_local_teardown_reason.store(
        static_cast<std::uint8_t>(reason),
        std::memory_order_release);
    g_local_teardown_notify_peers.store(
        notify_peers,
        std::memory_order_release);
    g_local_transport_teardown_complete.store(
        false,
        std::memory_order_release);
    g_local_teardown_requested.store(
        true,
        std::memory_order_release);
}

bool IsLocalTransportTeardownComplete() {
    return g_local_transport_teardown_complete.load(
        std::memory_order_acquire);
}
