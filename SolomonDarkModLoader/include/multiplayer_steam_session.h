#pragma once

#include "multiplayer_runtime_protocol.h"

#include <cstdint>

namespace sdmod::multiplayer {

bool InitializeSteamSession();
void ShutdownSteamSession();
void TickSteamSession(std::uint64_t now_ms);
bool IsSteamSessionEnabled();
bool IsSteamSessionHost();
void RequestSteamSessionTeardown(
    SessionGoodbyeReason reason,
    bool notify_peers);
bool IsSteamSessionTeardownComplete();

}  // namespace sdmod::multiplayer
