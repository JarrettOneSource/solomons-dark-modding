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

struct LoadingScreenRect {
    float left = 0.0f;
    float top = 0.0f;
    float right = 0.0f;
    float bottom = 0.0f;
};

struct LoadingScreenRenderLayout {
    std::uint64_t sequence = 0;
    std::string stage_id;
    std::string label;
    std::string background_art_id;
    float progress = 0.0f;
    bool progress_bar_visible = false;
    std::uint32_t viewport_x = 0;
    std::uint32_t viewport_y = 0;
    std::uint32_t viewport_width = 0;
    std::uint32_t viewport_height = 0;
    std::uint32_t background_width = 0;
    std::uint32_t background_height = 0;
    float crop_u0 = 0.0f;
    float crop_v0 = 0.0f;
    float crop_u1 = 1.0f;
    float crop_v1 = 1.0f;
    LoadingScreenRect background;
    LoadingScreenRect bottom_scrim;
    LoadingScreenRect progress_border;
    LoadingScreenRect progress_track;
    LoadingScreenRect progress_fill;
    LoadingScreenRect label_rect;
    float text_scale = 1.0f;
};

bool StartLoadingScreenRenderer(
    std::uintptr_t device_pointer_global,
    const std::filesystem::path& background_path,
    std::string* error_message);
void CaptureLoadingScreenEvidenceFrame(
    const LoadingScreenSnapshot& snapshot,
    const LoadingScreenRenderLayout* layout = nullptr);
bool TryGetLastLoadingScreenRenderLayout(
    LoadingScreenRenderLayout* layout);
void PresentLoadingScreenFrame();
void StopLoadingScreenRenderer();

}  // namespace sdmod::detail
