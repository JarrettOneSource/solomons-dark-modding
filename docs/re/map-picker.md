# Stock map picker

This note maps the retail `MapPicker` used when the player starts a run from
the Courtyard. It identifies the value boundary that a loader-owned
Boneyard picker must preserve. The stock tutorial controller does not invoke
`MapPicker`; after the Tutorial Game is active, the same ordinary Game map
control can reach this picker. The tutorial-side caller proof is documented in
[`tutorial-mechanics.md`](tutorial-mechanics.md#map-picker-handoff-for-mpk).

The addresses below are image-base virtual addresses for the analyzed retail
`SolomonDark.exe`:

- image base: `0x00400000`
- file size: `4,723,200` bytes
- SHA-256:
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`
- `MapPicker` vtable: `0x0079208C`

The analysis used the repository's read-only replicated Ghidra workflow. No
stock-game file was modified.

## Result

The picker does not enumerate `.boneyard` files. It scans a fixed 50-byte
Gameplay unlock bitmap, creates one generic UI entry for each unlocked story
index, and turns a click into
`data\levels\story<index>.boneyard`. That resolved native String is copied to
Gameplay's selected-Boneyard field at `+0x1BD8`. The picker then requests the
normal transition. Startup materializes the selected template as the working
`play.boneyard`, and `Arena_Create` loads that working file.

The start control is also the cancel/toggle control. Invoking it while the
picker is present starts the picker's close fade without setting its launch
sentinel. The picker is destroyed and no region transition is requested.

## 2026-08-26 affordance and Hub-wide activation correction

The start control is not a mutually exclusive compass/ready toggle. Fresh
read-only instruction and asset inspection of the same retail image closes the
complete five-record presenter in `0x0050DBF0`:

| College record | Gameplay control field | Presenter branch |
| ---: | ---: | --- |
| 14 | `+0xAF0` | return arrow while a `MapPicker` exists and is not closing |
| 15 | `+0xBB4` | unavailable symbol while Courtyard byte `+0x8EA0` is set |
| 16 | `+0xC78` | fixed `121 x 118` parchment base |
| 17 | `+0xD3C` | play triangle when no picker exists, and again while a picker closes |
| 18 | `+0xE00` | compass layer |

Records 17 and 18 are both submitted on every ordinary available frame. The
Courtyard fixed tick `0x0050C970` increments the integer phase at `+0x8EA4`
once per 100 Hz update. `0x0050DBF0` computes, with the retail float32 store
boundaries:

```text
radians = f32(f32(tick) * f32(pi) / 180)
compass_alpha = f32(0.5 + 0.5 * f32(sin(radians)))
action_alpha = f32(1 - compass_alpha)
```

The compass and current action record therefore crossfade complementarily on
a nominal 360-tick, 3.6-second sine cycle. The counter is not wrapped, so the
retail float32 angle store preserves its tiny phase-rounding residual instead
of bit-resetting at tick 360. Run-transition byte `+0x8EA8` forces
`compass_alpha = 1` and `action_alpha = 0`. This supersedes the older
interpretation that a fresh Hub shows only the compass and a separate
selected/ready state shows only the play triangle.

The same sweep closes reachability. `Game::RenderHud 0x005D2520` has exactly
one affordance call, guarded by the persistent Courtyard pointer
`DAT_00819A70`, not by the current fixed-room id or player coordinates.
`Game_AttachRegion 0x005CBA00` attaches `Game+0xE00` with the other Hub HUD
controls while that Courtyard owner exists. `Game_HandleControlAction
0x005D8120` forwards it to the Courtyard action vtable, and the sole callback
chain `0x00514A20 -> 0x0050E5E0` gates only the region fade at `+0x8E48`.
There is no world radius, proximity test, or Courtyard-current-room branch.
The control can therefore start/toggle a run from any stable College room;
crossing a room fade remains input-blocked by the common fade gate.

The optional rotated `CLICK HERE / WHEN YOU ARE / READY TO PLAY` painter is a
sibling of the global teaching-hint system: it is separately gated by
`DAT_00B3BCA1`, the no-picker/available/no-transition state, and application
tick `% 200 > 20`. It is not another activation target. Connected
non-authority suppression remains the loader policy documented in
`../bugs/beta32-ungated-client-interactions-2026-08-04.md`; it does not change
the offline/authority control contract above.

## Function map

| Address | Recovered role |
| ---: | --- |
| `0x00514A20` | Courtyard control dispatcher; recognizes the start-run control and calls `0x0050E5E0` at `0x00514AB9`. |
| `0x0050DBF0` | Dedicated renderer for the underlying `CLICK HERE / WHEN YOU ARE / READY TO PLAY` affordance; the full HUD calls it once at `0x005D3D02`. |
| `0x0050E5E0` | Opens a `MapPicker`, or closes the existing picker when the start control is invoked again. |
| `0x0050C730` | `MapPicker` constructor. |
| `0x00500980` | Creates and populates the unlocked-map entry list. |
| `0x00508C60` | Renders the picker background and entry markers. |
| `0x00508E20` | Handles an entry click and commits the selected Boneyard String. |
| `0x00500B40` | Begins ordinary close/cancel: sets the close flag and starts the fade. |
| `0x00509000` | Commits an already-selected path to the launch transition; used by the constructor's preselected/resume case. |
| `0x0050E980` | Picker tick/fade/destruction and launch-sentinel dispatch. |
| `0x0050E320` | Prepares the selected template as the working `play.boneyard` for run entry. |
| `0x005BB970` | Constructs Gameplay and stores the selected Boneyard template at Gameplay `+0x1BD8`. |
| `0x005CFA80` | Finalizes Gameplay startup and materializes the selected template when required. |
| `0x005CDDD0` | `Gameplay_SwitchRegion`; enters region 5 for the run. |
| `0x0046EA90` | `Arena_Create`; chooses and resolves `play.boneyard` or `testrun.boneyard`, loads it, and materializes the Arena. |
| `0x0046DC60` | Structured Boneyard load/generate boundary. |
| `0x00402AE0` | Native String assignment used by the loader handoff at Gameplay `+0x1BD8`. |
| `0x004EBA90` | Builds the eight-record `LevelPicker` sprite atlas used by this UI; it is not the `MapPicker` class. |

## Trigger and lifetime

The Courtyard action dispatcher at `0x00514A20` compares the activated
control with the Gameplay control stored at `+0xE00`. The start-run case
calls `0x0050E5E0` at `0x00514AB9`. No second direct call from the dispatcher
or control exists. The matching render path is likewise singular:
`0x005D2520` calls `0x0050DBF0` once at `0x005D3D02` while the Courtyard is
present. These two dedicated seams let the loader suppress both presentation
and activation for a connected non-authority client without hiding unrelated
Courtyard merchants or HUD layers.

When Courtyard `+0x8E94` is null, `0x0050E5E0`:

1. allocates `0xA0` bytes;
2. invokes `MapPicker::MapPicker` at `0x0050C730`;
3. stores the object at Courtyard `+0x8E94`;
4. stores the owning Courtyard at picker `+0x80`; and
5. attaches the picker to the stock UI tree.

When Courtyard `+0x8E94` is already non-null, the same function calls the
ordinary-close helper at `0x00500B40` and restores the underlying UI with
`0x005C7300` and `0x005C7390`. This is the stock cancel/toggle path.

The constructor initializes:

| Offset | Meaning |
| ---: | --- |
| `+0x78` | Fade alpha/progress. |
| `+0x7C` | Closing flag; initialized to zero. |
| `+0x80` | Owning Courtyard, filled by the caller. |
| `+0x84` | Completion/launch sentinel; initialized to `-1`. |
| `+0x88` | Beginning of the entry-list container. |
| `+0x90` | Entry count. |
| `+0x9C` | Entry pointer array. |

If the native String at Gameplay `+0x1BD8` already has a non-empty payload
at `+0x1BDC`, the constructor hides the interactive picker and invokes
`0x00509000`. That is a preselected/resume transition, not cancel.

## Data source and entry shape

`0x00500980` scans exactly 50 bytes beginning at Gameplay `+0x1CDC`. Byte
`i` is the unlock flag for story/map index `i`. A zero byte is skipped. A
nonzero byte creates a `0xB4`-byte generic stock UI control through
`0x00430430`, attaches it to the picker, lays it out from `LevelPicker` atlas
dimensions, and appends its pointer to the picker list.

Only a small part of the generic entry layout is picker-specific:

| Entry offset | Meaning |
| ---: | --- |
| `+0x00` | Generic UI-control vtable. |
| `+0x14`, `+0x18` | Position. |
| `+0x1C`, `+0x20` | Dimensions. |
| `+0x50` | Owning `MapPicker`. |
| `+0x6C` | Story/map index `i`. |

The picker therefore has no filename, display-name, mod, preview, or
filesystem record in each entry. Those are loader-seam concepts and must not
be inferred from the stock `0xB4` control.

`0x00508C60` draws the `LevelPicker` background record and a pulsing marker
for each pointer in the populated list. `LevelPicker_Build` at `0x004EBA90`
creates eight sprite records from `images/LevelPicker`; it is presentation
data, not the list's source.

## Selection and selected-value contract

`0x00508E20` ignores picks until the open fade reaches full alpha. It then
finds the clicked entry pointer in the picker list and reads entry `+0x6C`.
For index `i` it formats:

```text
data\levels\story<i>.boneyard
```

The path is resolved through `0x00423A30`. The resulting reference-counted
native String is copied into the Gameplay selected-Boneyard String whose
object begins at `+0x1BD8` (payload pointer `+0x1BDC`; reference-count fields
at `+0x1BE4` and `+0x1BE8`). The same index is recorded at Gameplay
`+0x1D40`.

After that copy the click handler:

- sets picker closing byte `+0x7C`;
- requests transition state `1` and transition kind `5` at the Courtyard
  transition owner `+0x8EA8/+0x8EAC`; and
- sets picker completion sentinel `+0x84` to `1`.

This String field, rather than the entry index or UI pointer, is the durable
selection value. A loader picker may have an arbitrary-size catalog, but its
successful pick must supply one resolved Boneyard path at this boundary.

## Cancel and dismissal

The close helper at `0x00500B40` sets picker `+0x7C` and starts the fade. It
does not write a selected String, a transition request, or the completion
sentinel.

`0x0050E980` decreases the fade while closing and removes the picker at zero.
It dispatches run preparation through `0x0050E320` only when `+0x84` is
nonnegative. A canceled picker retains its constructor value of `-1`, so it
is removed without launching.

`0x00509000` is a separate successful-selection helper. It validates the
preselected Gameplay String, applies the tutorial guard at Gameplay
`+0x1CD6`, and otherwise writes the same close, transition, and completion
state as an entry pick. It must not be used as the cancel callback.

## Launch consumption

The stock path separates the selected template from the mutable working
Boneyard:

```text
MapPicker click
  Gameplay selected template String              +0x1BD8
    picker completion tick                        0x0050E980
      selected-template preparation               0x0050E320
        working play.boneyard
          Gameplay startup/finalization           0x005CFA80
            Gameplay_SwitchRegion(5)              0x005CDDD0
              Arena_Create                        0x0046EA90
                structured Boneyard load          0x0046DC60
```

`0x0050E320` resolves the working `play.boneyard` path and prepares it from
the selected template. The later startup chain preserves the selected native
String at Gameplay `+0x1BD8` and materializes the working file as needed.

`Arena_Create` makes the final filename decision from Gameplay test-run state
at `+0x1BB4`: ordinary play uses `play.boneyard`; test-run mode uses
`testrun.boneyard`. It resolves that filename and passes it to `0x0046DC60`.
That loader procedurally generates first only when `DAT_00B3BEDC == 1`;
preselected/custom content uses the non-generation state and reads the
supplied Boneyard.

The loader hijack must therefore preserve two related facts:

1. the authoritative choice is a Boneyard path, not a stock story index; and
2. every peer must materialize the same chosen bytes at its own resolved
   working-Boneyard path before stock `Arena_Create` consumes it.

The loader must never distribute or trust one peer's absolute path. Catalog
identity crosses the network; each peer resolves that identity to the copy
already delivered with the host mod, then uses the stock working-file load
boundary locally.

## Tutorial relationship

The Tutorial controller never calls `MapPicker`. First-play boot loads
`data\levels\Tutorial.boneyard` through its own orchestration. Once that Game
is active, the normal map-control callback can still take the same verified
chain used by ordinary play:

```text
Game control callback 0x00514A20
  control = Game + 0x0E00
  Arena + 0x8E48 <= 0
    -> MapPicker_Open 0x0050E5E0
       -> MapPicker constructor 0x0050C730
```

The tutorial-side analysis independently recovered the same vtable, object
size, caller graph, Arena gate, and Arena picker pointer at `+0x8E94`. The
successful preselected-path helper also checks the tutorial flag at Gameplay
`+0x1CD6` before committing a launch. Tutorial orchestration therefore does not
change the ordinary picker's 50-byte list, generic entry shape, selected
String, or working-Boneyard consumption boundary documented here.
