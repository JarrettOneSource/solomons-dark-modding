# Custom Visuals / D3D9 Overlay Review — 2026-07-23

A code-level assessment and implementation record for the loader's custom
rendering stack. The six ranked improvements from the original review are now
implemented without changing the Lua API.

## What the system is

The retail game and loader both use Direct3D 9. One shared hook feeds three
presentation-only overlay pipelines:

- **Hook** (`d3d9_end_scene_hook.cpp`) resolves the live device from the game
  global, patches `Reset` vtable slot 16 and `EndScene` slot 42, and fans out
  to up to eight frame callbacks. It captures the game's device state once,
  restores it between subscribers, draws all subscribers before the original
  `EndScene`, and restores the game state once more before returning to the
  retail renderer. The hook also exposes the live device to the MSAA-aware
  backbuffer BMP capture used by verification workflows.
- **`lua_draw_renderer.cpp`** is the `sd.hud` immediate-mode lane: text,
  filled/outlined rectangles, lines, stock sprites, registered mod sprites,
  and consumable icons. It renders pre-transformed XYZRHW triangle lists and
  retains scratch vertex capacity between frames. A world-to-screen snapshot
  of the game's viewport and W/V/P matrices powers world-anchored HUD.
- **`lua_ui_renderer.cpp`** is the `sd.ui` authored-window lane. It calls the
  game's native panel and exact-text renderers through SEH-guarded seams, so
  authored UI inherits retail styling.
- **`debug_ui_overlay.cpp` and its `.inl` components** form the developer
  inspector and multiplayer presentation lane. It captures widget geometry
  and text from game memory and renders diagnostic surfaces, participant
  health bars, spectator text, and related presentation.

Lua mods still submit a bounded `pending` display list during their runtime
tick and commit it atomically to `active`. Rendering remains local to each
process and never enters the simulation or multiplayer authority path.

## Implemented improvements

### 1. One reset-aware state owner

The three per-subscriber, per-frame `CreateStateBlock(D3DSBT_ALL)` paths are
gone. `CaptureFrameStateUnlocked` now owns one reusable state block per device
(`d3d9_end_scene_hook.cpp:57`). Creation supplies the first capture; later
frames call `Capture`. The captured game state is applied between callbacks
and after the last callback (`d3d9_end_scene_hook.cpp:207`).

`HookReset` releases the state block before the retail device reset
(`d3d9_end_scene_hook.cpp:230`). A changed device pointer also releases and
recreates it lazily. Managed font and sprite textures continue to survive an
ordinary reset, while renderer-owned resources are rebuilt for a replacement
device. The frame callback takes a temporary COM reference while the state
block is used, so concurrent hook cleanup cannot invalidate it.

### 2. Consecutive draw-run batching

`LuaDrawBatcher` (`lua_draw_renderer/rendering_helpers.inl:102`) accumulates
consecutive untextured primitives, point-filtered font glyphs, or
linear-magnified sprites sharing the same texture. Each run configures its
fixed-function state once and submits one triangle list. Outlined rectangles
remain one logical command even though they append four quads.

The batch scratch vectors live in the renderer state, so their capacity is
reused instead of being allocated again every frame.

### 3. Generation-gated display-list snapshots

`RefreshLuaDrawFrameSnapshots` (`lua_draw_runtime.cpp:186`) compares each
committed mod generation with the renderer's cached snapshot. An unchanged
generation moves the cached snapshot forward without copying its command
vector or text strings; only a new committed generation performs a deep copy.
Removed or empty frames disappear on the same refresh.

### 4. Contract-correct `EndScene` ordering

`HookEndScene` invokes overlay callbacks before the original `EndScene`
(`d3d9_end_scene_hook.cpp:207`). This keeps every draw call inside the game's
active scene while retaining the existing subscriber order and final
backbuffer output.

### 5. Sprite filtering

Text in the Lua HUD remains point-filtered. Sprite and consumable runs use
`D3DTEXF_LINEAR` magnification while retaining point minification
(`lua_draw_renderer/rendering_helpers.inl:208`). Scaled art is therefore
smoother without softening the diagnostic font atlas.

### 6. Shared font-atlas implementation

The duplicated Lua HUD and debug-overlay GDI rasterizers now share
`d3d9_font_atlas.cpp` (`InitializeD3d9FontAtlas` at line 32). Each consumer
keeps its intended font size and weight, but GDI setup, glyph metrics,
managed-texture creation, pixel conversion, error handling, and release logic
have one owner. `sd.ui` continues using the game's native font object rather
than a loader atlas.

## Parallel verification ownership

The verification path now respects launcher instance groups:

- `Verify-Workspace.ps1` creates or accepts a named instance and stages under
  `runtime/instances/<name>`; live cleanup stops only the process ID returned
  by that launch. Its loader smoke reuses the bounded launcher JSON process
  helper, so a game process cannot pin the verifier's stdout pipe.
- `Reset-LocalRuntimeState.ps1` never queries or kills every Solomon Dark
  process and never deletes shared roaming AppData. It accepts only explicit
  owned process IDs (`Reset-LocalRuntimeState.ps1:3`, `:46`).
- The local multiplayer pair launcher never performs machine-wide cleanup.
  Its Python driver defaults to isolated ownership, always requests an exact
  process ledger, and rejects the former kill-existing mode
  (`verify_local_multiplayer_sync.py:224`).
- Manual pair creation no longer depends on the optional UI sandbox mod.
  `Wait-InstanceCreateSurface` waits out the stock delayed-dialog window and
  owns the semantic `dialog.primary`, `main_menu.play`, and
  `main_menu.new_game` path before selecting the requested element and
  discipline (`Launch-LocalMultiplayerPair.ps1:784`). The neutral
  `pair_manual` preset prevents a loaded sandbox mod from racing that owner.
- Native Lua entry loading uses a wide Win32 extended-length path and then
  `luaL_loadbufferx` (`lua_source_loader.cpp`). Initial load and hot-reload
  preflight share it. Long instance names therefore remain valid instead of
  letting a host load at 258 characters while its two-character-longer client
  silently loses all Lua mods at legacy `MAX_PATH`.

These rules let independent worktrees launch separate host/client groups
without moving, stopping, or reusing another agent's game processes.

## Verification evidence

Automated regression coverage lives in:

- `tests/test_overlay_renderer_contract.py` for the single reset-aware owner,
  callback ordering, batching/filtering, generation reuse, shared font
  implementation, and exact-process launcher invariants.
- `tests/test_lua_draw_verifier.py` for the bounded backbuffer retry that
  closes the display-list commit/render race without accepting the wrong
  pixels.
- `tests/test_local_multiplayer_process_isolation.py` for process ledgers,
  rejection of machine-wide cleanup, and launcher-owned stock navigation.
- `tests/test_lua_long_path_contract.py` for the shared extended-length Lua
  source loader used by both initial load and hot reload.

Live acceptance used fresh, named host/client groups and stopped only their
reported PIDs:

- A client loaded `sample.lua.hud_showcase` from a 274-character entry-script
  path, proving the long-path regression under the real 32-bit loader.
- The live 1600x900 D3D9 backbuffer showed the HUD, text, filled and outlined
  rectangles, thick line, and stock sprite over the hub. The verifier counted
  6,272 green-fill pixels, 1,818 cyan-line pixels, 313 white-text pixels,
  1,740 white-outline pixels, and 11,910 non-backdrop sprite pixels. Live
  world projection was visible and inside the viewport at generation 236.
- On the host-authoritative process, the retail native magic-hit handler
  applied an unfiltered 12-point hit for exactly 12 HP of real loss. Ordered
  `damage.dealing` and `damage.taken` rewrites reduced the next hit to
  1.466999 HP, and the cancellation filter produced exactly 0 HP loss.

## Current performance and robustness

The architecture remains appropriate for current HUD scale, but the dominant
fixed cost has changed from three state-block create/capture/release cycles to
one cached capture and bounded restores. Primitive-heavy HUDs now submit by
consecutive state/texture run instead of by command. Idle committed frames no
longer copy command strings on the render thread.

Textures remain `D3DPOOL_MANAGED`; atlas names and sprite rectangles stay
bounded and revision-checked; matrices and floats are finite-validated; D3D
failures use a capped log budget; and the native authored-UI lane remains
SEH-guarded. The mod-facing API and multiplayer fingerprint contract are
unchanged.
