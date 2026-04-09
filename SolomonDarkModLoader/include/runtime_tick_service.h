#pragma once

#include <cstdint>

namespace sdmod {

bool StartRuntimeTickService();
void StopRuntimeTickService();
bool IsRuntimeTickServiceRunning();
std::uint32_t GetRuntimeTickServiceIntervalMs();

}  // namespace sdmod
