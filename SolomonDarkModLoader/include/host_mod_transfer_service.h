#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string_view>
#include <vector>

namespace sdmod::multiplayer {

enum class HostModTransferBackend : std::uint8_t {
    LocalUdp = 1,
    Steam = 2,
};

struct HostModTransferRoute {
    HostModTransferBackend backend = HostModTransferBackend::LocalUdp;
    std::uint32_t ipv4_address = 0;
    std::uint16_t port = 0;
    std::uint64_t steam_id = 0;
};

struct HostModTransferPreparedResponse {
    HostModTransferRoute route;
    std::vector<std::uint8_t> bytes;
    bool chunk = false;
};

bool InitializeHostModTransferService(
    const std::filesystem::path& stage_runtime_directory,
    bool is_host,
    std::string_view manifest_sha256);
void ShutdownHostModTransferService();
bool IsHostModTransferPacket(const void* data, std::size_t size);
bool SubmitHostModTransferPacket(
    const HostModTransferRoute& route,
    const void* data,
    std::size_t size);
std::vector<HostModTransferPreparedResponse>
TakeHostModTransferResponses(
    HostModTransferBackend backend,
    std::size_t metadata_budget,
    std::size_t chunk_budget);

}  // namespace sdmod::multiplayer
