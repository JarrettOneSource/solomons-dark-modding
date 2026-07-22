#pragma once

#include <cstdint>
#include <string>

namespace sdmod {

bool TryTriggerRunEnemyDeath(uintptr_t actor_address, std::uint32_t* exception_code);
bool QueueNativeEnemyDeathProbe(
    uintptr_t actor_address,
    uintptr_t expected_config_address,
    uintptr_t restore_config_address,
    std::uint64_t* request_serial,
    std::string* error_message);
bool GetNativeEnemyDeathProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    std::uint32_t* exception_code,
    bool* config_restored,
    std::string* error_message);

}  // namespace sdmod
