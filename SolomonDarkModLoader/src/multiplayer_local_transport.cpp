#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <WinSock2.h>
#include <Ws2tcpip.h>

#include "multiplayer_local_transport.h"

#include "logger.h"
#include "mod_loader.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <sstream>
#include <string>
#include <system_error>
#include <vector>

#pragma comment(lib, "Ws2_32.lib")

namespace sdmod::multiplayer {
namespace {

constexpr const char* kTransportEnvironmentVariable = "SDMOD_MULTIPLAYER_TRANSPORT";
constexpr const char* kRoleEnvironmentVariable = "SDMOD_MULTIPLAYER_ROLE";
constexpr const char* kLocalPortEnvironmentVariable = "SDMOD_MULTIPLAYER_LOCAL_PORT";
constexpr const char* kRemoteHostEnvironmentVariable = "SDMOD_MULTIPLAYER_REMOTE_HOST";
constexpr const char* kRemotePortEnvironmentVariable = "SDMOD_MULTIPLAYER_REMOTE_PORT";
constexpr const char* kParticipantIdEnvironmentVariable = "SDMOD_MULTIPLAYER_PARTICIPANT_ID";
constexpr const char* kPlayerNameEnvironmentVariable = "SDMOD_MULTIPLAYER_PLAYER_NAME";
constexpr std::uint16_t kDefaultHostPort = 47770;
constexpr std::uint16_t kDefaultClientPort = 47771;
constexpr std::uint64_t kLocalDevParticipantIdBase = 0x2000000000000000ull;
constexpr std::uint64_t kLocalTransportSendIntervalMs = 50;
constexpr int kMaxPacketsPerTick = 64;

struct LocalPeerEndpoint {
    sockaddr_in address{};
    std::uint64_t participant_id = 0;
    std::uint64_t last_packet_ms = 0;
};

struct LocalTransportState {
    bool configured = false;
    bool initialized = false;
    bool winsock_initialized = false;
    bool is_host = false;
    SOCKET socket_handle = INVALID_SOCKET;
    std::uint16_t local_port = 0;
    std::string remote_host;
    std::uint16_t remote_port = 0;
    bool configured_remote_valid = false;
    sockaddr_in configured_remote{};
    std::uint64_t local_peer_id = 0;
    std::uint64_t last_send_ms = 0;
    std::uint32_t next_sequence = 1;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_received = 0;
    std::vector<LocalPeerEndpoint> peers;
};

LocalTransportState g_local_transport;

std::string ReadEnvironmentVariable(const char* name) {
    char* value = nullptr;
    std::size_t value_length = 0;
    if (_dupenv_s(&value, &value_length, name) != 0 || value == nullptr) {
        return {};
    }

    std::string result(value);
    std::free(value);
    return result;
}

std::string ToLowerAscii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        if (ch >= 'A' && ch <= 'Z') {
            return static_cast<char>(ch - 'A' + 'a');
        }
        return static_cast<char>(ch);
    });
    return value;
}

bool TryParseUnsigned64(const std::string& text, std::uint64_t* value) {
    if (value == nullptr || text.empty()) {
        return false;
    }

    const char* first = text.data();
    const char* last = text.data() + text.size();
    int base = 10;
    if (text.size() > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        first += 2;
        base = 16;
    }

    std::uint64_t parsed = 0;
    const auto result = std::from_chars(first, last, parsed, base);
    if (result.ec != std::errc{} || result.ptr != last) {
        return false;
    }

    *value = parsed;
    return true;
}

std::uint16_t ReadPortEnvironmentVariable(const char* name, std::uint16_t default_value) {
    const auto text = ReadEnvironmentVariable(name);
    std::uint64_t parsed = 0;
    if (!TryParseUnsigned64(text, &parsed) ||
        parsed == 0 ||
        parsed > (std::numeric_limits<std::uint16_t>::max)()) {
        return default_value;
    }
    return static_cast<std::uint16_t>(parsed);
}

std::uint64_t ReadParticipantId(std::uint16_t local_port) {
    const auto text = ReadEnvironmentVariable(kParticipantIdEnvironmentVariable);
    std::uint64_t parsed = 0;
    if (TryParseUnsigned64(text, &parsed) && parsed != 0 && parsed != kLocalParticipantId) {
        return parsed;
    }
    return kLocalDevParticipantIdBase | static_cast<std::uint64_t>(local_port);
}

bool SameEndpoint(const sockaddr_in& left, const sockaddr_in& right) {
    return left.sin_family == right.sin_family &&
           left.sin_port == right.sin_port &&
           left.sin_addr.S_un.S_addr == right.sin_addr.S_un.S_addr;
}

std::string EndpointToString(const sockaddr_in& address) {
    std::array<char, INET_ADDRSTRLEN> text{};
    const char* converted = InetNtopA(AF_INET, const_cast<IN_ADDR*>(&address.sin_addr), text.data(), text.size());
    std::ostringstream stream;
    stream << (converted != nullptr ? converted : "0.0.0.0")
           << ":" << ntohs(address.sin_port);
    return stream.str();
}

bool ResolveIpv4Endpoint(const std::string& host, std::uint16_t port, sockaddr_in* address) {
    if (address == nullptr || host.empty() || port == 0) {
        return false;
    }

    sockaddr_in resolved{};
    resolved.sin_family = AF_INET;
    resolved.sin_port = htons(port);
    if (InetPtonA(AF_INET, host.c_str(), &resolved.sin_addr) != 1) {
        addrinfo hints{};
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_DGRAM;
        addrinfo* result = nullptr;
        if (getaddrinfo(host.c_str(), nullptr, &hints, &result) != 0 || result == nullptr) {
            return false;
        }
        resolved.sin_addr = reinterpret_cast<sockaddr_in*>(result->ai_addr)->sin_addr;
        freeaddrinfo(result);
    }

    *address = resolved;
    return true;
}

bool IsLocalUdpRequested() {
    const auto transport = ToLowerAscii(ReadEnvironmentVariable(kTransportEnvironmentVariable));
    return transport == "local_udp" || transport == "local-udp" || transport == "udp";
}

bool ConfigureLocalTransport() {
    if (!IsLocalUdpRequested()) {
        g_local_transport = LocalTransportState{};
        return false;
    }

    const auto role = ToLowerAscii(ReadEnvironmentVariable(kRoleEnvironmentVariable));
    const bool is_host = role.empty() || role == "host" || role == "server";
    const auto local_port = ReadPortEnvironmentVariable(
        kLocalPortEnvironmentVariable,
        is_host ? kDefaultHostPort : kDefaultClientPort);
    const auto remote_port = ReadPortEnvironmentVariable(
        kRemotePortEnvironmentVariable,
        is_host ? kDefaultClientPort : kDefaultHostPort);
    auto remote_host = ReadEnvironmentVariable(kRemoteHostEnvironmentVariable);
    if (remote_host.empty()) {
        remote_host = "127.0.0.1";
    }

    g_local_transport = LocalTransportState{};
    g_local_transport.configured = true;
    g_local_transport.is_host = is_host;
    g_local_transport.local_port = local_port;
    g_local_transport.remote_host = remote_host;
    g_local_transport.remote_port = remote_port;
    g_local_transport.local_peer_id = ReadParticipantId(local_port);
    g_local_transport.configured_remote_valid = ResolveIpv4Endpoint(
        remote_host,
        remote_port,
        &g_local_transport.configured_remote);
    return true;
}

void UpsertPeerEndpoint(const sockaddr_in& address, std::uint64_t participant_id, std::uint64_t now_ms) {
    for (auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.address, address) && peer.participant_id == participant_id) {
            peer.participant_id = participant_id;
            peer.last_packet_ms = now_ms;
            return;
        }
    }

    LocalPeerEndpoint peer;
    peer.address = address;
    peer.participant_id = participant_id;
    peer.last_packet_ms = now_ms;
    g_local_transport.peers.push_back(peer);
    Log(
        "Multiplayer local UDP learned peer endpoint=" + EndpointToString(address) +
        " participant_id=" + std::to_string(participant_id));
}

std::string ReadLocalDisplayName() {
    auto name = ReadEnvironmentVariable(kPlayerNameEnvironmentVariable);
    if (name.empty()) {
        return {};
    }
    if (name.size() >= kParticipantDisplayNameBytes) {
        name.resize(kParticipantDisplayNameBytes - 1);
    }
    return name;
}

void CopyPacketDisplayName(const std::string& name, StatePacket* packet) {
    if (packet == nullptr) {
        return;
    }
    std::memset(packet->display_name, 0, sizeof(packet->display_name));
    if (name.empty()) {
        return;
    }
    const auto count = (std::min)(name.size(), sizeof(packet->display_name) - 1);
    std::memcpy(packet->display_name, name.data(), count);
}

std::string PacketDisplayName(const StatePacket& packet) {
    std::size_t length = 0;
    while (length < sizeof(packet.display_name) && packet.display_name[length] != '\0') {
        ++length;
    }
    return std::string(packet.display_name, packet.display_name + length);
}

ParticipantSceneIntent SceneIntentFromPacket(const StatePacket& packet) {
    ParticipantSceneIntent intent;
    intent.kind = packet.in_run != 0 ? ParticipantSceneIntentKind::Run
                                     : ParticipantSceneIntentKind::SharedHub;
    return intent;
}

ParticipantSceneIntent SceneIntentFromLocalScene() {
    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return DefaultParticipantSceneIntent();
    }

    ParticipantSceneIntent intent;
    if (scene_state.kind == "arena") {
        intent.kind = ParticipantSceneIntentKind::Run;
        return intent;
    }
    if (scene_state.kind == "hub") {
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        return intent;
    }

    intent.kind = ParticipantSceneIntentKind::PrivateRegion;
    intent.region_index = scene_state.current_region_index;
    intent.region_type_id = scene_state.region_type_id;
    return intent;
}

void RefreshLocalParticipantFromGameState() {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    const auto configured_name = ReadLocalDisplayName();
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* local = UpsertLocalParticipant(state);
        if (local == nullptr) {
            return;
        }

        local->ready = true;
        if (!configured_name.empty()) {
            local->name = configured_name;
        }
        local->transport_connected = true;
        local->transport_using_relay = false;
        local->runtime.valid = true;
        local->runtime.transform_valid = true;
        local->runtime.in_run = scene_intent.kind == ParticipantSceneIntentKind::Run;
        local->runtime.scene_intent = scene_intent;
        local->runtime.life_current = static_cast<std::int32_t>(std::lround(player_state.hp));
        local->runtime.life_max = static_cast<std::int32_t>(std::lround(player_state.max_hp));
        local->runtime.mana_current = static_cast<std::int32_t>(std::lround(player_state.mp));
        local->runtime.mana_max = static_cast<std::int32_t>(std::lround(player_state.max_mp));
        local->runtime.level = player_state.level;
        local->runtime.experience_current = player_state.xp;
        local->runtime.position_x = player_state.x;
        local->runtime.position_y = player_state.y;
        local->runtime.heading = player_state.heading;
    });
}

StatePacket BuildLocalStatePacket() {
    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);

    StatePacket packet{};
    packet.header = MakePacketHeader(PacketKind::State, g_local_transport.next_sequence++);
    packet.participant_id = g_local_transport.local_peer_id;
    if (local == nullptr) {
        return packet;
    }

    CopyPacketDisplayName(local->name, &packet);
    packet.ready = local->ready ? 1 : 0;
    packet.in_run = local->runtime.in_run ? 1 : 0;
    packet.transform_valid = local->runtime.transform_valid ? 1 : 0;
    packet.controller_kind = static_cast<std::uint8_t>(ParticipantControllerKind::Native);
    packet.run_nonce = local->runtime.run_nonce;
    packet.element_id = local->character_profile.element_id;
    packet.discipline_id = static_cast<std::int32_t>(local->character_profile.discipline_id);
    for (std::size_t index = 0; index < local->character_profile.appearance.choice_ids.size(); ++index) {
        packet.appearance_choice_ids[index] = local->character_profile.appearance.choice_ids[index];
    }
    packet.level = local->runtime.level;
    packet.wave = local->runtime.wave;
    packet.life_current = local->runtime.life_current;
    packet.life_max = local->runtime.life_max;
    packet.mana_current = local->runtime.mana_current;
    packet.mana_max = local->runtime.mana_max;
    packet.experience_current = local->runtime.experience_current;
    packet.experience_next = local->runtime.experience_next;
    packet.primary_entry_index = local->character_profile.loadout.primary_entry_index;
    packet.primary_combo_entry_index = local->character_profile.loadout.primary_combo_entry_index;
    for (std::size_t index = 0; index < local->character_profile.loadout.secondary_entry_indices.size(); ++index) {
        packet.queued_secondary_entry_indices[index] =
            local->character_profile.loadout.secondary_entry_indices[index];
    }
    packet.position_x = local->runtime.position_x;
    packet.position_y = local->runtime.position_y;
    packet.heading = local->runtime.heading;
    return packet;
}

void SendPacketToEndpoint(const StatePacket& packet, const sockaddr_in& endpoint) {
    const int sent = sendto(
        g_local_transport.socket_handle,
        reinterpret_cast<const char*>(&packet),
        static_cast<int>(sizeof(packet)),
        0,
        reinterpret_cast<const sockaddr*>(&endpoint),
        sizeof(endpoint));
    if (sent == static_cast<int>(sizeof(packet))) {
        g_local_transport.packets_sent += 1;
    }
}

void SendLocalState(std::uint64_t now_ms) {
    if (now_ms - g_local_transport.last_send_ms < kLocalTransportSendIntervalMs) {
        return;
    }
    g_local_transport.last_send_ms = now_ms;

    const auto packet = BuildLocalStatePacket();
    if (packet.transform_valid == 0) {
        return;
    }

    std::vector<sockaddr_in> endpoints;
    if (g_local_transport.configured_remote_valid) {
        endpoints.push_back(g_local_transport.configured_remote);
    }
    for (const auto& peer : g_local_transport.peers) {
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const sockaddr_in& existing) {
            return SameEndpoint(existing, peer.address);
        });
        if (!already_added) {
            endpoints.push_back(peer.address);
        }
    }

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void RelayStatePacketToPeers(const StatePacket& packet, const sockaddr_in& source) {
    if (!g_local_transport.is_host) {
        return;
    }

    std::vector<sockaddr_in> endpoints;
    for (const auto& peer : g_local_transport.peers) {
        if (SameEndpoint(peer.address, source)) {
            continue;
        }
        const bool already_added = std::any_of(endpoints.begin(), endpoints.end(), [&](const sockaddr_in& existing) {
            return SameEndpoint(existing, peer.address);
        });
        if (!already_added) {
            endpoints.push_back(peer.address);
        }
    }

    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void ApplyRemoteStatePacket(const StatePacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (packet.participant_id == 0 ||
        packet.participant_id == kLocalParticipantId ||
        packet.participant_id == g_local_transport.local_peer_id) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayStatePacketToPeers(packet, from);

    MultiplayerCharacterProfile profile;
    profile.element_id = packet.element_id;
    profile.discipline_id = static_cast<CharacterDisciplineId>(packet.discipline_id);
    for (std::size_t index = 0; index < profile.appearance.choice_ids.size(); ++index) {
        profile.appearance.choice_ids[index] = packet.appearance_choice_ids[index];
    }
    profile.loadout.primary_entry_index = packet.primary_entry_index;
    profile.loadout.primary_combo_entry_index = packet.primary_combo_entry_index;
    for (std::size_t index = 0; index < profile.loadout.secondary_entry_indices.size(); ++index) {
        profile.loadout.secondary_entry_indices[index] = packet.queued_secondary_entry_indices[index];
    }
    profile.level = packet.level;
    profile.experience = packet.experience_current;
    if (!IsValidCharacterProfile(profile)) {
        return;
    }

    const auto scene_intent = SceneIntentFromPacket(packet);
    const auto display_name = PacketDisplayName(packet);
    const bool transform_valid = packet.transform_valid != 0 &&
        std::isfinite(packet.position_x) &&
        std::isfinite(packet.position_y) &&
        std::isfinite(packet.heading);

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = UpsertRemoteParticipant(
            state,
            packet.participant_id,
            ParticipantControllerKind::Native);
        if (participant == nullptr) {
            return;
        }

        if (!display_name.empty()) {
            participant->name = display_name;
        } else if (participant->name.empty() || participant->name == "Remote Wizard") {
            participant->name = "Remote Wizard " + std::to_string(packet.participant_id);
        }
        participant->ready = packet.ready != 0;
        participant->transport_connected = true;
        participant->transport_using_relay = false;
        participant->last_packet_ms = now_ms;
        participant->character_profile = profile;
        participant->runtime.valid = true;
        participant->runtime.in_run = packet.in_run != 0;
        participant->runtime.run_nonce = packet.run_nonce;
        participant->runtime.scene_intent = scene_intent;
        participant->runtime.level = packet.level;
        participant->runtime.wave = packet.wave;
        participant->runtime.life_current = packet.life_current;
        participant->runtime.life_max = packet.life_max;
        participant->runtime.mana_current = packet.mana_current;
        participant->runtime.mana_max = packet.mana_max;
        participant->runtime.experience_current = packet.experience_current;
        participant->runtime.experience_next = packet.experience_next;
        participant->runtime.primary_entry_index = packet.primary_entry_index;
        participant->runtime.primary_combo_entry_index = packet.primary_combo_entry_index;
        for (std::size_t index = 0; index < participant->runtime.queued_secondary_entry_indices.size(); ++index) {
            participant->runtime.queued_secondary_entry_indices[index] =
                packet.queued_secondary_entry_indices[index];
        }
        if (transform_valid) {
            participant->runtime.transform_valid = true;
            participant->runtime.position_x = packet.position_x;
            participant->runtime.position_y = packet.position_y;
            participant->runtime.heading = packet.heading;
        }
    });

    SDModParticipantGameplayState gameplay_state;
    const bool participant_materialized =
        TryGetParticipantGameplayState(packet.participant_id, &gameplay_state) &&
        gameplay_state.entity_materialized &&
        gameplay_state.actor_address != 0;
    if (transform_valid && !participant_materialized) {
        std::string sync_error;
        (void)QueueParticipantEntitySync(
            packet.participant_id,
            profile,
            scene_intent,
            true,
            true,
            packet.position_x,
            packet.position_y,
            packet.heading,
            &sync_error);
    }
}

void ReceivePackets(std::uint64_t now_ms) {
    for (int packet_index = 0; packet_index < kMaxPacketsPerTick; ++packet_index) {
        StatePacket packet{};
        sockaddr_in from{};
        int from_length = sizeof(from);
        const int received = recvfrom(
            g_local_transport.socket_handle,
            reinterpret_cast<char*>(&packet),
            static_cast<int>(sizeof(packet)),
            0,
            reinterpret_cast<sockaddr*>(&from),
            &from_length);
        if (received == SOCKET_ERROR) {
            const int error = WSAGetLastError();
            if (error == WSAEWOULDBLOCK) {
                return;
            }
            return;
        }

        if (received != static_cast<int>(sizeof(StatePacket)) ||
            !IsValidHeader(packet.header, PacketKind::State)) {
            continue;
        }

        g_local_transport.packets_received += 1;
        ApplyRemoteStatePacket(packet, from, now_ms);
    }
}

void PublishLocalTransportRuntimeState() {
    UpdateRuntimeState([](RuntimeState& state) {
        state.transport_ready = true;
        state.session_status = SessionStatus::Ready;
        state.session_transport = SessionTransportKind::LocalUdp;
        std::ostringstream status;
        status << "Local UDP multiplayer transport ready. role="
               << (g_local_transport.is_host ? "host" : "client")
               << " local_port=" << g_local_transport.local_port
               << " participant_id=" << g_local_transport.local_peer_id
               << " peers=" << g_local_transport.peers.size()
               << " sent=" << g_local_transport.packets_sent
               << " received=" << g_local_transport.packets_received;
        state.status_text = status.str();
    });
}

}  // namespace

bool InitializeLocalTransport() {
    if (!ConfigureLocalTransport()) {
        return true;
    }

    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        Log("Multiplayer local UDP: WSAStartup failed.");
        g_local_transport = LocalTransportState{};
        return false;
    }
    g_local_transport.winsock_initialized = true;

    g_local_transport.socket_handle = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (g_local_transport.socket_handle == INVALID_SOCKET) {
        Log("Multiplayer local UDP: socket creation failed.");
        ShutdownLocalTransport();
        return false;
    }

    u_long nonblocking = 1;
    if (ioctlsocket(g_local_transport.socket_handle, FIONBIO, &nonblocking) != 0) {
        Log("Multiplayer local UDP: failed to set non-blocking mode.");
        ShutdownLocalTransport();
        return false;
    }

    sockaddr_in bind_address{};
    bind_address.sin_family = AF_INET;
    bind_address.sin_addr.s_addr = htonl(INADDR_ANY);
    bind_address.sin_port = htons(g_local_transport.local_port);
    if (bind(
            g_local_transport.socket_handle,
            reinterpret_cast<const sockaddr*>(&bind_address),
            sizeof(bind_address)) != 0) {
        Log("Multiplayer local UDP: bind failed on port " + std::to_string(g_local_transport.local_port) + ".");
        ShutdownLocalTransport();
        return false;
    }

    g_local_transport.initialized = true;
    std::ostringstream message;
    message << "Multiplayer local UDP transport initialized. role="
            << (g_local_transport.is_host ? "host" : "client")
            << " local_port=" << g_local_transport.local_port
            << " remote=" << g_local_transport.remote_host << ":" << g_local_transport.remote_port
            << " participant_id=" << g_local_transport.local_peer_id;
    Log(message.str());
    return true;
}

void ShutdownLocalTransport() {
    if (g_local_transport.socket_handle != INVALID_SOCKET) {
        closesocket(g_local_transport.socket_handle);
    }
    if (g_local_transport.winsock_initialized) {
        WSACleanup();
    }
    g_local_transport = LocalTransportState{};
}

void TickLocalTransport(std::uint64_t now_ms) {
    if (!g_local_transport.initialized) {
        return;
    }

    RefreshLocalParticipantFromGameState();
    ReceivePackets(now_ms);
    SendLocalState(now_ms);
    PublishLocalTransportRuntimeState();
}

bool IsLocalTransportEnabled() {
    return g_local_transport.initialized;
}

}  // namespace sdmod::multiplayer
