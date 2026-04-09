#pragma once

namespace sdmod {

[[nodiscard]] bool StartLuaExecPipeServer();
void StopLuaExecPipeServer();
bool IsLuaExecPipeServerRunning();

}  // namespace sdmod
