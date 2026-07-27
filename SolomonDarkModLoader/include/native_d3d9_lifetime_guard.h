#pragma once

#include <string>

namespace sdmod {

bool InitializeNativeD3d9LifetimeGuard(
    std::string* error_message);
bool IsNativeD3d9LifetimeGuardInstalled();

}  // namespace sdmod
