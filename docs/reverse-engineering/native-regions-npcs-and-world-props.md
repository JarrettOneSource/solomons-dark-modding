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
| Library | 12, 25..28 |
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
| 5013 Librarian | `0x00502C10` | `0x0050A4C0` | `0x0051E0E0` | Library 29..32 |
| 5016 Dowser | `0x00502C80` | `0x0050A4C0` | `0x0051E1F0` | Library 21..24 |
| 5017 Memorator | `0x00502D90` | `0x00513090` | `0x0051E270` | Memoratorium 2, 6, 7, 28..75 |
| 5022 Annalist2 | `0x00503000` | `0x005061E0` | `0x0051EAF0` | Memoratorium 11..13 |
| 5023 ArchChancellorDesk | `0x00502BA0` | `0x0050A4C0` | `0x005060A0` | Office 3 |
| 5024 ArchChancellorStanding | `0x00502B20` | `0x0050A4C0` | `0x0051DDC0` | College 51..53 |

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
| 2001 Tree | DeadHawg 228..242, 243..263, and 264..282; layered canopy/trunk/foreground with sway and collision. |
| 2009 Monument | DeadHawg 156..176. |
| 2029 Gravestone | DeadHawg base 97..113 and independent overlay 88..96. |
| 2040 Building | DeadHawg base 148..151 and upper 152..155. |
| 2061 Goodie | DeadHawg 145..147 plus BadGuys indicator/effect children; breaks into item/loot paths. |
| 2062 Scrub | DeadHawg 264..282; replaces loaded Tree variants 15..18 during materialization. |

Road, terrain, grate, gate, rail, wall, and scenery details—including exact
serialized fields, builders, collision registration, break/loot transitions,
and destruction-relevant ownership—are kept in the dedicated boneyard/world
document rather than duplicated here.

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
