# Native regions, NPCs, and world props

## Result

The retail world has two construction models:

1. Courtyard, Mortuary, StoreRoom, Library, and Office are compiled `Region`
   subclasses. Their geometry, actor populations, update rules, and atlas
   record choices are native code.
2. Arena is the boneyard-backed `Region` subclass. It reads or generates a
   `RegionLayout`, expands serialized specifications into runtime scenery and
   collision objects, and renders loose textures, DeadHawg selectors, and
   generated geometry.

Both models eventually share the same actor, collision, camera, audio,
presentation, and object-lifetime infrastructure. They do **not** share a
filename-addressed prop registry. Named interior NPCs and props are compiled
classes; `NPCRecipe` can instead construct and configure the generic
`GameNPC` class. Outdoor scenery uses compiled numeric types and selectors.

This document covers the retail `SolomonDark.exe` whose SHA-256 is
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
The full object registry and atlas xrefs are machine-readable in
[`native-game-object-catalog.json`](native-game-object-catalog.json) and
[`native-atlas-consumers.json`](native-atlas-consumers.json). Boneyard byte
grammar and generated-world details are in
[`native-boneyards-and-world.md`](native-boneyards-and-world.md).

## `Region` base object

`Region` is factory type 4000. Its constructor at `0x00652830` allocates and
initializes an 0x8E88-byte object with vtable `0x0079F3E4`. The object is not
only a tile background. It owns or embeds this region-local state:

- an `Array<Puppet*>`, a `PuppetManager`, and multiple actor/pointer lists;
- `MyCollider` and the world movement/collision substrate;
- `RegionLayout` at `+0x8510`;
- smart-pointer arrays for puppets and animations;
- per-frame NPC/presentation arrays and a miscellaneous-light array;
- four independent grids of 0x800 dwords each;
- camera, transition, scripted-movement, render-effect, string, and viewport
  state.

The same constructor also binds 13 **global** `AmbientSound` wrappers to
preconstructed `SoundLoop` slots. Those 0x10-byte wrappers are not embedded in
the 0x8E88-byte Region allocation. Base tick `0x0063EFC0` services the global
mix while a region is active; the exact wrapper addresses and loop mapping are
in [native-audio-system.md](native-audio-system.md#global-ambient-loop-mix).

Initialize slot `+0x04`, `0x0063E4B0`, requests an object handle/ID from the
million-entry allocator and stores it at `Region +0x178`. Base tick
`0x0063EFC0` performs system-level work before a subclass adds room behavior:

1. tick all 13 global ambient wrappers and clear their requested per-frame
   gains;
2. update transition alpha/velocity and call virtual slot `+0x128` when an
   endpoint is reached;
3. reset/fill per-frame presentation and NPC arrays;
4. tick manager/list members and optional region-owned state;
5. apply the enhanced/zoom gate at `DAT_00B3BCAC`;
6. damp camera impulse and screen displacement;
7. advance the global gameplay frame counter;
8. drive an optional scripted local-player movement target; and
9. advance a timing/state gate that can invoke subclass slot `+0xCC`.

The transition, camera, and actor-list state belongs to the region; an atlas
record does not own any of it. Region destruction at `0x0064A5D0` normalizes
the global ambient requests before tearing down region-local managers, actors,
collision state, and layout objects. It does not destroy the global wrappers
or their registry-owned loops.

## Fixed regions

The fixed room subclasses and their recovered roots are:

| Type | Class | Size | Constructor | Tick | Vtable | Published instance |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 4001 | Courtyard | `0x95AC` | `0x00506490` | `0x0050C970` | `0x00792644` | `DAT_00819A70` |
| 4002 | Mortuary | `0x9000` | `0x005090A0` | `0x00509330` | `0x007927DC` | `DAT_00819A74` |
| 4003 | StoreRoom | `0x8EA4` | `0x00509B10` | `0x00504220` | `0x0079294C` | `DAT_00819A78` |
| 4004 | Library | `0x8EA0` | `0x0050A360` | `0x00504BB0` | `0x00792C04` | `DAT_00819A80` |
| 4005 | Office | `0x8EDC` | `0x00509C70` | `0x00509F10` | `0x00792AB4` | `DAT_00819A7C` |
| 4006 | Arena | `0x9068` | `0x00464EE0` | `0x0046E570` | `0x00785934` | dynamic gameplay region |

Mortuary explicitly assigns the `MORTUARY` region name. The fixed subclasses
add room-specific camera points, actor/prop state, foreground/background
passes, and interaction logic. Arena instead delegates its population and
geometry to `RegionLayout`; its load, regenerate, save, and materialization
chain is documented in the boneyard map.

### Interior bounds, collision, and normal population

The four private interiors construct independent world bounds and center their
primary room atlases inside them:

| Region | World bounds | Primary art and offset | Static contour records | Normal fixed population / collision |
| --- | --- | --- | ---: | --- |
| Mortuary | `1024 x 1024` | Memoratorium `970 x 910` at `(27,57)` | 11 | Memorator `(628,770,r25)`; ten Painting actors `r15` with paired solids `r40` |
| StoreRoom | `1075 x 800` | Storage `1075 x 655` at `(0,72.5)` | 34 | solid shelving props `(538,324)`, `(537.5,434)`, `(536,542.5)`, each `r40` |
| Library | `1024 x 1024` | Library `992 x 819` at `(16,102.5)` | 27 | Librarian `(512,595,r55)`, Dowser `(900,642.5,r25)`, plus solids `(239.5,788)`, `(258.5,678.5)`, `(762,732.5)`, `(831,620.5)`, each `r40` |
| Office | `1024 x 1024` | Office `819 x 819` at `(102.5,102.5)` | 48 | Arch Chancellor `(514,467,r55)` plus solid `(517.5,681,r40)` |

The contour builders consume duplicated-point records from, respectively,
`DAT_00806660..DAT_00806710`, `DAT_00806710..DAT_00806930`,
`DAT_00806C30..DAT_00806DE0`, and
`DAT_00806930..DAT_00806C30`. The initial point is the pair at `tableStart-8`;
each subsequent point is the first pair in a 16-byte record. The builder joins
that previous point to each successive record point. They are authored
collision chains, not rectangles implied by the room art.

Those table points are primary-art-local, not Region-world coordinates. Each
setup routine translates both endpoints before passing them to segment
registrar `FUN_005213C0`:

`world = viewOrigin + 0.5 * viewSize + (tablePoint - tableOrigin)`

| Region | Setup routine | View size | Table origin | Table-to-world offset |
| --- | ---: | ---: | ---: | ---: |
| Mortuary | `0x00515290` | `1024 x 1024` | `(485,455)` | `(27,57)` |
| StoreRoom | `0x00517A30` | `1075 x 800` | `(537.5,327.5)` | `(0,72.5)` |
| Library | `0x00517F60` | `1024 x 1024` | `(496,409.5)` | `(16,102.5)` |
| Office | `0x00517D50` | `1024 x 1024` | `(409.5,409.5)` | `(102.5,102.5)` |

The translations exactly equal the centered primary-art offsets in the table
above. Office setup, for example, loads double `409.5` from `0x00792140`,
multiplies the `1024` view dimension by double `0.5` from `0x007DE808`, and
adds the resulting `102.5` delta to every table X and Y before registration.
The fixed actor and prop circles are separately authored in world coordinates
and do not receive this architecture transform.

The native ownership seam is the region layout, not the PNG pixels. Each
fixed-room constructor owns the room bounds and its authored contour table,
while the matching presentation routine owns the registered base and late
room layers. Depth-sorted solid props are separate world objects: their
object/class state supplies the collision body and their auxiliary renderer
selects the matching atlas record. Thus a faithful modular model should bind
an architecture layer to its authored segment chain and bind each visual prop
record to its authored actor collider. It should not infer collision from
opaque pixels or flatten actor props into the background.

A 2026-08-13 dump of every raw endpoint in all four static ranges matched the
web tables exactly, including authored order. That result established table
transcription but was previously misread as a world-space collision result. A
fresh isolated live Office capture on 2026-08-14 used the same clean retail
image (SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`),
runtime base `0x00E20000`, Office object `0x15CB8FD8`, and embedded controller
`0x15CB9350`. Its 48 registered segment objects contain transformed world
coordinates: segment 0 is `(600.5,972.5)->(598.5,921.5)`, segment 38 is
`(450.5,741.5)->(589.5,741.5)`, and segment 47 is
`(416.5,733.5)->(451.5,741.5)`. Each is the corresponding raw table segment
plus `(102.5,102.5)`. The controller retained its native `1024 x 1024` extent,
`7 x 7` spatial grid with `150 x 150` cells, and enabled slide flag; the shared
movement response was not the source of the reported displacement.

Painting talk bodies remain `r15`, while each associated `r40` solid scenery
body is centered two world units above it. The larger body fully determines
ordinary player collision while the smaller body remains the interaction
owner. That distinction should be preserved in the domain model without
adding a second, behaviorally redundant collision response.

The ten normal Mortuary Painting centers are `(512,697)`, `(350,683)`,
`(673,683)`, `(744,540)`, `(590,540)`, `(434,540)`, `(279,540)`,
`(354,400)`, `(512,400)`, and `(670,400)`. Alternate story population paths
exist, but they do not replace this ordinary Hub population by default.

Room presentation preserves three ownership bands: base/registered room art,
depth-sorted world actors and props, then later foreground fragments. The
Mortuary easels/portraits, StoreRoom shelving, Library tables/shelves and exit
corridor, and Office wall fragments therefore cannot be flattened into a
single background without losing native player occlusion.

The instruction-level painter order further resolves the normal fixed-room
composition:

- `StoreRoom::Present (0x00519070)` tiles Storage record 1 and submits record
  5 plus records 13..26 before the ordinary actor list. Its three solid shelf
  rows call the auxiliary pass with selectors 0..2, which draws records 2, 3,
  and 4 at the room transform and therefore depth-sorts them at the authored
  actor centers `(538,324)`, `(537.5,434)`, and `(536,542.5)`. Records 11 and
  12 are submitted only after the actor/effect lists. Storage record 0 is the
  small room-effect particle, while 7..10 are the interaction-marker bank;
  neither belongs in a flattened room background.
- `Library::Present (0x00511320)` draws room record 0 and the extended return
  corridor record 5 before actors. The three table render selectors 0..2 in
  `0x00512060` draw records 9, 10, and 11 in depth order; the fourth recorded
  solid is collision-only with respect to that selector. Records 1 and 2 are
  late candelabra fragments after the actor list. Record 3 is the small room
  particle, and records 6..8 plus 13..20 belong to the interaction/effect
  branch rather than the static room layer. After record 4 and the room-effect
  pass, the function sets opaque black and submits two untextured rectangles
  at room-local `(-496,289,381,121)` and `(115,289,381,121)`, then restores
  white. With the `(512,512)` room transform these cover world rectangles
  `(16,801)..(397,922)` and `(627,801)..(1008,922)`, leaving the authored
  230-pixel return corridor visible. These late exit masks are renderer-owned;
  they are not pixels in Library records 0..5.
- `Office::Present (0x00519E40)` draws room record 1 and extended return
  corridor record 4 before actors, then submits records 17..22 after the actor
  and effect lists. The one solid prop uses selector 0 in `0x00501060` and
  depth-sorts Office record 5 at `(517.5,681)`.
- `Mortuary::Present (0x0050EAC0)` draws base record 0 before actors. Its
  painting presentation is actor-owned by `0x00518620`; main-painter records
  1 and 5 are room-effect sprites, not a replacement static foreground.

These are renderer ownership facts, not merely record xrefs: the StoreRoom
and Library prop records must remain independent depth entries, and the late
room fragments must remain after the player/NPC list.

This ownership also explains the adjacent Boneyard case without making the
two formats identical. A Boneyard placed object already carries native class,
variant, transform, and registered art identity; collision is class/variant
behavior materialized from that object. Fixed Hub architecture instead uses a
region-owned contour chain. Both benefit from one semantic prop/layout record
feeding presentation and collision, but the Hub room schema must not be
serialized into `.boneyard`, nor should either path use pixel masks as its
physics contract.

The live painter capture fixes the late StoreRoom geometry more precisely.
Records 11 and 12 are both submitted with the room-center transform
`(537.5,400)`, resolve to world rectangles `(41,607)..(487,727)` and
`(589,607)..(1035,727)`, and leave the authored 102-pixel center doorway
transparent. A player below the wall is occluded at the left and right pieces
but remains visible through that center gap. Moving these records behind the
player to cure an entrance artifact would be a native regression; any such
artifact must instead be traced at the Courtyard entrance/camera layer.

Normal presentation also instantiates additive room particles from the small
effect records: 50 candle flames from Memoratorium 1, 9
from Storage 0, 17 from Library 3, and 7 from Office 2. The presentation loop
calls `FUN_00401310` twice per flame: Mortuary samples Y scale uniformly from
`[0.7,0.9]`, the other rooms sample `[0.8,1.2]`, and all rooms sample rotation
from `[-5,+5]` degrees while fixing X scale at `0.8`. It then calls transform
submitter `FUN_00415020` and uses blend source `5`, destination `2`, operation
`1`. These sprites are live presentation effects, not pixels that may be baked
into a background.

The 2026-08-20 reopened Memoratorium pass closed one omitted ordinary member.
After actors, room effects, and the 50 record-1 flames,
`Mortuary::Present (0x0050EAC0)` loads the Memoratorium singleton record-5
field at `+0x40C` three times and submits it at `0x0050F4D3`, `0x0050F55C`,
and `0x0050F5E5`. Record 5 is a registered `71 x 54` white memorial glow. All
three submissions use the normal room center with the compiled five-unit
vertical adjustment, producing world root `(512,507)`, and occur after the
world actor/effect lists. The former Website room pass mentioned record 5 as
effect-owned but implemented only the record-1 flame family. The full Hall and
memorial ownership thread is in
[`native-hall-of-fame-and-memoratorium.md`](native-hall-of-fame-and-memoratorium.md).

### Exact fixed-region art composition

The following bindings are executable record selections, not visual guesses:

| Region / routine | Atlas records selected |
| --- | --- |
| Courtyard presentation `0x0051EB60` | College 2..4, 7, 12..13, 19, 21..22, 26, 30..31, 40, 42..44, 59..62, 63..88, 93..118, 505..509; Title 7 and 9 |
| Courtyard tick `0x0050C970` | College 38 for its animated/state-dependent room effect |
| Mortuary presentation `0x0050EAC0` | Memoratorium 0..1, 5, and 24..27 |
| Mortuary auxiliary pass `0x00518620` | Memoratorium 3, 4, 7..9, 14..23 |
| StoreRoom presentation `0x00519070` | Storage 0..1, 5, and 7..26 |
| StoreRoom auxiliary pass `0x00500DD0` | Storage 2..4 |
| Library presentation `0x00511320` | Library 0..5 and 17..20 |
| Library auxiliary pass `0x00512060` | Library 6..11 |
| Office presentation `0x00519E40` | Office 1..2, 4, and 13..22 |
| Office auxiliary pass `0x00501060` | Office 5 |

The room routines build layered scenes. They change renderer transforms and
depth, draw base and foreground records, render actor/prop lists between those
layers, submit effect geometry, and restore presentation state. Replacing one
background record does not replace the room, its collision, or its foreground
occlusion.

The StoreRoom entrance report exposed the same ownership rule in the adjacent
Courtyard. A normal live painter capture at player `(602.408875,243.011703)`
showed College record 2 as base art at draw order 28, before the resident world
list. Four `CollegeObstacle` actors were then depth-sorted immediately around
the player:

| Record | Obstacle center | Captured order relative to player |
| ---: | ---: | --- |
| 23 | `(749.5,162.5)` | before |
| 24 | `(956,169)` | before |
| 20 | `(628,215)` | before |
| 25 | `(955.5,239.5)` | before |
| player | `(602.408875,243.011703)` | after all four |

Thus records 20, 23, 24, and 25 are not one fixed “spawn roof” at a `y=320`
boundary. Record 24 may not be flattened into the base either. Each obstacle
keeps its own actor-center depth, while record 2 remains in the pre-actor room
art. Collapsing those ownership bands makes the Storeroom doorway at record 20
incorrectly cover a player who has already walked south of it.

The original decompiler-source xref pass missed 40 of these selections because
untyped `thiscall` callees caused Ghidra to discard the ECX sprite argument.
`tools/ghidra-scripts/trace_singleton_register_offsets.py` follows the actual
x86 register setup and recovered those calls. After joining both passes, only
these fixed-room records are dormant in the retail executable:

| Atlas | Built records with no stock selection |
| --- | --- |
| College | 1, 9, 35, 36, 46 |
| Memoratorium | 10 |
| Storage | 6 |
| Library | 12 |
| Office | 6 |

These records are still parsed and resident when their bundle is acquired.
The absence of a stock selection means neither decompiled source nor the
instruction-level singleton trace reaches them. They remain valid bundle ABI
members, but appearance alone is not evidence of hidden gameplay use.

## Courtyard and interior actors

The College atlas combines room architecture with compiled character art.
Those character classes are not `GameNPC` variants created by a string name;
they have distinct vtables, sizes, ticks, renderers, and factory identities.

| Type / class | Constructor | Tick | Renderer | Native art |
| --- | ---: | ---: | ---: | --- |
| 5001 PerkWitch | `0x005018D0` | `0x0051ADC0` | `0x0051B1D0` | College 5, 45, 89..92, 517..524 |
| 5002 Student | `0x00501B80` | `0x0050A4E0` | `0x0051B2A0` | College 165..500 in fourteen 24-record directional/animation groups |
| 5003 Annalist | `0x00502120` | `0x0050A4C0` | `0x0051BFA0` | College 0, 47..50 |
| 5004 PotionGuy | `0x005023A0` | `0x0050B110` | `0x0051C1A0` | College 32..34, 54..58, 160..164 |
| 5005 ItemsGuy | `0x005024C0` | `0x0050A4C0` | `0x0051C660` | College 10, 11, 126..129 |
| 5006 Illuminator | `0x00502270` | `0x005052B0` | `0x0051C050` | College 8, 119..125 |
| 5007 Tyrannia | `0x00502450` | `0x0050B1F0` | `0x0051C560` | College 510..516 |
| 5008 Teacher | `0x00502570` | `0x0050B260` | `0x0051C710` | College 13, 501..504 |
| 5011 Polisher | `0x0050B4F0` | `0x00505EB0` | `0x0051DD50` | Office 23..26; embedded wipeglass audio loop |
| 5012 ArchChancellor | `0x00502A80` | `0x0050B6B0` | `0x0051DE40` | Office 0, 3, 7..12 |
| 5013 Librarian | `0x00502C10` | `0x0050A4C0` | `0x0051E0E0` | Library 25..32 |
| 5016 Dowser | `0x00502C80` | `0x0050A4C0` | `0x0051E1F0` | Library 21..24 |
| 5017 Memorator | `0x00502D90` | `0x00513090` | `0x0051E270` | Memoratorium 2, 6, 7, 28..75 |
| 5022 Annalist2 | `0x00503000` | `0x005061E0` | `0x0051EAF0` | Memoratorium 11..13 |
| 5023 ArchChancellorDesk | `0x00502BA0` | `0x0050A4C0` | `0x005060A0` | Office 3 |
| 5024 ArchChancellorStanding | `0x00502B20` | `0x0050A4C0` | `0x0051DDC0` | College 51..53 |

The normal named-NPC compositors are also layered rather than single-record
portraits. The base named-NPC constructor `0x005016E0` initializes animation
selector `Actor+0x144` to zero; `FUN_00747360` converts that stored float to
the integral frame index and does not randomize it. Consequently the ordinary
idle render is deterministic:

- `Librarian::Render (0x0051E0E0)` first draws all of Library 29..32 at the
  room-view center, then selects Library 25..28 by `Actor+0x144` and draws the
  selected body at `(actor.x, actor.y-57)`. The normal default is record 25
  over the counter/rail composition 29..32.
- `Dowser::Render (0x0051E1F0)` selects Library 21..24 by the same field; the
  normal default is record 21 at the actor root.
- `ArchChancellor::Render (0x0051DE40)` draws Office record 3 at the room-view
  center and selects one record from each paired bank 7..9 and 10..12 with the
  same frame. The body root is `(actor.x+6,
  actor.y-100+0.75*Actor+0x174)`; the constructor leaves `+0x174` at zero, so
  the normal default is records 7 and 10 at `(518,412)` over the desk.
- In normal Mortuary state (`Region+0x8F10 == 0`),
  `Memorator::Render (0x0051E270)` selects a 16-heading body/head composite at
  `(628,770)`. Heading index `i` uses body record `28+i` and head record
  `44+2*i`; index 0 faces north and indices advance clockwise. A settled
  ordinary entrance capture selected 39+66, facing the local player, while
  controlled player placements recovered 28+44 north, 30+48 north-east,
  32+52 east, 34+56 south-east, 36+60 south, and 40+68 west. The nearby
  question marker is record 27, submitted at `(598,710)` and resolving to
  center `(627,742)`, or `(-1,-28)` from the actor root. Constructor-zero
  28+44 is a transient north-facing frame, not the fixed player-visible idle.

The Painting pass has its own nearby eulogy lifecycle. Mortuary population
setup `0x00515290` creates the ten ranked Painting actors and can initialize a
selected `DAT_0081A3FC[index]` portrait id to `-1`; in
`Mortuary::RenderPainting (0x00518620)`, that transient unset state draws blank
registered easel record 4. That constructor observation was previously
mistaken for the ordinary visible room state. In a clean normal new-game Hub
with builder selector `Gameplay+0x1CD8 == 0`, the player-visible globals were
`DAT_0081A3FC[0..9] = 0,1,2,3,4,5,6,7,8,9` and
`DAT_0081A3C0[0..9] = 0,1,1,1,0,1,1,0,0,1` before entry. The room consequently
showed ten filled portraits and six marker urns. Each bundled filled painting
draws registered easel record 3, portrait record `14+id`, front record 7, and,
for a true marker bit, record 8 offset `(10,15)` from the Painting actor.
External portraits and the completed-eulogy update remain valid adjacent
branches, but ten blank easels are not a native-safe default for an ordinary
web Hub session.

These selections correct the earlier consumer-only interpretation that
mistook Library 29..32 for the Librarian body and treated Library 25..28 as
dormant. They also establish the exact default layer pairs used by a static web
parity frame while leaving animation selectors available for a later service
interaction slice.

There is no registered type 5014. `Astronomer` is instead a small region-owned
helper object constructed at `0x005025F0`, with vtable `0x00791A70`, update
`0x00505950`, and render `0x0051C790`. It uses College 130..147 and 525..542;
its update also reaches College 505..509. Treating it as a missing game-object
factory case would be incorrect.

Students are the roaming courtyard population. Their class-specific tick
routes steering into the shared stock movement/collision executor; named
trader characters mostly use the common named-NPC tick `0x0050A4C0` or a
narrow subclass extension. The art and movement rails therefore differ even
when both are friendly characters in the same room.

The courtyard creation loop around `0x0050CD10` registers each `0x138A`
Student and increments the owning region's signed Student count at `+0x9308`.
`Student::Tick (0x0050A4E0)` retires an expired Student through vtable slot
`+0x18`; the Student vtable at `0x007916DC` resolves that slot to
`0x00401FD0`, which sets the generic actor pending-remove byte at `+0x05`.
The tick then decrements the same owner `+0x9308` count. Multiplayer surplus
cleanup must mirror that deferred-retirement plus counter pair; calling the
actor-world unregister path directly skips the stock courtyard lifecycle.

## Generic `GameNPC` and recipes

`GameNPC` is type 5015, constructor `0x005E9A90`, vtable `0x0079CEBC`, and
size 0x268. Constructor state establishes actor group `0x20`, a recipe/config
pointer path, presentation selector, facing/movement state, callback flags,
and two initialized color rectangles.

The stock source/recipe materializer at `0x00466FA0` makes the descriptor ABI
exact. It factory-allocates type 5015, stores descriptor `+0x4C` as actor
presentation selector `+0x174`, the descriptor pointer itself at `+0x178`, and
descriptor `+0x50` as behavior/record ID `+0x17C`. It resolves preview
position through `0x00466600`, applies the position helper at `0x00466200`,
runs optional region callbacks/effects, registers the actor through
`0x0063F6D0`, and builds its source-driven visual state through `0x005E3080`.
A failed registration destroys the new actor and returns null. The only direct
retail caller is the create-wizard action path, so this proves the descriptor
layout and publication contract without inventing a general long-lived NPC
spawner that stock code never calls.

The two formerly opaque descriptor mirrors also have exact editor and runtime
meanings. `NPC_SETUP` parser `0x004B53F0` reads `IDLE BEHAVIOR` into descriptor
`+0x56` and `TALK SPEED` into `+0x74`. Render-descriptor builder `0x005E3080`
sign-extends the first into actor `+0x1C0` and copies the second into actor
`+0x194`. `GameNPC_Tick (0x00608110)` makes idle-behavior value 1 face the
local Player. Serializer `0x005E3330` persists both fields, and dialog/action
path `0x005EA1C0` consumes talk-speed value 1 when it builds the active dialog
object.

Tick `0x00608110` performs the following recovered flow:

1. run the common named-NPC update;
2. when presentation mode is 1, or qualifying mode 3, append the actor to the
   region's current-frame NPC list;
3. resolve its recipe/config behavior through the world helper;
4. smooth facing toward the desired orientation, with a bounded correction
   loop;
5. execute movement/follow state through the shared movement helpers;
6. interpret branch byte `+0x181` with compiled modes 1 through 4;
7. optionally face the local player; and
8. update animation cadence and smoothing state.

The scripting action rail can write `+0x181`, prime follow/move goals, select
type-5015 actors, and clone selected NPCs into the ally/player rail. Those
command semantics are detailed in [`npc-ally-investigation.md`](../npc-ally-investigation.md).

Renderer `0x00622430` switches on presentation selector `+0x174`:

- cases 0, 1, and 2 compose directional body/layer groups from NPCs 3..218;
- case 3 delegates to the full wizard renderer at `0x00621780`;
- NPCs 1..2 are conditional interaction/speech bubbles;
- conditional sparkle/presentation children use BadGuys art; and
- the renderer finishes through shared actor-presentation cleanup.

The exact NPCs groups are 3..20, 21..38, 39..92, 93..110, 111..128,
129..146, 147..164, and 165..218. NPCs record 0 is stock-dormant: the
exhaustive singleton/destination scan finds no compiled selection outside
bundle construction and teardown. A boneyard `NPCRecipe` can configure
this compiled class, but it cannot define a new renderer case or extend those
arrays merely by adding atlas records.

## Other region actors and props

| Type / class | Constructor | Update/render roots | Native art and role |
| --- | ---: | --- | --- |
| 5009 Solomon_Dig | `0x00481C20` | tick `0x0048A8B0`, render `0x004A2610` | Compiled Solomon encounter/cinematic actor; enemy-family logic, not a generic prop. |
| 5010 Lantern | `0x005E1120` | tick `0x005FF010`, presentation `0x005E61D0` | BadGuys 34 plus dynamic light/state. |
| 5018 Painting | `0x00502F40` | tick `0x0050A4C0`, callback `0x00506190` | Region-owned composition; the actor has no class-owned singleton selection or standalone atlas field. |
| 5019 Solomon_Riff | `0x004756C0` | tick `0x004756F0`, render `0x004A15E0` | SolomonRiff 1..12; record 0 is stock-dormant. |
| 5020 Solomon_DriveBy | `0x00475DD0` | tick `0x004896A0`, render `0x004A1A70` | Solomon 95..184 plus BadGuys 80. |
| 5021 Portal | `0x0047BD60` | tick `0x00489CC0`, render `0x004A1B30` | Hostile Imp Portal: BadGuys 251..254, 401..419, 1823..1833 and DeadHawg 46..77, 114..144, 180..199. |

`Portal` 5021 is not a generic room-transition object. It is the enemy portal
with health, attacks/spawns, damage/death logic, and effect children described
in [`native-enemies.md`](native-enemies.md). Room transitions are region and
scene state, not instances of this class.

Fixed courtyard scenery also includes `CollegeObstacle` 2007,
`CollegeStatue` 2008, and `CustomObject` 2041. `CollegeObstacle` renderer
`0x0051AB20` selects College 6, 20, 23..25, 27..29, and 148..159.
`CollegeStatue` selects record 39 in vtable function `0x00501490` and record 41
in `0x00501510`. `CustomObject` remains configured/region-driven without a
direct singleton record binding. Their object/collision lifetimes still use
the shared world-object base; art replacement alone does not replace their
collision or update behavior.

## Arena world components and derived ownership

The registered world-component band is exact:

| Type | Class | Native role |
| ---: | --- | --- |
| 3004 | Road | Serialized spline/control points; builds an 18-vertex mesh and selects one of five loose `road` textures. |
| 3005 | Fence | Serialized specification, not final visible/collidable scenery. |
| 3006 | Fencepost | Endpoint object; DeadHawg 36..42 or 320..347 from selector/style state. |
| 3007 | FenceGrate | Repeated loose `fencegrate` quads plus registered collision. |
| 3008 | ScriptThread | Runtime script execution state; no art. |
| 3009 | Terrain | Serialized point/scalar arrays transformed into generated vertex/index buffers. |
| 3010 | FX | Serialized/system effect data object; no standalone atlas binding in this band. |
| 3011 | FenceGrate_Broken | One materialized broken half; DeadHawg 3. |
| 3012 | Gate | Each of two materialized hinged leaves; DeadHawg 7/8 plus moving collision and bounce/damping. |
| 3013 | Wall | Generated wall mesh and polygon collision; multiple-shadow option at `DAT_00B3BCA9`. |
| 3014 | FenceGrate_Rails | Materialized rails; DeadHawg 23 plus generated line/quad geometry. |

`RegionLayout` post-load expands one type-3005 `Fence` using an exact five-code
grammar: code 0 creates one `FenceGrate` plus endpoint posts; code 1 creates
two `FenceGrate_Broken` leaves plus posts; code 2 creates two `Gate` leaves
plus posts; code 3 creates one `Wall` plus two `ZFightHelper` children and no
posts; code 4 creates one `FenceGrate_Rails` plus posts. Endpoint posts are
deduplicated by exact `(x, y)` equality across the materialization pass. Gate
tick `0x005ED5F0` integrates motion, tests the proposed collision segment,
rolls back and damps/reverses on contact, rebuilds collision state, and
rate-limits its sound. A peer that synchronizes only the Fence recipe but not
identical materialization state can diverge in both visuals and collision.

The principal selector-based outdoor classes are:

| Type / class | Native art |
| --- | --- |
| 2001 Tree | DeadHawg 228..242, 243..263, and 264..282; layered main/foreground with collision and viewer-local occlusion alpha. |
| 2009 Monument | DeadHawg 156..176. |
| 2029 Gravestone | DeadHawg base 97..113 and independent overlay 88..96. |
| 2040 Building | DeadHawg base 148..151 and upper 152..155. |
| 2061 Goodie | DeadHawg 145..147 plus BadGuys indicator/effect children; breaks into item/loot paths. |
| 2062 Scrub | DeadHawg 264..282; replaces loaded Tree variants 15..18 during materialization. |

Road, terrain, grate, gate, rail, wall, and scenery details—including exact
serialized fields, builders, collision registration, break/loot transitions,
and destruction-relevant ownership—are kept in the dedicated boneyard/world
document rather than duplicated here.

## 2026-08-27 Teacher cast-release VFX closure

Teacher type `5008` constructs at `0x00502570`, ticks at `0x0050B260`, renders
its four actor frames at `0x0051C710`, and creates the release children at
`0x00505560`. It consumes the game-wide 100 Hz tick rate; there is no 60 Hz
presentation clock.

The timer at Teacher `+0x140` advances by float32 `.075` while below `20`,
choosing frame `0/1` with `Integer(2)` every tick. The 267th cast tick leaves
the timer at approximately `20.025`; the next tick adds one, selects frame `2`,
and emits the release once through the `+0x174` latch. The 80th one-unit update
crosses 100 and selects frame `3`. The timer resets after it exceeds `600`, for
an exact 847-tick cycle and first release at cycle tick 268.

Release membership is finite:

| Child | Native construction | Tick/render/blend |
| --- | --- | --- |
| core | `Anim_Fade`, BadGuys 15, scale `(6,4)`, alpha `1`, loss `.1` | fixed scale; source-over through `0x00455A20`; ten visible age states |
| flare | `Anim_Fade`, BadGuys 82, scale `1+Float(.1)`, alpha `1`, loss `.0075` | fixed scale; source-over; 134 visible age states |
| column | `Anim_Fade` wrapped by `ZAnimLit`, BadGuys 81, alpha `2`, loss `.04`; wrapper radius `1`, intensity `2`, intensity delta `-.04` | fixed scale; source-over; renderer clamps alpha to one; float32 recurrence leaves 51 visible age states; provider `0x005E48E0` submits intensity `min(alpha,1)` at the child root |
| animated release | `Anim_SpriteArray` wrapped by `ZAnim`, BadGuys `1823..1833`, scale `2-Float(.5)`, frame step `.75*(1+Float(.2))`, alpha `1`, alpha delta `-.02*(1+the same Float(.2))`, `Integer(2)==1` X mirror | additive only through `0x0045D6E0`; retires at the 11-frame boundary |

All four children share the native cast origin at Teacher-local `(-38,15)`
after the recovered position offsets. The core/flare/column are not screen
blend, do not scale over life, and do not fade in. The sprite array alone is
additive. This supersedes the Website's normalized piecewise/screen composite.

They are not one parent composite. Constructor `0x00505560` registers the
flare through the pre-world `Region+0x278` animation manager, the core through
the post-world `Region+0x22C` manager, and the column then animated release
through `0x0063E5B0 -> Region+0x8B70`. Courtyard render proves the physical
order at `0x0051FD14..0x0051FD33`: pre-world manager, shared world-queue flush
`0x0068C480`, then post-world manager. The two shared-world children use root
Y `teacher.y+15`; column precedes the additive array on equal-bucket insertion.
Nesting all four beneath Teacher Y changes both physical-layer ownership and
occlusion against actors in the intervening depth buckets.

The column's `ZAnimLit` identity does not produce visible fixed-Courtyard
lighting. Fresh xrefs prove light-target reset `0x0057D4E0`, restore
`0x0057D5E0`, composite `0x0057D670`, and manager initialization `0x0057DF20`
each have exactly one caller: Arena render/create `0x0046EC80/0x00470A90`.
Teacher still registers the shared wrapper in the Region provider array, but
no fixed-region renderer submits or composites that array. A web Courtyard
must therefore retain the column sprite and omit an invented radial light.

## Asset-mod boundaries

- Fixed rooms are native scene compositions. Replacing their atlas records is
  viable when the record ABI is preserved; adding a new room or layer requires
  loader-owned indirection or native logic, not another PNG in the directory.
- A named interior actor is a compiled class. Its art can be replaced in place,
  but a new class name cannot be introduced through a boneyard.
- `NPCRecipe` is the stock data-driven actor seam, bounded by `GameNPC`'s four
  presentation modes, native body arrays, and compiled state machine.
- A serialized Fence is a recipe for a graph of derived render/collision
  objects. Installation and multiplayer activation must occur before region
  load/materialization.
- Loose world textures and fixed atlas records have different identities and
  replacement rules. A manifest must preserve that distinction.
- Removal requires native teardown: actor manager membership, collision and
  spatial handles, derived children, audio loops, and bundle references cannot
  be retired by dropping a pointer or deleting a disk file.

## Closure result

The construction, class, update, render, art-range, collision, derived-child,
and teardown contracts for this subsystem are closed. The instruction-level
trace reduced the former fixed-room residual list to proved dormant records;
the source/recipe-to-`GameNPC` field transfer and failure cleanup are exact;
Fence materialization and endpoint deduplication are exact; and the ambient
mix is now correctly attributed to global wrappers serviced by Region
lifecycle. The isolated stock run separately exercised Create, Courtyard,
Arena, enemy-wave, loot, and GameOver transitions without touching the other
agent's process; see [native-live-validation.md](native-live-validation.md).
