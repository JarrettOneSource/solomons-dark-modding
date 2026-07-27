#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace sdmod {

constexpr int kBotSpawnPlacementRadiusMultiples = 12;
constexpr int kBotSpawnPlacementMinimumRingSamples = 8;
constexpr std::uint32_t kBotSpawnPlacementMaximumProbeCount = 512;

enum class BotSpawnPlacementProbeResult {
    Clear,
    Blocked,
    Unavailable,
};

struct BotSpawnPlacementResult {
    float x = 0.0f;
    float y = 0.0f;
    float search_distance = 0.0f;
    std::uint32_t probe_count = 0;
    bool probe_unavailable = false;
};

inline float BotSpawnPlacementSearchBound(float collision_radius) {
    if (!std::isfinite(collision_radius) || collision_radius <= 0.0f) {
        return 0.0f;
    }
    return collision_radius *
           static_cast<float>(kBotSpawnPlacementRadiusMultiples);
}

template <typename Probe>
bool FindNearestClearBotSpawnPlacement(
    float anchor_x,
    float anchor_y,
    float collision_radius,
    Probe&& probe,
    BotSpawnPlacementResult* result) {
    if (result == nullptr) {
        return false;
    }
    *result = {};
    result->x = anchor_x;
    result->y = anchor_y;

    if (!std::isfinite(anchor_x) ||
        !std::isfinite(anchor_y) ||
        !std::isfinite(collision_radius) ||
        collision_radius <= 0.0f) {
        result->probe_unavailable = true;
        return false;
    }

    const auto test_candidate =
        [&](float x, float y, float distance) {
            if (result->probe_count >=
                kBotSpawnPlacementMaximumProbeCount) {
                result->probe_unavailable = true;
                return false;
            }
            ++result->probe_count;
            result->search_distance = distance;
            const auto probe_result = probe(x, y);
            if (probe_result ==
                BotSpawnPlacementProbeResult::Unavailable) {
                result->probe_unavailable = true;
                return false;
            }
            if (probe_result == BotSpawnPlacementProbeResult::Clear) {
                result->x = x;
                result->y = y;
                return true;
            }
            return false;
        };

    if (test_candidate(anchor_x, anchor_y, 0.0f)) {
        return true;
    }
    if (result->probe_unavailable) {
        return false;
    }

    constexpr float kTwoPi = 6.28318530717958647692f;
    for (int ring = 1;
         ring <= kBotSpawnPlacementRadiusMultiples;
         ++ring) {
        const auto distance =
            collision_radius * static_cast<float>(ring);
        const auto circumference = kTwoPi * distance;
        const auto sample_count = std::max(
            kBotSpawnPlacementMinimumRingSamples,
            static_cast<int>(
                std::ceil(circumference / collision_radius)));
        const auto angle_step =
            kTwoPi / static_cast<float>(sample_count);
        const auto angle_offset =
            (ring % 2 == 0) ? angle_step * 0.5f : 0.0f;
        for (int sample = 0; sample < sample_count; ++sample) {
            const auto angle =
                angle_offset +
                angle_step * static_cast<float>(sample);
            const auto x =
                anchor_x + std::cos(angle) * distance;
            const auto y =
                anchor_y + std::sin(angle) * distance;
            if (test_candidate(x, y, distance)) {
                return true;
            }
            if (result->probe_unavailable) {
                return false;
            }
        }
    }
    return false;
}

}  // namespace sdmod
