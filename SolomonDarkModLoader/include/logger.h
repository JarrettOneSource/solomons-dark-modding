#pragma once

#include <filesystem>
#include <string_view>

namespace sdmod {

void InitializeLogger(const std::filesystem::path& log_path);
void FlushLogger();
std::filesystem::path GetLoggerPath();
void ShutdownLogger();
void Log(std::string_view message);

}  // namespace sdmod
