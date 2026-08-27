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
| `+0xA4` | `0.0` | accepted-state dependent | exit black overlay |
| `+0xA8` | `0` | renderer sets only after exit alpha is exactly `1.0` | transition-ready gate |
| `+0xAC` | `0` | increment by one | acceptance clock |

Normal mode draws GameOver atlas record 0 at viewport center X and center
Y minus 175, record 1 at center X and center Y plus 125, and the continue
prompt at `(width / 2, height - 50)`. The records are respectively `307 x 119`
and `306 x 120`. Boneyard mode suppresses all three semantic glyphs, but it
retains both black overlays and therefore reveals the resident Arena beneath
the entry fade after 40 ticks.

The tick-1000 Boneyard edge synthesizes acceptance inside `GameOver::Tick`;
it does not open an input gate and it does not require a mouse, keyboard, or
controller message. On the tick where `+0xAC` becomes exactly 1000, the
Boneyard branch writes the accepted byte at `+0xA0` and the accepted-state
branch raises `+0xA4` by `0.0025`. Exit alpha is therefore already `0.0025`
on tick 1000 and reaches exactly `1.0` after 400 accepted ticks. The ordinary
mouse branch uses `0.05` (20 ticks), while its alternate/controller branch
uses `0.004` (250 ticks); neither branch owns Boneyard acceptance. Render
observes exact opacity, sets `+0xA8`, and only a later tick follows the
completion lineage. A web Boneyard port must therefore retain its terminal
Arena image, run the 40-tick black-to-clear entry, hold it clear until the
automatic tick-1000 edge, and remain on Game Over for the complete 400-tick
clear-to-black exit. Treating `gameOverTicks / 150` as a single increasing
alpha reverses the native entry fade and hides the authored hold.

The completion path is also mode-specific:

- the normal story branch archives the completed run, creates scene type
  `0xFA2` (`Mortuary`), and switches gameplay regions;
- the Boneyard branch automatically enters its accepted state at GameOver tick
  1000. It does not close immediately: the accepted state first owns the full
  400-tick exit fade. Completion then clears `DAT_0081A434`, runs the stock
  completed-run cleanup, and calls `FUN_005A7F60` (`0x005A7F60`) to select and
  install the stock front-end surface.

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
main-menu states. Boneyard coverage must send no input while Game Over owns the
surface: it waits passively for tick 1000, the 400-tick exit, and the
`FUN_005A7F60` front-end branch to reach stock Create. It then asserts the
retained selections and performs one explicit semantic Create confirmation per
participant before accepting the intact lobby hub. It neither activates a
foreground window nor mutates global mouse state. Mouse or Lua gameplay input
before Create would mask the automatic Boneyard contract and is not admissible
evidence for this branch.

## 2026-08-22 normal-screen and `Solomon_Riff` ownership correction

The earlier Website parity pass treated the normal `GAME` / `OVER` glyphs as
the whole sibling presentation and treated `Solomon_Riff` as an unrelated
factory member. A fresh read-only xref pass disproves that boundary. The only
direct constructor call to `Solomon_Riff` outside the type-5019 factory is at
`0x005CAFEF`, inside `GameOver` construction. The Game Over system therefore
includes the full normal-screen actor, its twelve-row authored bank, its delayed
stream, and both normal continuation paths.

### Constructor-owned presentation and audio

`GameOver` constructor `0x005CAD40` performs this ordered work after freezing
ordinary gameplay input:

1. set the two `Game` control seals at `Game+0x1ABD/+0x1ABE`, reset their
   embedded movement/aim owners, and replace ordinary HUD/control presentation
   with the application-level Game Over surface;
2. stop both music lanes at `0x005CAE3D`;
3. enqueue `SAY_SOLOMON_LAUGHBIG1` at `0x005CAE79` in both modes;
4. in Boneyard mode only, enqueue `SAY_SOLOMON_ANOTHERCORPSE` at
   `0x005CAEC8` after the huge laugh;
5. initialize entry alpha `1`, title alpha `-1.5`, prompt alpha `-2`, and exit
   alpha `0`;
6. build the three-record `GameOver` bundle and start song `death` immediately
   at `0x005CAFB9`; and
7. in normal mode only, allocate type `5019`, call `Solomon_Riff` constructor
   `0x004756C0`, and register that actor in the still-resident world.

The two narration calls use the shared narration owner at `0x004FCEC0`; the
second Boneyard line is queued behind an already active first line rather than
played as an unrelated simultaneous sound. `DeathGuitar__Stream` is not a
player-death-start cue. Its only recovered Game Over call is the normal-mode
`Solomon_Riff` tick at `0x004757DD`.

### Normal Game Over visual and continuation clocks

Renderer `0x005C9030` paints in this order: entry-black layer, normal-mode
glyphs, normal-mode prompt, exit-black layer. `GameOver.0` is `307 x 119` at
viewport center plus `(0,-175)`; `GameOver.1` is `306 x 120` at center plus
`(0,125)`. Both use title alpha. The prompt is `CLICK TO CONTINUE...`, centered
at `(width / 2, height - 50)` with Fonts group 3 and native RGBA
`(0.85,0.73,0.44,1)`. `GameOver.2` has no compiled consumer.

At the 100 Hz native clock:

| Member | Initial value | Recurrence / threshold |
| --- | ---: | --- |
| entry black | `1` | subtract `0.025`; clear at tick 40 |
| title alpha | `-1.5` | add `0.005`; first visible after 300, exact one at 500 |
| prompt alpha | `-2` | add `0.005`; first visible after 400, exact one at 600 |
| input virtual | n/a | `0x005C7910` accepts normal-mode activation only once title alpha is exactly one |
| clicked exit | `0` | add `0.05`; exact black after 20 accepted ticks |
| unattended exit | `0` | `Solomon_Riff` completion sets accepted and slow bytes together; add `0.004`, exact black after 250 accepted ticks |

The normal branch is therefore both interactive and bounded. A click can
continue from tick 500. If no input arrives, `GameOver::Tick` observes the Riff
actor only after its internal counter is greater than `9.5 * tick_rate` and its
frame cursor is greater than ten; on the stock 100 Hz clock the first eligible
state is tick 951. This sets the adjacent slow-exit byte and progresses without
input. Boneyard's separate tick-1000 / 400-tick automatic branch remains as
documented above.

### Complete `Solomon_Riff` authored program

Type `5019` has vtable `0x00786364`, constructor `0x004756C0`, initializer
`0x0047F480`, tick `0x004756F0`, and renderer `0x004A15E0`. The constructor
xref census has exactly two members: the generic type factory `0x005B7080`
and the Game Over constructor. `SolomonRiff.bundle` contains thirteen records:
record 0 is the dormant three-pixel placeholder; records 1 through 12 are the
complete extracted array at bundle object `+0x100`. Every array record uses a
`200 x 200` logical registration cell and is selected by truncating the
nonnegative frame cursor toward zero.

The actor starts hidden. When its counter first exceeds `2 * tick_rate` (tick
201), it copies the local player's render anchor, subtracts 375 from X, and
initializes the visible pose. Its initializer supplies vertical offset `-5`,
vertical velocity `-4`, frame zero, and phase zero. During the hop, each tick
adds `4.4` to X, adds velocity to the vertical offset, then adds `0.125` to
velocity; the offset clamps to zero on landing. This consumes 67 motion ticks
and lands at X offset `-80.2` from the copied player anchor.

On the ground, phase zero advances frames below three by net `0.10` per tick,
then advances by `0.13` and wraps at five back to three. The clamp happens
before rendering, so cursor value five / bundle record 6 is never selected.
Counter tick 550 plays
fixed stream 118 / registry offset `0x1364`,
`sounds\\DeathGuitar__Stream`. After counter 820, phase one alternates frames
0 and 1 every eight ticks. After counter 920, phase two starts at frame 6,
adds `0.2` per tick, and clamps at frame 11 (bundle record 12). The renderer
adds the live vertical offset and selects records 1..5 and 7..12; record 6 is
an authored but program-dormant sibling.

### Branch inventory and Website consequence

| Member | Native branch | Website disposition for the requested post-death flow |
| --- | --- | --- |
| entry/exit black layers and retained Arena | both | exact-ported |
| ordinary HUD, quickbar, loot notices, spectator text, chat, and touch controls | superseded by application surface | exact-ported: absent for the complete Game Over lifetime |
| `GAME`, `OVER`, and bitmap prompt | normal/story | exact-ported by explicit product request on the survival route |
| `Solomon_Riff` records 1..5 and 7..12 plus complete tick program | normal/story | exact-ported by explicit product request |
| `SolomonRiff.0`, program-skipped `SolomonRiff.6`, and `GameOver.2` | neither | out-of-system: no reachable Game Over selection |
| huge-laugh narration and immediate `death` song | both / constructor | exact-ported |
| `ANOTHERCORPSE` queued narration | Boneyard only | out-of-system: the requested visible branch follows normal Game Over presentation/audio ownership |
| Riff tick-550 death-guitar stream | normal/story | exact-ported; removed from individual player-death ownership |
| normal click at tick 500 and Riff-completion fallback | normal/story | exact-ported with server validation of run and event identity |
| Boneyard tick-1000 automatic acceptance and 400-tick fade | Boneyard only | out-of-system for the explicitly requested full normal Game Over screen; retained here as recovered sibling truth |
| normal Mortuary/Hall/MainMenu destination | normal/story | out-of-system: the Website's explicit post-run route remains direct Create/loadout |
| Create element and discipline selection | both post-run lineages | exact-ported: every surviving party participant chooses and confirms a fresh pair before shared-Hub return |

The Website result is intentionally a documented composition of stock owners:
normal Game Over presentation/input followed by the already requested direct
post-run Create route. It is not evidence that retail Boneyard mode itself
draws the normal glyphs or Riff actor. Authority must still reject stale
run/event continuation, and multiplayer return must not let one participant's
loadout silently overwrite or skip another participant's choice.

## 2026-08-26 post-Game-Over player-generation clarification

The generation boundary is completed Game Over, not individual player death.
A dying or spectating multiplayer participant keeps the same progression,
`Skills_Wizard`, active inventory, and equipment while another eligible player
keeps the run alive. The later Create confirmation owns the fresh generation.

The retained post-run element/Discipline values are Create defaults, not a
retained `Skills_Wizard` or active inventory. A fresh read-only xref sweep on
retail 0.72.5 found exactly two callers of finalizer `0x005D0290`:
`Create::Tick 0x0058A820` at `0x0058A96D` and startup owner `0x005D07D0` at
`0x005D0840`. The finalizer grants only the selected element root/primary/
secondary, selected Discipline, and roots `0,2,1,3,4,6,5,7`, refreshes derived
state, and then calls starter construction `0x005CFA80`. The already recovered
`Skills 0x006594E0` and `Skills_Wizard 0x00674EE0` constructors supply level 1,
XP 0, empty offer state, and a fresh 83-row book. No completed-run skill rank,
learned order, quickbar, or Tutorial-only Acid Rain member is copied into that
generation.

Item archival is a distinct preceding owner. `GameOver::Tick 0x005CF4F0` has
the only two refs to `0x005C9670`. Raw instructions at
`0x005C9696..0x005C96A2` apply `SETZ` to Player `+0x1C0` before calling
`0x005BE320`: an unconsumed corpse permits retail's ordinary carried equipment/
backpack Sack, a corpse consumed by Ether Drain suppresses it, and Last Word
`Skills_Wizard+0x7D8` independently adds eligible ground Sacks/Gold. The Sack
is Luthacus profile storage; `0x005CFA80` still builds fresh active gear and
potions for the next wizard.

The Website's direct-Create route may omit Mortuary/Hall/MainMenu, but it may
not turn Create preselection into skill/progression inheritance. The user has
also selected a stricter Website item policy than retail: terminal Game Over
does not archive ordinary carried equipment/backpack. Existing Luthacus
storage and Last Word's explicit ground recovery remain durable. This web
deviation is documented in the Website parity ledger and does not alter the
retail contract above.

## 2026-08-27 character-lifetime and starter-color clarification

The 2026-08-26 generation clarification recovered the fresh skill finalizer
but stopped before the enclosing object lifetime and the guarded starter-color
branch. A player report that Website clothing colors survived Game Over exposed
that omission. Fresh static passes used the canonical read-only Ghidra replica
against the same 4,723,200-byte retail image, SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`,
preferred image base `0x00400000`.

### Complete caller and lifetime census

| Native member | Complete static membership | Recovered consequence |
| --- | --- | --- |
| new-character finalizer `0x005D0290` | exactly two references: `Create::Tick 0x0058A820` at `0x0058A96D`, startup owner `0x005D07D0` at `0x005D0840` | selected element/primary/secondary and Discipline are granted before starter construction |
| starter constructor `0x005CFA80` | exactly two references: finalizer at `0x005D0756`, start owner `0x005D2380` at `0x005D24FF` | one guarded owner constructs the real Hat, Robe, Staff, Health Potion, and Mana Potion objects and then enters/rebuilds the target world |
| `Game` construction | `Game::Game 0x005CC800` | initializes the `Game` vtable, all component/region containers, selection/start flags including `Game+0x86 = 0`, and publishes the new Game pointer |
| `Game` destruction | deleting wrapper `0x005CFA60` -> destructor `0x005CD3A0` | closes the active child surface, saves/cleans profile state, unregisters and destroys all six regions plus auxiliary/component containers, clears the global Game pointer, then releases the object |
| Game Over archive | `GameOver::Tick 0x005CF4F0` -> `0x005C9670` -> `0x005BE320` | archives completed-run inventory/profile output; it does not itself destruct the player or Game |
| scripted full-region reset | `0x005CF920` | destroys/recreates the six region objects inside one still-live Game; it is not a fresh character/Game substitute |

The native normal post-run lineage ultimately leaves the completed Game and
constructs another Game. A literal Game object is therefore a stronger
lifetime boundary than the archive call or a `Region` switch. The Website's
retained socket/host and direct Create product route deliberately omit those
front-end objects, so it must reproduce the semantic boundary by replacing all
character-owned components while keeping only authenticated identity and its
separately declared durable profile.

### Ordinary versus College starter appearance

`0x005CFA80` creates starter items only while `Game+0x86` is clear. In the
ordinary Create path, `0x005D0290` has already mapped the new element to primary
row `8`, `16`, `24`, `32`, or `40`; the starter color switch reads that new
selection before consuming the three jitter draws and constructing Hat/Robe.
The resulting base-color family is therefore Ether, Fire, Air, Water, or Earth
for the newly confirmed wizard, never an archive-time copy from the dead
wizard.

The post-Tutorial College path is the complete guarded sibling and must not be
folded into that rule. College admission reaches starter construction while
`DAT_00B3BCA0` is live, so it uses the authored College base `(0.25,0.5,0.25,1)`.
Office exit later sets `Game+0x86 = 1` before attaching Create. Confirmation
still refreshes selected skills but the guard prevents a second starter build;
the existing College Hat/Robe colors intentionally survive that first Create.

Fresh decompilation of common grant helper `0x00660320` closes the neighboring
root-rank ambiguity. Its finalizer calls for `0,2,1,3,4,6,5,7` each reach the
same permanent-rank increment/clamp path, so all eight root rows finish at rank
one. Selected element/Discipline fields still alone govern offer membership,
and the starting primary/secondary remain the displayed learned pair. The
earlier Website-ledger claim that only the two selected roots receive rank is
superseded; this correction belongs to every fresh constructor, not only the
reported post-Game-Over member.

### Boundary dispositions

| Branch/member | Disposition for Website `/game` | Reason |
| --- | --- | --- |
| individual multiplayer death/spectator | `verified-already-at-parity` | same run and actor generation remain live while an eligible peer survives |
| Game Over inventory/profile archive | `verified-already-at-parity` with the documented no-carried-items product rule | archive is durable output, not character reuse |
| native Game destructor/new Game constructor | `out-of-system` as literal browser classes; semantic lifetime required | browser host/session persists by product design |
| all 15 selected element/Discipline skill tuples | `exact-ported` through fresh Website generation construction | raw Create preselection cannot retain old ranks, selections, or quickbar |
| ordinary selected-element starter colors | `exact-ported` by the 2026-08-27 reopening | new confirmation/generation owns the Hat/Robe family and a newer replicated economy revision |
| College-green starter colors | `verified-already-at-parity` | the native one-shot guard intentionally retains them through first Create |
| active carried inventory/equipment | `out-of-system` for retention under explicit Website policy | next wizard receives only fresh starter active items |
| durable gold/storage/perks/unforge/onboarding state | `verified-already-at-parity` | profile owner survives without becoming old character-owned spell/inventory state |
| completed Hall/Memorial portrait | `verified-already-at-parity` | immutable pre-retirement capture keeps the dead generation's appearance and score; next-wizard colors cannot rewrite it |
| browser resumable-save invalidation | `out-of-system` for this native lifetime | save storage and in-memory character destruction are separate Website owners |

No member is blocked by the browser platform. The only RNG adaptation remains
the Website's deterministic host generation seed in place of retail's shared
process-global draw cursor; it must still select the exact recovered color
family and mixing formula.
