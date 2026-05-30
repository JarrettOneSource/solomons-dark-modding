#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <WinSock2.h>
#include <Ws2tcpip.h>

#include "multiplayer_local_transport.h"

#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
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
#include <unordered_map>
#include <unordered_set>
#include <utility>
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
constexpr std::uint64_t kRunWorldActorNetworkIdBase = 0x1000000000000ull;
constexpr std::uint64_t kRunHostLocalWorldActorNetworkIdBase = 0x1001000000000ull;
constexpr std::uint64_t kRunLootDropNetworkIdBase = 0x1002000000000ull;
constexpr std::uint64_t kLocalTransportSendIntervalMs = 50;
constexpr std::uint64_t kLocalTransportWorldSnapshotIntervalMs = 100;
constexpr std::uint64_t kLocalTransportLootSnapshotIntervalMs = 100;
constexpr std::uint64_t kClientHostRunFollowRetryMs = 1000;
constexpr std::uint32_t kGoldRewardNativeTypeId = 0x07DC;
constexpr std::size_t kGoldRewardAmountTierOffset = 0x13C;
constexpr std::size_t kGoldRewardAmountOffset = 0x140;
constexpr std::size_t kGoldRewardLifetimeOffset = 0x144;
constexpr std::size_t kGoldRewardActiveOffset = 0x148;
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
    std::uint64_t last_world_snapshot_send_ms = 0;
    std::uint64_t last_loot_snapshot_send_ms = 0;
    std::uint64_t last_client_host_run_request_ms = 0;
    std::uint32_t next_sequence = 1;
    std::uint32_t world_scene_epoch = 0;
    std::uint64_t packets_sent = 0;
    std::uint64_t packets_received = 0;
    std::string world_scene_key;
    std::unordered_map<uintptr_t, std::uint64_t> hub_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_host_local_world_actor_ids_by_address;
    std::unordered_map<uintptr_t, std::uint64_t> run_loot_drop_ids_by_address;
    std::uint32_t next_hub_world_actor_serial = 1;
    std::uint32_t next_run_host_local_world_actor_serial = 1;
    std::uint32_t next_run_loot_drop_serial = 1;
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

WorldSceneKind WorldSceneKindFromSceneIntent(const ParticipantSceneIntent& intent) {
    switch (intent.kind) {
    case ParticipantSceneIntentKind::SharedHub:
        return WorldSceneKind::SharedHub;
    case ParticipantSceneIntentKind::PrivateRegion:
        return WorldSceneKind::PrivateRegion;
    case ParticipantSceneIntentKind::Run:
        return WorldSceneKind::Run;
    }

    return WorldSceneKind::Unknown;
}

ParticipantSceneIntent SceneIntentFromWorldSceneKind(WorldSceneKind kind) {
    ParticipantSceneIntent intent;
    switch (kind) {
    case WorldSceneKind::SharedHub:
        intent.kind = ParticipantSceneIntentKind::SharedHub;
        break;
    case WorldSceneKind::PrivateRegion:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        break;
    case WorldSceneKind::Run:
        intent.kind = ParticipantSceneIntentKind::Run;
        break;
    case WorldSceneKind::Unknown:
    default:
        intent.kind = ParticipantSceneIntentKind::PrivateRegion;
        break;
    }
    return intent;
}

LootDropKind LootDropKindFromPacketValue(std::uint8_t kind) {
    switch (static_cast<LootDropKind>(kind)) {
    case LootDropKind::Gold:
        return LootDropKind::Gold;
    case LootDropKind::Item:
        return LootDropKind::Item;
    case LootDropKind::Potion:
        return LootDropKind::Potion;
    case LootDropKind::Orb:
        return LootDropKind::Orb;
    case LootDropKind::Powerup:
        return LootDropKind::Powerup;
    case LootDropKind::Unknown:
    default:
        return LootDropKind::Unknown;
    }
}

std::string BuildWorldSceneKey(const SDModSceneState& scene_state) {
    std::ostringstream stream;
    stream << scene_state.kind
           << ":" << scene_state.name
           << ":" << scene_state.current_region_index
           << ":" << scene_state.region_type_id
           << ":" << scene_state.gameplay_scene_address;
    return stream.str();
}

std::uint64_t BuildRunWorldActorNetworkId(std::uint32_t spawn_serial) {
    if (spawn_serial == 0) {
        return 0;
    }
    return kRunWorldActorNetworkIdBase | static_cast<std::uint64_t>(spawn_serial);
}

std::uint64_t BuildRunLootDropNetworkId(std::uint32_t spawn_serial) {
    if (spawn_serial == 0) {
        return 0;
    }
    return kRunLootDropNetworkIdBase | static_cast<std::uint64_t>(spawn_serial);
}

std::uint64_t AllocateRunHostLocalWorldActorNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.run_host_local_world_actor_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.run_host_local_world_actor_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_run_host_local_world_actor_serial == 0) {
        g_local_transport.next_run_host_local_world_actor_serial = 1;
    }
    const auto serial = g_local_transport.next_run_host_local_world_actor_serial++;
    const auto network_actor_id =
        kRunHostLocalWorldActorNetworkIdBase | static_cast<std::uint64_t>(serial);
    g_local_transport.run_host_local_world_actor_ids_by_address.emplace(actor.actor_address, network_actor_id);
    return network_actor_id;
}

std::uint64_t AllocateRunLootDropNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.run_loot_drop_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.run_loot_drop_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_run_loot_drop_serial == 0) {
        g_local_transport.next_run_loot_drop_serial = 1;
    }
    const auto serial = g_local_transport.next_run_loot_drop_serial++;
    const auto network_drop_id = BuildRunLootDropNetworkId(serial);
    g_local_transport.run_loot_drop_ids_by_address.emplace(actor.actor_address, network_drop_id);
    return network_drop_id;
}

bool ShouldReplicateWorldActor(
    const SDModSceneActorState& actor,
    ParticipantSceneIntentKind scene_kind) {
    if (!actor.valid ||
        actor.actor_address == 0 ||
        actor.object_type_id == 0 ||
        actor.object_type_id == 1 ||
        !std::isfinite(actor.x) ||
        !std::isfinite(actor.y) ||
        !std::isfinite(actor.radius) ||
        actor.radius < 0.0f) {
        return false;
    }

    if (scene_kind == ParticipantSceneIntentKind::Run) {
        return actor.tracked_enemy &&
               std::isfinite(actor.hp) &&
               std::isfinite(actor.max_hp) &&
               actor.max_hp > 0.0f;
    }

    return scene_kind == ParticipantSceneIntentKind::SharedHub;
}

bool ShouldReplicateLootDropActor(
    const SDModSceneActorState& actor,
    ParticipantSceneIntentKind scene_kind) {
    return scene_kind == ParticipantSceneIntentKind::Run &&
           actor.valid &&
           actor.actor_address != 0 &&
           actor.object_type_id == kGoldRewardNativeTypeId &&
           std::isfinite(actor.x) &&
           std::isfinite(actor.y) &&
           std::isfinite(actor.radius) &&
           actor.radius >= 0.0f;
}

std::uint64_t AllocateHubWorldActorNetworkId(const SDModSceneActorState& actor) {
    if (actor.actor_address == 0 || actor.object_type_id == 0) {
        return 0;
    }

    const auto existing = g_local_transport.hub_world_actor_ids_by_address.find(actor.actor_address);
    if (existing != g_local_transport.hub_world_actor_ids_by_address.end()) {
        return existing->second;
    }

    if (g_local_transport.next_hub_world_actor_serial == 0) {
        g_local_transport.next_hub_world_actor_serial = 1;
    }
    const auto serial = g_local_transport.next_hub_world_actor_serial++;
    const auto network_actor_id =
        (static_cast<std::uint64_t>(actor.object_type_id) << 32) |
        static_cast<std::uint64_t>(serial);
    g_local_transport.hub_world_actor_ids_by_address.emplace(actor.actor_address, network_actor_id);
    return network_actor_id;
}

void ClearHubWorldActorNetworkIds() {
    g_local_transport.hub_world_actor_ids_by_address.clear();
    g_local_transport.next_hub_world_actor_serial = 1;
}

void ClearRunHostLocalWorldActorNetworkIds() {
    g_local_transport.run_host_local_world_actor_ids_by_address.clear();
    g_local_transport.next_run_host_local_world_actor_serial = 1;
}

void ClearRunLootDropNetworkIds() {
    g_local_transport.run_loot_drop_ids_by_address.clear();
    g_local_transport.next_run_loot_drop_serial = 1;
}

void RefreshWorldSceneTracking(const SDModSceneState& scene_state) {
    const auto scene_key = BuildWorldSceneKey(scene_state);
    if (scene_key == g_local_transport.world_scene_key) {
        return;
    }

    g_local_transport.world_scene_key = scene_key;
    g_local_transport.world_scene_epoch += 1;
    ClearHubWorldActorNetworkIds();
    ClearRunHostLocalWorldActorNetworkIds();
    ClearRunLootDropNetworkIds();
}

void PruneHubWorldActorNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::SharedHub) {
        ClearHubWorldActorNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateWorldActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.hub_world_actor_ids_by_address.begin();
         iterator != g_local_transport.hub_world_actor_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.hub_world_actor_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void PruneRunHostLocalWorldActorNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::Run) {
        ClearRunHostLocalWorldActorNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateWorldActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.run_host_local_world_actor_ids_by_address.begin();
         iterator != g_local_transport.run_host_local_world_actor_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.run_host_local_world_actor_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

void PruneRunLootDropNetworkIds(
    const std::vector<SDModSceneActorState>& actors,
    ParticipantSceneIntentKind scene_kind) {
    if (scene_kind != ParticipantSceneIntentKind::Run) {
        ClearRunLootDropNetworkIds();
        return;
    }

    std::unordered_set<uintptr_t> live_actor_addresses;
    for (const auto& actor : actors) {
        if (ShouldReplicateLootDropActor(actor, scene_kind)) {
            live_actor_addresses.insert(actor.actor_address);
        }
    }

    for (auto iterator = g_local_transport.run_loot_drop_ids_by_address.begin();
         iterator != g_local_transport.run_loot_drop_ids_by_address.end();) {
        if (live_actor_addresses.find(iterator->first) == live_actor_addresses.end()) {
            iterator = g_local_transport.run_loot_drop_ids_by_address.erase(iterator);
        } else {
            ++iterator;
        }
    }
}

float ReadActorHeadingOrZero(uintptr_t actor_address) {
    if (actor_address == 0 || kActorHeadingOffset == 0) {
        return 0.0f;
    }

    float heading = 0.0f;
    if (!ProcessMemory::Instance().TryReadField(actor_address, kActorHeadingOffset, &heading) ||
        !std::isfinite(heading)) {
        return 0.0f;
    }
    return heading;
}

bool IsHubStudentActorType(std::uint32_t native_type_id) {
    return native_type_id == 0x138A;
}

bool IsSharedHubFactoryActorType(std::uint32_t native_type_id) {
    switch (native_type_id) {
    case 0x1389:
    case 0x138A:
    case 0x138B:
    case 0x138C:
    case 0x138D:
    case 0x138F:
    case 0x1390:
        return true;
    default:
        return false;
    }
}

void PopulateWorldActorPresentationSnapshot(
    uintptr_t actor_address,
    std::uint32_t native_type_id,
    ParticipantSceneIntentKind scene_kind,
    WorldActorSnapshotPacketState* snapshot) {
    if (actor_address == 0 || snapshot == nullptr) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    if (scene_kind == ParticipantSceneIntentKind::SharedHub &&
        IsSharedHubFactoryActorType(native_type_id) &&
        kActorAnimationDriveStateByteOffset != 0) {
        std::uint32_t drive_word = 0;
        if (memory.TryReadField(actor_address, kActorAnimationDriveStateByteOffset, &drive_word)) {
            snapshot->presentation_flags |= WorldActorPresentationFlagAnimationDriveWord;
            snapshot->anim_drive_state_word = drive_word;
        }
    }

    if (scene_kind != ParticipantSceneIntentKind::SharedHub ||
        !IsHubStudentActorType(native_type_id)) {
        return;
    }

    if (kActorRenderVariantPrimaryOffset != 0 &&
        kActorRenderVariantSecondaryOffset != 0 &&
        kActorRenderWeaponTypeOffset != 0 &&
        kActorRenderSelectionByteOffset != 0 &&
        kActorRenderVariantTertiaryOffset != 0) {
        bool have_variant_bytes = true;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantPrimaryOffset,
            &snapshot->render_variant_primary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantSecondaryOffset,
            &snapshot->render_variant_secondary) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderWeaponTypeOffset,
            &snapshot->render_weapon_type) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderSelectionByteOffset,
            &snapshot->render_selection_byte) && have_variant_bytes;
        have_variant_bytes = memory.TryReadField(
            actor_address,
            kActorRenderVariantTertiaryOffset,
            &snapshot->render_variant_tertiary) && have_variant_bytes;
        if (have_variant_bytes) {
            snapshot->presentation_flags |= WorldActorPresentationFlagStudentVariantBytes;
        }
    }

    if (kStudentVisualStateBlockOffset != 0 &&
        memory.TryRead(
            actor_address + kStudentVisualStateBlockOffset,
            snapshot->student_visual_state,
            kWorldActorStudentVisualStateBytes)) {
        snapshot->presentation_flags |= WorldActorPresentationFlagStudentVisualState;
    }
}

bool TryPopulateGoldLootDropSnapshot(
    const SDModSceneActorState& actor,
    std::uint64_t network_drop_id,
    LootDropSnapshotPacketState* snapshot) {
    if (snapshot == nullptr ||
        network_drop_id == 0 ||
        !ShouldReplicateLootDropActor(actor, ParticipantSceneIntentKind::Run)) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    std::uint8_t amount_tier = 0;
    std::uint32_t amount_raw = 0;
    std::uint32_t lifetime = 0;
    std::uint8_t active = 0;
    if (!memory.TryReadField(actor.actor_address, kGoldRewardAmountTierOffset, &amount_tier) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardAmountOffset, &amount_raw) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardLifetimeOffset, &lifetime) ||
        !memory.TryReadField(actor.actor_address, kGoldRewardActiveOffset, &active)) {
        return false;
    }

    LootDropSnapshotPacketState built{};
    built.network_drop_id = network_drop_id;
    built.native_type_id = actor.object_type_id;
    built.drop_kind = static_cast<std::uint8_t>(LootDropKind::Gold);
    built.flags = active != 0 ? LootDropSnapshotFlagActive : 0;
    built.amount = amount_raw <= static_cast<std::uint32_t>((std::numeric_limits<std::int32_t>::max)())
                       ? static_cast<std::int32_t>(amount_raw)
                       : (std::numeric_limits<std::int32_t>::max)();
    built.amount_tier = amount_tier;
    built.actor_slot = actor.actor_slot;
    built.world_slot = actor.world_slot;
    built.lifetime = lifetime;
    built.position_x = actor.x;
    built.position_y = actor.y;
    built.radius = actor.radius;
    *snapshot = built;
    return true;
}

std::vector<sockaddr_in> BuildKnownSendEndpoints() {
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
    return endpoints;
}

void RefreshLocalParticipantFromGameState() {
    SDModPlayerState player_state;
    if (!TryGetPlayerState(&player_state) || !player_state.valid) {
        return;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    const auto configured_name = ReadLocalDisplayName();
    SDModWorldState world_state;
    const bool have_world_state = TryGetWorldState(&world_state) && world_state.valid;
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
        local->owned_progression.initialized = true;
        local->owned_progression.gold = player_state.gold;
        if (have_world_state) {
            local->runtime.wave = world_state.wave;
        }
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

bool BuildLocalWorldSnapshotPacket(WorldSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::SharedHub &&
        scene_intent.kind != ParticipantSceneIntentKind::Run) {
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneHubWorldActorNetworkIds(actors, scene_intent.kind);
    PruneRunHostLocalWorldActorNetworkIds(actors, scene_intent.kind);

    WorldSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::WorldSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    const bool run_scene = scene_intent.kind == ParticipantSceneIntentKind::Run;
    std::uint32_t total_actor_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateWorldActor(actor, scene_intent.kind)) {
            continue;
        }
        std::uint64_t network_actor_id = 0;
        if (run_scene) {
            std::uint32_t spawn_serial = 0;
            if (TryGetRunLifecycleEnemySpawnSerial(actor.actor_address, &spawn_serial)) {
                g_local_transport.run_host_local_world_actor_ids_by_address.erase(actor.actor_address);
                network_actor_id = BuildRunWorldActorNetworkId(spawn_serial);
            } else {
                network_actor_id = AllocateRunHostLocalWorldActorNetworkId(actor);
                static std::uint64_t s_last_missing_run_actor_id_log_ms = 0;
                const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
                if (now_ms - s_last_missing_run_actor_id_log_ms >= 1000) {
                    s_last_missing_run_actor_id_log_ms = now_ms;
                    Log(
                        "world_snapshot: assigned host-local run enemy network id. actor=" +
                        HexString(actor.actor_address) +
                        " enemy_type=" + std::to_string(actor.enemy_type) +
                        " network_actor_id=" + std::to_string(network_actor_id));
                }
            }
        } else {
            network_actor_id = AllocateHubWorldActorNetworkId(actor);
        }
        if (network_actor_id == 0) {
            continue;
        }
        total_actor_count += 1;
        if (built.actor_count >= kWorldSnapshotMaxActors) {
            continue;
        }

        auto& snapshot = built.actors[built.actor_count];
        snapshot.network_actor_id = network_actor_id;
        snapshot.native_type_id = actor.object_type_id;
        snapshot.enemy_type = actor.enemy_type;
        snapshot.actor_slot = actor.actor_slot;
        snapshot.world_slot = actor.world_slot;
        snapshot.anim_drive_state = actor.anim_drive_state;
        snapshot.position_x = actor.x;
        snapshot.position_y = actor.y;
        snapshot.radius = actor.radius;
        snapshot.heading = ReadActorHeadingOrZero(actor.actor_address);
        snapshot.hp = std::isfinite(actor.hp) ? actor.hp : 0.0f;
        snapshot.max_hp = std::isfinite(actor.max_hp) ? actor.max_hp : 0.0f;
        PopulateWorldActorPresentationSnapshot(
            actor.actor_address,
            actor.object_type_id,
            scene_intent.kind,
            &snapshot);
        if (actor.dead) {
            snapshot.flags |= WorldActorSnapshotFlagDead;
        }
        if (actor.tracked_enemy) {
            snapshot.flags |= WorldActorSnapshotFlagTrackedEnemy;
        }
        if (run_scene) {
            snapshot.flags |= WorldActorSnapshotFlagLifecycleOwned;
        }
        built.actor_count += 1;
    }
    built.actor_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_actor_count, 0xFFu));
    if (total_actor_count > built.actor_count) {
        built.snapshot_flags |= WorldSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

bool BuildLocalLootSnapshotPacket(LootSnapshotPacket* packet) {
    if (packet == nullptr || !g_local_transport.is_host) {
        return false;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid) {
        return false;
    }

    std::vector<SDModSceneActorState> actors;
    if (!TryListSceneActors(&actors)) {
        return false;
    }

    const auto scene_intent = SceneIntentFromLocalScene();
    if (scene_intent.kind != ParticipantSceneIntentKind::Run) {
        PruneRunLootDropNetworkIds(actors, scene_intent.kind);
        return false;
    }

    RefreshWorldSceneTracking(scene_state);
    PruneRunLootDropNetworkIds(actors, scene_intent.kind);

    LootSnapshotPacket built{};
    built.header = MakePacketHeader(PacketKind::LootSnapshot, g_local_transport.next_sequence++);
    built.authority_participant_id = g_local_transport.local_peer_id;
    built.scene_epoch = g_local_transport.world_scene_epoch;
    built.scene_kind = static_cast<std::uint8_t>(WorldSceneKindFromSceneIntent(scene_intent));

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local != nullptr) {
        built.run_nonce = local->runtime.run_nonce;
    }

    std::uint32_t total_drop_count = 0;
    for (const auto& actor : actors) {
        if (!ShouldReplicateLootDropActor(actor, scene_intent.kind)) {
            continue;
        }

        const auto network_drop_id = AllocateRunLootDropNetworkId(actor);
        if (network_drop_id == 0) {
            continue;
        }

        LootDropSnapshotPacketState snapshot{};
        if (!TryPopulateGoldLootDropSnapshot(actor, network_drop_id, &snapshot)) {
            continue;
        }

        total_drop_count += 1;
        if (built.drop_count >= kLootSnapshotMaxDrops) {
            continue;
        }

        built.drops[built.drop_count] = snapshot;
        built.drop_count += 1;
    }

    built.drop_total_count = static_cast<std::uint8_t>((std::min<std::uint32_t>)(total_drop_count, 0xFFu));
    if (total_drop_count > built.drop_count) {
        built.snapshot_flags |= LootSnapshotFlagTruncated;
    }

    *packet = built;
    return true;
}

void SendBufferToEndpoint(const void* packet, std::size_t packet_size, const sockaddr_in& endpoint) {
    if (packet == nullptr || packet_size == 0 || packet_size > static_cast<std::size_t>((std::numeric_limits<int>::max)())) {
        return;
    }
    const int sent = sendto(
        g_local_transport.socket_handle,
        reinterpret_cast<const char*>(packet),
        static_cast<int>(packet_size),
        0,
        reinterpret_cast<const sockaddr*>(&endpoint),
        sizeof(endpoint));
    if (sent == static_cast<int>(packet_size)) {
        g_local_transport.packets_sent += 1;
    }
}

void SendPacketToEndpoint(const StatePacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const WorldSnapshotPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
}

void SendPacketToEndpoint(const LootSnapshotPacket& packet, const sockaddr_in& endpoint) {
    SendBufferToEndpoint(&packet, sizeof(packet), endpoint);
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

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void SendWorldSnapshot(std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        now_ms - g_local_transport.last_world_snapshot_send_ms < kLocalTransportWorldSnapshotIntervalMs) {
        return;
    }
    g_local_transport.last_world_snapshot_send_ms = now_ms;

    WorldSnapshotPacket packet{};
    if (!BuildLocalWorldSnapshotPacket(&packet) || packet.actor_count == 0) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
    for (const auto& endpoint : endpoints) {
        SendPacketToEndpoint(packet, endpoint);
    }
}

void SendLootSnapshot(std::uint64_t now_ms) {
    if (!g_local_transport.is_host ||
        now_ms - g_local_transport.last_loot_snapshot_send_ms < kLocalTransportLootSnapshotIntervalMs) {
        return;
    }
    g_local_transport.last_loot_snapshot_send_ms = now_ms;

    LootSnapshotPacket packet{};
    if (!BuildLocalLootSnapshotPacket(&packet)) {
        return;
    }

    const auto endpoints = BuildKnownSendEndpoints();
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

bool IsConfiguredRemoteAuthorityEndpoint(const sockaddr_in& from) {
    return g_local_transport.configured_remote_valid &&
           SameEndpoint(from, g_local_transport.configured_remote);
}

bool IsLocalSceneAlreadyRun(const SDModSceneState& scene_state) {
    return scene_state.kind == "arena" || scene_state.name == "testrun";
}

bool IsLocalSceneSharedHub(const SDModSceneState& scene_state) {
    return scene_state.kind == "hub" || scene_state.name == "hub";
}

void MaybeQueueClientHostRunStart(
    const StatePacket& packet,
    const ParticipantSceneIntent& scene_intent,
    const sockaddr_in& from,
    std::uint64_t now_ms) {
    if (!IsLocalTransportClient() ||
        scene_intent.kind != ParticipantSceneIntentKind::Run ||
        packet.ready == 0 ||
        !IsConfiguredRemoteAuthorityEndpoint(from)) {
        return;
    }

    SDModSceneState scene_state;
    if (!TryGetSceneState(&scene_state) || !scene_state.valid ||
        IsLocalSceneAlreadyRun(scene_state)) {
        return;
    }
    if (!IsLocalSceneSharedHub(scene_state)) {
        Log(
            "Multiplayer local UDP ignored host run intent outside hub. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " local_scene=" + scene_state.name +
            " kind=" + scene_state.kind);
        return;
    }

    const auto last_request_ms = g_local_transport.last_client_host_run_request_ms;
    if (last_request_ms != 0 && now_ms < last_request_ms + kClientHostRunFollowRetryMs) {
        return;
    }

    std::string error_message;
    g_local_transport.last_client_host_run_request_ms = now_ms;
    if (!QueueHubStartTestrun(&error_message)) {
        Log(
            "Multiplayer local UDP failed to follow host run intent. authority_participant_id=" +
            std::to_string(packet.participant_id) +
            " error=" + error_message);
        return;
    }

    Log(
        "Multiplayer local UDP queued host-authoritative run entry. authority_participant_id=" +
        std::to_string(packet.participant_id) +
        " sequence=" + std::to_string(packet.header.sequence));
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

            ParticipantTransformSample sample;
            sample.valid = true;
            sample.received_ms = now_ms;
            sample.sequence = packet.header.sequence;
            sample.run_nonce = packet.run_nonce;
            sample.scene_intent = scene_intent;
            sample.position_x = packet.position_x;
            sample.position_y = packet.position_y;
            sample.heading = packet.heading;
            AppendParticipantTransformSample(participant, sample);
        }
    });

    MaybeQueueClientHostRunStart(packet, scene_intent, from, now_ms);

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

void ApplyWorldSnapshotPacket(const WorldSnapshotPacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    const auto actor_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.actor_count, kWorldSnapshotMaxActors));
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);

    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    UpdateRuntimeState([&](RuntimeState& state) {
        WorldSnapshotRuntimeInfo snapshot;
        snapshot.valid = true;
        snapshot.authority_participant_id = packet.authority_participant_id;
        snapshot.received_ms = now_ms;
        snapshot.sequence = packet.header.sequence;
        snapshot.scene_epoch = packet.scene_epoch;
        snapshot.run_nonce = packet.run_nonce;
        snapshot.actor_total_count = packet.actor_total_count;
        snapshot.truncated = (packet.snapshot_flags & WorldSnapshotFlagTruncated) != 0;
        snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
        snapshot.actors.reserve(actor_count);

        for (std::uint8_t index = 0; index < actor_count; ++index) {
            const auto& packet_actor = packet.actors[index];
            if (packet_actor.network_actor_id == 0 ||
                packet_actor.native_type_id == 0 ||
                !std::isfinite(packet_actor.position_x) ||
                !std::isfinite(packet_actor.position_y) ||
                !std::isfinite(packet_actor.radius) ||
                packet_actor.radius < 0.0f) {
                continue;
            }

            WorldActorSnapshot actor;
            actor.network_actor_id = packet_actor.network_actor_id;
            actor.native_type_id = packet_actor.native_type_id;
            actor.enemy_type = packet_actor.enemy_type;
            actor.actor_slot = packet_actor.actor_slot;
            actor.world_slot = packet_actor.world_slot;
            actor.dead = (packet_actor.flags & WorldActorSnapshotFlagDead) != 0;
            actor.tracked_enemy = (packet_actor.flags & WorldActorSnapshotFlagTrackedEnemy) != 0;
            actor.lifecycle_owned = (packet_actor.flags & WorldActorSnapshotFlagLifecycleOwned) != 0;
            actor.anim_drive_state = packet_actor.anim_drive_state;
            actor.presentation_flags = packet_actor.presentation_flags;
            actor.position_x = packet_actor.position_x;
            actor.position_y = packet_actor.position_y;
            actor.radius = packet_actor.radius;
            actor.heading = std::isfinite(packet_actor.heading) ? packet_actor.heading : 0.0f;
            actor.hp = std::isfinite(packet_actor.hp) ? packet_actor.hp : 0.0f;
            actor.max_hp = std::isfinite(packet_actor.max_hp) ? packet_actor.max_hp : 0.0f;
            actor.anim_drive_state_word = packet_actor.anim_drive_state_word;
            actor.render_variant_primary = packet_actor.render_variant_primary;
            actor.render_variant_secondary = packet_actor.render_variant_secondary;
            actor.render_weapon_type = packet_actor.render_weapon_type;
            actor.render_selection_byte = packet_actor.render_selection_byte;
            actor.render_variant_tertiary = packet_actor.render_variant_tertiary;
            std::memcpy(
                actor.student_visual_state.data(),
                packet_actor.student_visual_state,
                actor.student_visual_state.size());
            snapshot.actors.push_back(actor);
        }

        AppendWorldSnapshot(&state, std::move(snapshot));
    });
}

void ApplyLootSnapshotPacket(const LootSnapshotPacket& packet, const sockaddr_in& from, std::uint64_t now_ms) {
    if (g_local_transport.is_host ||
        packet.authority_participant_id == 0 ||
        packet.authority_participant_id == g_local_transport.local_peer_id) {
        return;
    }

    const auto drop_count = static_cast<std::uint8_t>(
        (std::min<std::uint32_t>)(packet.drop_count, kLootSnapshotMaxDrops));
    UpsertPeerEndpoint(from, packet.authority_participant_id, now_ms);

    const auto scene_kind = static_cast<WorldSceneKind>(packet.scene_kind);
    UpdateRuntimeState([&](RuntimeState& state) {
        LootSnapshotRuntimeInfo snapshot;
        snapshot.valid = true;
        snapshot.authority_participant_id = packet.authority_participant_id;
        snapshot.received_ms = now_ms;
        snapshot.sequence = packet.header.sequence;
        snapshot.scene_epoch = packet.scene_epoch;
        snapshot.run_nonce = packet.run_nonce;
        snapshot.drop_total_count = packet.drop_total_count;
        snapshot.truncated = (packet.snapshot_flags & LootSnapshotFlagTruncated) != 0;
        snapshot.scene_intent = SceneIntentFromWorldSceneKind(scene_kind);
        snapshot.drops.reserve(drop_count);

        for (std::uint8_t index = 0; index < drop_count; ++index) {
            const auto& packet_drop = packet.drops[index];
            if (packet_drop.network_drop_id == 0 ||
                packet_drop.native_type_id == 0 ||
                !std::isfinite(packet_drop.position_x) ||
                !std::isfinite(packet_drop.position_y) ||
                !std::isfinite(packet_drop.radius) ||
                packet_drop.radius < 0.0f) {
                continue;
            }

            LootDropSnapshot drop;
            drop.network_drop_id = packet_drop.network_drop_id;
            drop.native_type_id = packet_drop.native_type_id;
            drop.drop_kind = LootDropKindFromPacketValue(packet_drop.drop_kind);
            drop.active = (packet_drop.flags & LootDropSnapshotFlagActive) != 0;
            drop.amount = packet_drop.amount;
            drop.amount_tier = packet_drop.amount_tier;
            drop.actor_slot = packet_drop.actor_slot;
            drop.world_slot = packet_drop.world_slot;
            drop.lifetime = packet_drop.lifetime;
            drop.position_x = packet_drop.position_x;
            drop.position_y = packet_drop.position_y;
            drop.radius = packet_drop.radius;
            snapshot.drops.push_back(drop);
        }

        state.loot_snapshot = std::move(snapshot);
    });
}

void ReceivePackets(std::uint64_t now_ms) {
    for (int packet_index = 0; packet_index < kMaxPacketsPerTick; ++packet_index) {
        std::array<char, sizeof(WorldSnapshotPacket)> packet_buffer{};
        sockaddr_in from{};
        int from_length = sizeof(from);
        const int received = recvfrom(
            g_local_transport.socket_handle,
            packet_buffer.data(),
            static_cast<int>(packet_buffer.size()),
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

        if (received < static_cast<int>(sizeof(PacketHeader))) {
            continue;
        }

        PacketHeader header{};
        std::memcpy(&header, packet_buffer.data(), sizeof(header));
        if (!IsValidPacketHeader(header)) {
            continue;
        }

        const auto kind = static_cast<PacketKind>(header.kind);
        if (kind == PacketKind::State && received == static_cast<int>(sizeof(StatePacket))) {
            StatePacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::State)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyRemoteStatePacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::WorldSnapshot && received == static_cast<int>(sizeof(WorldSnapshotPacket))) {
            WorldSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::WorldSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyWorldSnapshotPacket(packet, from, now_ms);
            continue;
        }

        if (kind == PacketKind::LootSnapshot && received == static_cast<int>(sizeof(LootSnapshotPacket))) {
            LootSnapshotPacket packet{};
            std::memcpy(&packet, packet_buffer.data(), sizeof(packet));
            if (!IsValidHeader(packet.header, PacketKind::LootSnapshot)) {
                continue;
            }
            g_local_transport.packets_received += 1;
            ApplyLootSnapshotPacket(packet, from, now_ms);
        }
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
    SendWorldSnapshot(now_ms);
    SendLootSnapshot(now_ms);
    PublishLocalTransportRuntimeState();
}

bool IsLocalTransportEnabled() {
    return g_local_transport.initialized;
}

bool IsLocalTransportHost() {
    return g_local_transport.initialized && g_local_transport.is_host;
}

bool IsLocalTransportClient() {
    return g_local_transport.initialized && !g_local_transport.is_host;
}

}  // namespace sdmod::multiplayer
