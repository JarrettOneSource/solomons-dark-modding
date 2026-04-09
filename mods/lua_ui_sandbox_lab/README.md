# Lua UI Sandbox Lab

This runtime mod is a repeatable UI probe harness for Solomon Dark menu work.
Surfaced menu flows now drive through the loader's live UI snapshot API and direct engine-level control activation. Gameplay probe gaps that are not yet first-class `sd.ui` surfaces can still fall back to normalized host-window clicks.

Usage:

- Enable the mod with `./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.lua.ui_sandbox_lab`
- Set the preset in [`config/active_preset.txt`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/mods/lua_ui_sandbox_lab/config/active_preset.txt) or set `SDMOD_UI_SANDBOX_PRESET`
- Launch with `./dist/launcher/SolomonDarkModLauncher.exe launch`
- Read the loader log at `runtime/stage/.sdmod/logs/solomondarkmodloader.log`
- Or run [`scripts/Replay-UiSandbox.ps1`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/scripts/Replay-UiSandbox.ps1), which stages a preset, launches, waits for the semantic sandbox outcome, and optionally captures a screenshot by process id
- [`scripts/Drive-DarkCloudBrowser.ps1`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/scripts/Drive-DarkCloudBrowser.ps1) is now just a Dark Cloud browser wrapper over the generic replay script
- [`runtime/sd_replay_darkcloud.ps1`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/runtime/sd_replay_darkcloud.ps1) is a one-command live replay wrapper for the current `Sort` preset

Current presets are defined authoritatively in [`scripts/main.lua`](/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader/mods/lua_ui_sandbox_lab/scripts/main.lua).

Current preset families:

- title/browser semantic flows such as `title_menu_checkpoint`, `title_menu_to_play`, `title_menu_to_explore_dark_cloud_*`, `dark_cloud_browser_play`, and `browser_sort_activate_only`
- settings semantic flows such as `title_menu_to_settings`, `title_menu_settings_done`, `title_menu_explore_leave_settings_done`, `title_menu_to_settings_fullscreen`, `title_menu_to_settings_resolution`, `title_menu_to_settings_customize_keyboard`, `title_menu_to_settings_tweak_game`, and `title_menu_to_settings_login_info`
- character-creation and gameplay-entry flows such as `enter_gameplay` and `enter_gameplay_wait`
- gameplay probe flows such as `enter_gameplay_pause_menu`, `enter_gameplay_inventory`, `enter_gameplay_skills`, and `enter_gameplay_start_run`
- diagnostic probes such as `diagnostic_get_state`

Notes:

- The loader now exposes `sd.ui.get_snapshot`, `sd.ui.find_element`, `sd.ui.find_action`, `sd.ui.get_action_dispatch`, and `sd.ui.activate_action`, so the sandbox waits on live surfaces, resolves canonical action ids, tracks request lifecycle, and dispatches the game's own owner/control handlers without OS mouse injection.
- `enter_gameplay_start_run` now starts the run through the native `sd.hub.start_testrun()` binding. The separate `enter_gameplay_hub_trace_start_button` preset is reserved for diagnostic tracing when you need to study the live hub button click path.
- `enter_gameplay_start_run` is the current arena bot-regression preset. It enters `testrun`, spawns a single slot-backed companion wizard, waits for the visual regression summary, and is the supported arena path for bot-visibility verification.
- `enter_gameplay_wait` is the matching hub bot-regression preset. It leaves the hub settled long enough for the same slot-backed companion wizard path to materialize and verify without transitioning into `testrun`.
- `sd.ui.activate_action` is now single-flight. It returns a request id on success, and the sandbox waits on `sd.ui.get_action_dispatch(request_id)` instead of reissuing the same action while an earlier request is still queued or dispatching.
- Title-menu and browser presets now target stable action ids such as `dialog.primary`, `main_menu.explore_dark_cloud`, and `dark_cloud_browser.sort` instead of labels or screen coordinates.
- Preset selection is data-driven, but the Lua sandbox intentionally remains in a single entry script at [`scripts/main.lua`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/mods/lua_ui_sandbox_lab/scripts/main.lua). The embedded Solomon Dark Lua runtime strips file-loading helpers like `loadfile` and `io`, so external Lua module files are not a stable option in this engine.
- The sandbox now exercises `dialog`, `main_menu`, `dark_cloud_browser`, `dark_cloud_search`, `settings`, `controls`, `simple_menu`, `pause_menu`, `create`, `inventory`, and `skills`.
- `inventory`, `skills`, and true gameplay `pause_menu` follow-through are currently verified probe paths, not yet fully promoted first-class `sd.ui` surfaces.
- Every step logs the preset name, step index, action kind, current surface, and result so failed transitions are easier to localize.
- The default preset is the current browser sort probe. Change the preset file or environment variable when you want a different entry point.
