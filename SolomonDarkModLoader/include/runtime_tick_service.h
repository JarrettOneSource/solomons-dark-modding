#pragma once

#include <cstdint>

namespace sdmod {

struct RuntimeTickContext {
    std::uint32_t tick_interval_ms;
    std::uint64_t tick_count;
    std::uint64_t monotonic_milliseconds;
};

bool StartRuntimeTickService();
void StopRuntimeTickService();
bool IsRuntimeTickServiceRunning();
std::uint32_t GetRuntimeTickServiceIntervalMs();

}  // namespace sdmod
