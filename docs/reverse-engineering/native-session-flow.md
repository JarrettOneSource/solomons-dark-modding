# Native session flow and room lifecycle (G13)

This is the implementation contract for the retail session/room machine. It
closes browser-rebuild gap G13 against `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
An implementing agent can rebuild the flow from this document and the checked-in
golden without opening the binary.

This document owns the machine that connects surfaces and worlds, not the
contents of either:

- G11 owns the boot/menu screens, their layout, and their 39 internal navigation
  edges. Import [the native shell contract](native-menus-and-boot.md) and
  [`menu-focus-model.json`](../../webgame-contracts/menu-focus-model.json);
  do not recreate those screens from this state list.
- G8 owns what the Courtyard and its private hub rooms contain, including NPCs,
  shops, dig, and the run-entry portal. This document treats those worlds only
  as region states and transition endpoints. The territory boundary is the
  [G8 roadmap row](../browser-rebuild-roadmap.md#tier-b--hub-and-world-presentation-second).
- G14 owns input routing and the loading seal. The authoritative contract is
  [the native input model](native-input-model.md#loading-screen-input-seal-uigate);
  this document only places its already-defined seal and unseal in the room
  lifecycle.
- The terminal object, spectator split, and post-death UI behavior remain owned
  by [the Game Over session contract](native-game-over-session-semantics.md).
  This document connects that contract to region teardown and re-entry.

The live fixture is
[`session-flow-goldens.json`](../../tests/fixtures/webgame/session-flow-goldens.json).
It was recorded by `tools/record_native_session_flow_goldens.py` from isolated
instance `flw-g13-final`, recorder source
`3c49c4eef6d4b91fe40b58cad99678e119007d84`, PID `33708`, UDP ports
`52321/52322`, and the capture-only loader DLL SHA-256
`23c12dc955ae7cbf31906107e4b5a9f4596100578d5bf9095ed68205cb05a08c`.
The tool drove stock presentation input through that exact PID, used existing
Lua-exec read probes, and recorded native lifecycle detours. The recorder is
opt-in through `SDMOD_NATIVE_SESSION_FLOW_CAPTURE_DIRECTORY`; with the variable
absent all added observers are inert.

## The state machine

### It is a product of machines, not one retail enum

No single retail `SessionState` field exists. The reconstructable state is the
product of four owners:

1. the application root (`MyLoader`, front end, or `Gameplay`);
2. the current native gameplay region, when `Gameplay` exists;
3. a presentation overlay such as Game Over or the loader's Boneyard loading
   barrier; and
4. the loader's multiplayer activity label (`not-in-game`, `in-hub`, or
   `in-boneyard`).

The browser should preserve that product. In particular, Game Over is installed
over the still-resident Arena, and post-Boneyard progression temporarily has
region 1 resident underneath a front-end controller. Flattening either case to
one screen name destroys information needed for correct teardown.

G11's individual menu controllers are substates of `frontend.shell` or modal
overlays on a gameplay root. They are intentionally not duplicated here. Their
entry/exit edges are imported by reference from the G11 navigation graph.

### Where the current state lives

All addresses below are preferred virtual addresses for the analyzed x86 image;
relocate them by the runtime image base. The live graph fixture also records the
relocated addresses from its exact process.

| Owner | Address / field | Meaning |
| --- | --- | --- |
| Gameplay singleton | `DAT_0081C264` | Current `Gameplay*`; null before a gameplay root exists. |
| Region assignment vector | `DAT_00819E84` | Pointer to an `int` vector. Entry 0 is the authoritative current native region id. It is the value tested and replaced by `Gameplay_SwitchRegion` at `0x005CDDD0`. |
| Pending transition | `Gameplay+0x78` | Region id staged by a presentation endpoint. `-1` means no pending transition. `Game::Tick` at `0x005D7EF0` consumes a nonnegative value and resets it to `-1` after the synchronous switch returns. |
| Region objects | `Gameplay+0x133C,+0x1340,+0x1344,+0x1348,+0x134C,+0x1350` | Pointers for native region ids `0..5`. These objects normally remain allocated across an ordinary room switch. |
| Active world/region | `DAT_0081C260` | Published incoming region pointer, assigned by `0x005CBA00` during attach. This is not the region id. |
| Local gameplay actor/controller | `Gameplay+0x1358` | Gameplay-owned object passed to the incoming region and later to the outgoing post-switch virtual. It survives an ordinary region boundary. |
| Boot controller | `MyApp+0xDA4` | `MyLoader*`; vtable `0x00799BDC`. |
| Main front end | `MyApp+0xDAC` | `MainMenu*`, installed by `0x005A7D90`. G11 owns its screen subtree. |
| Hall of Fame | `MyApp+0xDB0` | Outer `HallOfFame*`; vtable `0x00799334`. |
| Game Over | application surface/CPU manager | Object with vtable `0x0079B0CC`; its presence has precedence over the underlying Arena for session presentation. |

`DAT_00819E84[0]`, `Gameplay+0x78`, and `DAT_0081C260` are deliberately
separate. A port that writes only a new room id misses the pending presentation
gate and the active-object publication boundary.

The loader publishes a separate activity projection:

| Activity label | Exact meaning |
| --- | --- |
| `not-in-game` | No materialized shared-hub or active-run actor. Boot, front-end screens, private hub rooms, Game Over, and post-run screens all map here. |
| `in-hub` | Local player and shared Courtyard world are materialized. |
| `in-boneyard` | Local player belongs to a live run nonce in Arena. |

These labels are multiplayer/session projections, not replacements for the
native state list.

### Complete G13 stable state list

| State id | Native identifier and construction address | Native id / storage | Tick or discriminant |
| --- | --- | --- | --- |
| `boot.loader` | `MyLoader`, startup `0x005BAB60` | `MyApp+0xDA4` | vtable `0x00799BDC`, render `0x005BCA40` |
| `frontend.shell` | front-end installer `0x005A7F60`; MainMenu installer `0x005A7D90`, constructor `0x0058D940` | `MyApp+0xDAC` | vtable `0x007980CC`; screen substates belong to G11 |
| `gameplay.courtyard` | `Courtyard`, constructor `0x00506490`, factory type `0xFA1` | region `0`, `Gameplay+0x133C` | tick `0x0050C970`, vtable `0x00792644` |
| `gameplay.mortuary` | `Mortuary`/`Memoratorium`, constructor `0x005090A0`, factory type `0xFA2` | region `1`, `Gameplay+0x1340` | tick `0x00509330`, vtable `0x007927DC` |
| `gameplay.library` | `Library`, constructor `0x0050A360`, factory type `0xFA4` | region `2`, `Gameplay+0x1344` | tick `0x00504BB0`, vtable `0x00792C04` |
| `gameplay.storeroom` | `StoreRoom`, constructor `0x00509B10`, factory type `0xFA3` | region `3`, `Gameplay+0x1348` | tick `0x00504220`, vtable `0x0079294C` |
| `gameplay.office` | `Office`, constructor `0x00509C70`, factory type `0xFA5` | region `4`, `Gameplay+0x134C` | tick `0x00509F10`, vtable `0x00792AB4` |
| `loading.boneyard` | loader readiness barrier; no retail object or region id | overlays the `0 -> 5` switch | `LoadingScreenSnapshot.active`; stages and rendering belong to G11 |
| `gameplay.arena` | `Arena`, constructor `0x00464EE0`, factory type `0xFA6` | region `5`, `Gameplay+0x1350` | tick `0x0046E570`, vtable `0x00785934` |
| `overlay.game_over` | `GameOver`, constructor `0x005CAD40`, installer `0x005CB570` | application surface over region 5 | tick `0x005CF4F0`, vtable `0x0079B0CC` |
| `post_run.mortuary_frontend` | region-1 `Mortuary` plus front-end installer `0x005A7F60` | composite: native region `1` and a front-end surface | Boneyard-mode stock completion only |
| `frontend.hall_of_fame` | factory `0x005A7E30`, constructor `0x00598120` | `MyApp+0xDB0` | tick `0x00589CD0`, vtable `0x00799334` |

`loading.boneyard` and `post_run.mortuary_frontend` are explicit composite
states needed by a portable multiplayer implementation. Their zero/nonnative
addresses in the fixture are declarations, not missing evidence.

### Complete legal cross-state edge set

This table is exactly mirrored by `transition_graph.edges` in the live golden.
It excludes G11-internal screen navigation while including every evidenced edge
that changes a G13 state.

| Source | Edge id | Trigger | Destination |
| --- | --- | --- | --- |
| `boot.loader` | `boot_complete` | loader completion flag/work ratio finishes | `frontend.shell` |
| `frontend.shell` | `startup_hub` | new, resumed, or post-run onboarding selects region 0 | `gameplay.courtyard` |
| `frontend.shell` | `startup_office` | startup pending kind selects region 4 during onboarding | `gameplay.office` |
| `frontend.shell` | `startup_boneyard` | direct Boneyard startup selects region 5 | `loading.boneyard` |
| `loading.boneyard` | `arena_materialized` | region 5 is attached and the readiness barrier releases | `gameplay.arena` |
| `gameplay.courtyard` | `enter_mortuary` | Mortuary portal collision/endpoint | `gameplay.mortuary` |
| `gameplay.mortuary` | `return_courtyard` | Mortuary return portal | `gameplay.courtyard` |
| `gameplay.mortuary` | `completed_story_continue` | completed-story continuation after Game Over | `frontend.hall_of_fame` |
| `gameplay.courtyard` | `enter_library` | Library portal collision/endpoint | `gameplay.library` |
| `gameplay.library` | `return_courtyard` | Library return portal | `gameplay.courtyard` |
| `gameplay.courtyard` | `enter_storeroom` | StoreRoom portal collision/endpoint | `gameplay.storeroom` |
| `gameplay.storeroom` | `return_courtyard` | StoreRoom return portal | `gameplay.courtyard` |
| `gameplay.courtyard` | `enter_office` | Office portal collision/endpoint | `gameplay.office` |
| `gameplay.office` | `return_courtyard` | Office return portal | `gameplay.courtyard` |
| `gameplay.courtyard` | `start_run` | authority accepts MapPicker/start-match action | `loading.boneyard` |
| `gameplay.courtyard` | `leave_game` | stock Pause then Leave Game action | `frontend.shell` |
| `gameplay.arena` | `terminal_death` | solo terminal callback or authority all-dead command | `overlay.game_over` |
| `gameplay.arena` | `authority_leave_run` | host stock Leave Game followed by authenticated client stock follow | `frontend.shell` |
| `overlay.game_over` | `story_completion` | normal Game Over accepts armed input and closes | `gameplay.mortuary` |
| `overlay.game_over` | `boneyard_completion` | Boneyard Game Over automatically accepts at tick 1000, finishes its exit fade, then cleans up | `post_run.mortuary_frontend` |
| `gameplay.arena` | `scripted_terminal_reset` | `WIN LEVEL` or `LOSE LEVEL` finish fade | `gameplay.courtyard` |
| `post_run.mortuary_frontend` | `open_hall_of_fame` | stock Menu action exposes the Hall of Fame controller | `frontend.hall_of_fame` |
| `frontend.hall_of_fame` | `continue_to_frontend` | accepted continue; linear close progress exceeds `1.0` | `frontend.shell` |

The normal onboarding observed in the full-session golden is the composite path
`startup_office -> return_courtyard`; run entry is
`start_run -> arena_materialized`; and the recorded Boneyard death return is
`boneyard_completion -> open_hall_of_fame -> continue_to_frontend -> startup_hub`.
The fixture records those paths rather than pretending each is one retail call.

The G13 graph and timeline fixture retains its original 2026-08-05 semantic
labels (`tick-1000 input acceptance` and `exact-PID stock window input`) as
immutable capture provenance. Those labels do not establish causal ownership:
the later `GameOver::Tick` re-decompile and a passive isolated live run prove
that Boneyard acceptance is internal and automatic. Exact-PID input remains
part of that historical campaign, but only the input sent after stock Create
is semantically required. Current acceptance therefore waits without input
until Create appears.

### Illegal requests and non-edges

| Request | Native/loader result |
| --- | --- |
| private region `1..4` directly to a different private region | No stock edge. Return to Courtyard first, then enter the other portal. |
| private region `1..4` directly to Arena | No stock edge. Run entry originates in Courtyard. |
| ordinary/raw Arena switch to any fixed region | Illegal lifecycle shortcut. Death, synchronized Leave Game, or scripted terminal reset owns exit. |
| same region id | `0x005CDDD0` compares target to `DAT_00819E84[0]` and returns; it is a no-op, not an edge. |
| target `-1` | Detach transient, not a stable state. It can unregister the outgoing region and return before publishing a replacement. Do not expose it to game logic. |
| target outside `0..5` | Native table indexing is unchecked and can access arbitrary memory. The semantic Lua seam rejects it before dispatch. |
| post-run Mortuary directly to Courtyard | Two isolated three-process probes access-violated. The only supported recovery is the stock front-end/Hall-of-Fame/onboarding path. |
| multiplayer client self-authors Arena entry | Loader rejects it unless a fresh authenticated host run intent for a nonzero nonce is present. |
| wave change inside Arena | Not an edge. All waves remain in native region 5. |

## Transition lifecycle

### Presentation-driven ordinary room switch

The exact ordering is:

1. A portal/controller selects a destination and starts the outgoing region's
   fade-out by making `Region+0x8E4C` positive. `Region+0x8E48` is alpha.
2. `Region` base tick `0x0063EFC0` continues ticking the outgoing world and adds
   the rate to alpha. On the endpoint it clamps alpha to `1.0`, invokes region
   vtable slot `+0x128`, then zeroes the rate.
3. The endpoint stores the destination in `Gameplay+0x78`. The outgoing scene
   is fully covered before any load begins.
4. On the next `Game::Tick` (`0x005D7EF0`), the game reads the pending id. If it
   is nonnegative, it calls `Gameplay_SwitchRegion` (`0x005CDDD0`) synchronously.
5. If an outgoing region exists, `0x005CDDD0` performs, in this order:
   outgoing vtable `+0xD4(slot=0)` player-slot detach; outgoing vtable `+0xDC`
   sleep/cache; `0x00428160(Gameplay,outgoing)` lifecycle unregister.
   `0x00428160` removes the child from the owner's manager and clears
   `child+0x70` when it points back to `Gameplay`; it does **not** free the
   region object.
6. The function saves the old region id, writes the target to
   `DAT_00819E84[0]`, calls incoming vtable `+0xE0` wake, then calls
   `0x005CBA00(Gameplay,target)` attach.
7. Attach publishes `DAT_0081C260`, calls the incoming setup/entry virtuals,
   updates the previous/current assignment fields, registers the incoming
   region plus Gameplay-owned controllers, and attaches player slots/actors.
8. When the old id was valid, the old region receives vtable
   `+0xC8(Gameplay+0x1358)`. The semantic purpose of this post-switch callback
   is not yet named; its position and argument are exact and must be preserved.
   Target 5 then receives the Arena-specific finalizer `0x005C7820`.
9. `Gameplay_SwitchRegion` returns. `Game::Tick` resets `Gameplay+0x78` to
   `-1`; no asynchronous loader owns the native swap itself.
10. The incoming region runs its fade-in with a negative rate. Base tick
    clamps alpha to `0.0`, invokes the same `+0x128` endpoint, and clears the
    rate. Thus stock order is **fade-out endpoint, load/swap, fade-in**.

### Exact ordinary Hub portal choreography

Courtyard tick `0x0050C970` owns four direct portal-contact tests. Each match
clears the local actor's normal action/cast path, calls scripted movement
helper `0x0063E4D0`, stores the destination for the outgoing endpoint, and
starts `Region+0x8E4C` at `+0.01`:

| Target | Contact segment | Scripted movement target | Speed |
| ---: | --- | --- | ---: |
| `1` Mortuary | `(179,394)` to `(33,529)` | `(32,363)` | `0.65` |
| `2` Library | `(1995.5,606.5)` to `(1915.5,443.5)` | `(2057.5,460.5)` | `0.45` |
| `3` StoreRoom | `(679.5,146.5)` to `(576.5,146.5)` | `(627.5,-1000)` | `0.45` |
| `4` Office | `(1024.5,115.5)` to `(881.5,115.5)` | `(881.5,-1000)` | `0.45` |

The contact primitive is `FUN_00410B40`, an inclusive circle-to-segment test:
the squared closest-point distance is accepted when it is **less than or equal
to** the actor radius squared. Courtyard base tick `FUN_0063EFC0` runs before
these four tests, so collision resolution supplies the position tested by the
portal code.

The Office row corrects a previous x87-stack transcription error. At
`0x0050D7C0`, the function loads `0x00793078 = 115.5` and leaves it on the x87
stack while it stores the two X constants `0x00793074 = 1024.5` and
`0x00793070 = 881.5`. Both endpoint Y stores consume the retained `115.5`;
`881.5` is the second endpoint X and the later scripted-target X, not the
portal Y. The matching branch at `0x0050D85C` writes target region `4` at
`0x0050D896`. A full-image write search found no second Courtyard writer for
target `4`.

This placement is also consistent with Courtyard attach `0x00503F20`: a fresh
retail new game normalizes previous region `-1` to Office id `4`, places the
local actor at `(952.5,67.5)`, and scripts it to `(952.5,157.5)`. The Office
portal is therefore the north doorway immediately above the settled spawn,
not the southern sigil. Web parity still needs an inclusive portal-contact
predicate kept separate from the strict penetration predicate used to resolve
solid walls.

The correction was validated on 2026-08-14 against the unmodified retail EXE
SHA-256 `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
A clean new game entered Office by holding W from spawn. An isolated loader
run then measured the settled Courtyard actor at approximately
`(944.0377,164.3609)` and, after 700 ms of W, region `4` at
`(511.9665,903.5174)`. This is direct stock behavior, not a diagnostic region
switch.

The private-room ticks use physical exits at the bottom view boundary.
StoreRoom, Library, and Office test the exact horizontal segment
`centerX +/- 100` at `bottomY - 100`. Contact scripts the local actor toward
`(centerX,bottomY+1000)` at speed `1`, clears casting, and begins the outgoing
`+0.01` fade. Mortuary tick `0x00509330` deliberately differs: its segment is
`centerX +/- 1000` at `bottomY - 60`, and its scripted target preserves the
actor's contact X while using `bottomY + 1000`. Ghidra data reads establish the
compiled doubles `0x007DE908 = 100`, `0x007DE938 = 1000`, and
`0x007849A0 = 60`. The Mortuary incoming target is therefore 60 units above
the return line and does not immediately retrigger it. Mortuary owns an
additional completed-story branch, but its ordinary return still uses this
region endpoint. The ordinary endpoint functions write pending target `0`:
Mortuary `0x00500D50`, StoreRoom `0x00500FE0`, and the Library/Office shared
endpoint `0x00501250`.

The Courtyard's Storeroom doorway barrier is adjacent state, not base geometry.
The constructor `0x00506490` initializes barrier byte `Courtyard+0x95A0` and
close countdown `+0x95A4` to zero. A StoreRoom return through `0x00500FE0`
arms `+0x95A4 = 200` only when `StoreRoom+0x8EA0` is set. Courtyard tick
`0x0050C970` counts down and calls `0x005001E0`, which marks the barrier
present, requests `doorslam__stream`, and registers the exact segment
`(573.5,180)..(681.5,180)` through `0x005213C0`. Thus the neutral ordinary Hub
has 129 stable Courtyard segments and an open Storeroom route; the previously
dumped 130th segment represents a later story-closed state.

Incoming attach stages the actor and lets the scripted movement continue
during the black-to-room fade. StoreRoom, Library, and Office place a remote
or nonmatching slot at `(centerX,bottomY-100)`; the local slot begins farther
inside at `bottomY-150`. Mortuary uses `bottomY-70` and `bottomY-120`
respectively. Private attach first writes `-0.025` (`0x0079146C`) to the
incoming fade rate. StoreRoom keeps it; Mortuary, Library, and Office overwrite
it with `-0.01` (`0x007914A0`). Ordinary Courtyard re-entry also uses `-0.01`.
The per-room attach routines are `0x00500BD0`, `0x00500EC0`, `0x005012B0`,
`0x005010C0`, and `0x00503F20`. A diagnostic immediate switch can clear in one
tick when the cached incoming alpha was already zero, but that is not the
ordinary return-portal clock.

Courtyard attach distinguishes the old private region and reconstructs the
corresponding entrance walk:

| Old id | Courtyard actor position | Scripted target |
| ---: | --- | --- |
| `1` Mortuary | `(63,413)` | `(123,488)` |
| `2` Library | `(1990.5,504.5)` | `(1917.5,563.5)` |
| `3` StoreRoom | `(627.5,98.5)` | `(627.5,198.5)` |
| `4` Office | `(952.5,67.5)` | `(952.5,157.5)` |

The Mortuary target values are the stock floats at `0x00787C68` (`123`) and
`0x0079207C` (`488`); they are not extrapolated from another entrance.

### Ordinary-room audio and multiplayer ownership

A direct-call sweep of the four fixed-room ticks, attach routines, ordinary
endpoints, and Courtyard portal branches found no portal-door cue and no music
change. The `doorslam__stream` call reached from `0x005001E0` belongs to the
flagged StoreRoom-return countdown and its dynamic Courtyard barrier, not to
these ordinary room edges. Academy music remains under the Hub owner, and
common actor movement continues to emit its normal footsteps.

Private-room intent is participant-local. Host and clients can occupy distinct
regions `0..4`; a remote actor is materialized only when its participant scene
intent matches the local scene. Shared Courtyard simulation and transport do
not pause when the local participant is private. This is why a multiplayer
port must publish region/transition per participant and filter actor presence
and region-local cues, rather than synchronizing one global Hub room.

`sd.scene.switch_region` is a diagnostic/authored immediate switch seam. It
queues step 4 directly and therefore does not prove a preceding stock portal
fade. The golden deliberately includes both: onboarding captures a stock
fade-out before the Office-to-Courtyard swap, while the Library probe captures
the immediate semantic seam and its post-load fade-in.

### Tick graph and input

There is no global scheduler pause inside `0x005CDDD0`. The outgoing region
ticks while fading out. The swap is a synchronous portion of the next game
tick; after it returns, later work addresses the newly published region.
Application/UI and loader transport ticks continue throughout. A browser must
not stop networking while it awaits room materialization.

Ordinary fixed-room switches do not activate the loader's Boneyard input seal.
Do not generalize the match-loading gate to every portal. For Arena entry the
ordered boundary is exact:

1. host/client authorization accepts the run switch;
2. `BeginBoneyardLoadingScreen()` activates the blocking overlay **before** the
   first outgoing player-slot detach or cache sleep;
3. participant/world teardown and the native `0 -> 5` swap run while sealed;
4. native Arena creation, native fade-in, and `Arena_StartWaves` may run while
   the seal is still active;
5. the process proves the exact expected actor set stable for `250 ms`;
6. only the host release (or the bounded timeout path) advances to
   `gameplay_ready`, closes the overlay, and emits `input.unseal`.

The G14 rule applies unchanged: movement, key/mouse edges, holds, and cast
queues observed while sealed are dropped, never deferred, and a fresh
post-unseal input is required. The live start-run trace records
`switch.enter -> input.seal -> detach/sleep/unregister -> wake/run.create ->
attach -> fade-in endpoint -> run.wave.start -> input.unseal`.

### Ordinary switch versus full reset

`0x005CF920` is a different operation used by scripted terminal reset. It sets
the reset flag `DAT_00819A84=1` so region sleep does not write caches, then
iterates all six pointers at `Gameplay+0x133C..+0x1350`: unregister each
non-null child through the Gameplay virtual and invoke its destructor at
vtable `+0x18`. It recreates the region set through `0x005C6E40`, switches to
region 0, repopulates through `0x005C8960`, and resets the view. Reusing the
ordinary cached-room path for this edge leaks old region objects and run state.

## Room entry and exit

### Boneyard is one room

The retail Boneyard does **not** change native room at a wave boundary. The
whole run is `gameplay.arena`, native region `5`. `Arena_StartWaves` at
`0x00465C00` changes Arena-owned wave state and spawns/reconciles actors in the
same region object. The live golden records `run.wave.start.begin/end` at tick
`4398`, both with `current_region=5`, followed by a stable region-5 snapshot.

Therefore there is no `Arena room N -> Arena room N+1` edge to implement. The
next wave is determined by Arena/wave data (owned by the wave contracts), not
by `Gameplay+0x78`. A Boneyard selection determines which map and run seed are
materialized before region 5 entry; the picker/catalog contract is
[`boneyard-picker-seam.md`](../design/boneyard-picker-seam.md). G8 owns the hub
portal interaction that requests this pipeline.

### What survives an ordinary fixed-room boundary

| Survives | Is replaced, quiesced, or rebuilt |
| --- | --- |
| `Gameplay*` and its six region pointer slots | `DAT_0081C260` active-region publication |
| All six allocated region objects | outgoing region's active lifecycle registration |
| Gameplay-owned local actor/controller object at `+0x1358` | outgoing player-slot/world registrations |
| profile, completed-run globals, loaded assets, and process | incoming live actor/world bindings |
| authenticated lobby, participant identities, durable loadout/progression/inventory state | loader transient participant materializations, transform samples, queued sync/equip/sack work, replicated hub actor and loot presentation bindings |
| serialized `Region%d.cache` state when the reset flag is clear | scene-local transient effects and unfinished actions; they are not replayed in the next world |

Sleep `0x00649F90` writes the outgoing region cache unless the full-reset flag
is set. Wake `0x0063F460` loads/synchronizes that cache when present; otherwise
it invokes the cold-create virtual and marks `Region+0x8E6D` initialized. The
region object therefore persists, but its live entity registry does not simply
remain the active world.

Immediately before native detach, the multiplayer preparation boundary clears
local tick ownership, transient target locks, pending participant sync,
inventory-equip and sack requests, replicated hub actors, loot presentation
bindings, and every materialized remote/bot wizard binding. A participant who
was moving or casting does not resume that queued action in the destination.
Durable participant state survives and is applied to a newly materialized
actor when local and remote scene intents match.

The golden's entity counts are observations, not constants: the full session
records `0 -> 24` for frontend/onboarding to hub, `24 -> 5` for hub to Library,
`5 -> 24` for Library to hub, `23 -> 1` for hub to Arena, `1 -> 1` for death
overlay installation, and `1 -> 21` for the stock post-run return. Their role
is to prove that each boundary sampled both sides, not to fix population sizes
owned by G8 or wave generation.

## Run lifecycle

### Start and wave progression

1. Only the host/offline authority accepts the MapPicker/start action. The
   authority fixes the Boneyard selection, seed, expected participant set, and
   a nonzero run nonce before clients enter.
2. Clients cache only authenticated configured-host intent. That authorization
   expires after `3000 ms`; a client-authored or stale region-5 switch is
   rejected.
3. Every participant seals input, clears transient scene bindings, and executes
   its own stock region-5 switch. Arena wake calls the native run constructor
   path before Gameplay attach publishes the world.
4. `Arena_StartWaves` (`0x00465C00`) is a hook inside Arena, not a room edge.
5. Loading remains visible until mutual materialization has held continuously
   for `250 ms` and the host publishes release over both participant frames and
   the reliable checkpoint lane. Only then does input unseal.

### Successful/scripted terminal end

Script action ids `1062` (`WIN LEVEL`) and `1063` (`LOSE LEVEL`) both call the
same terminal path at `0x00467A50`. After their finish fade they invoke the full
reset at `0x005CF920`: destroy all six region objects, recreate the set, switch
to a new Courtyard, repopulate, and reset the view. The boolean/result carried
by the script determines outcome bookkeeping; it does not select a different
room teardown algorithm. This is the `scripted_terminal_reset` edge.

### Death: final blow to Game Over and back

The final blow does not switch room immediately:

1. PlayerWizard terminal dispatch invokes Arena virtual `+0xD8`, resolved as
   `0x004633D0`.
2. Arena plays native audio actions 6 and 4, then calls
   `Game_OnGameOver` (`0x005CB570`).
3. A solo run continues through that original call immediately. In a
   multiplayer run, local deaths enter spectator presentation while another
   eligible participant is alive; the authority emits one replay-safe all-dead
   command when none remains alive, and every peer invokes the same original
   call exactly once on its own application thread.
4. `Game_OnGameOver` allocates/constructs the `GameOver` object and installs it
   over the still-resident Arena. The recorded terminal callback and overlay
   installation share tick `4413`; region 5 and its one local entity remain
   present on both sides.
5. Boneyard mode is intentionally fade-only. Game Over ticks independently and
   does not accept continuation merely because it reaches tick `1000`; input
   at/after that threshold triggers close.
6. Completion archives/cleans the run, performs the native `5 -> 1` switch,
   and installs the stock front end. The lobby remains alive while activity is
   `not-in-game`.
7. Stock Menu exposes Hall of Fame; its validated outer controller sets close
   rate `1.0`. `HallOfFame::Tick` integrates until progress exceeds `1.0` and
   reinstalls MainMenu.
8. G11 onboarding/Create commits the retained loadout and enters a fresh
   region-0 world. Direct `1 -> 0` dispatch is not an alternative.

This is why the death return is a pipeline rather than a single
`GameOver -> hub` edge. The full-session fixture records native event sequences
`159..194` plus before/after entity counts for it. Detailed Game Over alpha,
screen, and authority semantics remain in the dedicated Game Over document.

### Voluntary run exit

The host invokes the stock Pause/Leave Game action. Its authenticated state
then advertises `in_run=0` with the old nonce. Each client accepts that only
from its configured authority, opens its own stock pause menu, and dispatches
its own `pause_menu.leave_game`. An accepted all-dead command suppresses this
follow path so it cannot race Game Over. Raw Arena region switches are never a
valid leave operation.

## Multiplayer transition ownership

### Who decides and how peers converge

- Hub-private navigation is participant-local. Host and clients may occupy
  different regions `0..4`; remote actors materialize only when both scene
  intents match. The host continues the dormant shared-Courtyard simulation
  while its own player is private. Arbitrary authoritative simulation of
  several different private interiors remains outside v1.
- Run entry is host-authored. The host publishes selection, seed, nonce, and
  intent. A client cannot convert mere transport connectivity into permission
  to enter Arena.
- Run death is host-authoritative only for the all-dead decision. Every process
  still owns and ticks its own native Game Over object.
- Run Leave Game is initiated by the host and followed through stock UI on each
  client. Lobby leave/disconnect is a separate session operation.

The run-loading roster is frozen from connected authenticated participants at
start. Each process hashes its sorted visible participant ids, requires exact
count/hash equality, and holds that exact set for `250 ms`. The host accepts
acks only from the expected authenticated set on the active nonce and releases
once all have acked. The release is duplicated on low-latency frames and the
reliable checkpoint lane.

### Participant mid-action behavior

At a synchronized run switch, input sealing happens before native world
teardown. G14 clears device levels/edges and cast queues. The scene-preparation
boundary then clears queued participant synchronization and owner-local
inventory work, removes replicated transient world bindings, and dematerializes
remote/bot actors before the outgoing region sleeps. No movement edge, held
cast, target lock, or queued equip operation is replayed after attach. Durable
participant identity, loadout, vitals/progression ledger, lobby membership, and
the new run nonce survive and seed the replacement actor.

### Join and leave by state

| State | Join behavior | Leave/disconnect behavior |
| --- | --- | --- |
| `boot.loader` / `frontend.shell` (`not-in-game`) | Lobby membership may establish, but no gameplay actor exists. The participant advances its own G11 prerequisite/Create flow before hub materialization. | Lobby leave tears down transport membership; there is no world actor to detach. |
| `gameplay.courtyard` (`in-hub`) | A ready participant receives current durable checkpoints and materializes only after its loadout/world is ready. Existing participants remain live. | Its materialized actor/bindings retire; remaining members and the shared hub continue. |
| private regions `1..4` (`not-in-game`) | Navigation is local. A joining participant follows its own onboarding/hub path and is not forced into another participant's private room. Actors become mutually visible only for matching scene intents. | The private actor/bindings retire without moving other participants. Lobby membership otherwise follows the common teardown path. |
| `loading.boneyard` | The initial expected set is frozen. A later join is not retroactively inserted into that already-running barrier; it must resolve the retained Boneyard selection before following active authority intent. | A participant lost from the frozen set does not silently shrink the run-loading proof. The host releases the loaded peers at the `25 s` timeout and logs the waiting ids. |
| `gameplay.arena` (`in-boneyard`) | Late join is permitted only after the retained map digest resolves and authenticated host run intent/nonce is available. Missing content keeps that client outside while the active run continues. | A nonauthority departure retires its run membership. Host stock Leave Game drives authenticated client follow. Authority-disconnect migration is not established here. |
| `overlay.game_over` / post-run / Hall of Fame (`not-in-game`) | The run nonce is terminal; a new join does not enter that dead run. Lobby/checkpoint membership may persist while each process owns its local stock surface. | Leaving ends lobby membership but must not be confused with native Game Over cleanup. |
| returned `gameplay.courtyard` | All participants must independently complete stock onboarding and become world-ready. A later run allocates a fresh nonce in the same lobby. | Normal hub leave rules apply. |

## Failure and edge cases

The retail switch is `void` and is not transactional. It has no rollback result
for cache, allocation, or attach failure. Semantic callers must validate before
entering it.

- Same-region requests are safe no-ops.
- An invalid positive target can index beyond the six region slots and access
  violate. Native recovery was not found.
- `-1` can unregister the outgoing region without publishing a replacement;
  it is reachable as an internal transient but unrecoverable as a public stable
  state. Do not serialize or network it.
- Direct post-run `Mortuary -> Courtyard` probes access-violated even after a
  two-second stable wait. Once in that composite state, stock front-end/Hall of
  Fame progression is the recovery path.
- A stale or unauthenticated client run intent is rejected before native
  dispatch; it remains in its current state and may retry after a fresh host
  checkpoint.
- A missing selected Boneyard is fail-closed. Before launch it blocks the host;
  after launch it leaves only the affected late joiner outside and retries
  resolution without changing the authority's selection.
- Run-loading failure is bounded, not fatal: host and client each have a
  `25,000 ms` monotonic deadline. Timeout closes the loading presentation,
  marks the release reason `timeout`, and keeps the loaded run alive.
- Hall-of-Fame input during its entry fade is a native no-op. The stock flow
  validates the exact vtable/ABI and retries until the surface actually
  advances; call return is not completion evidence.
- Boneyard Game Over accepts itself when its counter becomes exactly 1000,
  begins its exit fade on the same tick, and reaches stock continuation without
  input. Waiting indefinitely at or beyond that edge is a failure.

### Not Yet Reversed

- The semantic purpose/name of outgoing region vtable `+0xC8` is unknown. Its
  exact order and `Gameplay+0x1358` argument are recovered and contracted.
- Native behavior for an unreadable/corrupt `Region%d.cache`, allocation
  failure in `0x005B7080`, or an exception inside incoming wake/attach is not
  reachable through the existing read-only Lua seams. No fallback is claimed.
- Stock Pause/Leave Game from each private region was not live-censused as a
  separate G13 edge. G11 proves the Courtyard pause edge; this document does
  not infer four additional cross-state edges from one screen action.
- Authority migration after the host disconnects mid-transition or mid-run is
  not established. The current contract is host-authoritative and fail-closed;
  no browser election rule should be invented from it.

## Golden interpretation

The fixture has two independently headed sections:

- `session_timeline`: six transitions for a complete
  title/front-end -> onboarding -> hub -> Library -> hub -> Arena -> death ->
  stock post-run -> hub session, each with its trigger, exact ordered native
  steps and simulation ticks, and live entity counts on both sides; and
- `transition_graph`: the 12 states, all 23 documented legal cross-state edges,
  and the illegal edge classes above, emitted by the running recorder.

Raw JSONL events, graph, status, and the Game Over frame remain in
`D:\codex-evidence\flowre-20260805\live-session-flow-final`. Their SHA-256
values are provenance constants in the committed header because those evidence
files are intentionally not part of CI. The fixture itself is reviewable text
and is the only committed copy of the recording.

For a browser implementation, the non-negotiable ordering is:

`fade-out endpoint -> seal if entering Arena -> transient participant cleanup
-> slot detach -> cache sleep -> lifecycle unregister -> publish target -> wake
-> attach -> old-region post callback -> target finalizer -> fade-in -> barrier
release -> unseal`.

Do not collapse this to `currentRoom = nextRoom`; that loses the exact points at
which native state, actors, presentation, input, and multiplayer authority
change owners.

## 2026-08-24 Website active-party rejoin integration

This addendum does not introduce a new retail address or claim that the stock
application owns a browser save, Website party, supervisor, or rejoin token.
It records the exact reuse boundary for the Website implementation so the
already recovered `gameplay.arena` late-materialization row cannot be replaced
by a save fork.

The complete applicable G13 membership is:

| Member | Native G13 disposition | Website consequence |
| --- | --- | --- |
| authenticated late Arena materialization | established: retained map digest plus authority run intent/nonce | a former party member may re-enter only the same still-active run after the host resolves those identities |
| nonauthority departure | established: retire run membership and actor bindings | do not leave an idle or XP-receiving ghost actor while the browser is absent |
| durable participant identity/loadout/progression/vitals | established survivor across materialization | retain one host-authoritative owner projection for the returning participant |
| input, cast queue, target locks, equip/sack work, replicated actor/effect bindings | established transient cleanup membership | discard them; rejoin requires neutral input and newly allocated live bindings |
| Boneyard selection, world, wave, enemies, loot, RNG, scripts, and run nonce | current authority-owned Arena state | never deserialize the returning browser's saved world over the live party run |
| `loading.boneyard` frozen expected set | established initial-launch roster | active-party rejoin is a later materialization, not a mutation of the completed start barrier |
| active `gameplay.arena` | established late-join state | exact eligible phase for reattachment |
| Game Over, post-run, Hall, returned Hub, replaced/empty run | established terminal/non-Arena states | reject the live claim and use the ordinary saved-wizard flow |
| authority departure | retail migration still not established | retain the Website's separately documented deterministic party-leader promotion without presenting it as stock evidence |

For the Website, a random capability may authenticate the former participant,
but it is a web transport mechanism only. It must bind player, party, session,
sealed content, and run nonce; become usable only after that participant's live
actor retires; and disappear when the run is no longer active. It is distinct
from the public Party ID and must not make private or playing parties
discoverable.

The actor returns through the cold Boneyard materialization seam at the
authored spawn. Its durable actor-private columns and Hall row are imported,
while current world state remains resident and all transient action/effect
owners stay cleared. No wall-clock disconnect interval is replayed as native
fixed ticks. This is the same durable/transient ownership split already proven
above, applied to a browser reconnection boundary rather than a new retail
edge.

## 2026-08-25 Website update-recovery ordering supersession

This addendum supersedes only the Website ordering in the preceding active-
party integration. It adds no retail process-resurrection or authority-
migration claim. Retail G13 still proves that an authenticated Arena actor can
materialize after the initial roster once map digest, authority run intent, and
the nonzero run nonce resolve. It does not require that actor to have been the
departed authority.

For a coordinated Website update, every responsive browser receives a final
owner-only authoritative checkpoint before any actor disconnects. The old host
binds that exact checkpoint to the announced replacement revision with a
server-only signature. After the supervisor is replaced, the first former
member presenting a valid bound checkpoint may reconstruct the same run and
become the recovered Website party's leader. A former nonleader is therefore
not blocked waiting for the old leader. Later former members with claims for
the same recovery/run identity attach to that one reconstructed authority.
This deterministic election is Website policy; retail behavior after loss of
the authority process remains unknown.

The materialization order is now:

`verify live/revision-bound recovery -> recover or resolve authority run ->
retain returning participant detached -> synchronize actor-private pending
choices -> resolve all detached choices while authority run continues -> cold
Arena materialization at authored spawn -> publish party membership -> accept
gameplay input`.

The detached interval is not a native Arena participant state. The participant
has durable identity/progression but no live actor binding, collision, target,
input, cast/effect lane, Hall membership, party membership, or run participant
row. Consequently it is not a member of the materialized ActorWorld cohort
until the final attach. Other clients must not observe or render a ghost actor.
If the run becomes terminal before attach, the recovery is retired instead.

Complete applicable membership remains: global and private authority, old
leader and nonleader return order, same-host detach, announced whole-process
replacement, racing first claims, later claims, sealed vanilla/mod content,
zero or pending private choices, second disconnect, another announced update
while detached, terminal/empty/replaced runs, capacity, and new-member
admissions. New public/Party-ID/request members remain out of this recovery
system and barred during play.

Validation receipt: the exact documentation candidate based on
`b638bb7ada23f7476bc694f1235fc50d29c9de72` passed the complete registered Mac
static RE suite `501/501`. The paired Website candidate passed its canonical
gate and real global/private Chrome journeys; those receipts and frame hashes
are owned by `Website/docs/game-native-parity-re.md`.

## 2026-08-25 Website durable-leader supersession

This addendum supersedes the Website-only election rule immediately above.
Retail process-loss authority migration remains unknown; no native claim has
changed. The explicit Website policy is now that transport loss does not
remove party membership and therefore cannot transfer leadership. The
original `leaderPlayerId` remains the leader while its actor and socket are
absent. The dedicated host process continues fixed ticks, but connected
nonleaders receive no leader-only party, run-start, or portal authority.

For coordinated replacement, each revision-bound signed checkpoint now carries
the same full ordered party roster, original leader, visibility, and bounded
last-authoritative ally projection. The first valid former member may still
seed the recovered authority world, including a nonleader, but restoration
installs the signed party before that member becomes observable. Later claims
attach actors to the already restored membership. Return order consequently
cannot elect, promote, or demote anyone.

The materialization order becomes:

`verify bound recovery and roster -> reconstruct authority world -> restore
original membership and leader -> retain claimant detached when choices are
pending -> advance live world while actor-private choices resolve -> cold
Arena materialization -> accept gameplay input`.

The durable party row is not a durable ActorWorld binding. Disconnected
members remain in Website social/presentation membership but have no collision,
target, cast, input, effect, or Hall actor lane until final materialization.
Explicit Leave Party or Kick remains the membership-removal boundary and may
then invoke the established Website promotion policy. Terminal/replaced run
teardown still retires the recovery lineage rather than restoring a ghost
world.

Validation receipt: the rebased pre-receipt documentation candidate
`00541fee374c9faffa2db15cbaf79d4fe3412f8e` passed the complete registered Mac
static RE suite `501/501` under Python 3.12.10. The paired Website candidate
passed its canonical Mac gate and global/private Chrome journeys; exact run and
frame receipts are owned by `Website/docs/game-native-parity-re.md`.

## 2026-08-25 correction: first story-Game Office admission before Create

The 2026-08-24 pass got the destination right and the lifecycle wrong. It
stopped after finding the region-4 branch, treated a diagnostic run's held
south input as an automatic native lane, and did not follow Office vtable slot
`+0xC8` far enough to discover that it opens Create only *after* Office exit.
It also reused the normal survival Office population instead of sweeping the
story-mode builder. The corrected stock order is:

```text
Tutorial Game Over / first-play completion
  -> front-end dispatch
  -> first normal story Game
  -> interactive story Office
  -> Office exit and covered 4 -> 0 switch
  -> Office post-switch callback opens Create
  -> element + Discipline confirmation
  -> Courtyard incoming transition
```

A port that shows Create first and then plays an automatic Office exit still
skips the native onboarding system.

### Mode, owner, and one-shot branch

The Tutorial Game is a dedicated `Game` marked at `+0x1CD4`. Its terminal
path `GameOver::Tick 0x005CF4F0` clears profile byte `0x0081A434`, saves,
runs completed-run cleanup, and dispatches the front end through
`0x005A7F60`. The Tutorial does not write survival selector
`DAT_00B3BEDC`; the process remains in story mode `0`. The full-image writer
sweep finds explicit writes of `1` for survival at `0x0058E8F6` and `2`
for the editor/custom path at `0x0058F64A`, but no runtime writer that turns a
Tutorial Game into survival mode before this first story Game.

`Game::Game 0x005CC800` initializes the story-admission byte
`Game+0x87 = 0` at `0x005CCE26`. `Gameplay_FinalizePlayerStart
0x005CFA80` selects Office region `4` only when all of these are true:

- ordinary non-test startup (`Game+0x1BB4 == 0`, `Game+0x1C05 == 0`);
- story mode (`DAT_00B3BEDC == 0`);
- no general modal/debug override (`DAT_00B3BCA0 == 0` at the destination
  test); and
- `Game+0x87 == 0`.

Survival mode and a consumed story admission select Courtyard region `0`
directly. The flag belongs to one native `Game`, not `darkdata.cfg`.

### Interactive Office entry

Office attach `0x005010C0` receives previous region `-1` for the initial
story entry. With the first-start byte `Game+0x1CD6` set, it places the local
actor at room center plus `(0,50)`: exact Office position `(512,562)`. It
then uses the ordinary Office incoming rate `-0.01f`, so the black cover clears
in 100 fixed ticks. The earlier claimed `(512,924)` / 40-tick hold was a
diagnostic sample already driven to the exit and is not the initial attach.

After the cover clears, ordinary player movement, collision, HUD, footsteps,
camera, NPC contact, Chat, inventory, and menu input are live. Office tick
`0x00509F10` does **not** force the actor south on entry. Only a later inclusive
circle contact with exit segment `(412,924)..(612,924)` clears action/casting,
starts scripted movement toward `(512,2024)` at native speed `1`, and raises
the outgoing cover by `+0.01f`. This preserves an arbitrarily long,
player-controlled conversation/exploration interval before exit.

### Story Office phase-zero population

Story-mode fixed-region builder `0x00513BE0`, selected by
`DAT_00B3BEDC == 0`, consumes `Game+0x1CD8`. The first story Game uses phase
zero and constructs the complete two-actor Office population:

| Member | Native identity and geometry | Dialogue / presentation |
| --- | --- | --- |
| Archchancellor | type `5012`, ctor/tick/render `0x00502A80/0x0050B6B0/0x0051DE40`, `(514,467)`, interaction radius `55` | `ARCH_INTRO_0`, `ARCH_Q1_0`, `ARCH_Q2_0`, `ARCH_Q3_0`, `ARCH_DISMISS_0`; Office records `3,7..12`; help-right marker record `15` |
| Polisher | type `5011`, ctor/tick/render `0x0050B4F0/0x00505EB0/0x0051DD50`, `(566,735)`, interaction radius `15` | `POLISHER_INTRO_0`, `POLISHER_Q1_0`, `POLISHER_Q2_0`, `POLISHER_DISMISS_0`; Office records `23..26`; talk-left marker record `14` |

The Archchancellor intro has the only shipped story-Office voice file,
`voices/ARCH_INTRO_0.wav`, 1,231,088 bytes, SHA-256
`b819a5aa7397df964ec9f9e03149941450d65d10fe207f71c3643419fd071255`.
Questions, dismissals, and Polisher lines have no corresponding retail WAV.

Polisher animation starts at phase `0` and signed speed `0.05`. Each 100-Hz
tick adds `(1 + Float(0.25,false)) * speed`, wraps the phase in `[0,4)`, and
reverses speed on `Integer(1500) == 3`. Rendering selects Office record
`23 + trunc(phase)`. Its embedded `dynamic_sounds/wipeglass.wav` loop is
full gain through distance 50, falls linearly to zero across distance 50..200,
and is silent beyond 200. Actor destruction/Office reconstruction owns loop
teardown/restart.

Phase one and the standing/desk Archchancellor variants remain the later story
system. Normal survival `ARCH_INTRO/ARCH_Q/ARCH_DISMISS` remains the separate
survival-Hub graph. Neither may replace the phase-zero first admission.

### Exit opens Create; Create does not precede Office

At exact outgoing black, `Gameplay_SwitchRegion 0x005CDDD0` performs the
ordinary covered `4 -> 0` switch. Its post-switch callback invokes the old
Office object's vtable slot `+0xC8`, `Office::AfterSwitch 0x00504AD0`.
That callback is the decisive Create owner:

- it verifies the callback argument is the local player;
- it tests selected element root `player progression +0x82C == -1`;
- it sets `Game+0x86 = 1`;
- it allocates/attaches the `Create` surface and marks it as the in-Game
  variant; and
- it writes `Game+0x87 = 1`.

The Courtyard may already be attached behind the opaque Create surface, but
loadout selection remains the visible owner. After element and Discipline
confirmation, `0x005D0290 -> 0x005CFA80` sees `Game+0x87 != 0`, selects
Courtyard directly, and runs the ordinary Courtyard incoming placement
`(952.5,67.5) -> (952.5,157.5)` with `-0.01f` cover. Later same-Game Create
generations do not replay Office.

### Portable web consequence

A browser save/session can cross the native Game lifetime, so the smallest
portable projection remains a durable pending bit, but its transition meaning
is corrected:

- fresh browser profiles start pending; historical profiles migrate completed;
- Tutorial entry and Tutorial gameplay preserve pending;
- after Tutorial terminal fade, and after the browser-only Tutorial `NO`
  branch when the first normal Game begins, pending starts an interactive story
  Office at `(512,562)` before any Create surface;
- the initial incoming cover does not lock movement after tick 100;
- story Archchancellor and Polisher are participant-local Office population;
- touching the normal Office exit runs the ordinary outgoing kernel, then opens
  Create at the covered switch boundary;
- Create confirmation resumes the existing Courtyard incoming kernel;
- pending clears only after the Courtyard entrance settles; and
- disconnect/reload before settlement replays from the Office entry, while
  later deaths/loadouts route directly to the Courtyard.

In a shared browser Hub, one participant's story Office/Create flow is local to
that participant. It does not pause, relocate, or replace the shared Courtyard
for other participants. There is no browser-only cinematic timer, forced
40-tick hold, automatic Office exit, survival Arch dialogue substitution, or
Create-before-Office fallback.

### Validation receipt

The exact rebased documentation candidate
`0e3dd4ce4b5c7776fa96d9b589873ae964cd8ac2` (tree
`a15e08bf113dee9d6fb5474d1fe182f6fefe5572`, base
`35d0941d6baad59dd7c46907a39d2ba6e6072c09`) passed the complete registered
Mac static RE suite `502/502`. Log SHA-256 is
`a77caa5631efaf25cc45edc74af5193e6700b6534d450c1bf5ae0a77ad45e2ba`.
The paired Website exact-tree and Chrome/Metal receipts are recorded in
`Website/docs/game-native-parity-re.md`.
