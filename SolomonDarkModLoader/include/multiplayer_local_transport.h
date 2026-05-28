#pragma once

#include <cstdint>

namespace sdmod::multiplayer {

bool InitializeLocalTransport();
void ShutdownLocalTransport();
void TickLocalTransport(std::uint64_t now_ms);
bool IsLocalTransportEnabled();

}  // namespace sdmod::multiplayer
