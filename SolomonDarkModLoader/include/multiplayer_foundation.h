#pragma once

#include "multiplayer_runtime_state.h"

namespace sdmod::multiplayer {

void InitializeFoundation();
void ShutdownFoundation();
bool IsFoundationInitialized();
RuntimeState SnapshotFoundationState();

}  // namespace sdmod::multiplayer
