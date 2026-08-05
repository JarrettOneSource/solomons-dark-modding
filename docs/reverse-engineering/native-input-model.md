# Native input model and browser Intent contract

Status: **G14 closed** from retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Static findings are from the read-only Ghidra project; dynamic findings are from
the live `inp-earth` and `inp-water` solo instances recorded at loader source
SHA `8b49b15a42e5e499a4dce33ef78390a7ccc3cfee`.

This document distinguishes three things that are easy to conflate:

1. Win32 control routing decides which screen surface receives a mouse edge.
2. `Input` samples held device state for the fixed-step game graph.
3. `PlayerActor::Tick` turns the sampled levels into movement, aim, and spell
   state, subject to gameplay and UI gates.

The active retail PC path does **not** implement click-to-move. A left click
over the world is primary aim/cast input. Native movement is a level-triggered
keyboard vector. The binary retains a non-hit-testable movement-control object,
but normal mouse routing cannot target it; that dormant object is not evidence
of a shipped mouse movement action. The browser `Intent` contract deliberately
supports both a world target and a unit movement vector so a future browser
producer may offer point movement without misdescribing it as native behavior.

## Evidence boundary

| Claim class | Evidence | Confidence |
| --- | --- | --- |
| Win32 ingress, queue records, control routing, hit-test order, fixed-step order, keyboard/mouse sampling | Headless Ghidra decompilation/disassembly at the addresses below | High |
| Primary aim, Earth charge, Frost channel, right-button secondary path, default bindings | Headless Ghidra plus the live traces | High |
| Open-ground click, wall click, tap/three Earth holds, Frost hold/release, HUD swallow | Live generated [`input-goldens.json`](../../tests/fixtures/webgame/input-goldens.json) | High |
| Loading-screen seal | Existing implementation, bug record, and static contract | High for loader behavior; this is not a retail feature |
| Complete gamepad action path and menu focus order | Negative xref/control-graph census | **Absent by observation** |

Addresses are preferred-image virtual addresses for the analyzed 32-bit retail
image. Loader source names are supporting observation seams, not replacements
for stock behavior.

## Device to game path

### Ordered path

| Order | Native location | Contract |
| --- | --- | --- |
| 1. Win32 ingress | `GameWindowProc` `0x00443440` | Receives keyboard, character, mouse move/button/wheel, and system-key messages. `0x00442910` converts client coordinates to the game's native coordinate scale. |
| 2. Event buffering | append routine `0x00443330`; record base `0x00818CA4`; count `0x00B4021C`; stride `0x18` | The WndProc appends an ordered record. A message is not consumed directly by `PlayerActor::Tick`. Mouse down also updates the raw held-button mask and starts Win32 capture; mouse up clears the bit and releases capture. |
| 3. App-tick drain | queue drain `0x0040D6B0`; app dispatch `0x0040D900` | The app tick drains queued edges in order and invokes the control router. This is the surface-dispatch path. |
| 4. Control target | move router `0x0040DF10`; down `0x0040E050`; up `0x0040E190`; recursive hit test `0x00428620` | Capture wins first. Otherwise the active modal/main root is hit-tested. The first topmost hit receives the edge through its mouse virtual. |
| 5. Device sample | `Input::Refresh` `0x00429820`; keyboard level query `0x00429930`; keyboard edge query `0x00429950` | The active double buffer toggles at `Input + 0x480`. DirectInput supplies 256 keyboard bytes. The mouse bytes are cleared and repopulated from the app raw-button mask (left bit `1`, right bit `2`, middle bit `4`). |
| 6. Fixed tick | scheduler `0x0040D3C0`; fixed-step body `0x0040D1B0`; object-manager traversal `0x004022A0` | Input is drained/refreshed before registered game objects tick. The nominal fixed step is 10 ms. Input was registered before `Game`, so the tick graph sees the new sample, not the prior one. |
| 7. Game controls | `Game::Tick` `0x005D7EF0`; control synthesis `0x005C6D60`; global `Game*` slot `0x0081C264` | The embedded movement control at `Game + 0x8C` exposes its vector at `+0x108/+0x10C`; the aim/cast control at `Game + 0x158` exposes aim at `+0x1D4/+0x1D8`, primary level at `+0x1E4`, and its right-button discriminator at `+0x1E5`. Movement and cast seals are `+0x1ABD` and `+0x1ABE`. |
| 8. Actor dispatch | `PlayerActor::Tick` `0x00548B00` | The local actor consumes the movement, current aim, and cast level once per stock tick and dispatches the selected primary/secondary skill. |

The WndProc encoding is itself part of the contract:

- `WM_KEYDOWN` becomes native type `6`, `WM_KEYUP` type `7`, and character
  input type `8`. Key-up also produces the native snapshot record type `0x0D`.
- `WM_MOUSEMOVE` is type `1`; button down/double-click is type `2`; button up
  is type `3`; wheel is type `0x0C`.
- A control event represents left as button `-1`, middle as `0`, and right as
  `+1`. That encoding is separate from the held-mask bits above.
- `WM_SYSKEYDOWN` does not create a general Alt-modified action. The special
  Alt+Enter path becomes native type `0x0E`; other Alt system-key input is
  swallowed at the window boundary.

### One world click, end to end

For one left click over the arena:

1. `WM_MOUSEMOVE` and `WM_LBUTTONDOWN` enter `0x00443440`. Coordinates are
   scaled, records are appended, the left held bit becomes `1`, and Win32 mouse
   capture begins.
2. On the next app/fixed tick, `0x0040D6B0` drains the edge. `0x0040E050`
   routes it to the hit control. The arena's full-window control can be the
   target; its constructor is `0x00464EE0`, vtable is `0x00785934`, and its
   down forwarder `0x00427C60` reaches owner slot `+0x64` (`0x004A6E30`, a
   no-op for this owner).
3. Independently of that control callback, `0x00429820` mirrors the raw left
   bit into the active input buffer. The control router and the held-state path
   therefore observe the same physical click for different purposes.
4. `0x005C6D60` refreshes the two embedded control objects. `Game::Tick`
   reanchors the aim control to the current player screen point before
   `PlayerActor::Tick` reads its unit direction and primary level. If
   `Game + 0x1ABE` is zero, checks at `0x005495B0` and `0x0054960D` permit the
   selected primary skill to dispatch. `0x005C7390` owns the seal transition and
   clears stale aim when blocking begins.
5. `WM_LBUTTONUP` takes the same queue/router path, clears the held bit, and
   releases Win32 capture. The next fixed tick sees the cast level fall and
   runs the spell's release/stop transition.

This dual route explains why a world control callback may be a no-op while the
click still casts, and why a HUD control can receive the edge while the actor
does not cast.

## Surface routing

### Hit-test and priority rules

The down/move/up routers use the same ownership rules:

1. An active captured control wins; no other surface is hit-tested until mouse
   up releases capture.
2. With no capture, the active modal root is considered before the ordinary
   main root. A menu/dialog therefore owns the click instead of the arena.
3. `0x00428620` walks children in reverse insertion order. Last-added/topmost
   children are tested first, deleted controls are skipped, and the first hit
   wins. There is no bubbling to a lower world surface after a control accepts
   the edge.
4. Coordinates are converted into each parent/control's local space before its
   mouse virtual is invoked: down at vtable `+0x3C`, move at `+0x40`, up at
   `+0x44`.
5. If no child wins, the full-window arena/main control is the fallback. That
   is the world surface, but a world click means aim/cast, not movement.

| Surface | Winning rule | Result |
| --- | --- | --- |
| Modal menu/dialog | Active modal root, then reverse-z child hit | Its control callback owns the edge. The lower HUD and world do not receive it. |
| HUD | Topmost HUD child hit before the arena fallback | The HUD interaction owns the edge. In the live `hud_click_swallowed` trace, the input buffer still sampled left held while `cast_blocked=false` and `gameplay_input_blocked=false`, yet every actor tick kept `cast_active=false`. No world action was emitted. |
| Arena/world | No captured/modal/HUD child wins, so the arena fallback is hit | The full-window aim control owns normal mouse input. Left level drives primary aim/cast; right is the configured secondary/belt input. The movement-control object is not hit-testable in the PC profile, so there is no native world-move click. |
| Loading overlay (`uigate`) | Loader blocking-overlay predicate supersedes gameplay ingress | Gameplay input is discarded while loader UI keeps its own window/render path. |

Controls may swallow input by returning through their own handler without
forwarding to an owner/world handler. The first-hit rule means "not handled as
gameplay" is final for that edge. There is no later z-layer retry.

### Loading-screen input seal (`uigate`)

The retail loading presentation did not provide the multiplayer loader's
required seal. The implemented contract is recorded in
[`beta32-ungated-client-interactions-2026-08-04.md`](../bugs/beta32-ungated-client-interactions-2026-08-04.md)
and pinned by
[`static_re_ui_interaction_gate_contracts.py`](../../tests/re/static_re_ui_interaction_gate_contracts.py).
When `LoadingScreenSnapshot.active` is true:

- the common `BlockingOverlayOwnsGameplayInput()` predicate owns gameplay
  ingress;
- pending scancode, movement, both mouse holds, mouse edges, and cast queues
  are cleared;
- the current movement lanes, both active mouse-buffer bytes, keyboard edges,
  and cast intent are masked before the stock local-player tick;
- blocked input is **dropped, never deferred** and never restored after the
  overlay closes; and
- loader-authored loading UI still receives its own window/render input path.

This is the browser contract too: a blocking load state emits no gameplay
`Intent`. Producers must discard device state changes seen inside the barrier
and require a fresh post-barrier edge/level.

## Semantics per action

### Movement: keyboard vector, not click-to-move

Native movement is a level vector synthesized at `0x005C6D60` and consumed from
`Game + 0x108/+0x10C` by `0x00548B00`. Keyboard levels are normalized, so
diagonal movement is a direction rather than two independent full-speed axes.

The reason this is not merely a negative live observation is visible in the
control graph. `Game` embeds a movement control at `Game + 0x8C` and the
full-window aim/cast control at `Game + 0x158`. Both use mouse down/move/up
handlers `0x0042FF80`, `0x004301F0`, and `0x004303D0`, but the generic hit test
at `0x00427EB0` returns a control itself only when flags bit `0x01` is set. In a
fresh live PC profile the movement control is `0x14` (not targetable), while the
aim control is `0x15` (targetable) and spans the native viewport. Mode `0` at
`0x00B3BCB0` instead feeds the movement object from keyboard bindings through
`0x0042FD80`. The dormant mouse-capable class therefore does not create an
active mouse movement route.

A click supplies neither a target point nor a path request and is not a held
movement repeat in the active PC route. The live trials classify the actual
cursor world point with `sd.nav.test_segment` before recording: one segment is
open and the other blocked by stock navigation/collision. Both traces have:

- zero `move` Intents;
- zero native actor-position delta; and
- a primary aim plus press/hold/release cast stream.

The fixture names contain `native_absence` intentionally: they are the requested
open-ground/wall click trials and prove that "click-to-move" is absent, rather
than inventing a native behavior to satisfy the roadmap's earlier wording.

### Primary click-to-cast and aim

Mouse down at `0x0042FF80` enables the primary/alternate level and derives the
primary aim as a normalized vector from the current player screen anchor to the
native mouse point:

```text
native_primary_aim = normalize(mouse_screen - player_screen_anchor)
```

Mouse move handler `0x004301F0` updates the stored pointer point and mouse up
`0x004303D0` clears the level. While held, `Game::Tick` reanchors the control to
the current player projection through `0x0042FE50` and `PlayerActor::Tick`
consumes the latest vector every fixed tick. Aim can therefore resample when the
pointer moves, when the actor moves, or when camera/view state changes. It
persists only while all three remain unchanged.

The abstract producer emits a world point. The exact camera projection recovered
at `0x00462110` is:

```text
world.x = view_origin.x + mouse_screen.x / view_scale
world.y = view_origin.y + mouse_screen.y / view_scale
```

For primary casts this world point is a canonical representation, not a claim
that retail stores a point: retail stores the player-anchored unit direction.
A faithful producer reprojects throughout a hold when pointer, player, or camera
state changes. Cursor-placed secondary spells do use the world projection
directly.

### Earth: hold-to-charge and release

Earth primary is skill `0x28` (decimal `40`). `PlayerActor::Tick` enters its
dispatcher at `0x00544C60`; Boulder construction is `0x005FA270`, held update is
`0x00609D30`, and release virtual is `0x005E5450`.

- **Threshold:** zero ticks, therefore 0 ms. A Boulder exists on the first held
  stock tick. There is no minimum-charge timer before the cast becomes real.
- **Initial state:** charge starts at approximately `0.18`.
- **Cadence:** one update per fixed stock tick (nominally 10 ms). Each update
  adds `growth_rate * 0.0025`, clamped to `max_charge`; the recorded level-one
  growth rate is `0.5`, so the observed increment is about `0.00125` per tick.
- **Aim while held:** the dispatcher revisits the current aim/target each held
  tick. Pointer movement can retarget the live Boulder before release.
- **Release:** the first tick after the primary cast level falls runs the native
  release path. A skill transition or charge cap may also end the gather loop.

The three live holds reached distinct maxima: approximately `0.19375` at 120
ms, `0.25375` at 600 ms, and `0.36875` at 1500 ms. These figures validate input
cadence only. Damage is deliberately not re-derived here; use
[`multiplayer-earth-charge-baseline-2026-07-26.md`](multiplayer-earth-charge-baseline-2026-07-26.md)
and
[`earth-boulder-damage-formula-2026-07-27.md`](earth-boulder-damage-formula-2026-07-27.md).

### Frost: channel start and stop

Frost primary is skill `0x20` (decimal `32`). Its dispatcher `0x00543860` runs
on every tick with primary cast held. The channel-loop transition is reached at
`0x00549BB2`; after the level falls, the stock transition/stop path at
`0x00549725` runs on the following actor tick(s). There is no charge threshold:
press starts the channel on the first eligible tick, hold sustains it, and
release stops it. Sound/animation cleanup can trail the input fall by another
stock tick, so consumers must key channel authority to the cast level, not to a
presentation loop still finishing.
The longer presentation lifecycle is cross-checked in
[`multiplayer-frost-channel-stop-2026-07-26.md`](multiplayer-frost-channel-stop-2026-07-26.md).

### Right click and modifiers

Right is raw held bit `2`, control button `+1`, and binding pseudo-key `0x201`.
In both stock control presets belt slot 1 defaults to `0x201`, making right click
the default secondary/belt action. `0x0054CC50` contains the secondary-at-mouse
matrix; the low byte at `0x00B3BCF4` enables cursor/world-point placement for
eligible secondaries.

There is no stock Shift-click, Ctrl-click, or Alt-click action family. Shift and
Ctrl can participate only if the normal binding system is explicitly rebound
to their scan codes. Alt system keys are swallowed as described above, except
the dedicated Alt+Enter display toggle.

### Keyboard bindings and defaults

The preset initializer is `0x005A8790`. Values are DirectInput scan codes except
the mouse pseudo-code. A fresh WASD live profile also recorded menu `0x01`,
inventory `0x17`, skills `0x14`, belt 1 `0x201`, and belts 2-8 `0x02..0x08`.

| Action | WASD preset (mode 2) | Arrow preset (mode 1) |
| --- | --- | --- |
| Up | `W` / `0x11` | Up / `0xC8` |
| Down | `S` / `0x1F` | Down / `0xD0` |
| Left | `A` / `0x1E` | Left / `0xCB` |
| Right | `D` / `0x20` | Right / `0xCD` |
| Menu/back | Escape / `0x01` | Escape / `0x01` |
| Inventory | `I` / `0x17` | `I` / `0x17` |
| Skills | `T` / `0x14` | `T` / `0x14` |
| Belt 1 | Right mouse / `0x201` | Right mouse / `0x201` |
| Belts 2-8 | `1` through `7` / `0x02..0x08` | Delete, End, Backspace, Page Up, Page Down, Insert, Home / `0xD3,0xCF,0x0E,0xC9,0xD1,0xD2,0xC7` |

The binding globals are movement at `0x00B3BCB4..0x00B3BCC0`, inventory
`0x00B3BCC4`, skills `0x00B3BCC8`, menu `0x00B3BCCC`, and belt slots
`0x00B3BCD0..0x00B3BCEC`.

### Edge-triggered versus level-triggered

| Input/use | Trigger model |
| --- | --- |
| Control hit, menu activation, interact, cast press/release | Win32/queued edge |
| Keyboard movement | DirectInput level sampled each fixed tick |
| Primary/secondary held, Frost channel | Mouse/cast level sampled each fixed tick |
| Aim | Latest level; updated by mouse-move edges while held and consumed each tick |
| Earth charge | Level-driven update every fixed tick; release on falling level/stock transition |
| Keyboard binding edge query | `0x00429950`; separate from the level query at `0x00429930` |

## Intent

The normative machine form is
[`webgame-contracts/intent-schema.json`](../../webgame-contracts/intent-schema.json).
The schema root is the action union every device producer targets:

```text
Intent =
  | { kind: "move", phase: "start" | "update" | "stop",
      move: { type: "world_target", point: WorldPoint }
          | { type: "unit_vector", vector: Unit2 } }
  | { kind: "aim", point: WorldPoint }
  | { kind: "cast", slot: "primary" | "secondary",
      phase: "press" | "hold" | "release" }
  | { kind: "interact", target: string, phase: "press" | "release" }
  | { kind: "menu_nav", command: "up" | "down" | "left" | "right"
      | "confirm" | "back" | "next" | "previous",
      phase: "press" | "release" }
```

`Unit2` components are bounded to `[-1, 1]`; producers and tests additionally
require magnitude 1 within floating-point tolerance. A `move.stop` record repeats
the producer's last target/vector, avoiding an invalid zero "unit" vector.

### Native mapping

| Native observation | Intent output |
| --- | --- |
| Keyboard movement level begins/changes/ends | `move` with `unit_vector` and `start/update/stop` |
| Native cursor/player/camera projection changes | `aim` with the current world point |
| Left down / eligible held tick / left up | primary `cast` press / hold / release |
| Right/belt-secondary down / held / up | secondary `cast` press / hold / release, plus `aim` when cursor-placed |
| HUD/menu control hit | `interact`; no world `cast` or `move` from the same edge |
| Designed controller menu focus action | `menu_nav` (browser-only; no native focus order to copy) |

A browser mouse producer may choose to emit `move.world_target`, but the native
mouse producer never does. A controller producer emits `move.unit_vector` and a
world `aim` point. The sim receives only this union and never Win32, DOM, or
Gamepad API events.

### Lossless native-mouse profile

There are two required meanings of lossless:

1. **Semantic replay:** the world aim point is retained on every held actor
   sample, and the cast slot plus exact press/hold/release tick stream reproduce
   native mouse gameplay. Native mouse has no movement information to lose in
   the active PC route.
2. **Bit-exact trace round trip:** `$defs.nativeEncodingRecord` is a golden-only
   envelope with zero or more Intents plus one immutable `native_source.raw`.
   There is exactly one encoding record for every recorded Win32, input-sample,
   and actor-tick event. Samples which emit no semantic action retain an empty
   `intents` array. Reconstructing every `native_source.raw` in order is exactly
   equal to `raw_timeline`, and both canonical SHA-256 values match.

This provenance envelope is not sent to the sim and does not pollute `Intent`.
It exists so the native producer can be audited without pretending that every
raw sample is a gameplay action.

## Live goldens and recorder contract

[`input-goldens.json`](../../tests/fixtures/webgame/input-goldens.json) was
mechanically generated by
[`capture_native_input_goldens.py`](../../tools/capture_native_input_goldens.py).
Each header names the exact instance, source SHA, executable SHA, capture method,
timestamp, trace hash, and round-trip hashes. The traces were driven through the
exact staged PID/path with `SendMessageTimeoutW` mouse messages into the retail
WndProc; no fixture event or Intent was hand-authored.

The harness raised the disposable solo actor's HP/max HP to 5000 before each
trace so the wave could not kill the recorder subject. Those writes occurred
through `sd.debug` while the recorder was disarmed; they do not alter the input,
camera, cast, charge, or routing records and are not product behavior.

The additive recorder is read-only and inert unless explicitly armed through
`sd.debug`. It observes:

- the stock WndProc before/after loader ownership decisions;
- post-native `Input::Refresh` state; and
- local `PlayerActor` state after each stock tick, including the native active
  Boulder object when readable.

It is bounded at 768 records. State transitions are always recorded; unchanged
input samples are checkpointed every 10 actor ticks, while every actor tick is
retained. A capture fails instead of writing a fixture if any event is dropped.
The eight final captures contain all three event kinds and prove exact
raw-to-encoding-to-raw equality.

## Absent by observation

- **No active native click-to-move:** no target-point request or path request
  exists, and normal PC mouse routing cannot target the embedded movement
  control. The class is mouse-capable, but its live `0x14` hit-test flags make it
  dormant while the full-window `0x15` aim control owns world clicks.
- **No complete native gamepad path:** `0x005C6D60` contains a partial generic
  joystick-axis mode capable of writing movement/aim lanes. The binary census
  found no complete controller button-to-cast/interact mapping, no supported
  action-binding preset, and no menu navigation integration. Partial axes are
  not gamepad support.
- **No native menu focus order:** menus are pointer hit-test trees. There is no
  default focus, next/previous focus graph, D-pad traversal, wrap rule, or
  controller back/confirm model. G11 must design those and label them
  designed-not-observed.
- **No native modifier action layer:** ordinary modifier chords do not form a
  separate command vocabulary.

## Not Yet Reversed

- The exact final retail field/predicate which suppresses the actor cast level
  for every individual HUD control has not been named. The routing outcome is
  proven live: the HUD trace has left sampled, all gameplay/cast gates open,
  and no actor cast. Do not guess the leaf predicate.
- Individual menu control graphs, screen-by-screen swallow behavior, and mouse
  wheel consumers belong to G11 and are not claimed here.
- The partial joystick-axis substrate's device enumeration and vendor mapping
  are not a supported action path and were not expanded into a fictional native
  controller contract.
