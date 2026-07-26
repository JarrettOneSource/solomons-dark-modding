#pragma once

#include <string>
#include <string_view>

namespace sdmod {

struct MultiplayerJoinFlowPresentation {
    bool visible = false;
    std::string message;
};

bool InitializeMultiplayerJoinFlow();
void ShutdownMultiplayerJoinFlow();
void TickMultiplayerJoinFlow();
void ObserveMultiplayerJoinFlowSurface(std::string_view surface_id);
void NotifyMultiplayerJoinFlowRunStart();
MultiplayerJoinFlowPresentation GetMultiplayerJoinFlowPresentation();

}  // namespace sdmod
