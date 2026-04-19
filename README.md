# Solomon's Dark Modding

A modding framework for `SolomonDark.exe`. Stages a local game copy, applies file overlays, and injects a native loader that hosts Lua scripts, native DLL mods, a scriptable bot runtime, and an opt-in debug overlay.

The repository excludes original game files, staged runtime output, and local editor state. Keep a local Solomon's Dark copy outside this repository and point the launcher at it.

## Components

- `SolomonDarkModLauncher/` — CLI launcher. Discovers mods, tracks enable/disable state, mirrors the retail tree into `runtime/stage/`, stages runtime manifests, launches the staged copy, and injects the loader.
- `SolomonDarkModLauncher.UI/` — WPF front-end that shells the CLI through its `--json` contract.
- `SolomonDarkModLoader/` — x86 native DLL. Hosts the embedded Lua runtime, the `sd.*` script API, native DLL mods, the bot runtime, Steam bootstrap, and the D3D9 debug overlay.
- `config/` — binary-layout anchors and debug overlay configuration staged into the game tree.
- `mods/` — sample mods (overlay, Lua, native, and hybrid).
- `scripts/` — build, reset, verification, window capture, and Lua-exec helpers.
- `tools/ghidra-scripts/` — Ghidra automation for reverse engineering.
- `docs/` — design notes, binary maps, and investigation write-ups.

## Mod types

Mods are discovered from `manifest.json`. Each mod may be:

- **Overlay** — files under `files/` copied over the staged tree in priority order.
- **Lua** — entry scripts under `scripts/` loaded by the embedded Lua runtime.
- **Native** — DLLs under `native/` loaded through `SDModPlugin_Initialize` / `SDModPlugin_Shutdown`.
- **Hybrid** — any combination of the above.

Sample mods: `item_gold_focus`, `skill_shock_nova`, `story_custom_intro`, `wave_fast_start`, `lua_bots`, `lua_dark_cloud_sort_bootstrap`, `lua_ui_sandbox_lab`.

## Runtime contract

The launcher stages these files into `runtime/stage/.sdmod/`:

- `runtime/runtime-flags.ini` and `runtime/runtime-bootstrap.ini` — the loader's runtime contract.
- `config/binary-layout.ini` — image base and recovered UI anchors.
- `config/debug-ui.ini` — debug overlay configuration.
- `stage-report.json` — launcher's staging report.
- `startup-status.json` — per-launch token written by the loader so the launcher can distinguish the current run from stale artifacts.

The launcher also stages `steam_appid.txt` (AppID `3362180`) and copies an x86 `steam_api.dll` into the staged game root when one is not already present. Provide a 32-bit Steamworks runtime at `SolomonDarkModLauncher/assets/steam/win32/steam_api.dll` or pass `--steam-api-dll`.

## Loader features

- Embedded Lua engine with the `sd.*` API (gameplay, runtime, UI, input, debug, bots).
- Native DLL mod host (`SDModPlugin_Initialize` / `SDModPlugin_Shutdown`).
- Scriptable bot runtime exposed through `sd.bots.*`, driven from the runtime tick service.
- Steam bootstrap: `steam_api.dll` load, `SteamAPI_Init`, and legacy friends/matchmaking/networking interface binding.
- Memory-access helpers for hook development and live probing.
- Named-pipe Lua exec server for external scripts to submit code to the live runtime and capture return values plus `print(...)` output.
- D3D9 `EndScene` debug overlay using the configured text draw helper and live `MsgBox` seams.

## Build

```powershell
pwsh ./scripts/Build-All.ps1
```

## Verify

```powershell
pwsh ./scripts/Verify-Workspace.ps1 -Configuration Debug
pwsh ./scripts/Verify-Workspace.ps1 -Configuration Debug -LaunchAndVerifyLoader
```

## Run

CLI (defaults to `../SolomonDarkAbandonware` when present):

```powershell
./dist/launcher/SolomonDarkModLauncher.exe list-mods
./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.items.gold_focus
./dist/launcher/SolomonDarkModLauncher.exe disable-mod sample.items.gold_focus
./dist/launcher/SolomonDarkModLauncher.exe stage
./dist/launcher/SolomonDarkModLauncher.exe stage --runtime-profile bootstrap_only
./dist/launcher/SolomonDarkModLauncher.exe launch
./dist/launcher/SolomonDarkModLauncher.exe launch --steam-api-dll path\to\steam_api.dll
```

GUI:

```powershell
./dist/ui/SolomonDarkModLauncher.UI.exe
```

Visual Studio: open `SolomonDarkModding.sln`, set `SolomonDarkModLauncher.UI` as the startup project, `F5`.

## Runtime helpers

Live Lua exec (requires a running Solomon's Dark process launched through the loader with Lua enabled):

```powershell
pwsh ./scripts/Invoke-LuaExec.ps1 -Code "return sd.world.get_scene()"
py -3 ./tools/lua-exec.py "return sd.debug.read_u32(0x008203F0)"
```

Window capture for overlay verification:

```powershell
py -3 ./scripts/capture_window.py --title SolomonDark --output ./runtime/debug-ui-current.png --method window
py -3 ./scripts/capture_window.py --title SolomonDark --output ./runtime/debug-ui-screen.png --method screen --activate
```

## Documentation

- `docs/sd-framework-rebuild-roadmap.md` — framework planning.
- `docs/expansion-guide.md` — module ownership and extension rules.
- `docs/ui-binary-map.md` — recovered UI seams and coverage.
- `docs/ui-engine-system-map.md` — higher-level UI engine architecture and hook targets.
- `docs/debug-ui-overlay.md` — debug overlay architecture and limits.
- `docs/bot-render-re-map.md` — wizard bot render-path notes.
- `docs/bot-and-multiplayer-plan.md` — bot and multiplayer plan.
- `TODO.md` — current hook and API work.
