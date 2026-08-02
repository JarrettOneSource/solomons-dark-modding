#pragma once

#include <cstdint>
#include <string_view>

namespace sdmod {

struct NativeWorldIndicatorColor {
    std::uint8_t red = 255;
    std::uint8_t green = 255;
    std::uint8_t blue = 255;
    std::uint8_t alpha = 255;
};

bool DrawNativeWorldIndicatorExactText(
    std::string_view text,
    float x,
    float y);
bool TryProjectNativeWorldIndicatorPoint(
    float world_x,
    float world_y,
    float* screen_x,
    float* screen_y);
bool DrawNativeWorldIndicatorHealthBar(
    float center_x,
    float top,
    float width,
    float health_ratio);
void RenderGameplayWorldIndicatorsInNativePass();

void QueueNativeWorldDampenPresentation(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence,
    float x,
    float y);

}  // namespace sdmod
