namespace {

constexpr std::uint64_t kNavGridMinRebuildIntervalMs = 500;

struct PendingNavGridRebuild {
    int subdivisions = 0;
};

std::mutex g_nav_grid_snapshot_mutex;
std::shared_ptr<const SDModGameplayNavGridState> g_last_nav_grid_snapshot;
std::optional<PendingNavGridRebuild> g_pending_nav_grid_request;
std::uint64_t g_last_nav_grid_rebuild_tick_ms = 0;

}  // namespace

void RequestNavGridSnapshotRebuild(int subdivisions) {
    const int clamped = subdivisions > 0 ? subdivisions : 1;
    std::lock_guard<std::mutex> lock(g_nav_grid_snapshot_mutex);
    if (!g_pending_nav_grid_request.has_value()) {
        g_pending_nav_grid_request = PendingNavGridRebuild{clamped};
    } else if (clamped > g_pending_nav_grid_request->subdivisions) {
        g_pending_nav_grid_request->subdivisions = clamped;
    }
}

std::shared_ptr<const SDModGameplayNavGridState> GetLastNavGridSnapshotShared() {
    std::lock_guard<std::mutex> lock(g_nav_grid_snapshot_mutex);
    return g_last_nav_grid_snapshot;
}

void RebuildNavGridSnapshotIfRequested_GameplayThread() {
    PendingNavGridRebuild request{};
    const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
    {
        std::lock_guard<std::mutex> lock(g_nav_grid_snapshot_mutex);
        if (!g_pending_nav_grid_request.has_value()) {
            return;
        }
        if (g_last_nav_grid_rebuild_tick_ms != 0 &&
            now_ms - g_last_nav_grid_rebuild_tick_ms < kNavGridMinRebuildIntervalMs) {
            return;
        }
        request = *g_pending_nav_grid_request;
        g_pending_nav_grid_request.reset();
    }

    auto new_snapshot = std::make_shared<SDModGameplayNavGridState>();
    const bool built = TryGetGameplayNavGridState(new_snapshot.get(), request.subdivisions);

    std::lock_guard<std::mutex> lock(g_nav_grid_snapshot_mutex);
    if (built && new_snapshot->valid) {
        g_last_nav_grid_snapshot = std::move(new_snapshot);
    }
    g_last_nav_grid_rebuild_tick_ms = static_cast<std::uint64_t>(GetTickCount64());
}

void FlushNavGridSnapshotOnSceneUnload() {
    std::lock_guard<std::mutex> lock(g_nav_grid_snapshot_mutex);
    g_last_nav_grid_snapshot.reset();
    g_pending_nav_grid_request.reset();
    g_last_nav_grid_rebuild_tick_ms = 0;
}
