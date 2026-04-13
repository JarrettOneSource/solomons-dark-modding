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

Preset flow wiring now lives under [`scripts/lib/`](/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader/mods/lua_ui_sandbox_lab/scripts/lib), with the thin bootstrap entry at [`scripts/main.lua`](/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader/mods/lua_ui_sandbox_lab/scripts/main.lua) and the probe seam constants in [`config/probe-layout.ini`](/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader/mods/lua_ui_sandbox_lab/config/probe-layout.ini).

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
- `enter_gameplay_start_run_ready` is the matching no-auto-spawn `testrun` preset. Use it when you want a settled arena scene first, then plan to arm traces or spawn bots manually through the live debug tools.
- Patrol bot presets default to `wizard_id = 0` unless you override `SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID`. Use that override when you want color tests for water/earth/air/mind instead of the default fire bot.
- Combined create/gameplay presets now support explicit element + discipline selection:
  - `create_ready_fire_body`
  - `create_ready_water_mind`
  - `map_create_fire_arcane`
  - `map_create_air_body`
  If the discipline suffix is omitted, the sandbox still defaults to `arcane`.
- The create-screen element semantics were corrected on April 13, 2026. The public preset names now match the actual stock visuals:
  - `fire` -> orange
  - `water` -> blue
  - `earth` -> green
  - `air` -> cyan
  - `ether` -> purple
- intrusive `sd.debug.trace_function` / `sd.debug.watch_write` spawn probes are now reserved for explicit diagnostic presets such as `static_bot_render_debug` and `enter_gameplay_start_run_debug`; the default `enter_gameplay_start_run` regression run avoids hardware watch traps so render verification can complete cleanly.
- the gameplay diagnostic presets intentionally do not trace the generic `PointerList_DeleteBatch` / `object.delete` deleter anymore. That trampoline was proven to destabilize the run before bot spawn completed, so the supported debug contract is to trace the higher-level world and PuppetManager callbacks instead.
- [`tools/live_bot_render_debug.py`](/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader/tools/live_bot_render_debug.py) is the supported live helper for render investigations. It waits for a settled `testrun` scene, arms the shared trace probe, spawns a bot on demand, and dumps the current scene/player/bot visual state into `runtime/live_bot_render_debug_state.json`. Hardware write watches stay opt-in there because the current DRx path can still destabilize live runs with `STATUS_SINGLE_STEP`.
- [`docs/lua-memory-tooling.md`](/mnt/c/Users/User/Documents/GitHub/SB Modding/Solomon Dark/Mod Loader/docs/lua-memory-tooling.md) is the current reference for direct `sd.debug` workflows, including pointer-chain helpers, trace-hit history, write-hit history, and vtable dumping.
- `enter_gameplay_wait` is the matching hub bot-regression preset. It leaves the hub settled long enough for the same slot-backed companion wizard path to materialize and verify without transitioning into `testrun`.
- `sd.ui.activate_action` is now single-flight. It returns a request id on success, and the sandbox waits on `sd.ui.get_action_dispatch(request_id)` instead of reissuing the same action while an earlier request is still queued or dispatching.
- Title-menu and browser presets now target stable action ids such as `dialog.primary`, `main_menu.explore_dark_cloud`, and `dark_cloud_browser.sort` instead of labels or screen coordinates.
- The sandbox is now modular. [`scripts/main.lua`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/mods/lua_ui_sandbox_lab/scripts/main.lua) bootstraps a mod-local loader through `sd.runtime.get_mod_text_file`, and the mode implementations live under [`scripts/lib/`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/mods/lua_ui_sandbox_lab/scripts/lib).
- All remaining hardcoded gameplay/create-probe addresses, offsets, and structure sizes for this mod were moved into [`config/probe-layout.ini`](/mnt/c/users/user/documents/github/sb%20modding/Solomon%20Dark/Mod%20Loader/mods/lua_ui_sandbox_lab/config/probe-layout.ini).
- The sandbox now exercises `dialog`, `main_menu`, `dark_cloud_browser`, `dark_cloud_search`, `settings`, `controls`, `simple_menu`, `pause_menu`, `create`, `inventory`, and `skills`.
- `inventory`, `skills`, and true gameplay `pause_menu` follow-through are currently verified probe paths, not yet fully promoted first-class `sd.ui` surfaces.
- Every step logs the preset name, step index, action kind, current surface, and result so failed transitions are easier to localize.
- The default preset is the current browser sort probe. Change the preset file or environment variable when you want a different entry point.
