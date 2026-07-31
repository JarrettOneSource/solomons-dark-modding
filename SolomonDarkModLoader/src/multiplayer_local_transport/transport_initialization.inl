bool InitializeLocalTransport() {
    g_local_transport_enabled.store(false, std::memory_order_release);
    g_local_transport_is_udp.store(false, std::memory_order_release);
    g_local_teardown_requested.store(false, std::memory_order_release);
    g_local_transport_teardown_complete.store(
        true,
        std::memory_order_release);
    g_local_transport_host.store(false, std::memory_order_release);
    g_local_terminated_run_nonce.store(
        0,
        std::memory_order_release);
    ResetParticipantHitFeedbackState();
    ResetRunGameOverState("transport_initialize");
    ResetRunLoadingBarrierState("transport_initialize");
    if (!ConfigureLocalTransport()) {
        g_local_transport_authority_participant_id.store(
            0,
            std::memory_order_release);
        return !g_local_transport.configured;
    }
    g_local_transport_authority_participant_id.store(
        0,
        std::memory_order_release);
    ResetSteamGameplayQueues();

    g_local_transport.local_session_nonce =
        GenerateTransportSessionNonce();
    if (g_local_transport.backend ==
        GameplayTransportBackend::Steam) {
        if (g_local_transport.local_peer_id == 0) {
            Log(
                "Multiplayer Steam transport requested without an "
                "initialized Steam identity.");
            g_local_transport = LocalTransportState{};
            return false;
        }
        std::string death_hook_error;
        if (!InitializeLocalDeathProgressionTickHook(
                &death_hook_error)) {
            Log(
                "Multiplayer Steam transport could not install the "
                "dead-owner progression boundary: " +
                death_hook_error);
            g_local_transport = LocalTransportState{};
            return false;
        }
        g_local_transport.initialized = true;
        g_local_transport_enabled.store(
            true,
            std::memory_order_release);
        g_local_transport_host.store(
            g_local_transport.is_host,
            std::memory_order_release);
        if (g_local_transport.is_host) {
            g_local_transport_authority_participant_id.store(
                g_local_transport.local_peer_id,
                std::memory_order_release);
        }
        Log(
            "Multiplayer Steam gameplay transport initialized. role=" +
            std::string(
                g_local_transport.is_host ? "host" : "client") +
            " participant_id=" +
            std::to_string(g_local_transport.local_peer_id) +
            " session_nonce=" +
            std::to_string(
                g_local_transport.local_session_nonce));
        RecordNetworkTransportStart(
            "steam",
            g_local_transport.is_host ? "host" : "client",
            0,
            0,
            0);
        return true;
    }

    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        Log("Multiplayer local UDP: WSAStartup failed.");
        g_local_transport = LocalTransportState{};
        return false;
    }
    g_local_transport.winsock_initialized = true;

    g_local_transport.socket_handle =
        socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (g_local_transport.socket_handle == INVALID_SOCKET) {
        Log("Multiplayer local UDP: socket creation failed.");
        ShutdownLocalTransport();
        return false;
    }

    u_long nonblocking = 1;
    if (ioctlsocket(
            g_local_transport.socket_handle,
            FIONBIO,
            &nonblocking) != 0) {
        Log(
            "Multiplayer local UDP: failed to set non-blocking "
            "mode.");
        ShutdownLocalTransport();
        return false;
    }

    sockaddr_in bind_address{};
    bind_address.sin_family = AF_INET;
    const auto remote_address = ntohl(
        g_local_transport
            .configured_remote.udp_address.sin_addr.s_addr);
    const bool loopback_peer =
        (remote_address & 0xFF000000u) == 0x7F000000u;
    bind_address.sin_addr.s_addr = htonl(
        loopback_peer ? INADDR_LOOPBACK : INADDR_ANY);
    bind_address.sin_port = htons(g_local_transport.local_port);
    if (bind(
            g_local_transport.socket_handle,
            reinterpret_cast<const sockaddr*>(&bind_address),
            sizeof(bind_address)) != 0) {
        Log(
            "Multiplayer local UDP: bind failed on port " +
            std::to_string(g_local_transport.local_port) + ".");
        ShutdownLocalTransport();
        return false;
    }

    std::string death_hook_error;
    if (!InitializeLocalDeathProgressionTickHook(
            &death_hook_error)) {
        Log(
            "Multiplayer local UDP could not install the dead-owner "
            "progression boundary: " +
            death_hook_error);
        ShutdownLocalTransport();
        return false;
    }
    if (!StartLocalUdpIngressWorker(
            g_local_transport.socket_handle)) {
        Log(
            "Multiplayer local UDP: failed to start the "
            "ingress worker.");
        ShutdownLocalTransport();
        return false;
    }
    g_local_transport.initialized = true;
    g_local_transport_is_udp.store(
        true,
        std::memory_order_release);
    g_local_transport_enabled.store(
        true,
        std::memory_order_release);
    g_local_transport_host.store(
        g_local_transport.is_host,
        std::memory_order_release);
    g_local_transport_teardown_complete.store(
        false,
        std::memory_order_release);
    if (g_local_transport.is_host) {
        g_local_transport_authority_participant_id.store(
            g_local_transport.local_peer_id,
            std::memory_order_release);
    }
    std::ostringstream message;
    message << "Multiplayer local UDP transport initialized. role="
            << (g_local_transport.is_host ? "host" : "client")
            << " local_port=" << g_local_transport.local_port
            << " bind="
            << (loopback_peer ? "127.0.0.1" : "0.0.0.0")
            << " remote=" << g_local_transport.remote_host
            << ":" << g_local_transport.remote_port
            << " participant_id="
            << g_local_transport.local_peer_id
            << " session_nonce="
            << g_local_transport.local_session_nonce;
    Log(message.str());

    int receive_buffer_bytes = 0;
    int send_buffer_bytes = 0;
    int option_length = sizeof(receive_buffer_bytes);
    if (getsockopt(
            g_local_transport.socket_handle,
            SOL_SOCKET,
            SO_RCVBUF,
            reinterpret_cast<char*>(&receive_buffer_bytes),
            &option_length) != 0) {
        receive_buffer_bytes = -1;
    }
    option_length = sizeof(send_buffer_bytes);
    if (getsockopt(
            g_local_transport.socket_handle,
            SOL_SOCKET,
            SO_SNDBUF,
            reinterpret_cast<char*>(&send_buffer_bytes),
            &option_length) != 0) {
        send_buffer_bytes = -1;
    }
    RecordNetworkTransportStart(
        "local_udp",
        g_local_transport.is_host ? "host" : "client",
        g_local_transport.local_port,
        receive_buffer_bytes,
        send_buffer_bytes);
    return true;
}
