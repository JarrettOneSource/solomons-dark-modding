std::uint64_t RecommendedWorldSnapshotInterpolationDelayMs(
    const RuntimeState& state) {
    constexpr std::uint64_t kFallbackDelayMs = 150;
    constexpr std::uint64_t kMinimumDelayMs = 100;
    constexpr std::uint64_t kMaximumDelayMs = 600;

    if (state.world_snapshot_history.size() < 2) {
        return kFallbackDelayMs;
    }

    std::vector<std::uint64_t> arrival_intervals;
    arrival_intervals.reserve(
        state.world_snapshot_history.size() - 1);
    for (std::size_t index = 1;
         index < state.world_snapshot_history.size();
         ++index) {
        const auto& before = state.world_snapshot_history[index - 1];
        const auto& after = state.world_snapshot_history[index];
        if (!SameWorldSnapshotTimeline(before, after) ||
            after.received_ms <= before.received_ms) {
            continue;
        }
        arrival_intervals.push_back(
            after.received_ms - before.received_ms);
    }
    if (arrival_intervals.empty()) {
        return kFallbackDelayMs;
    }

    std::sort(arrival_intervals.begin(), arrival_intervals.end());
    const auto percentile_index =
        (arrival_intervals.size() * 9u + 9u) / 10u - 1u;
    const auto p90_ms = arrival_intervals[percentile_index];
    const auto delay_ms =
        p90_ms >
                (std::numeric_limits<std::uint64_t>::max)() /
                    3u
            ? kMaximumDelayMs
            : (p90_ms * 3u + 1u) / 2u;
    return (std::clamp)(
        delay_ms,
        kMinimumDelayMs,
        kMaximumDelayMs);
}
