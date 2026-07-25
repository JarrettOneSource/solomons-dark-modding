#pragma once

#include <string>

namespace sdmod {

bool InitializeLaunchAudioDisable(std::string* error_message);
void ShutdownLaunchAudioDisable();

}  // namespace sdmod
