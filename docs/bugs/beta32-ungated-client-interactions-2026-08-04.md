# beta.32 ungated client interactions

## Scope and baseline

This investigation started from `8d86100a337e7584f169834df0fa847a61120fb9`
(`v0.1.0-beta.32-1`) before any production fix. It covers two owner-playtest
regressions:

1. a connected transport client can see and activate the Courtyard start-run
   affordance; and
2. gameplay input continues to reach the local player while the blocking
   `Loading Boneyard` presentation is active.

The live baseline used isolated `uig-*` instances, audio disabled, and only UDP
ports `52161` through `52168`. The game copies and profiles lived below
`C:\sd-uigate-20260804`; no owner install or primary checkout was changed.

## Reproduction

### Connected client starts its own run path

An untouched two-peer build placed both peers in the shared hub. The client's
native parchment start affordance was visible. A window-scoped click at its
center caused only the client to fade from the hub to a permanently black
scene; the host remained in the hub. This reproduces the owner's report without
using a loader-authored start API.

### Gameplay input crosses the loading barrier

A client-side `runtime.tick` probe armed before the host began a synchronized
test run. On the first tick where
`sd.runtime.get_multiplayer_state().loading_screen.active` became true, it
queued positive-Y movement, both mouse buttons, and a belt binding. While the
overlay remained active the probe observed:

- 396 active loading ticks across `receiving_wave_checkpoint`,
  `materializing_participants`, `waiting_for_participants`, and
  `confirming_participants`;
- Y movement from `150.0` to `268.72839355469`;
- both mouse buttons becoming down; and
- the mouse-left edge serial advancing from `0` to `1`.

The changing transform and button edge are in-world input effects, not merely
accepted queue calls.

## Native Courtyard start path

The existing read-only Ghidra project was queried headlessly with analysis
disabled. No project database was modified.

### Render

`0x0050DBF0` is the dedicated Courtyard start-affordance renderer. It draws the
Gameplay controls and the exact string:

```text
CLICK HERE
WHEN YOU ARE
READY TO PLAY
```

The full gameplay HUD renderer at `0x005D2520` has one call to this function,
at `0x005D3D02`, guarded only by a non-null Courtyard. The function is a
`__thiscall` with the Courtyard in `ECX` and one stack argument. Its first three
instructions are `PUSH EBP`, `MOV EBP,ESP`, and `AND ESP,...`, so a six-byte
detour boundary is available. There was no loader hook or multiplayer-authority
test on this render path.

### Activation

`0x00514A20` is the Courtyard control dispatcher. Its vtable reference is
`0x00792654`. When the activated control is `Gameplay + 0xE00`, the dispatcher
calls `0x0050E5E0` at `0x00514AB9`. The other branches dispatch independent
merchant controls.

`0x0050E5E0` is the stock MapPicker start/toggle function already named
`map_picker_start` by the loader. Its only direct call from the Courtyard
dispatcher is the call above. The search therefore falsified a suspected
second direct run-start path: render and activation each have one dedicated
native seam.

## Root causes

### Client start affordance

`HasBoneyardAuthority()` correctly returns false for a connected transport
client. `ShouldHijackHostBoneyardStart()` consequently returns false too, but
`HookMapPickerStart` treats that result as a reason to call the stock
trampoline. The authority rejection therefore opts the client back into the
native MapPicker instead of suppressing activation.

There are two compounding gaps:

- no hook exists at `0x0050DBF0`, so the client renders the stock affordance;
- `InitializeBoneyardPicker` installs no hooks when the custom boneyard catalog
  is empty, although connected-client suppression is required independently of
  whether any provider contributed a custom map.

The custom picker APIs themselves already reject non-authority peers. The bug
is the stock fallback surrounding them.

### Loading-screen input

`LoadingScreenSnapshot.active` is presentation and lifecycle state only. The
keyboard edge hook, mouse refresh hook, injected movement queue, cast intent,
and local `PlayerActor` stock-input bridge never consult it. The loading flow
therefore paints a modal screen without owning gameplay input.

Blocking only keyboard edges would be incomplete: movement is written through
the Gameplay movement fields, mouse holds are consumed through both native
input buffers, and casts use the local cast-intent field. The live positive-Y
movement result confirms that these paths bypass the existing
`BoneyardPickerOwnsScancode` check.

## Required correction

The implementation must preserve these invariants:

- connected transport clients neither render nor activate the Courtyard start
  affordance and cannot reach either stock or custom MapPicker state;
- host and offline/solo calls retain their existing stock-or-custom behavior;
- the two stock authority hooks remain installed even with zero custom
  boneyards, while the custom full-HUD renderer may remain catalog-dependent;
- one blocking-overlay ownership policy derives from
  `LoadingScreenSnapshot.active` and is enforced at the shared gameplay input
  ingress/stock-player bridge, covering movement, keyboard edges, both mouse
  buttons, and cast intent;
- input submitted during the barrier is dropped, not deferred until the
  overlay closes; and
- loader-owned loading UI continues through its own window/render path.

Static regression contracts must bind the recovered render address, both
client suppressions, zero-catalog hook installation, the common overlay
predicate, queue dropping, and the stock-tick input mask. Live acceptance must
then prove client/host/solo behavior and zero transform, mouse-edge, mana, or
cast change from input injected during an active barrier.
