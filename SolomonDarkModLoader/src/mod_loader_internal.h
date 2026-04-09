#pragma once

#include <string>

namespace sdmod {

bool InitializeBackgroundFocusBypass(std::string* error_message);
void ShutdownBackgroundFocusBypass();

bool InitializeRunLifecycleHooks(std::string* error_message);
void ShutdownRunLifecycleHooks();

}  // namespace sdmod
