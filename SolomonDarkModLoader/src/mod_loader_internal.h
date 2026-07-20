#pragma once

#include <string>

namespace sdmod {

bool InitializeBackgroundFocusBypass(std::string* error_message);
void ShutdownBackgroundFocusBypass();

bool InitializeCpuLifecycleGuard(std::string* error_message);
void ShutdownCpuLifecycleGuard();
void LogCpuLifecycleGuardActivity();

void PumpGameplayMainThreadWork();
void PumpGameplayPostStockTickWork();

bool InitializeRunLifecycleHooks(std::string* error_message);
void ShutdownRunLifecycleHooks();

}  // namespace sdmod
