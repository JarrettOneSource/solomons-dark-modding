# Native Game Over session semantics

## Scope and evidence

This note separates the stock terminal Game Over transition from the
multiplayer death/spectator presentation. It intentionally does not redefine
the corpse timer, death animation, dropped staff, or red death effect covered
by [native-player-death-spectator.md](native-player-death-spectator.md).

The static findings below come from the analyzed retail executable:

- file: `SolomonDarkAbandonware/SolomonDark.exe`
- SHA-256:
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`
- Ghidra project: `Decompiled Game/ghidra_project/SolomonDark.gpr`
- headless workflow: `scripts/Invoke-GhidraHeadless.ps1` with a read-only
  replica and `tools/ghidra-scripts/decompile_targets.py`

The live baseline used the isolated `go-base-solo-a1` loader instance with one
participant and zero transport peers. A stock magic-hit dispatch reduced the
local player from positive life to negative life and reached the native corpse
drive state. The run-ended detour suppressed Game Over and, after the
presentation delay, displayed `Spectating - waiting for an alive player`.
`sd.ui.get_snapshot()` reported no native UI surface. This proves that an
initialized multiplayer transport is not evidence of a multiplayer session.

## Retail terminal call graph

The PlayerWizard terminal path eventually invokes the active arena's terminal
virtual. For the retail arena, that virtual is `FUN_004633D0`:

```text
PlayerWizard terminal dispatch
  -> Arena virtual +0xD8
     -> FUN_004633D0
        -> FUN_0068B6D0(6)
        -> FUN_0068B6D0(4)
        -> Game_OnGameOver (0x005CB570)
```

The two audio actions happen before `Game_OnGameOver`. The loader's existing
run-ended hook is installed at `0x005CB570`, so returning from that detour
preserves the native death/audio work while suppressing only the terminal
screen. Calling its trampoline later is the exact way to resume the retail
terminal transition; reimplementing the arena virtual or its audio work would
duplicate stock behavior.

`Game_OnGameOver` allocates `0xB0` bytes, constructs the object through
`FUN_005CAD40`, and installs it through the current application's surface
virtual at `+0xA8`. The constructed object uses vtable `0x0079B0CC` and builds
the stock `GameOver` presentation. Its renderer at `0x005C9030` draws the two
active Game Over atlas records, text, and the fullscreen fade layers.

### Boneyard/survival presentation branch

The renderer has one stock mode split which is material to multiplayer
acceptance. When `DAT_0081A434` (`0x0081A434`) is zero, `GameOver::Render`
draws the normal `GAME`, `OVER`, and click-prompt glyphs as their object-local
alphas become positive. When it is nonzero, the renderer intentionally skips
those glyphs and draws only the fullscreen fade layers. The Boneyard
`testrun` path used by launcher multiplayer starts with this flag nonzero.
Consequently, a black terminal frame in that mode is the retail Game Over
presentation, not evidence that the object failed to install.

The Game Over object is not an opaque-black hold. Fresh decompilation of its
constructor, tick (`FUN_005CF4F0`), and renderer (`FUN_005C9030`) recovered
the complete fixed-tick envelope:

| Field | Initial value | Tick recurrence | Render role |
|---|---:|---|---|
| `+0x78` | `1.0` | `max(0, value - 0.025)` | entry black overlay; transparent after 40 ticks |
| `+0x7C` | `-1.5` | `min(1, value + 0.005)` | normal-mode GAME/OVER alpha |
| `+0x80` | `-2.0` | `min(1, value + 0.005)` | normal-mode continue-prompt alpha |
| `+0xA4` | `0.0` | input-path dependent | exit black overlay |
| `+0xA8` | `0` | renderer sets only after exit alpha is exactly `1.0` | transition-ready gate |
| `+0xAC` | `0` | increment by one | input/timeout clock |

Normal mode draws GameOver atlas record 0 at viewport center X and center
Y minus 175, record 1 at center X and center Y plus 125, and the continue
prompt at `(width / 2, height - 50)`. The records are respectively `307 x 119`
and `306 x 120`. Boneyard mode suppresses all three semantic glyphs, but it
retains both black overlays and therefore reveals the resident Arena beneath
the entry fade after 40 ticks.

The tick-1000 Boneyard edge synthesizes an accepted input; it does not jump
immediately to the next surface. Accepted Boneyard input raises exit alpha by
exactly `0.0025` per tick, taking 400 ticks to reach black. The ordinary mouse
branch uses `0.05` (20 ticks), while its alternate/controller branch uses
`0.004` (250 ticks). Render observes exact opacity, sets `+0xA8`, and only a
later tick follows the completion lineage. A web Boneyard port must therefore
freeze its terminal Arena image, run the 40-tick black-to-clear entry, hold it
clear through the input gate, and remain on Game Over for the complete
400-tick clear-to-black exit. Treating `gameOverTicks / 150` as a single
increasing alpha reverses the native entry fade and hides the authored hold.

The completion path is also mode-specific:

- the normal story branch archives the completed run, creates scene type
  `0xFA2` (`Mortuary`), and switches gameplay regions;
- the Boneyard branch reaches its stock input-acceptance threshold at GameOver
  tick 1000. It does not close merely because the counter reaches that value.
  Once stock input is accepted, completion clears `DAT_0081A434`, runs the
  stock completed-run cleanup, and calls `FUN_005A7F60` (`0x005A7F60`) to
  select and install the stock front-end surface.

Read-only live evidence on 2026-07-25 found the Boneyard GameOver object in
the application's `+0x44` CPU manager with vtable `0x0079B0CC`. Across a
ten-second sample its tick counter advanced from 6 to 972, title alpha from
`-1.47` to `1.0`, and click alpha from `-1.97` to `1.0`, while the renderer
correctly remained fade-only because the mode flag was set. This distinguishes
the stock mode branch from both a stalled GameOver tick and an arbitrary dark
death frame without writing native state.

The same three-peer trace then observed the stock
`Gameplay_SwitchRegion(game, 1)` hook on all processes and a stable
`memorator` scene after the GameOver object closed. The front-end surface
dispatch does not itself move a connected multiplayer party into the shared
Courtyard. That is why waiting only for a main-menu surface leaves a post-run
party parked in the private Memoratorium even though native Game Over cleanup
has completed normally.

### Stock post-Boneyard front-end lineage

The follow-up headless pass recovered the exact native objects behind the
post-Boneyard front end:

```text
GameOver Boneyard completion
  -> FUN_005A7F60                              0x005A7F60
     -> MainMenu installer                     0x005A7D90
        -> MainMenu constructor                0x0058D940
        -> application +0xDAC = MainMenu*
        -> register surface                    0x004277E0
        -> application surface virtual +0xA8

stock post-run Menu input
  -> HallOfFame factory                        0x005A7E30
     -> HallOfFame constructor                 0x00598120
     -> application +0xDB0 = HallOfFame*
     -> register surface                       0x004277E0
     -> application surface virtual +0xA8

HallOfFame input virtual +0x10                 0x00589DB0
  -> if controller+0x7C == 0.0, set it to 1.0
  -> RET 4: consumes one ignored 32-bit stack argument
HallOfFame::Tick virtual +0x08                 0x00589CD0
  -> controller+0x78 += controller+0x7C * dt
  -> when controller+0x78 > 1.0:
       MainMenu installer                      0x005A7D90
```

The outer Hall of Fame controller has vtable `0x00799334`. It is distinct
from the render-helper object with vtable `0x00799264` that the observability
layer tracks while drawing the screen. This distinction matters for safe
automation: invoking the input virtual is valid only after reading
`application+0xDB0` and validating the outer controller's exact vtable and
slot-`0x10` target.
Its machine-code ABI is not a no-argument C++ member function: the handler
returns with `ret 4`. Typed dispatch must therefore supply one ignored 32-bit
stack argument in addition to `ECX=this`. Calling it as `void
(__thiscall*)(void*)` leaves the caller and callee with different stack
expectations and corrupts the process on return. The binary layout records the
four-byte contract beside the handler address.

Read-only three-peer control runs confirmed the live sequence. After native
Game Over completion all processes were stable in private `memorator`; the
stock Menu binding exposed `hall_of_fame` on every process. The gameplay mouse
queue then rejected a click because gameplay is no longer active, correctly
showing that Hall of Fame belongs to the application front end. The safe
continuation seam is therefore its native controller virtual on the
application thread. The handler only changes state once `controller+0x7C`
has reached zero, so a call made during the initial fade is a safe no-op.
Automation must retry the validated handler until the surface advances; call
return alone is not proof that Hall of Fame accepted the input.
After the main menu reopens Create, the multiplayer onboarding flow starts a
new loadout generation. It remembers the choices committed on the preceding
Create owner and preselects them on the new stock owner at `Create+0x1A4`
(element) and `Create+0x22C` (discipline). Both stock choice groups remain
interactive. Clicking the retained discipline confirms the unchanged loadout
in one semantic stock action; choosing a different element returns the stock
controller to its discipline step before that new pair is committed. The
discipline is masked only while the new pick is uncommitted or, on a client,
while the authority has not published a world-ready state. This prevents
stock world creation from bypassing the picker or the host barrier without
inventing a replacement screen.

Two attempted direct `Gameplay_SwitchRegion(game, 0)` probes are negative
evidence, not an implementation option. One ran immediately after the
stock region-1 transition and one waited for the same private scene, world,
and local actor to remain unchanged for two seconds. Both access-violated all
three isolated processes. Post-run continuity must follow the native
front-end objects above and must never issue a raw region switch from
Memoratorium.

## The Game Over object owns the post-death flow

The Game Over tick at `0x005CF4F0` owns input arming, timeout behavior, fade
progress, and completion. Once its close conditions are satisfied, it invokes
its native close virtual at `+0x18` and follows the stock global-state branch.
The normal retail branch:

1. performs the native Game Over cleanup, including `FUN_005C9670`;
2. creates native scene type `0xFA2` (`Mortuary`) through `FUN_005B7080`;
3. configures that native scene from the completed run globals;
4. switches the region through `FUN_005CDDD0`;
5. leaves subsequent Hall of Fame and main-menu progression to native UI.

Existing isolated retail validation observed the corresponding user-visible
sequence: arena, full Game Over, input, Hall of Fame, then the stock main menu.
The Game Over atlas becomes resident while the arena presentation remains
resident underneath it, which is part of the full stock screen rather than a
replacement scene assembled by the loader.

### Decomposed cleanup boundary

The 2026-07-25 read-only headless pass extended the completion lineage through
the concrete close and region calls:

```text
GameOver::Tick                                      0x005CF4F0
  -> GameOver vtable +0x18
     -> close/remove surface                        0x004277B0
        -> application surface manager virtual +0x1C
        -> surface+0x05 = closed
  -> archive completed-run state                    0x005C9670
     -> completed-run/item processing               0x005BE320
     -> completed-run persistence helper            0x005BE0B0
  -> gameplay-scene factory(type=0xFA2)             0x005B7080
  -> Gameplay_SwitchRegion(game, 1)                 0x005CDDD0
     -> old region virtual +0xD4 / +0xDC
     -> unregister old region lifecycle              0x00428160
     -> new region virtual +0xE0
```

`0x004277B0` unregisters the Game Over surface from the application's surface
manager and marks that surface closed. `0x005C9670` reads the current gameplay
object and application-owned completed-run fields, then delegates the
inventory/result work to `0x005BE320`; it does not close an application,
socket, or external session. `0x005CDDD0` owns the old-region exit and
new-region entry virtuals. G13's later instruction-level pass corrects the
earlier destructor interpretation: `0x00428160` removes the outgoing child
from the owner's manager and clears the child's `+0x70` owner pointer when it
matches; it does not free the region. The six region objects survive an
ordinary switch and are destroyed only by the full-reset path described in
[`native-session-flow.md`](native-session-flow.md#ordinary-switch-versus-full-reset).
The switch boundary is the native gameplay region, not a multiplayer lobby.

There are no Steam, Winsock, process-exit, or loader transport calls in this
lineage. The retail executable has no knowledge of the loader's lobby.
Consequently, native Game Over completion and multiplayer-session teardown are
independent state machines: the stock path must be allowed to retire the run
scene and completed-run state, while the loader must keep its authenticated
lobby and transport alive until an explicit leave, disconnect, or process
shutdown.

Therefore, “proceed normally” has one foundational implementation:
dispatch the original `Game_OnGameOver` trampoline exactly once on each local
process and allow the native Game Over object to own every step afterward.
Loader code must not manually create Mortuary, skip the fade, synthesize Hall
of Fame, or issue a competing leave-game transition. Once stock progression
has reached a stable non-run surface, a still-connected multiplayer flow may
re-enter shared hub gameplay through a stock transition appropriate to that
surface. Story/main-menu completion reuses the initial title/profile flow.
Boneyard completion uses the stock Menu binding, validates and invokes the
native Hall of Fame continue virtual, and lets `HallOfFame::Tick` reinstall
the stock main menu. The existing onboarding state machine owns the later hub
entry. Both routes are loader session-continuity operations; neither replaces
any native cleanup call above, writes a native field, or calls
`Gameplay_SwitchRegion` from the private post-run scene.

## Session boundary

Spectator eligibility is a property of the active run membership, not of
transport initialization:

- A run with only one connected, ready participant on its run nonce is solo.
  Its lethal terminal callback must not activate any spectator state or
  spectator UI. The run-ended detour must immediately continue through the
  original trampoline.
- A run with at least two connected, ready participants on the same run nonce
  is multiplayer. A local death may suppress the Game Over trampoline and
  enter the multiplayer death/spectator presentation while another participant
  remains alive.

This cardinality test must include the local participant and use the active run
nonce. Session capacity, a configured UDP endpoint, Steam initialization, or a
stale participant from another run cannot make a solo run multiplayer.

## All-dead terminal transition

No participant process should independently infer and dispatch Game Over from
an incomplete disposable snapshot. The session authority must publish one
monotonic terminal command for the active run after all eligible participants
have valid life state and none remains alive. The command must carry the run
nonce, be accepted only from the configured authority, and be repeated over
the protocol's reliable checkpoint lane until peers acknowledge or retire the
run.

Every participant then consumes that command once on its game/application
thread and invokes the same original `Game_OnGameOver` trampoline. This gives
the host and every client an independently owned native Game Over object while
keeping the decision host-authoritative. The object renders the full title in
story mode and the stock fade-only presentation in Boneyard mode. Dispatch
also retires local spectator camera/HUD state before the native surface is
installed.

Installing the Game Over surface retires the ordinary local run state before
the transport stops pumping. Terminal command and acknowledgment envelopes
must therefore retain the accepted terminal run nonce independently; otherwise
post-dispatch packets carry a zero ordinary nonce and peers correctly reject
the command as cross-run traffic.

The terminal command is distinct from wave respawn and ordinary host run-exit:

- wave respawn is invalid once the session has terminalized;
- a normal host run-exit cannot substitute for local native Game Over because
  it does not construct the participant's Game Over surface;
- host run-exit following must not race ahead of an accepted all-dead command
  and navigate a client away from its native Game Over flow.

The accepted terminal command must likewise not retire authenticated lobby
membership. It ends one run nonce, not the lobby. A later host run request in
the same authenticated lobby must allocate a new run nonce and may start
without recreating or rejoining the lobby.

## Regression obligations

Static and live gates must prove both sides of the boundary:

- solo: exactly one active-run participant, a real native lethal dispatch,
  spectator state never active, full `game_over` surface visible, then native
  Hall of Fame/main-menu progression;
- multiplayer trio: the first two native deaths remain in the spectator
  system with a living target and no Game Over surface; the last death produces
  one authority terminal command and a native Boneyard GameOver object on all
  three processes, a fade-only frame with the object tick/input alphas fully
  advanced, the stock private Memoratorium transition, the native Hall of Fame
  controller transition, and then a next-generation stock Create picker on
  every process. Each prior loadout must be visibly preselected and require an
  explicit stock confirmation before that participant returns to the shared
  hub;
- protocol: terminal commands are authority-validated, run-nonce scoped,
  replay-safe, and present in the reliable state path;
- lifecycle: native Game Over dispatch occurs exactly once per participant and
  suppresses competing host-run-exit follow for that terminalized run.

The live story post-flow gate sends stock mouse input only to each
executable-path-validated process ID and verifies Mortuary, Hall of Fame, and
main-menu states. Boneyard coverage waits for the native tick-1000 input
threshold, sends mouse messages only to the exact owned process window, and
then verifies the `FUN_005A7F60` front-end branch before the launcher flow
follows the validated `HallOfFame` controller into stock Create. It asserts
the retained selections there and performs one explicit semantic stock
confirmation per participant before accepting the intact lobby hub. It
neither activates a foreground window nor mutates global mouse state. Lua
gameplay-click injection is not evidence for the Game Over surface because the
native Game Over object owns its own input tick.
