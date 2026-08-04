#pragma once

#include <cmath>

namespace sdmod::multiplayer {

inline bool ParticipantVitalsCorrectionHasConverged(
    float reported_life_current,
    float reported_life_max,
    float corrected_life_current,
    float corrected_life_max) {
    if (!std::isfinite(reported_life_current) ||
        !std::isfinite(reported_life_max) ||
        !std::isfinite(corrected_life_current) ||
        !std::isfinite(corrected_life_max) ||
        reported_life_max <= 0.0f ||
        corrected_life_max <= 0.0f) {
        return false;
    }

    const float tolerance = corrected_life_max * 0.001f > 0.05f
        ? corrected_life_max * 0.001f
        : 0.05f;
    return std::fabs(reported_life_current - corrected_life_current) <=
            tolerance &&
        std::fabs(reported_life_max - corrected_life_max) <=
            tolerance;
}

}  // namespace sdmod::multiplayer
