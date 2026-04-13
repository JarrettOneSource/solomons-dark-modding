#pragma once

#include <filesystem>
#include <string_view>

namespace sdmod {

void InitializeLogger(const std::filesystem::path& log_path);
void InstallCrashHandler(const std::filesystem::path& crash_log_path);
void FlushLogger();
std::filesystem::path GetLoggerPath();
void ShutdownCrashHandler();
void ShutdownLogger();
void Log(std::string_view message);
void SetCrashContextSummary(std::string_view summary);

}  // namespace sdmod
