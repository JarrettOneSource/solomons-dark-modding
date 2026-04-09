#pragma once

#include <cstdint>

namespace sdmod::multiplayer {

bool StartServiceLoop();
void StopServiceLoop();
bool IsServiceLoopRunning();
std::uint32_t GetServiceTickIntervalMs();

}  // namespace sdmod::multiplayer
