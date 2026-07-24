# Custom Visuals / D3D9 Overlay Review — 2026-07-23

A code-level assessment of the loader's custom rendering stack: what it is,
whether it is performant, and a ranked improvement list. Verified against
source on this date; file references are exact.

## What the system is

Yes — Direct3D 9, matching the retail game. One shared hook feeds three
overlay pipelines:

- **Hook** (`d3d9_end_scene_hook.cpp`): resolves the live device from a game
  global, patches vtable slot 42 (`EndScene`), and fans out to up to 8 frame
  callbacks. Callbacks run **after** the original `EndScene` returns. Also
  hosts the backbuffer BMP capture used by the verification workflows
  (MSAA-resolve → SYSTEMMEM readback → BMP).
- **`lua_draw_renderer.cpp`** — the `sd.hud` immediate-mode lane: text /
  filled+outlined rects / lines / sprites as pre-transformed (XYZRHW)
  fixed-function quads via `DrawPrimitiveUP`. Text uses a GDI-baked 512×256
  Consolas atlas (ASCII 32–126, baked once, MANAGED pool). Mod sprite atlases
  are loaded once into MANAGED pool and cached by name with revision-based
  invalidation. A world→screen projection snapshot (viewport + W/V/P captured
  from the game) powers world-anchored HUD.
- **`lua_ui_renderer.cpp`** — the `sd.ui` authored-window lane. Notably it
  draws through the **game's own native panel renderer** (resolved render
  context + `DrawNativePanel`, SEH-guarded), so authored UI inherits stock
  styling instead of reimplementing it. Good design choice.
- **`debug_ui_overlay.cpp` + 50 `.inl`s** — the dev inspector: its own font
  atlas, widget-geometry/text capture from game memory, and surface
  rendering. Dev-facing; toggled by `loader.debug_ui` (which participates in
  the multiplayer fingerprint, so peers can't mix it silently).

Command flow for the Lua HUD: mods fill a `pending` list and commit, which
swaps `pending`→`active` (double buffer, `lua_draw_runtime.cpp:115`); the
render callback snapshots every mod's `active` list each frame under the
runtime mutex.

## Is it performant?

**At current HUD scales, yes** — typical cost is well under a millisecond per
frame, per-frame heap traffic is modest, and there are no per-frame texture
creations, no lost-device leaks, and no unbounded growth. But there is real
per-frame ceremony that costs 2–3× what the same output needs, and it is all
cheap to fix:

1. **Three full state blocks per frame.** Each pipeline independently runs
   `CreateStateBlock(D3DSBT_ALL)` → `Capture()` → draw → `Apply()` →
   `Release()` every frame (`lua_draw_renderer.cpp:331`,
   `lua_ui_renderer.cpp:381`,
   `debug_ui_overlay/label_resolution_surface_registry_and_frame_render.inl:251`).
   `D3DSBT_ALL` snapshots hundreds of device states; creating and destroying
   it per frame (×3) is the single largest fixed cost. The `Capture()`
   immediately after `CreateStateBlock` is also redundant — creation already
   records current state.
2. **No batching / redundant state churn.** Every rect, line, and sprite is
   its own `DrawPrimitiveUP` preceded by a full texture-stage reconfig,
   `SetFVF`, and `SetTexture` — even when consecutive commands share all
   three. Text is the exception: one string = one batched triangle list
   (good).
3. **Per-frame deep copies on the render thread.** `SnapshotLuaDrawFrames`
   copies every mod's full command vector — including a `std::string` per
   text command — under the shared runtime mutex, every frame, even when
   nothing changed. A `generation` counter already exists per frame; it just
   isn't used to skip unchanged copies.

## Correctness and robustness observations

- **Drawing after `EndScene`.** Callbacks draw once the scene is closed.
  This demonstrably works on the retail runtime and under DXVK/Proton, but it
  is outside the documented D3D9 contract (draw calls belong between
  `BeginScene`/`EndScene`). Drawing *before* calling the original — the
  standard overlay pattern — is a trivial reorder and removes the
  spec-fragility entirely.
- **Reset safety is genuinely sound, partly by accident.** All textures live
  in `D3DPOOL_MANAGED` (survive `Reset`), no default-pool resources are
  retained across frames, and the per-frame state blocks never span a
  `Reset`. Device *recreation* is handled by the `resource_device` swap check
  releasing and lazily rebuilding resources. There is no `Reset` hook, and
  none is currently needed — but note that the wasteful per-frame state block
  is what makes that true; a once-created state block (recommendation 1)
  must be released on device loss, so pair that change with a small
  reset/recreate notification.
- **Point filtering everywhere.** Scaled sprites and scaled text are drawn
  with `D3DTEXF_POINT`, so any non-1:1 HUD art looks blocky. Text is a
  single baked 16 px Consolas — fine for diagnostics, mediocre for
  mod-facing HUD polish; ASCII-only (non-ASCII renders `?`).
- **Defensive quality is high**: every D3D call is HRESULT-checked, draw
  failures are logged with a capped budget, matrices/floats are validated
  finite before use, sprite rects are bounds-checked against atlas
  dimensions, and the native-panel path is SEH-guarded.
- The three pipelines each maintain their own font atlas implementation —
  duplicate infrastructure worth consolidating eventually, though only a
  maintenance cost.

## Ranked recommendations

1. **Retire the per-frame `D3DSBT_ALL` state blocks.** Either create one
   saved-state block per device and reuse it (release on device change), or
   save/restore only the ~20 states the overlay actually touches. Biggest
   single win, applies ×3.
2. **Batch by (mode, texture) runs.** Accumulate consecutive same-texture
   quads into one vertex array and issue one `DrawPrimitiveUP` per run;
   configure stages only on run boundaries. Turns N commands into a handful
   of draws.
3. **Generation-gate the frame snapshot.** Copy a mod's command list only
   when its committed generation changes; idle HUDs become free and the
   mutex hold time drops.
4. **Draw before the original `EndScene`** instead of after, for contract
   safety at zero cost.
5. **`D3DTEXF_LINEAR` mag filtering for sprites** (keep POINT for the text
   atlas, or bake a 2× atlas for crisp scaled text).
6. **Consolidate the three font-atlas implementations** into one shared
   module when convenient.

None of this is urgent at today's HUD scales — the architecture (single
shared hook, managed-pool resources, double-buffered immediate-mode contract,
native-renderer reuse for authored UI) is the right shape, and the waste is
concentrated in per-frame ceremony that can be removed without touching the
API surface mods see.
