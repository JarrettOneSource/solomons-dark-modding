# Solomon's Dark Modding

A modding framework for `SolomonDark.exe`. Stages a local game copy, applies file overlays, and injects a native loader that hosts Lua scripts, native DLL mods, a scriptable bot runtime, and an opt-in debug overlay.

The repository excludes original game files, staged runtime output, and local editor state. Keep a local Solomon's Dark copy outside this repository and point the launcher at it.

The friend-playtest beta is distributed as a self-contained ZIP. Extract it,
run `SolomonDarkMultiplayerBeta.exe`, and choose the original Solomon Dark
0.72.5 folder; release users do not need Visual Studio or a .NET installation.
Bundled sample mods are discovered but start disabled on a clean install.

## Components

- `SolomonDarkModLauncher/` — CLI launcher. Discovers mods, tracks enable/disable state, mirrors the retail tree into `runtime/stage/`, stages runtime manifests, launches the staged copy, and injects the loader.
- `SolomonDarkModLauncher.UI/` — WPF front-end that shells the CLI through its `--json` contract.
- `SolomonDarkModLoader/` — x86 native DLL. Hosts the embedded Lua runtime, the `sd.*` script API, native DLL mods, the bot runtime, Steam bootstrap, and the D3D9 debug overlay.
- `config/` — binary-layout anchors and debug overlay configuration staged into the game tree.
- `mods/` — sample mods (overlay, Lua, native, and hybrid).
- `scripts/` — build, reset, verification, window capture, and Lua-exec helpers.
- `tools/ghidra-scripts/` — Ghidra automation for reverse engineering.
- `docs/` — system design notes, binary maps, and implementation investigations.

## Mod types

Mods are discovered from `manifest.json`. Each mod may be:

- **Overlay** — files under `files/` copied over the staged tree in priority order.
- **Lua** — entry scripts under `scripts/` loaded by the embedded Lua runtime.
- **Native** — DLLs under `native/` loaded through `SDModPlugin_Initialize` / `SDModPlugin_Shutdown`.
- **Hybrid** — any combination of the above.

Sample mods include `item_gold_focus`, `skill_shock_nova`, `story_custom_intro`,
`wave_fast_start`, `lua_bots`, `lua_dark_cloud_sort_bootstrap`,
`lua_hud_showcase`, `lua_ui_sandbox_lab`, and the paired Lua bus labs.

Website-distributed packages use the same root-level manifest and may contain
data overlays/Boneyards, root `images/` art overlays, sandboxed Lua, or any
combination of those three. Native DLL mods remain manual installations and
are never auto-downloaded. The public authoring guide, JSON Schema, and package
examples live in the website repository under `frontend/public/`.

Downloaded art overlays replace files in the game's native `images/` tree.
Compatible sprite replacements must preserve the stock PNG/bundle consumer
ABI: bundle record destinations, record count, and geometry remain fixed unless
the mod also supplies loader-owned code that expands those native tables. The
website path intentionally supports deterministic art replacement, not an
unbounded new-atlas registry.

Boneyard overlays are parsed against the retail SyncBuffer container before
they are discovered or downloaded. Stock-level replacements target
`data/levels/*.boneyard`; editor/custom levels target
`sandbox/DarkCloud/mylevels/*.boneyard`. The recovered native format, load/save
flow, and inspection tool are documented in
[`docs/reverse-engineering/boneyard-system.md`](docs/reverse-engineering/boneyard-system.md).

Before any join with a concrete Steam lobby ID—including website links, direct
Steam invites, and manual lobby-ID joins—the launcher asks the configured
website for the host's exact active `id` + `version` + content-hash set. It
reuses exact manual or cached copies, securely downloads missing versions, and
stages only that set. This is session-scoped and does not rewrite the user's
persistent enabled-mod choices.

The website is optional. If its lobby metadata is unavailable, the launcher
continues with the locally enabled mod set; clients that manually install and
enable the same exact mods can therefore join over direct P2P with no website.
The native multiplayer fingerprint still rejects any mod, loader, game-build,
or runtime mismatch.

## Runtime contract

The launcher stages these files into `runtime/stage/.sdmod/`:

- `runtime/runtime-flags.ini` and `runtime/runtime-bootstrap.ini` — the loader's runtime contract.
- `config/binary-layout.ini` — image base and recovered UI anchors.
- `config/debug-ui.ini` — debug overlay configuration.
- `stage-report.json` — launcher's staging report.
- `startup-status.json` — per-launch token written by the loader so the launcher can distinguish the current run from stale artifacts.
- `multiplayer-session-status.json` — launch-token-bound Steam phase, lobby, peer, overlay, route, and error state used by the CLI and desktop UI.

The launcher stages `steam_appid.txt` with Solomon Dark AppID `3362180` for all
launches. It also
copies an x86 `steam_api.dll` into the staged game root when one is not already
present. Provide a 32-bit Steamworks runtime at
`SolomonDarkModLauncher/assets/steam/win32/steam_api.dll` or pass
`--steam-api-dll`.

## Loader features

- Embedded Lua engine with the `sd.*` API (gameplay, runtime, replicated state/events, local storage/timers/bus, immediate drawing/HUD, UI, input, debug, bots).
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
dotnet run --project ./tests/launcher-contracts/SolomonDarkModLauncher.ContractTests.csproj
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
./dist/ui/SolomonDarkMultiplayerBeta.exe
```

Visual Studio: open `SolomonDarkModding.sln`, set `SolomonDarkModLauncher.UI` as the startup project, `F5`.

## Beta package

Build and verify the portable prerelease artifact:

```powershell
.\scripts\New-BetaReleasePackage.ps1
py -3 .\tools\verify_beta_release_artifact.py
```

The result is
`artifacts\SolomonDarkMultiplayerBeta-v<version>.zip` plus
`artifacts\SHA256SUMS.txt`. The archive includes the self-contained desktop and
x86 launchers, loader, config, sample mods, and the x86 Steam runtime; it does
not include Solomon's Dark or Steam credentials.

After an abnormal game exit, the desktop launcher checks the native crash log,
minidumps, and process exit code, then asks before submitting anything. Choosing
`Submit Logs` sends a private, Steam-authenticated ZIP containing only the crash
diagnostics, launcher/stage metadata, runtime configuration, and enabled-mod
list. Choosing `Don't Send` makes no request. Save files and Steam credentials
are never included.

Published GitHub releases attach the authorized standalone original game as
`Solomons-Dark-0.72.5-Original-Game.zip` with a matching `.sha256` asset. The
release workflow copies the canonical, hash-pinned game archive from
`v0.1.0-beta.8`; it never packages a developer's local game directory or save
data.

See
`docs/networking/steam-friend-playtest.md` for the host/join sequence and
current beta limits.

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

- `docs/multiplayer-participant-model.md` — shared participant/profile/scene model for bots and future remote players.
- `docs/networking/README.md` — target networking architecture and current implementation boundary.
- `docs/participant-entrance-follow.md` — hub/private/run follow semantics for participant bots.
- `docs/lua-memory-tooling.md` — live Lua memory and reverse-engineering helpers.
- `docs/lua-state-and-events.md` — authority-owned replicated state, ordered custom events, limits, and live acceptance.
- `docs/lua-draw.md` — local immediate-mode text, primitives, stock sprites, projection, and bounds.
- `docs/lua-event-filters.md` — synchronous owner-side damage rewrites, cancellation, ordering, and live acceptance.
- `docs/ui-binary-map.md` — recovered UI seams and coverage.
- `docs/ui-engine-system-map.md` — higher-level UI engine architecture and hook targets.
- `docs/ui-automation-inventory.md` — semantic `sd.ui` surface coverage and cutover map.
- `docs/debug-ui-overlay.md` — debug overlay architecture and limits.
- `docs/pathfinding-investigation.md` — native scene grid, placement, and bot pathing implementation.
- `docs/spell-cast-cleanup-chain.md` — player/bot spell-cast state, cleanup, and pure-primary seams.
- `docs/combat-casting-enable-investigation.md` — combat-casting investigation notes.
- `docs/inventory-item-investigation.md` — inventory, item, drop, and equip system notes.
- `docs/bugs/README.md` — active bug-investigation index.
