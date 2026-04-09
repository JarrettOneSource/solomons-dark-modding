# Solomon's Dark Modding

This workspace is the reset baseline for bringing modding support to `SolomonDark.exe`.

Repository scope:

- this repository intentionally excludes original game files, staged runtime output, local editor state, and one-off reverse-engineering scratch artifacts
- keep a local Solomon's Dark game copy outside this repository and point the launcher at it when needed

Current status (2026-04-09):

- the repo is now split into a standalone public Solomon's Dark workspace with the launcher, injected loader, sample mods, scripts, and reverse-engineering notes in one place
- the launcher and WPF UI can stage a local game copy, apply overlays, inject the loader, and surface structured startup state
- the loader hosts a real embedded Lua runtime, native mod loading, gameplay/runtime hooks, and the first loader-owned bot runtime
- standalone wizard bots can now be created, registered, published into real gameplay slots, and rendered in arena probes, but the current visual still borrows the player's render context and needs an independent render-node path
- the debug/runtime toolchain now includes a live Lua execution pipe plus PowerShell/Python client helpers so runtime probes can read memory, write fields, and execute Lua code against the running game
- the latest rendering and bot findings are captured in `docs/bot-render-re-map.md` and `docs/bot-and-multiplayer-plan.md`

Current scope:

- `SolomonDarkModLauncher/`: CLI-first launcher for mod discovery, persistent enable or disable state, staged file mirroring, Steam bootstrap staging, runtime metadata staging, launch, and loader injection
- `SolomonDarkModLauncher.UI/`: standalone WPF wrapper that shells `SolomonDarkModLauncher.exe` and renders its structured output
- `SolomonDarkModLoader/`: x86 native DLL scaffold with structured startup reporting, runtime feature flags, runtime bootstrap parsing, native-mod host plumbing, Steamworks bootstrap validation, a real embedded Lua runtime, a loader-owned synthetic bot runtime, and in-process memory-access helpers preserved for future runtime work
- `config/`: staged binary-layout metadata, first-pass Solomon Dark UI coverage anchors, and launcher-owned debug UI overlay config
- `mods/`: sample overlay mods plus sample runtime mods for Lua or native extension points
- `scripts/`: build, reset, and Ghidra helpers
- `tools/ghidra-scripts/`: Ghidra automation scripts carried forward for reverse engineering

Current behavior:

- the launcher defaults to the local `../SolomonDarkAbandonware` copy when it exists
- the launcher remains CLI-first and authoritative
- the GUI lives in a separate `SolomonDarkModLauncher.UI` project and shells the CLI through the `--json` contract instead of maintaining a separate control path
- mods can be pure overlays, pure runtime mods, or hybrids that stage both overlay files and runtime metadata
- the launcher mirrors the retail tree into `runtime/stage/`, applies enabled overlays, stages runtime manifests under `.sdmod/runtime/`, launches the staged copy, injects `SolomonDarkModLoader.dll`, and waits for structured loader startup completion
- the launcher stages `steam_appid.txt` with AppID `3362180` by default and can copy an x86 `steam_api.dll` into the staged game root when the mirrored build does not already ship one
- the launcher always stages `runtime-flags.ini` and `runtime-bootstrap.ini`; the injected loader consumes those files as its runtime contract
- the injected loader writes `.sdmod/startup-status.json` with a per-launch token so the launcher can distinguish the current run from stale prior-stage artifacts
- the injected loader attempts `steam_api.dll` load, `SteamAPI_Init`, and legacy friends or matchmaking or networking interface binding so Steam P2P groundwork exists before gameplay sync work begins
- the injected loader builds as `Win32`, initializes a real embedded Lua engine behind runtime flags, hosts loader-owned `sd` Lua APIs, and hosts native runtime DLL mods through `SDModPlugin_Initialize` or `SDModPlugin_Shutdown`
- the loader now exposes a first scriptable bot runtime through `sd.bots.*` and drives Lua callbacks from the existing runtime tick service
- wizard bot rendering now depends on a real gameplay slot entry plus stock `PlayerActorTick`; the arena bot is visible again, but independent render-node ownership and correct wizard-specific visuals are still follow-up work
- the launcher stages `config/binary-layout.ini` into `.sdmod/config/` and the loader consumes it for the configured image base and recovered UI anchors
- the launcher stages `config/debug-ui.ini` into `.sdmod/config/`; when enabled, the loader uses the configured text draw helper, the live `MsgBox` root-object seams for the beta modal, and the D3D9 device global to classify Solomon Dark UI elements and render an opt-in `EndScene` overlay
- when Lua is enabled, the loader also starts a named-pipe Lua exec server so external scripts can submit code to the live runtime and capture returned values plus `print(...)` output
- the loader still keeps the low-level memory access layer so Solomon Dark hook work can restart from a cleaner baseline

Build:

```powershell
pwsh ./scripts/Build-All.ps1
```

Repeatable workspace verification:

```powershell
pwsh ./scripts/Verify-Workspace.ps1 -Configuration Debug
pwsh ./scripts/Verify-Workspace.ps1 -Configuration Debug -LaunchAndVerifyLoader
```

Common commands:

```powershell
./dist/launcher/SolomonDarkModLauncher.exe list-mods
./dist/launcher/SolomonDarkModLauncher.exe enable-mod sample.items.gold_focus
./dist/launcher/SolomonDarkModLauncher.exe disable-mod sample.items.gold_focus
./dist/launcher/SolomonDarkModLauncher.exe stage
./dist/launcher/SolomonDarkModLauncher.exe launch
./dist/launcher/SolomonDarkModLauncher.exe stage --runtime-profile bootstrap_only
./dist/launcher/SolomonDarkModLauncher.exe launch --steam-api-dll path\\to\\steam_api.dll
```

GUI:

```powershell
./dist/ui/SolomonDarkModLauncher.UI.exe
```

Visual Studio:

- open `SolomonDarkModding.sln`
- set `SolomonDarkModLauncher.UI` as the Startup Project
- press `F5` to launch the GUI directly

Window capture for overlay verification:

```powershell
py -3 .\scripts\capture_window.py --title SolomonDark --output .\runtime\debug-ui-current.png --method window
py -3 .\scripts\capture_window.py --title SolomonDark --output .\runtime\debug-ui-screen.png --method screen --activate
```

Live Lua exec helpers:

```powershell
pwsh ./scripts/Invoke-LuaExec.ps1 -Code "return sd.world.get_scene()"
py -3 ./tools/lua-exec.py "return sd.debug.read_u32(0x008203F0)"
```

These helpers require a running Solomon's Dark process launched through the mod loader with Lua enabled.

The stage report is written to `runtime/stage/.sdmod/stage-report.json`.
The staged binary layout is written to `runtime/stage/.sdmod/config/binary-layout.ini`.
The staged runtime flags and bootstrap manifest are written to `runtime/stage/.sdmod/runtime/`.
The loader startup contract is written to `runtime/stage/.sdmod/startup-status.json`.
If the staged Solomon Dark build does not already contain `steam_api.dll`, place the 32-bit Steamworks runtime at `SolomonDarkModLauncher/assets/steam/win32/steam_api.dll` or pass `--steam-api-dll`.

Framework planning notes for the SD rebuild live at `docs/sd-framework-rebuild-roadmap.md`.
Recovered wizard bot render-path notes live at `docs/bot-render-re-map.md`.
Module ownership and extension rules live at `docs/expansion-guide.md`.
Recovered UI seams and first-pass coverage notes live at `docs/ui-binary-map.md`.
Recovered higher-level UI engine architecture and hook targets live at `docs/ui-engine-system-map.md`.
Debug overlay architecture and limits live at `docs/debug-ui-overlay.md`.
