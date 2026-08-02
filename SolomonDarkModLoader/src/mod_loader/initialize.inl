void Initialize(HMODULE module_handle) {
    g_module_handle = module_handle;
    g_project_root = FindProjectRoot(GetModuleDirectory(module_handle));

    const auto stage_runtime_directory = GetStageRuntimeDirectory();
    std::filesystem::create_directories(stage_runtime_directory / "logs");
    InitializeLogger(stage_runtime_directory / "logs" / "solomondarkmodloader.log");
    InitializeNetworkTelemetry(
        stage_runtime_directory / "logs" / "network-telemetry.jsonl");
    InstallCrashHandler(stage_runtime_directory / "logs" / "solomondarkmodloader.crash.log");
    ResetStartupStatus(stage_runtime_directory);

    StartupStatusSnapshot startup_status;
    startup_status.launch_token = GetEnvironmentString(kLaunchTokenEnvironmentVariable);
    startup_status.code = "pending";
    startup_status.message = "SolomonDarkModLoader startup is in progress.";
    startup_status.log_path = GetLoggerPath();
    startup_status.runtime_flags_path = GetRuntimeFlagsPath(stage_runtime_directory);
    startup_status.runtime_bootstrap_path = GetRuntimeBootstrapPath(stage_runtime_directory);
    startup_status.binary_layout_path = GetBinaryLayoutPath(stage_runtime_directory);
    WriteStartupStatus(stage_runtime_directory, startup_status);

    const auto write_failed_status = [&](const char* code, const std::string& message) {
        startup_status.completed = true;
        startup_status.success = false;
        startup_status.code = code == nullptr ? "startup-failed" : code;
        startup_status.message = message;
        RefreshStartupStatusSnapshot(&startup_status);
        WriteStartupStatus(stage_runtime_directory, startup_status);
    };

    const auto write_success_status = [&](const std::string& message) {
        startup_status.completed = true;
        startup_status.success = true;
        startup_status.code = "startup-complete";
        startup_status.message = message;
        RefreshStartupStatusSnapshot(&startup_status);
        WriteStartupStatus(stage_runtime_directory, startup_status);
    };

    try {
        Log("SolomonDarkModLoader attached.");
        Log("Module path: " + GetModulePath(module_handle).string());
        Log("Module directory: " + GetModuleDirectory(module_handle).string());
        Log("Host process directory: " + GetHostProcessDirectory().string());
        Log("Stage runtime directory: " + stage_runtime_directory.string());
        Log("Project root: " + g_project_root.string());

        RuntimeFeatureFlags runtime_flags;
        std::string runtime_flags_error;
        if (!LoadRuntimeFeatureFlags(stage_runtime_directory, &runtime_flags, &runtime_flags_error)) {
            Log(runtime_flags_error);
            write_failed_status("runtime-flags-load-failed", runtime_flags_error);
            return;
        }

        SetActiveRuntimeFeatureFlags(runtime_flags);
        startup_status.runtime_flags_path = GetRuntimeFlagsPath(stage_runtime_directory);
        Log("Runtime feature flags: " + DescribeRuntimeFeatureFlags(runtime_flags));

        RuntimeBootstrap runtime_bootstrap;
        std::string runtime_bootstrap_error;
        if (!LoadRuntimeBootstrap(stage_runtime_directory, &runtime_bootstrap, &runtime_bootstrap_error)) {
            Log(runtime_bootstrap_error);
            write_failed_status("runtime-bootstrap-load-failed", runtime_bootstrap_error);
            return;
        }

        startup_status.runtime_bootstrap_path = GetRuntimeBootstrapPath(stage_runtime_directory);
        Log("Runtime bootstrap: " + DescribeRuntimeBootstrap(runtime_bootstrap));
        if (runtime_bootstrap.api_version != kRuntimeApiVersion) {
            const auto message =
                "Runtime bootstrap apiVersion mismatch. loader=" + std::string(kRuntimeApiVersion) +
                " bootstrap=" + runtime_bootstrap.api_version;
            Log(message);
            write_failed_status("runtime-api-version-mismatch", message);
            return;
        }

        if (InitializeBinaryLayout(stage_runtime_directory)) {
            startup_status.binary_layout_loaded = true;
            startup_status.binary_layout_path = GetBinaryLayoutPath(stage_runtime_directory);
            if (const auto* binary_layout = TryGetBinaryLayout(); binary_layout != nullptr) {
                Log("Binary layout loaded.");
                Log("Binary layout path: " + binary_layout->source_path.string());
                Log("Configured binary: " + binary_layout->binary_name + " " + binary_layout->binary_version);
                Log("Configured image base: " + HexString(binary_layout->image_base));
                Log("Configured UI surfaces: " + std::to_string(binary_layout->ui_surfaces.size()));
                Log("Configured UI actions: " + std::to_string(binary_layout->ui_actions.size()));
            }
        } else {
            startup_status.binary_layout_loaded = false;
            Log("Binary layout failed to load. " + GetBinaryLayoutLoadError());
            Log("Config-driven address resolution and UI seam discovery are unavailable.");
        }

        {
            std::string close_url_patch_error;
            if (!InitializeNativeCloseUrlPatch(
                    &close_url_patch_error)) {
                const auto message =
                    close_url_patch_error.empty()
                    ? std::string(
                        "Native close URL patch failed to initialize.")
                    : close_url_patch_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status(
                    "close-url-patch-failed",
                    message);
                return;
            }
        }

        {
            std::string d3d_lifetime_error;
            if (!InitializeNativeD3d9LifetimeGuard(
                    &d3d_lifetime_error)) {
                const auto message = d3d_lifetime_error.empty()
                    ? std::string(
                        "Native D3D9 process-lifetime guard "
                        "failed to initialize.")
                    : d3d_lifetime_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status(
                    "d3d-lifetime-guard-failed",
                    message);
                return;
            }
        }

        {
            std::string audio_disable_error;
            if (!InitializeLaunchAudioDisable(
                    &audio_disable_error)) {
                const auto message = audio_disable_error.empty()
                    ? std::string(
                        "Launch audio disable failed to initialize.")
                    : audio_disable_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("audio-disable-failed", message);
                return;
            }
        }

        {
            std::string native_audio_observability_error;
            if (!InitializeNativeAudioObservability(
                    &native_audio_observability_error)) {
                Log(
                    "Native audio observability unavailable. " +
                    native_audio_observability_error);
            }
        }

        {
            std::string keyboard_injection_error;
            if (!InitializeGameplayKeyboardInjection(&keyboard_injection_error)) {
                Log("Gameplay keyboard injection unavailable. " + keyboard_injection_error);
            }
        }

        {
            std::string boneyard_picker_error;
            if (!InitializeBoneyardPicker(
                    runtime_bootstrap,
                    &boneyard_picker_error)) {
                const auto message = boneyard_picker_error.empty()
                    ? std::string(
                        "Boneyard picker provider failed to initialize.")
                    : boneyard_picker_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status(
                    "boneyard-picker-failed",
                    message);
                return;
            }
        }

        {
            std::string camera_error;
            if (!InitializeLuaCameraRuntime(&camera_error)) {
                Log("Lua camera runtime unavailable. " + camera_error);
            }
        }

        if (InitializeDebugUiOverlayConfig(stage_runtime_directory)) {
            if (const auto* debug_ui_config = TryGetDebugUiOverlayConfig(); debug_ui_config != nullptr) {
                Log("Debug UI config loaded.");
                Log("Debug UI config path: " + debug_ui_config->source_path.string());
                Log("Debug UI diagnostic visuals configured: " + std::string(debug_ui_config->enabled ? "true" : "false"));
            }
        } else {
            Log("Debug UI config failed to load. " + GetDebugUiOverlayConfigLoadError());
        }

        auto& memory = ProcessMemory::Instance();
        Log("Host module base: " + HexString(memory.ModuleBase()));
        std::string headless_error;
        if (!InitializeHeadlessSimulation(&headless_error)) {
            const auto message = headless_error.empty()
                ? std::string("Headless simulation failed to initialize.")
                : headless_error;
            Log(message);
            ShutdownPartialRuntime();
            write_failed_status("headless-simulation-failed", message);
            return;
        }

        {
            std::string background_focus_bypass_error;
            if (!InitializeBackgroundFocusBypass(&background_focus_bypass_error)) {
                const auto message = background_focus_bypass_error.empty()
                    ? std::string("Background focus bypass failed to initialize.")
                    : background_focus_bypass_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("background-focus-bypass-failed", message);
                return;
            }
        }

        {
            std::string cpu_lifecycle_guard_error;
            if (!InitializeCpuLifecycleGuard(&cpu_lifecycle_guard_error)) {
                const auto message = cpu_lifecycle_guard_error.empty()
                    ? std::string("CPU lifecycle guard failed to initialize.")
                    : cpu_lifecycle_guard_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("cpu-lifecycle-guard-failed", message);
                return;
            }
        }

        if (runtime_flags.multiplayer.steam_bootstrap) {
            InitializeSteamBootstrap();
        } else {
            Log("Steam bootstrap disabled by runtime flags.");
        }

        if (runtime_flags.multiplayer.foundation) {
            multiplayer::InitializeFoundation();
        } else {
            Log("Multiplayer foundation disabled by runtime flags.");
        }

        if (multiplayer::IsFoundationInitialized()) {
            multiplayer::InitializeBotRuntime();
        } else {
            Log("Bot runtime not initialized because the multiplayer foundation is unavailable.");
        }

        startup_status.lua_engine_enabled = runtime_flags.loader.lua_engine;
        if (runtime_flags.loader.lua_engine) {
            std::string lua_engine_error;
            if (!InitializeLuaEngine(runtime_bootstrap, &lua_engine_error)) {
                const auto message = lua_engine_error.empty()
                    ? std::string("Lua engine failed to initialize.")
                    : lua_engine_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-engine-failed", message);
                return;
            }
        } else {
            Log("Lua engine disabled by runtime flags.");
        }

        const bool native_world_renderer_required =
            runtime_flags.loader.lua_engine ||
            multiplayer::IsFoundationInitialized();
        if (native_world_renderer_required) {
            if (!IsLuaWorldRenderRuntimeInitialized()) {
                InitializeLuaWorldRenderRuntime();
            }
            std::string lua_world_renderer_error;
            if (!InitializeLuaWorldRenderer(&lua_world_renderer_error)) {
                const auto message = lua_world_renderer_error.empty()
                    ? std::string("Lua native world renderer failed to initialize.")
                    : lua_world_renderer_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-world-renderer-failed", message);
                return;
            }
        } else {
            Log(
                "Native world renderer disabled because Lua and multiplayer "
                "are unavailable.");
        }

        if (runtime_flags.loader.lua_engine) {
            std::string lua_item_hook_error;
            if (!InitializeLuaItemNativeHooks(&lua_item_hook_error)) {
                const auto message = lua_item_hook_error.empty()
                    ? std::string("Lua item native hooks failed to initialize.")
                    : lua_item_hook_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-item-hooks-failed", message);
                return;
            }

            std::string run_lifecycle_hook_error;
            if (!InitializeRunLifecycleHooks(&run_lifecycle_hook_error)) {
                const auto message = run_lifecycle_hook_error.empty()
                    ? std::string("Run lifecycle hooks failed to initialize.")
                    : run_lifecycle_hook_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("run-lifecycle-hooks-failed", message);
                return;
            }

            if (!StartLuaExecPipeServer()) {
                const std::string message = "Lua exec pipe server failed to start.";
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-exec-pipe-failed", message);
                return;
            }
        }

        startup_status.runtime_tick_service_enabled = runtime_flags.loader.runtime_tick_service;
        if (runtime_flags.loader.runtime_tick_service && HasLuaRuntimeTickHandlers()) {
            if (!StartRuntimeTickService()) {
                const std::string message = "Runtime tick service failed to start.";
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("runtime-tick-service-failed", message);
                return;
            }
        } else if (!runtime_flags.loader.runtime_tick_service) {
            Log("Runtime tick service disabled by runtime flags.");
        } else {
            Log("Runtime tick service not started because no runtime tick handlers were loaded.");
        }

        {
            std::string tutorial_bypass_error;
            if (!InitializeFreshSaveTutorialBypass(
                    &tutorial_bypass_error)) {
                const auto message = tutorial_bypass_error.empty()
                    ? std::string(
                        "Fresh-save tutorial bypass failed to initialize.")
                    : tutorial_bypass_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("tutorial-bypass-failed", message);
                return;
            }
        }

        std::string multiplayer_join_flow_error;
        if (!InitializeMultiplayerJoinFlow(&multiplayer_join_flow_error)) {
            const auto message = multiplayer_join_flow_error.empty()
                ? std::string("Multiplayer join flow failed to initialize.")
                : multiplayer_join_flow_error;
            Log(message);
            ShutdownPartialRuntime();
            write_failed_status("multiplayer-join-flow-failed", message);
            return;
        }
        const bool multiplayer_join_flow_enabled = IsMultiplayerJoinFlowEnabled();
        const auto* join_flow_ui_config =
            TryGetDebugUiOverlayConfig();
        const bool diagnostic_ui_enabled =
            runtime_flags.loader.debug_ui &&
            !multiplayer_join_flow_enabled &&
            join_flow_ui_config != nullptr &&
            join_flow_ui_config->enabled;
        const bool native_ui_bridge_required =
            runtime_flags.loader.lua_engine ||
            runtime_flags.multiplayer.foundation ||
            multiplayer_join_flow_enabled;
        if (native_ui_bridge_required || diagnostic_ui_enabled) {
            if (!InitializeDebugUiOverlay(diagnostic_ui_enabled)) {
                if (multiplayer_join_flow_enabled) {
                    const std::string message =
                        "Multiplayer quick start could not initialize its native UI bridge.";
                    Log(message);
                    ShutdownPartialRuntime();
                    write_failed_status(
                        "multiplayer-quick-start-failed",
                        message);
                    return;
                }
                Log("Native UI bridge requested but failed to initialize.");
            }
        } else {
            Log("Native UI bridge disabled by runtime flags.");
        }

        if (runtime_flags.loader.lua_engine) {
            const auto* debug_ui_config = TryGetDebugUiOverlayConfig();
            std::string lua_draw_error;
            if (debug_ui_config == nullptr ||
                debug_ui_config->device_pointer_global == 0 ||
                !StartLuaDrawRenderer(
                    debug_ui_config->device_pointer_global,
                    &lua_draw_error)) {
                const auto message = lua_draw_error.empty()
                    ? std::string(
                        "Lua draw renderer could not resolve the D3D9 device pointer seam.")
                    : lua_draw_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-draw-renderer-failed", message);
                return;
            }

            std::string lua_ui_error;
            if (!StartLuaUiRenderer(&lua_ui_error)) {
                const auto message = lua_ui_error.empty()
                    ? std::string("Lua UI renderer could not resolve its native UI seams.")
                    : lua_ui_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status("lua-ui-renderer-failed", message);
                return;
            }
            InitializeLuaDeveloperConsole();
        }

        {
            const auto* loading_screen_config =
                TryGetDebugUiOverlayConfig();
            std::string loading_screen_error;
            if (loading_screen_config == nullptr ||
                loading_screen_config->device_pointer_global == 0 ||
                !InitializeLoadingScreen(
                    loading_screen_config->device_pointer_global,
                    stage_runtime_directory /
                        "assets" /
                        "loading" /
                        "Wizards_dire_BG.png",
                    &loading_screen_error)) {
                const auto message = loading_screen_error.empty()
                    ? std::string(
                        "Loading screen could not resolve the D3D9 "
                        "device pointer seam.")
                    : loading_screen_error;
                Log(message);
                ShutdownPartialRuntime();
                write_failed_status(
                    "loading-screen-failed",
                    message);
                return;
            }
        }

        RefreshStartupStatusSnapshot(&startup_status);
        std::ostringstream startup_summary;
        startup_summary << "SolomonDarkModLoader startup complete."
                        << " binary_layout=" << (startup_status.binary_layout_loaded ? 1 : 0)
                        << " headless_simulation=" << (startup_status.headless_simulation_enabled ? 1 : 0)
                        << " steam_transport=" << (startup_status.steam_transport_ready ? 1 : 0)
                        << " multiplayer_foundation=" << (startup_status.multiplayer_foundation_ready ? 1 : 0)
                        << " bot_runtime=" << (startup_status.bot_runtime_initialized ? 1 : 0)
                        << " lua_engine=" << (startup_status.lua_engine_initialized ? 1 : 0)
                        << " lua_mods=" << startup_status.lua_loaded_mod_count
                        << " runtime_tick_service=" << (startup_status.runtime_tick_service_running ? 1 : 0);
        Log(startup_summary.str());
        write_success_status(startup_summary.str());
    } catch (const std::exception& ex) {
        const auto message = std::string("Unhandled exception during loader startup: ") + ex.what();
        Log(message);
        ShutdownPartialRuntime();
        write_failed_status("startup-exception", message);
    } catch (...) {
        const std::string message = "Unhandled non-standard exception during loader startup.";
        Log(message);
        ShutdownPartialRuntime();
        write_failed_status("startup-exception", message);
    }
}
