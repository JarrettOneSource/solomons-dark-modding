#pragma once

#include <string>

namespace sdmod {

bool InitializeNativeCloseUrlPatch(std::string* error_message);
void ShutdownNativeCloseUrlPatch();

}  // namespace sdmod
