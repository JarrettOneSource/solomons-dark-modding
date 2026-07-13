#pragma once

#include <cstdint>

namespace sdmod::multiplayer {

bool InitializeSteamSession();
void ShutdownSteamSession();
void TickSteamSession(std::uint64_t now_ms);
bool IsSteamSessionEnabled();

}  // namespace sdmod::multiplayer
