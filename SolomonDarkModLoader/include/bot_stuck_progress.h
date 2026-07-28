#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <deque>
#include <limits>

namespace sdmod {

constexpr std::uint64_t kBotStuckWindowMs = 30000;
constexpr std::uint64_t kBotStuckTeleportCooldownMs = 10000;
constexpr float kBotStuckMeaningfulDistanceProgress = 0.5f;
constexpr float kBotStuckTargetContinuityDistance = 32.0f;

struct BotStuckProgressSample {
    std::uint64_t observed_ms = 0;
    float distance_to_target = 0.0f;
    bool waypoint_progress = false;
};

struct BotStuckProgressTracker {
    bool target_valid = false;
    float target_x = 0.0f;
    float target_y = 0.0f;
    std::uint64_t cooldown_until_ms = 0;
    std::deque<BotStuckProgressSample> samples;
};

inline bool IsBotStuckTargetContinuous(
    const BotStuckProgressTracker& tracker,
    float target_x,
    float target_y) {
    if (!tracker.target_valid ||
        !std::isfinite(target_x) ||
        !std::isfinite(target_y)) {
        return false;
    }
    const auto delta_x = target_x - tracker.target_x;
    const auto delta_y = target_y - tracker.target_y;
    return delta_x * delta_x + delta_y * delta_y <=
           kBotStuckTargetContinuityDistance *
               kBotStuckTargetContinuityDistance;
}

inline void ResetBotStuckProgress(
    BotStuckProgressTracker* tracker) {
    if (tracker == nullptr) {
        return;
    }
    tracker->target_valid = false;
    tracker->target_x = 0.0f;
    tracker->target_y = 0.0f;
    tracker->samples.clear();
}

inline void DiscardBotStuckWaypointProgress(
    BotStuckProgressTracker* tracker) {
    if (tracker == nullptr) {
        return;
    }
    for (auto& sample : tracker->samples) {
        sample.waypoint_progress = false;
    }
}

inline bool ObserveBotStuckProgress(
    BotStuckProgressTracker* tracker,
    std::uint64_t now_ms,
    float target_x,
    float target_y,
    float distance_to_target,
    bool meaningful_waypoint_progress) {
    if (tracker == nullptr ||
        !std::isfinite(target_x) ||
        !std::isfinite(target_y) ||
        !std::isfinite(distance_to_target) ||
        distance_to_target < 0.0f) {
        return false;
    }

    if (now_ms < tracker->cooldown_until_ms) {
        ResetBotStuckProgress(tracker);
        return false;
    }

    if (!IsBotStuckTargetContinuous(
            *tracker,
            target_x,
            target_y)) {
        tracker->target_valid = true;
        tracker->target_x = target_x;
        tracker->target_y = target_y;
        tracker->samples.clear();
    } else {
        // Follow small destination adjustments without treating ordinary
        // move_to/repath revision churn as a new pursuit.
        tracker->target_x = target_x;
        tracker->target_y = target_y;
    }

    tracker->samples.push_back(
        BotStuckProgressSample{
            now_ms,
            distance_to_target,
            meaningful_waypoint_progress});

    const auto cutoff_ms =
        now_ms >= kBotStuckWindowMs
            ? now_ms - kBotStuckWindowMs
            : 0;
    while (tracker->samples.size() > 1 &&
           tracker->samples[1].observed_ms <= cutoff_ms) {
        tracker->samples.pop_front();
    }
    if (tracker->samples.empty() ||
        now_ms < tracker->samples.front().observed_ms ||
        now_ms - tracker->samples.front().observed_ms <
            kBotStuckWindowMs) {
        return false;
    }

    bool waypoint_progress = false;
    const auto midpoint_ms =
        tracker->samples.front().observed_ms +
        (now_ms - tracker->samples.front().observed_ms) / 2;
    auto opening_nearest_distance =
        std::numeric_limits<float>::infinity();
    auto closing_nearest_distance =
        std::numeric_limits<float>::infinity();
    for (const auto& sample : tracker->samples) {
        waypoint_progress =
            waypoint_progress || sample.waypoint_progress;
        auto& nearest_distance =
            sample.observed_ms <= midpoint_ms
                ? opening_nearest_distance
                : closing_nearest_distance;
        nearest_distance =
            std::min(nearest_distance, sample.distance_to_target);
    }
    if (!std::isfinite(opening_nearest_distance) ||
        !std::isfinite(closing_nearest_distance)) {
        return false;
    }
    const auto distance_progress =
        opening_nearest_distance -
        closing_nearest_distance;
    return !waypoint_progress &&
           distance_progress <
               kBotStuckMeaningfulDistanceProgress;
}

inline void RecordBotStuckTeleport(
    BotStuckProgressTracker* tracker,
    std::uint64_t now_ms) {
    if (tracker == nullptr) {
        return;
    }
    ResetBotStuckProgress(tracker);
    tracker->cooldown_until_ms =
        now_ms + kBotStuckTeleportCooldownMs;
}

}  // namespace sdmod
