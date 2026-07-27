#pragma once

#include <cstddef>
#include <cstdint>

namespace sdmod::multiplayer {

bool InitializeSteamSession();
void ShutdownSteamSession();
void TickSteamSession(std::uint64_t now_ms);
bool IsSteamSessionEnabled();
void RecoverSteamSessionFromGameplayCongestion(
    std::uint64_t remote_steam_id,
    std::uint64_t duration_ms,
    std::size_t queued_reliable_packets,
    std::uint64_t dropped_disposable_packets);

}  // namespace sdmod::multiplayer
