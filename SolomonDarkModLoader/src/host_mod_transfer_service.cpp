#include "host_mod_transfer_service.h"

#include "logger.h"
#include "multiplayer_runtime_protocol.h"

#include <Windows.h>
#include <process.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <fstream>
#include <limits>
#include <mutex>
#include <string>
#include <utility>

namespace sdmod::multiplayer {
namespace {

constexpr std::size_t kIndexHeaderBytes = 96;
constexpr std::size_t kIndexEntryBytes = 264;
constexpr std::size_t kMaximumQueuedRequests = 64;
constexpr std::size_t kMaximumQueuedChunkRequests = 24;
constexpr std::size_t kMaximumChunkRequestsPerTransfer = 8;
constexpr std::size_t kMaximumPreparedResponseBytesPerTransfer = 64 * 1024;
constexpr std::size_t kMaximumPreparedResponseBytes = 192 * 1024;
constexpr std::size_t kMaximumActiveTransfers = 3;
constexpr std::uint64_t kTransferIdleExpiryMs = 30'000;

using Digest = std::array<std::uint8_t, kModTransferDigestBytes>;
using ClientId = std::array<std::uint8_t, kModTransferClientIdBytes>;

struct TransferIndexEntry {
    std::array<char, kModTransferModIdBytes> mod_id{};
    std::array<char, kModTransferVersionBytes> version{};
    Digest content_sha256{};
    Digest package_sha256{};
    std::uint64_t package_bytes = 0;
    std::filesystem::path package_path;
};

struct TransferIndex {
    Digest host_manifest_sha256{};
    Digest index_sha256{};
    std::uint64_t total_package_bytes = 0;
    std::vector<TransferIndexEntry> entries;
};

struct QueuedRequest {
    HostModTransferRoute route;
    std::vector<std::uint8_t> bytes;
};

struct ActiveTransfer {
    HostModTransferRoute route;
    ClientId client_id{};
    std::uint64_t last_request_ms = 0;
};

enum class IndexState {
    Loading,
    Ready,
    Unavailable,
};

std::mutex g_mutex;
std::condition_variable g_work_ready;
std::deque<QueuedRequest> g_requests;
std::deque<HostModTransferPreparedResponse> g_responses;
std::size_t g_response_bytes = 0;
std::atomic<bool> g_stop_requested{false};
HANDLE g_worker_thread = nullptr;
std::filesystem::path g_stage_runtime_directory;
Digest g_expected_manifest{};
bool g_is_host = false;
std::atomic<IndexState> g_index_state{IndexState::Unavailable};
TransferIndex g_index;
std::vector<ActiveTransfer> g_active_transfers;
std::uint32_t g_next_sequence = 1;

bool SameRoute(
    const HostModTransferRoute& left,
    const HostModTransferRoute& right) {
    if (left.backend != right.backend) {
        return false;
    }
    return left.backend == HostModTransferBackend::Steam
        ? left.steam_id != 0 && left.steam_id == right.steam_id
        : left.ipv4_address == right.ipv4_address &&
              left.port != 0 && left.port == right.port;
}

bool IsZero(const std::uint8_t* bytes, std::size_t size) {
    if (bytes == nullptr) {
        return true;
    }
    for (std::size_t index = 0; index < size; ++index) {
        if (bytes[index] != 0) {
            return false;
        }
    }
    return true;
}

#include "host_mod_transfer_service/index_loading.inl"

ClientId ReadClientId(const std::vector<std::uint8_t>& bytes) {
    ClientId result{};
    if (bytes.size() >= 36) {
        std::memcpy(result.data(), bytes.data() + 20, result.size());
    }
    return result;
}

ActiveTransfer* FindTransfer(
    const HostModTransferRoute& route,
    const ClientId& client_id) {
    const auto found = std::find_if(
        g_active_transfers.begin(),
        g_active_transfers.end(),
        [&](const ActiveTransfer& transfer) {
            return SameRoute(transfer.route, route) &&
                transfer.client_id == client_id;
        });
    return found == g_active_transfers.end() ? nullptr : &*found;
}

void ExpireTransfers(std::uint64_t now_ms) {
    g_active_transfers.erase(
        std::remove_if(
            g_active_transfers.begin(),
            g_active_transfers.end(),
            [&](const ActiveTransfer& transfer) {
                return now_ms >= transfer.last_request_ms &&
                    now_ms - transfer.last_request_ms >= kTransferIdleExpiryMs;
            }),
        g_active_transfers.end());
}

template <typename Packet>
void QueueResponse(
    const HostModTransferRoute& route,
    const Packet& packet,
    bool chunk = false,
    std::size_t wire_size = sizeof(Packet)) {
    HostModTransferPreparedResponse response;
    response.route = route;
    response.chunk = chunk;
    const auto* begin = reinterpret_cast<const std::uint8_t*>(&packet);
    response.bytes.assign(begin, begin + wire_size);
    std::lock_guard<std::mutex> lock(g_mutex);
    std::size_t transfer_response_bytes = 0;
    for (const auto& queued : g_responses) {
        if (SameRoute(queued.route, route) &&
            queued.bytes.size() >= 36 &&
            response.bytes.size() >= 36 &&
            std::memcmp(
                queued.bytes.data() + 20,
                response.bytes.data() + 20,
                kModTransferClientIdBytes) == 0) {
            transfer_response_bytes += queued.bytes.size();
        }
    }
    if (transfer_response_bytes + response.bytes.size() >
        kMaximumPreparedResponseBytesPerTransfer) {
        return;
    }
    if (g_response_bytes + response.bytes.size() >
        kMaximumPreparedResponseBytes) {
        return;
    }
    g_response_bytes += response.bytes.size();
    g_responses.push_back(std::move(response));
}

void ProcessManifest(const QueuedRequest& request) {
    ModTransferManifestRequestPacket packet{};
    std::memcpy(&packet, request.bytes.data(), sizeof(packet));
    ModTransferManifestResponsePacket response{};
    response.header = MakePacketHeader(
        PacketKind::ModTransferManifestResponse, g_next_sequence++);
    response.lobby_id = packet.lobby_id;
    std::memcpy(response.client_transfer_id, packet.client_transfer_id, 16);
    std::memcpy(response.host_manifest_sha256, g_expected_manifest.data(), 32);
    const bool expected_matches =
        IsZero(packet.expected_manifest_sha256, 32) ||
        std::memcmp(packet.expected_manifest_sha256,
                    g_expected_manifest.data(), 32) == 0;
    if (!g_is_host) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::NotHost);
    } else if (!expected_matches) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::FingerprintMismatch);
    } else if (g_index_state != IndexState::Ready) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::Unavailable);
    } else {
        const auto client_id = ReadClientId(request.bytes);
        auto* active = FindTransfer(request.route, client_id);
        if (active == nullptr &&
            g_active_transfers.size() >= kMaximumActiveTransfers) {
            response.status_code = static_cast<std::uint8_t>(
                ModTransferStatusCode::Busy);
        } else {
            if (active == nullptr) {
                g_active_transfers.push_back({
                    request.route, client_id, GetTickCount64()});
            } else {
                active->last_request_ms = GetTickCount64();
            }
            response.status_code = static_cast<std::uint8_t>(
                ModTransferStatusCode::Ready);
            std::memcpy(response.index_sha256, g_index.index_sha256.data(), 32);
            response.package_count =
                static_cast<std::uint32_t>(g_index.entries.size());
            response.total_package_bytes = g_index.total_package_bytes;
        }
    }
    QueueResponse(request.route, response);
}

bool ValidateTransferIdentity(
    const QueuedRequest& request,
    const std::uint8_t* host_manifest,
    const std::uint8_t* index_digest,
    ActiveTransfer** active) {
    const auto client_id = ReadClientId(request.bytes);
    *active = FindTransfer(request.route, client_id);
    if (*active == nullptr || g_index_state != IndexState::Ready ||
        std::memcmp(host_manifest, g_index.host_manifest_sha256.data(), 32) != 0 ||
        std::memcmp(index_digest, g_index.index_sha256.data(), 32) != 0) {
        return false;
    }
    (*active)->last_request_ms = GetTickCount64();
    return true;
}

void ProcessDescriptor(const QueuedRequest& request) {
    ModTransferDescriptorRequestPacket packet{};
    std::memcpy(&packet, request.bytes.data(), sizeof(packet));
    ModTransferDescriptorResponsePacket response{};
    response.header = MakePacketHeader(
        PacketKind::ModTransferDescriptorResponse, g_next_sequence++);
    response.lobby_id = packet.lobby_id;
    std::memcpy(response.client_transfer_id, packet.client_transfer_id, 16);
    std::memcpy(response.host_manifest_sha256, g_expected_manifest.data(), 32);
    if (g_index_state == IndexState::Ready) {
        std::memcpy(response.index_sha256, g_index.index_sha256.data(), 32);
    }
    response.descriptor_index = packet.descriptor_index;
    ActiveTransfer* active = nullptr;
    if (!ValidateTransferIdentity(
            request,
            packet.host_manifest_sha256,
            packet.index_sha256,
            &active)) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::StaleIndex);
    } else if (packet.descriptor_index >= g_index.entries.size()) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::BoundsRejected);
    } else {
        const auto& entry = g_index.entries[packet.descriptor_index];
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::Ready);
        std::memcpy(response.mod_id, entry.mod_id.data(), entry.mod_id.size());
        std::memcpy(response.version, entry.version.data(), entry.version.size());
        std::memcpy(response.content_sha256, entry.content_sha256.data(), 32);
        std::memcpy(response.package_sha256, entry.package_sha256.data(), 32);
        response.package_bytes = entry.package_bytes;
    }
    QueueResponse(request.route, response);
}

void ProcessChunk(const QueuedRequest& request) {
    ModTransferChunkRequestPacket packet{};
    std::memcpy(&packet, request.bytes.data(), sizeof(packet));
    ModTransferChunkResponsePacket response{};
    response.header = MakePacketHeader(
        PacketKind::ModTransferChunkResponse, g_next_sequence++);
    response.lobby_id = packet.lobby_id;
    std::memcpy(response.client_transfer_id, packet.client_transfer_id, 16);
    response.descriptor_index = packet.descriptor_index;
    std::memcpy(response.package_sha256, packet.package_sha256, 32);
    response.package_bytes = packet.package_bytes;
    response.offset = packet.offset;
    ActiveTransfer* active = nullptr;
    const bool identity_ok = ValidateTransferIdentity(
        request,
        packet.host_manifest_sha256,
        packet.index_sha256,
        &active);
    const bool index_ok = identity_ok &&
        packet.descriptor_index < g_index.entries.size();
    const auto* entry = index_ok
        ? &g_index.entries[packet.descriptor_index]
        : nullptr;
    const bool bounds_ok = entry != nullptr &&
        std::memcmp(packet.package_sha256, entry->package_sha256.data(), 32) == 0 &&
        packet.package_bytes == entry->package_bytes &&
        packet.requested_bytes > 0 &&
        packet.requested_bytes <= kModTransferChunkPayloadBytes &&
        packet.offset % kModTransferChunkPayloadBytes == 0 &&
        packet.offset < packet.package_bytes &&
        packet.requested_bytes <= packet.package_bytes - packet.offset;
    if (!identity_ok) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::StaleIndex);
    } else if (!bounds_ok) {
        response.status_code = static_cast<std::uint8_t>(
            ModTransferStatusCode::BoundsRejected);
    } else {
        std::ifstream input(entry->package_path, std::ios::binary);
        input.seekg(static_cast<std::streamoff>(packet.offset));
        input.read(
            reinterpret_cast<char*>(response.payload),
            static_cast<std::streamsize>(packet.requested_bytes));
        Digest payload_digest{};
        if (!input ||
            input.gcount() !=
                static_cast<std::streamsize>(packet.requested_bytes) ||
            !HashBytes(
                response.payload,
                packet.requested_bytes,
                &payload_digest)) {
            response.status_code = static_cast<std::uint8_t>(
                ModTransferStatusCode::Unavailable);
        } else {
            response.status_code = static_cast<std::uint8_t>(
                ModTransferStatusCode::Ready);
            response.payload_bytes = packet.requested_bytes;
            std::memcpy(
                response.payload_sha256,
                payload_digest.data(),
                payload_digest.size());
        }
    }
    QueueResponse(
        request.route,
        response,
        true,
        ModTransferChunkResponsePacketWireSize(response.payload_bytes));
}

void ProcessTerminal(const QueuedRequest& request) {
    PacketHeader header{};
    std::memcpy(&header, request.bytes.data(), sizeof(header));
    const auto client_id = ReadClientId(request.bytes);
    if (FindTransfer(request.route, client_id) == nullptr) {
        return;
    }
    Digest package_digest{};
    if (static_cast<PacketKind>(header.kind) ==
        PacketKind::ModTransferComplete) {
        ModTransferCompletePacket packet{};
        std::memcpy(&packet, request.bytes.data(), sizeof(packet));
        const auto package = std::find_if(
            g_index.entries.begin(),
            g_index.entries.end(),
            [&](const TransferIndexEntry& entry) {
                return std::memcmp(
                    packet.package_sha256,
                    entry.package_sha256.data(),
                    entry.package_sha256.size()) == 0;
            });
        if (g_index_state != IndexState::Ready ||
            std::memcmp(
                packet.host_manifest_sha256,
                g_index.host_manifest_sha256.data(),
                g_index.host_manifest_sha256.size()) != 0 ||
            std::memcmp(
                packet.index_sha256,
                g_index.index_sha256.data(),
                g_index.index_sha256.size()) != 0 ||
            package == g_index.entries.end()) {
            return;
        }
        std::memcpy(
            package_digest.data(),
            packet.package_sha256,
            package_digest.size());
        Log(
            "Host mod transfer completed. package_sha256=" +
            DigestHex(package_digest));
    } else {
        ModTransferAbortPacket packet{};
        std::memcpy(&packet, request.bytes.data(), sizeof(packet));
        if (packet.reason_code < static_cast<std::uint8_t>(
                ModTransferAbortReason::Completed) ||
            packet.reason_code > static_cast<std::uint8_t>(
                ModTransferAbortReason::HostUnavailable) ||
            std::memcmp(
                packet.host_manifest_sha256,
                g_expected_manifest.data(),
                g_expected_manifest.size()) != 0) {
            return;
        }
        std::memcpy(
            package_digest.data(),
            packet.package_sha256,
            package_digest.size());
        Log(
            "Host mod transfer aborted. reason=" +
            std::to_string(packet.reason_code) +
            " package_sha256=" + DigestHex(package_digest));
    }
    g_active_transfers.erase(
        std::remove_if(
            g_active_transfers.begin(),
            g_active_transfers.end(),
            [&](const ActiveTransfer& transfer) {
                return SameRoute(transfer.route, request.route) &&
                    transfer.client_id == client_id;
            }),
        g_active_transfers.end());
}

void ProcessRequest(const QueuedRequest& request) {
    PacketHeader header{};
    std::memcpy(&header, request.bytes.data(), sizeof(header));
    ExpireTransfers(GetTickCount64());
    switch (static_cast<PacketKind>(header.kind)) {
    case PacketKind::ModTransferManifestRequest:
        ProcessManifest(request);
        break;
    case PacketKind::ModTransferDescriptorRequest:
        ProcessDescriptor(request);
        break;
    case PacketKind::ModTransferChunkRequest:
        ProcessChunk(request);
        break;
    case PacketKind::ModTransferComplete:
    case PacketKind::ModTransferAbort:
        ProcessTerminal(request);
        break;
    default:
        break;
    }
}

unsigned __stdcall WorkerMain(void*) {
    TransferIndex index;
    std::string error;
    const bool loaded = g_is_host && LoadIndex(&index, &error);
    if (loaded) {
        g_index = std::move(index);
        g_index_state = IndexState::Ready;
        Log(
            "Host mod transfer index ready. packages=" +
            std::to_string(g_index.entries.size()) +
            " total_bytes=" +
            std::to_string(g_index.total_package_bytes) +
            " index_sha256=" + DigestHex(g_index.index_sha256));
    } else {
        g_index_state = IndexState::Unavailable;
        if (g_is_host) {
            Log("Host mod transfer unavailable: " + error + ".");
        }
    }
    while (!g_stop_requested.load(std::memory_order_acquire)) {
        QueuedRequest request;
        {
            std::unique_lock<std::mutex> lock(g_mutex);
            g_work_ready.wait(lock, [] {
                return g_stop_requested.load(std::memory_order_acquire) ||
                    !g_requests.empty();
            });
            if (g_stop_requested.load(std::memory_order_acquire)) break;
            request = std::move(g_requests.front());
            g_requests.pop_front();
        }
        ProcessRequest(request);
    }
    return 0;
}

bool ExpectedPacketSize(PacketKind kind, std::size_t size) {
    switch (kind) {
    case PacketKind::ModTransferManifestRequest:
        return size == sizeof(ModTransferManifestRequestPacket);
    case PacketKind::ModTransferDescriptorRequest:
        return size == sizeof(ModTransferDescriptorRequestPacket);
    case PacketKind::ModTransferChunkRequest:
        return size == sizeof(ModTransferChunkRequestPacket);
    case PacketKind::ModTransferComplete:
        return size == sizeof(ModTransferCompletePacket);
    case PacketKind::ModTransferAbort:
        return size == sizeof(ModTransferAbortPacket);
    default:
        return false;
    }
}

}  // namespace

bool InitializeHostModTransferService(
    const std::filesystem::path& stage_runtime_directory,
    bool is_host,
    std::string_view manifest_sha256) {
    ShutdownHostModTransferService();
    g_stage_runtime_directory = stage_runtime_directory;
    g_is_host = is_host;
    g_index_state = is_host ? IndexState::Loading : IndexState::Unavailable;
    g_index = TransferIndex{};
    g_active_transfers.clear();
    g_next_sequence = 1;
    if (!ParseHexDigest(manifest_sha256, &g_expected_manifest)) {
        Log("Host mod transfer disabled by an invalid stage fingerprint.");
        return !is_host;
    }
    if (!is_host) return true;
    g_stop_requested.store(false, std::memory_order_release);
    const auto thread = _beginthreadex(
        nullptr, 0, &WorkerMain, nullptr, 0, nullptr);
    if (thread == 0) {
        Log("Host mod transfer worker could not start.");
        return false;
    }
    g_worker_thread = reinterpret_cast<HANDLE>(thread);
    return true;
}

void ShutdownHostModTransferService() {
    g_stop_requested.store(true, std::memory_order_release);
    g_work_ready.notify_all();
    if (g_worker_thread != nullptr) {
        WaitForSingleObject(g_worker_thread, INFINITE);
        CloseHandle(g_worker_thread);
        g_worker_thread = nullptr;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_requests.clear();
    g_responses.clear();
    g_response_bytes = 0;
    g_active_transfers.clear();
    g_index = TransferIndex{};
    g_index_state = IndexState::Unavailable;
}

bool IsHostModTransferPacket(const void* data, std::size_t size) {
    if (data == nullptr || size < sizeof(PacketHeader)) return false;
    PacketHeader header{};
    std::memcpy(&header, data, sizeof(header));
    if (!IsValidPacketHeader(header)) return false;
    return ExpectedPacketSize(static_cast<PacketKind>(header.kind), size);
}

bool SubmitHostModTransferPacket(
    const HostModTransferRoute& route,
    const void* data,
    std::size_t size) {
    if (!g_is_host || g_worker_thread == nullptr ||
        !IsHostModTransferPacket(data, size)) {
        return false;
    }
    const auto* begin = static_cast<const std::uint8_t*>(data);
    PacketHeader header{};
    std::memcpy(&header, data, sizeof(header));
    const auto kind = static_cast<PacketKind>(header.kind);
    if (kind == PacketKind::ModTransferManifestRequest &&
        g_index_state.load(std::memory_order_acquire) ==
            IndexState::Loading) {
        ModTransferManifestRequestPacket packet{};
        std::memcpy(&packet, data, sizeof(packet));
        ModTransferManifestResponsePacket response{};
        response.header = MakePacketHeader(
            PacketKind::ModTransferManifestResponse,
            packet.header.sequence);
        response.lobby_id = packet.lobby_id;
        std::memcpy(
            response.client_transfer_id,
            packet.client_transfer_id,
            kModTransferClientIdBytes);
        std::memcpy(
            response.host_manifest_sha256,
            g_expected_manifest.data(),
            g_expected_manifest.size());
        response.status_code = static_cast<std::uint8_t>(
            IsZero(packet.expected_manifest_sha256, kModTransferDigestBytes) ||
            std::memcmp(
                packet.expected_manifest_sha256,
                g_expected_manifest.data(),
                g_expected_manifest.size()) == 0
                ? ModTransferStatusCode::Busy
                : ModTransferStatusCode::FingerprintMismatch);
        QueueResponse(route, response);
        return true;
    }
    const ClientId client_id = [&] {
        ClientId value{};
        std::memcpy(value.data(), begin + 20, value.size());
        return value;
    }();
    std::lock_guard<std::mutex> lock(g_mutex);
    const auto chunk_count = std::count_if(
        g_requests.begin(), g_requests.end(), [](const QueuedRequest& request) {
            PacketHeader queued{};
            std::memcpy(&queued, request.bytes.data(), sizeof(queued));
            return static_cast<PacketKind>(queued.kind) ==
                PacketKind::ModTransferChunkRequest;
        });
    const auto client_chunk_count = std::count_if(
        g_requests.begin(), g_requests.end(), [&](const QueuedRequest& request) {
            PacketHeader queued{};
            std::memcpy(&queued, request.bytes.data(), sizeof(queued));
            return static_cast<PacketKind>(queued.kind) ==
                    PacketKind::ModTransferChunkRequest &&
                SameRoute(request.route, route) &&
                ReadClientId(request.bytes) == client_id;
        });
    if (g_requests.size() >= kMaximumQueuedRequests ||
        (kind == PacketKind::ModTransferChunkRequest &&
         (chunk_count >= kMaximumQueuedChunkRequests ||
          client_chunk_count >= kMaximumChunkRequestsPerTransfer))) {
        return false;
    }
    g_requests.push_back({
        route,
        std::vector<std::uint8_t>(begin, begin + size)});
    g_work_ready.notify_one();
    return true;
}

std::vector<HostModTransferPreparedResponse>
TakeHostModTransferResponses(
    HostModTransferBackend backend,
    std::size_t metadata_budget,
    std::size_t chunk_budget) {
    std::vector<HostModTransferPreparedResponse> result;
    std::lock_guard<std::mutex> lock(g_mutex);
    for (auto iterator = g_responses.begin(); iterator != g_responses.end();) {
        if (iterator->route.backend != backend ||
            (iterator->chunk ? chunk_budget == 0 : metadata_budget == 0)) {
            ++iterator;
            continue;
        }
        if (iterator->chunk) --chunk_budget;
        else --metadata_budget;
        g_response_bytes -= iterator->bytes.size();
        result.push_back(std::move(*iterator));
        iterator = g_responses.erase(iterator);
    }
    return result;
}

}  // namespace sdmod::multiplayer
