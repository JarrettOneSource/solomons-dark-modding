#pragma once

#include "runtime_bootstrap.h"
#include "sdmod_plugin_api.h"

#include <cstddef>
#include <string>

namespace sdmod {

bool InitializeLuaEngine(const RuntimeBootstrap& bootstrap, std::string* error_message);
void ShutdownLuaEngine();
bool IsLuaEngineInitialized();
std::size_t GetLoadedLuaModCount();
bool HasLuaRuntimeTickHandlers();
void DispatchLuaRuntimeTick(const SDModRuntimeTickContext& context);

}  // namespace sdmod
