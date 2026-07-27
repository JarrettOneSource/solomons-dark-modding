#pragma once

#include <cstdint>
#include <filesystem>
#include <string>

namespace sdmod {
struct LoadingScreenSnapshot;
}

namespace sdmod::detail {

inline constexpr std::uint64_t
    kLoadingScreenPresentationDelayMs = 150;

bool StartLoadingScreenRenderer(
    std::uintptr_t device_pointer_global,
    const std::filesystem::path& background_path,
    std::string* error_message);
void CaptureLoadingScreenEvidenceFrame(
    const LoadingScreenSnapshot& snapshot);
void PresentLoadingScreenFrame();
void StopLoadingScreenRenderer();

}  // namespace sdmod::detail
