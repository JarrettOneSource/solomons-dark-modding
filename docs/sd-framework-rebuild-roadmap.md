# Solomon Dark Framework Rebuild Roadmap

This note captures the post-reset Solomon Dark baseline and the main SB systems that should be rebuilt intentionally in SD.

## Current baseline

- `launch` now stages Solomon Dark, starts `SolomonDark.exe`, and injects `SolomonDarkModLoader.dll`.
- the injected loader logs to `.sdmod/logs/solomondarkmodloader.log`
- the loader hosts a real embedded Lua runtime, loads staged Lua mods, and exposes live `sd.runtime`, `sd.events`, `sd.ui`, `sd.input`, `sd.hub`, and `sd.bots` namespaces
- overlay staging still works and the in-process memory access layer remains available
- the launcher-owned debug UI overlay is now the current `sd.ui` snapshot/action backbone for title, browser, settings, simple-menu, and character-creation automation
- gameplay automation is already working in the Lua sandbox for title/browser/settings flows, character creation, gameplay pause/inventory/skills probes, and hub/testrun entry
- multiplayer transport and the old UI stack remain out of scope for now

Relevant current SD files:

- `SolomonDarkModLauncher/src/Launch/StagedGameLauncher.cs`
- `SolomonDarkModLauncher/src/Launch/WindowsDllInjector.cs`
- `SolomonDarkModLoader/src/mod_loader.cpp`
- `SolomonDarkModLoader/src/lua_engine.cpp`
- `SolomonDarkModLoader/include/memory_access.h`

## Cleanup resolved in this pass

- loader startup logging now flushes every line so injected startup diagnostics survive forced shutdown during verification
- stale unused install-target constants were removed from the native target header
- stale unused launcher target fields were removed from `GameInstallation`
- the old SB Lua vendor tree, MinHook vendor tree, and stale launcher assets were already removed from the SD tree before this pass

## Main rebuild tracks from the SB framework

### 1. Binary layout and compatibility verification

SB sources:

- `Mod Loader/SBModLoader/include/binary_layout.h`
- `Mod Loader/SBModLoader/src/binary_layout.cpp`
- `Mod Loader/SBModLauncher/src/Staging/RuntimeMetadataMaterializer.cs`
- `Mod Loader/docs/architecture/06-loader-reliability-and-compatibility.md`

What this system did in SB:

- owned the authoritative function/global/offset table for the retail binary
- in SB, loaded `binary-layout.lua` at runtime
- verified or healed runtime seam availability before advanced modules activated
- separated stable mod capabilities from raw per-build addresses

What SD should rebuild:

- an x86 `SolomonDark.exe` layout descriptor set
- a staged `.sdmod/config/binary-layout.ini` plus a compatibility report
- version/build detection for the abandoned `0.72.5` target and any future forks you want to support
- semantic verification around critical seams before hooks or typed object readers activate

Why this is near the front:

- every higher-level runtime system depends on trusted addresses, offsets, and globals
- it gives you a clean place to gate features instead of letting Lua or native code guess at pointers

Current SD status:

- `config/binary-layout.ini` now stages the image base plus recovered first-pass UI anchors for title, main menu, pause/settings, controls, inventory, skills, spell/book pickers, and the asset-backed screen builders
- the injected loader parses the staged layout before address resolution is used

### 2. Lua runtime host

SB sources:

- `Mod Loader/SBModLoader/include/lua_runtime.h`
- `Mod Loader/SBModLoader/src/lua_runtime.cpp`
- `Mod Loader/SBModLoader/src/lua_runtime_bootstrap.cpp`
- `Mod Loader/SBModLoader/src/lua_runtime_bindings.cpp`
- `Mod Loader/SBModLoader/src/lua_runtime_registration_bindings.cpp`
- `Mod Loader/docs/mod-loader/05-lua-scripting-and-hooks.md`

What this system did in SB:

- hosted one embedded Lua VM in the injected loader
- loaded staged runtime metadata and mod entry scripts
- exposed a semantic `sb.*` API instead of raw addresses
- registered events, content definitions, and debug memory helpers

What SD should rebuild:

- keep the single embedded-runtime model
- stage and load one bootstrap manifest owned by the launcher
- keep growing the current SD API surface around stable seams:
  - `sd.runtime`
  - `sd.events`
  - `sd.ui`
  - `sd.input`
  - `sd.hub`
  - `sd.bots`
- move future gameplay-heavy namespaces toward typed readers instead of adding more ad hoc raw seam exposure

Current SD status:

- the embedded runtime is live in `SolomonDarkModLoader/src/lua_engine.cpp`, staged mods are loaded, unsafe globals are stripped, and the current `sd.*` bindings are registered in `SolomonDarkModLoader/src/lua_engine_bindings.cpp`

### 3. Runtime bootstrap, sandbox, cache, and data roots

SB sources:

- `Mod Loader/SBModLauncher/src/Staging/RuntimeMetadataMaterializer.cs`
- `Mod Loader/SBModLoader/include/runtime_flags.h`
- `Mod Loader/SBModLoader/include/runtime_catalog.h`

What this system did in SB:

- staged runtime mods into `.sbmod/mods`
- created per-mod sandbox roots for `data`, `cache`, and `tmp`
- wrote bootstrap metadata and runtime feature flags
- separated durable mod state from disposable runtime state

What SD should rebuild:

- a `.sdmod` runtime contract owned by the launcher
- per-mod storage keys and sandbox roots under the stage
- explicit `data`, `cache`, and `tmp` directories for each runtime mod
- a small bootstrap manifest the injected loader can trust
- feature flags that gate SD runtime modules cleanly

Why this matters:

- Lua becomes manageable only when runtime state has a stable filesystem contract
- binary compatibility, cache invalidation, and future tooling all benefit from a defined runtime layout

### 4. Typed memory and live object access layer

SB sources:

- `Mod Loader/SBModLoader/include/memory_access.h`
- `Mod Loader/SBModLoader/include/lua_runtime.h`
- `Mod Loader/docs/save-editor/02-data-model.md`

What this system did in SB:

- provided guarded low-level read/write primitives
- layered semantic snapshots like `PlayerStateSnapshot`, `WorldStateSnapshot`, and `ItemStateSnapshot` over raw memory
- fed both Lua and tooling without exposing raw pointers directly to mod authors
- treated typed save/runtime objects as first-class models instead of ad hoc offsets everywhere

What SD should rebuild:

- keep `ProcessMemory` as the raw access foundation
- add typed SD readers around verified globals and structures:
  - player state
  - world/run state
  - item/equipment state
  - UI/menu state
- keep raw reads/writes in internal code only
- expose stable semantic views to Lua and future tools

How the new overlay fits:

- `docs/debug-ui-overlay.md` now documents the current `sd.ui` snapshot/action backbone
- it already powers live title, browser, search, settings, simple-menu, and character-creation automation
- the next clean step is not to discard it, but to add typed readers and promote the remaining gameplay surfaces onto the same first-class path

This is the system you were remembering:

- the usable typed-object layer in SB was not just the raw memory helper
- it was the combination of verified offsets plus snapshot/reader types layered on top of `ProcessMemory`

### 5. Runtime identity/catalog layer

SB sources:

- `Mod Loader/SBModLoader/include/runtime_catalog.h`
- `Mod Loader/SBModLoader/src/runtime_catalog.cpp`

What this system did in SB:

- mapped stable ids to retail skills and enemy types
- kept Lua/content definitions keyed by semantic ids instead of raw integers

What SD should rebuild:

- canonical ids for SD skills, enemies, items, wizards, and UI surfaces
- a translation layer between script/content ids and the verified runtime integer/object model

Why this matters:

- it prevents the Lua API and typed object layer from leaking retail enum integers everywhere

### 6. Hook and capability modules

SB sources:

- `Mod Loader/SBModLoader/include/game_hooks.h`
- `Mod Loader/SBModLoader/src/game_hooks.cpp`
- `Mod Loader/docs/architecture/08-concrete-runtime-seams.md`

What this system did in SB:

- activated advanced runtime seams only when verified
- separated ordinary launch/staging from deeper hook-backed capabilities

What SD should rebuild:

- small, capability-scoped hook modules
- feature gating driven by the binary compatibility layer
- explicit failure reporting per capability instead of one giant on/off switch

This should stay behind the binary checker and typed object layer, not in front of them.

### 7. Native plugin ABI

SB sources:

- `Mod Loader/SBModLoader/include/sbmod_plugin_api.h`
- `Mod Loader/SBModLoader/src/native_mods.cpp`

What this system did in SB:

- allowed native runtime mods to load under the main injected host
- shared a host-owned API boundary instead of letting third-party DLLs patch the game blindly

What SD should rebuild:

- a narrow SD plugin ABI only after the loader, binary checker, and typed state surfaces are stable

This is lower priority than Lua unless you need early native-only experiments.

## Recommended rebuild order

1. finish the SD binary layout/compatibility layer for `0.72.5`
2. keep hardening `.sdmod` bootstrap metadata with per-mod sandbox roots
3. build typed SD readers on top of `ProcessMemory`
4. keep expanding the existing embedded Lua runtime around typed readers and config-driven seams
5. promote first-class gameplay UI surfaces on top of the current `sd.ui` backbone
6. add hook-backed gameplay modules only where typed reads are not enough
7. revisit native plugins, save editing, and multiplayer after the core runtime contract is stable

## Systems to leave out for now

- multiplayer transport and remote-avatar sync
- alternate UI frontends
- large content-registration systems beyond what the verified SD seams can support

Runtime automation is already in scope; the remaining work there is typed readers plus first-class gameplay surface promotion. The items above are still cheaper to rebuild once the binary checker, runtime metadata, and typed object layer are in place.
