#pragma once

#include "runtime_bootstrap.h"
#include "sdmod_plugin_api.h"

#include <cstddef>
#include <string>

namespace sdmod {

bool InitializeNativeMods(const RuntimeBootstrap& bootstrap, std::string* error_message);
void ShutdownNativeMods();
std::size_t GetLoadedNativeModCount();
bool HasLoadedNativeMods();
void DispatchNativeModRuntimeTick(const SDModRuntimeTickContext& context);

}  // namespace sdmod
