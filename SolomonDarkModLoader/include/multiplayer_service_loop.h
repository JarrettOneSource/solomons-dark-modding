#pragma once

#include <cstdint>

namespace sdmod::multiplayer {

bool StartServiceLoop();
void StopServiceLoop();
void TickSessionAndTransportOnAppThread(std::uint64_t now_ms);
bool IsServiceLoopRunning();
std::uint32_t GetServiceTickIntervalMs();

}  // namespace sdmod::multiplayer
