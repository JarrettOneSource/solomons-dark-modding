#pragma once

#include <cstdint>

namespace sdmod {

bool TryTriggerRunEnemyDeath(uintptr_t actor_address, std::uint32_t* exception_code);

}  // namespace sdmod
