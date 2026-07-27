#pragma once

#include <cstdint>
#include <string>

namespace sdmod::multiplayer {

bool RequestSessionLeaveAfterPipeAck(std::string* error_message);
void ResolveSessionLeavePipeResponse(bool delivered);
void NotifyRemoteHostSessionClosed();
void NotifySessionAuthorityLost();
void TickSessionTeardownOnAppThread(std::uint64_t now_ms);
void PrepareSessionTeardownForProcessExit();
void ResetSessionTeardownCoordinator();

}  // namespace sdmod::multiplayer
