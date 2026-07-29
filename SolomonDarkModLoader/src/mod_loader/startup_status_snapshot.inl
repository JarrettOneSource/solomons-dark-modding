void RefreshStartupStatusSnapshot(StartupStatusSnapshot* snapshot) {
    if (snapshot == nullptr) {
        return;
    }

    snapshot->log_path = GetLoggerPath();
    snapshot->headless_simulation_enabled =
        IsHeadlessSimulationEnabled();
    snapshot->steam_transport_ready =
        GetSteamBootstrapSnapshot().transport_interfaces_ready;
    snapshot->multiplayer_foundation_ready =
        multiplayer::IsFoundationInitialized();
    snapshot->lua_engine_initialized = IsLuaEngineInitialized();
    snapshot->lua_loaded_mod_count =
        static_cast<int>(GetLoadedLuaModCount());
    snapshot->bot_runtime_initialized =
        multiplayer::IsBotRuntimeInitialized();
    snapshot->runtime_tick_service_running =
        IsRuntimeTickServiceRunning();
}
