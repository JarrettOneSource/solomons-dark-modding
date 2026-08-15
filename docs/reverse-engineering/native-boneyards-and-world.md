# Native boneyards, procedural world construction, and scenery

## Scope and current result

This document recovers the retail `.boneyard` byte grammar, the complete
top-level `RegionLayout` schema, the load/regenerate/materialize chain, static
scenery classes, roads, terrain, fences, compact decorations, recipes,
triggers, and timelines. It follows world records through art selection,
collision construction, update behavior, derived-object ownership, and
destruction-relevant state.

The native boneyard and outdoor-scenery pass is complete. The byte grammar,
materialization graph, compact-art selectors, collision ownership, reward
edge cases, and retail SyncBuffer configuration paths have all been closed by
static analysis and the isolated runtime evidence in
[`native-live-validation.md`](native-live-validation.md). Fixed interiors and
NPCs are mapped in
[`native-regions-npcs-and-world-props.md`](native-regions-npcs-and-world-props.md),
bosses/portals in [`native-enemies.md`](native-enemies.md), and items plus
ground pickups in
[`native-items-equipment-and-loot.md`](native-items-equipment-and-loot.md).
No website/mod-download behavior was implemented during this work.

All addresses refer to the analyzed retail `SolomonDark.exe` with SHA-256:

```text
03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3
```

Machine-readable evidence is checked in as
[`native-boneyard-catalog.json`](native-boneyard-catalog.json). It is generated
by [`build_native_boneyard_catalog.py`](../../tools/build_native_boneyard_catalog.py)
on top of the independent recursive parser in
[`inspect_native_boneyard.py`](../../tools/inspect_native_boneyard.py).

## SyncBuffer container grammar

A `.boneyard` is a recursive `SyncBuffer`. There is no magic signature,
version word, central directory, alignment padding, or trailing checksum in
the stock files.

An anonymous chunk node is encoded as:

```text
u32 little-endian payload_size
u8[payload_size] payload
u32 little-endian anonymous_child_count
anonymous children, recursively and in order
```

A complete `SyncBuffer` is encoded as:

```text
root anonymous chunk node
u32 little-endian named_child_count
for each named child:
    u32 byte_length_including_NUL
    NUL-terminated name bytes
    recursive SyncBuffer
```

The native implementation contains a dormant repeating-key XOR transform.
`SyncBuffer` construction leaves the embedded key string at `+0x04` empty,
sets transform byte `+0x20` to zero, leaves companion byte `+0x21` at one, and
sets mode byte `+0x22` to zero. Read path `0x004243C0` only calls transform
helper `0x004221E0` when the key has nonzero length; the write path has the
corresponding conditional transform. All fifteen executable call sites that
construct a `SyncBuffer` were audited: none assigns the key or changes the
transform byte, and nested buffers only inherit/copy the parent mode byte.
Consequently, XOR is a latent library capability, not a format variant used or
enabled by any retail game/editor path. Every retail and saved-editor boneyard
cataloged here stores plain bytes. The checked-in parser intentionally
describes and validates that observed on-disk form; it does not silently guess
an XOR key.

The apparent global `+0x20` write at `0x00424661` is not a SyncBuffer option
write: disassembly shows it zero-initializing a newly allocated `0x5C`-byte
anonymous chunk node inside `0x004245B0`. It therefore does not contradict the
constructor-call-site audit.

### Native serializer functions

| Address | Recovered role |
| ---: | --- |
| `0x00423F70` | `SyncBuffer` constructor |
| `0x004243C0` | open/read mode; mode byte at `+0x22` becomes zero |
| `0x004242D0` | open/write mode; mode byte at `+0x22` becomes one |
| `0x004248F0` | commit the completed buffer |
| `0x004247B0` | begin anonymous chunk |
| `0x00424860` | end anonymous chunk |
| `0x00424DA0` | byte field |
| `0x00424E30` | 32-bit field/list count |
| `0x00424F60` | boolean field |
| `0x00425210` | scalar/float field |
| `0x004252C0` | rectangle field |
| `0x00425130` | string field |
| `0x00424BE0` | recursively write an anonymous node |
| `0x004235E0`, `0x00424CA0` | recursively read anonymous nodes |
| `0x00424A60` | write a complete `SyncBuffer` |
| `0x004245B0` | read a complete `SyncBuffer` |
| `0x004227A0`, `0x00422370` | write/read the length-prefixed NUL string |

`BeginChunk` and `EndChunk` are semantic boundaries, not byte markers. The
writer accumulates a node tree, then recursively emits sizes, payloads, and
children. The reader reconstructs that tree before individual object
serializers consume their fields.

### Cataloged files

All seven samples parse exactly to end-of-file. All contain one `SyncBuffer`
and zero named child buffers.

| Source | Bytes | SHA-256 | Nodes | Payload bytes | Max depth |
| --- | ---: | --- | ---: | ---: | ---: |
| `data/levels/story0.boneyard` | 40,565 | `d596b4915140f5faa23fd1286e3d622c6189ecb00b9667f5e7b3444a84b8322b` | 879 | 33,529 | 9 |
| `data/levels/story1.boneyard` | 212,160 | `5876a0130f43a4b63aa22ab9c482d16912240dfbe773b20fd01f3d48e0cb1cda` | 9,015 | 140,036 | 9 |
| `data/levels/survival.boneyard` | 3,059 | `fe2e01b0ab62f644c3e5bf53f71df3a41968b95c8e22fa44c1d1250ba08cdb5b` | 73 | 2,471 | 9 |
| `data/levels/tutorial.boneyard` | 33,220 | `97802f2ca45d9bc6f90a497e7c12a55926298161e191fa70eee5e666b90106ed` | 676 | 27,808 | 9 |
| `sandbox/play.boneyard` | 252,690 | `bd3c38468481b7337b1e7382e5503cc214356906571763a68188b23e821e73fb` | 9,704 | 175,054 | 9 |
| `New Boneyard 1.boneyard` | 154,858 | `8ae9cd4d371f926b7bf24b05d2a1b1a2a521d797e3f925f3ed9447e8bcff3828` | 8,061 | 90,366 | 9 |
| multiplayer flat fixture | 148,413 | `7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d` | 7,721 | 86,641 | 9 |

To inspect a file or a particular subtree:

```bash
python3 tools/inspect_native_boneyard.py path/to/file.boneyard --json
python3 tools/inspect_native_boneyard.py path/to/file.boneyard \
  --node 0.12.0 --max-depth 1 --preview-bytes 80
```

The parser rejects truncated fields, invalid NUL strings, nonexistent node
paths, negative child indexes, and any trailing bytes it did not consume.

## Arena load, regeneration, and save chain

`Arena_Create` at `0x0046EA90` selects the source boneyard. Normal custom play
uses `sandbox\\play.boneyard`; editor test runs can use
`sandbox\\testrun.boneyard`. `0x0046DC60` is the structured Arena loader.

When global `DAT_00B3BEDC` equals one, the loader can call `0x0046D7B0` to:

1. construct a temporary Arena;
2. invoke the procedural generator at `0x006388B0`;
3. serialize and commit the generated arena through `SyncBuffer`; and
4. destroy the temporary Arena.

`0x006388B0` is also reached from editor preview/test paths and recursively
builds generation subregions. The executable contains a patch site at
`0x0063D78F` that prevents a null candidate dereference in this generator.

Arena state is serialized into ordered outer chunks named by their traversal
paths (`0.0`, `0.1`, and so on). RegionLayout is Arena child 12. The
RegionLayout object itself is its first child, so its exact node path in every
cataloged file is `0.12.0`.

## Arena and editor base-field rendering

There is no loose arena-ground image. The base fill is produced by the
renderer, and the positive render path is now recovered rather than inferred
only from the absence of a file:

1. `Arena::Render` at `0x0046EC80` passes RGB `(0, 0, 0)` to `0x0057D4E0`.
   That helper calls renderer clear wrapper `0x0041D840` with alpha `1.0`.
2. `Bonedit::Render` at `0x004D5F40` calls `0x0041D840` directly with RGBA
   `(0, 0, 0, 1)`.
3. `0x0041D840` reaches `0x00440D40`, which packs the four channels and calls
   Direct3D device vtable slot `+0xAC` (`IDirect3DDevice9::Clear`). The field
   therefore starts as an opaque black render-target clear, not decoded image
   pixels.
4. Both renderers then walk the visible world rectangle in 200-by-200 logical
   steps and call sprite draw helper `0x004142E0`. `Bonedit` and a normal
   Arena use absolute Sprite object `0x00B2F368`, which is DeadHawg record 21.
   Arena field modes 1 and 2 instead use `0x00B2F2A4`, DeadHawg record 20.

The two fixed descriptors are adjacent 0xC4-byte Sprite objects in the loaded
DeadHawg bundle object:

| DeadHawg record | Static Sprite address | Atlas crop | Logical canvas | Native use |
| ---: | ---: | ---: | ---: | --- |
| 20 | `0x00B2F2A4` | 102x77 | 102x77 | Arena field modes 1/2 |
| 21 | `0x00B2F368` | 43x35 | 200x200 | `Bonedit` and Arena mode 0 |

The Arena constructor `0x00464EE0` initializes mode byte `+0x8F20` to zero.
Temporary procedural generation path `0x0046D7B0` chooses a value in 0..2 and
copies it to the generated Arena, while script dispatcher `0x00689750` can
write the byte explicitly. Instructions `0x0046F528`, `0x0046F651`, and
`0x004D6223` contain the absolute Sprite addresses. This compiler-folded
addressing is an important exception to the singleton-relative consumer scan:
DeadHawg record 21 must not be read as dormant merely because its destination
has no mapped consumer in `native-asset-object-map.json`.

`paintbkg` is unrelated to this path. Function `0x005BED10` uses it while
capturing portraits and writes `Portraits\\portrait%d.raw`; no Arena or
`Bonedit` ground renderer consumes it.

The website editor's `arena-ground.webp` is consequently a derived reference
asset, not a recovered loose game file. Website commit `1060924` samples the
composed retail editor field, mirror-tiles it to remove seams, and stores an
84,158-byte WebP (SHA-256
`dabc48e7af0220283889647f57cde6442aecc79629555ce9104815ebadbdb070`).
Those are literally captured retail render pixels and are appropriate for the
browser editor's calm survey-scale approximation. They should not be listed
as a native disk asset or treated as evidence that `paintbkg` is ground art.

### Arena light field and Lantern source

The opaque black clear is also the base of a separate Region light field; it
is not sufficient to draw the ground and then place one translucent black
rectangle over the finished scene. Initializer `0x0057DF20` creates the
manager's offscreen render target at `+0x4C` and records the light-quality
scale at `+0xC4`. Each `Arena::Render` frame resets the manager at
`Arena + 0x8C44` through `0x0057D4E0`. That reset binds the offscreen target,
clears it to ambient RGB `(0,0,0)`, installs the target transform, and clears
the 0x1C-byte source-record count at `+0x108`. Arena then collects providers
from the list at `Arena +0x8D80` (`count +0x8D8C`) and invokes each provider's
vtable slot `+0x30`. `0x0057D5E0` restores the main target after collection.

Generic submitter `0x0057FE40` has two inseparable products. It draws
DeadHawg record `18` (`DeadHawg +0xE00`) into the offscreen target at the
query-space point with scale `radius` and presentation alpha `intensity`.
That stock asset is the `336 x 305` crop of a `336 x 336` logical field, with
registration `(168,153)` and a white, alpha-graded ellipse. The same call
records source point `+0x00/+0x04`, query-space point `+0x08/+0x0C`, radius
`+0x10`, intensity `+0x14`, and shadow flag `+0x18` for analytic queries.
Flag-zero submissions first pass the existing-source containment check at
`0x0057E2F0`; a fully covered source may therefore produce neither raster nor
record when Multiple Shadows is off.

Compositor `0x0057D670` draws the completed target over a view-sized quad. It
selects renderer blend state `2`; `0x004208A0` resolves that state to
`source=ZERO` and `destination=SRCCOLOR`, so the operation is the exact
framebuffer multiply `out = destination * lightMap`. With Complex Lighting on
(`0x00B3BCA8 != 0`), `Arena::Render` calls it at `0x0046FAFF` after the direct
base/underlay/compact lanes but before shared world-queue flush `0x0068C480`
at `0x0046FDAF`. Main actors are subsequently drawn with their analytic local
scalar, and late proxy/foreground lanes remain after the multiply. With
Complex Lighting off, the same composite moves to `0x00470107`, after the
shared queue, while per-object scalar sampling is forced to one. The latter is
the retail low-cost flattened-lighting branch, not evidence that the light-map
composite is optional.

`0x0057FE40` records one source as source point `+0x00/+0x04`, query-space
point `+0x08/+0x0C`, radius `+0x10`, intensity `+0x14`, and shadow flag
`+0x18`. The ordinary scalar query at `0x0057F980` takes the maximum source
contribution, not their sum. For source radius `r`, intensity `i`, and query
delta `(dx,dy)`, its exact unoccluded falloff is:

```text
d2 = (dx / r)^2 + (dy / (0.85 * r))^2

d2 <  75^2: scalar = i
d2 >= 145^2: scalar = 0
otherwise: scalar = i * (1 - (d2 - 75^2) / (145^2 - 75^2))
```

The constants are retail doubles/floats at `0x00785858 == 0.85`,
`0x00797218/20 == 5625 == 75^2`, `0x00797224 == 21025 == 145^2`, and
`0x00797210 == 15400`. The common Puppet dispatcher stores this scalar at
object `+0xCC` and multiplies it into the object's requested tint before its
main painter. Base ground and explicit pre-main underlays do not acquire an
object scalar, but they are already present when the Region light texture is
multiplied in the Complex Lighting branch. Late proxy/foreground art retains
its caller-owned color because it is submitted afterward. A single multiply
over the completed scene is therefore also wrong: it would move the boundary
past the main queue and late proxies.

The ordinary player provider at `0x005299A0` submits a point 15 world units
along the player's heading with `radius=2.6`, `intensity=1`, and flag `1` when
its drive-state predicate permits it. The Boneyard Lantern is runtime type
5010 (constructor `0x005E1120`, static vtable `0x0079C854`). Its tick
`0x005FF010` enrolls the object in the Arena provider list, and slot-`+0x30`
provider `0x005E6220` submits the Lantern root with `radius=0.65`, intensity
`0.55 + RandomFloat(0.2)`, and the retail Multiple Shadows flag
`DAT_00B3BCAA`. Thus its per-render intensity lies in `[0.55,0.75)` and is
presentation RNG, not authored layout state.

The Lantern is one member of a shared source protocol. The retail executable
has 36 direct references to generic submitter `0x0057FE40`: one Arena replay
of stored source records and 35 class-owned provider functions. The provider
families recovered from vtable slot `+0x30` are:

| Family | Native owners |
| --- | --- |
| actors and world residents | Skeleton, SkeletonArcher, SkeletonMage, Imp/GoodImp/GreenImp, Wraith, DemonSkull, Demon, DireFaculty, Heartmonger, Coffin, Portal, Lantern, GameNPC, and `ZAnimLit` |
| missiles and transient effects | Magic/Fire/Frost/Guided/Skull/Ball-Lightning missiles, Fireball, Boulder/EBoulder/Hailstones, Ember/EvilEmber, Arrow/Firebolt/DarkFireball/Silk, Meteor, GreenFire, Fire/Goodguy/MovingFire/DireFire, GroundSpark, Shockwave/FreezeWave, Leviathan, EtherBolt/UnholySpit, Golem, MagicTrap, Bonus, DemonBomb, StormCloud/AcidRain, RainOfBones, EtherDrain, Comet, and OffscreenMagic |

The ordinary player and its 180-tick level-up variation use the sibling
submitter `0x00580130` from provider `0x005299A0`, so they are additional light
owners even though they do not appear among those 36 direct generic calls.

That provider census is not the whole producer census. `Region` owns a
separate `Array<Region::MiscLight>` at `+0x8DF0` (backing store `+0x8DF4`,
capacity `+0x8DF8`, count `+0x8E00`). `Region::Tick` at `0x0063EFC0` clears its
count at `0x0063F078`; effect/action updates then append the same 0x1C-byte
source shape through `0x0044F4B0`. `Arena::Render` replays those records through
`0x0057FE40` after the provider-list pass. There are 13 direct append calls in
ten retail functions:

| Misc-light producer | Append callsites |
| --- | --- |
| `Action_Demonskull_MouthBeam` (`0x0044FFE0`) | `0x00451576` |
| `Anim_UltraBanish` (`0x00460AB0`) | `0x00460C44` |
| three `ZAnimSplit` paths (`0x00531640`, `0x00531F00`, `0x005328D0`) | `0x00531D61`, `0x00531EBE`, `0x00532734`, `0x00532891`, `0x005331B5`, `0x00533312` |
| `MagicCircle` (`0x006006E0`) | `0x00600834` |
| `EyeLaser` (`0x006054F0`) | `0x00605742` |
| `Mod_ElectricBurn` (`0x00628F10`) | `0x00628FE8` |
| `Mod_Burn` (`0x00629A40`) | `0x00629CAE` |
| `Mod_EtherBurn` (`0x00629CD0`) | `0x00629ED8` |

Both generic submitters apply the source flag before rasterization. Flag zero
calls containment test `0x0057E2F0`; an existing source suppresses the new one
only when its intensity is at least as high and its 145-scaled circle strictly
contains the new circle:

```text
existing.intensity >= candidate.intensity
distance(existing, candidate)^2
  < ((existing.radius - candidate.radius) * 145)^2
```

Equality at the circle boundary is not containment. A nonzero flag bypasses
this suppression. The ordinary player passes one; the Lantern passes the
`Multiple Shadows` setting, whose retail default is off. Provider order and
the fixed-tick misc-light append order are therefore part of a future
spell/enemy adapter's presentation contract.

This expanded inventory defines source adapters for future combat parity; it
does not make dormant enemy, modifier, or spell systems part of an entry-only
Boneyard renderer. `Portal` here is the hostile type-5021 Imp spawner, not a
Hub room-transition trigger. Likewise, the compiled Courtyard Teacher update
and cast functions are absent from both producer censuses; its currently
implemented pose/rune/audio cycle does not submit a Region light.

An isolated live Arena run independently validated the static chain. The
runtime Lantern at `0x1AF7B090` had rebased vtable `0x00B2C854`; its slot
`+0x30` resolved to rebased `0x00976220`. Traces armed at original addresses
`0x005FF010` and `0x005E6220` observed 199 Lantern ticks and 57 light submits
over the same sampling window, both with `ECX=0x1AF7B090`. A player source
record sampled from the live manager held the recovered 15-unit anchor,
`radius=2.6`, `intensity=1`, and flag `1`. Sampling the provider list between
reset and collection can legitimately observe zero; the function traces prove
that such a sample does not mean the Lantern stopped owning its light.

### Complex directional object shadows

The source record's `+0x18` flag is not merely a light-list containment hint.
With `Game.ComplexLighting` (`0x00B3BCA8`) enabled, complex query
`0x0057F0E0` also requires that flag before it appends directional shadow work
for a world object. `Game.ComplexShadows` (`0x00B3BCA9`) then controls whether
the object painters emit that work. Both settings default to true in the
retail initializer and in the inspected clean stock profile. The separate
`Game.MultipleShadows` setting (`0x00B3BCAA`) defaults to false. Consequently
the ordinary player source always participates because provider `0x005299A0`
submits flag `1`; the default Lantern usually illuminates without casting this
directional shadow because it submits the Multiple Shadows byte. The visible
orange staff orb is therefore supporting presentation evidence for the source,
not its owner: the native contract is the player-owned point 15 world units
along heading.

For every eligible source inside the same elliptical 145-unit falloff,
`0x0057F0E0` appends this 0x24-byte record to the object list at `+0xAC`:

| Offset | Meaning |
| ---: | --- |
| `+0x00/+0x04` | unit direction from source to object |
| `+0x08/+0x0C` | source world position |
| `+0x10` | base opacity factor, initialized to `1` |
| `+0x14` | light scalar sampled one world unit behind the object along that direction |
| `+0x18` | normalized elliptical distance squared, `d2 / 145^2` |
| `+0x1C` | projection distance, `(145 - RandomFloat()) * source.radius` |
| `+0x20` | source radius |

When more than one flagged source reaches the same object, the query compares
their direction vectors pairwise. Each record's base factor is attenuated by
`max(dot(directionA, directionB), other.distanceFraction)`. This is the actual
Multiple Shadows interaction; summing darkness or choosing only the nearest
source is not equivalent.

Shared geometry helper `0x00655970` consumes the class's explicit object-local
outline. For each outline edge it computes the edge midpoint and normal,
rejects edges that do not face the source, and projects both endpoints radially
away from the source by the record's fixed projection distance. It submits one
black two-triangle quad per accepted edge. The two object-edge vertices use
the record's base factor as alpha. The two projected vertices use
`((1 - behindScalar) * (1 - distanceFraction))^3`, yielding the native soft
tail through ordinary per-vertex interpolation. This is directional silhouette
geometry, not a blurred ellipse beneath the object.

The following recovered painters establish the relevant ownership and the
adjacent object family:

| Caster | Painter | Outline source |
| --- | ---: | --- |
| Tree | `0x00608AB0` | variant table at `0x0081B910` |
| Gravestone | `0x0060F260` | variant table at `0x0081BE50` |
| Fencepost | `0x00612DC0` | 14-entry style/frame table at `0x0081B0B8` |
| FenceGrate | `0x00600ED0` | sibling custom projected-mesh path |

Tree's outline source is now closed rather than approximate. Static initializer
`0x005BF6A0` constructs fifteen `0x34`-byte shapes at `0x0081B910`, one for
each materialized Tree main variant `0..14`. `Tree::RenderBoundsAndShadow`
`0x00608AB0` reads the main selector at `+0x140`, computes
`0x0081B910 + selector * 0x34` at `0x00608C85..0x00608C95`, and passes that
shape to `0x00655970` for every record in the object's `+0xAC` shadow list.
The same painter selects `DeadHawg[228 + mainVariant]` through the manager bank
at `+0x1A90/+0x1A94`; this resolves the previously open selector relation for
DeadHawg 228..242. The dynamic complex-shadow branch never reads secondary
selector `+0x142`, secondary-enable byte `+0x144`, or current Tree alpha
`+0x150` when selecting its silhouette.

The initializer appends each vertex through `0x006554B0`, applies the listed
common translation through `0x006554F0`, and closes the edge/normal arrays
through `0x00655570`. The resulting object-local `(x,y)` vertices are exact:

```text
 0: (-2,12)   (18,9)    (17,-8)   (-5,-4)
 1: (3,14)    (14,-3)   (-4,-13)  (-19,3)
 2: (1,9)     (15,-2)   (7,-13)   (-15,-3)
 3: (7,7)     (27,1)    (24,-16)  (4,-11)
 4: (5,10)    (12,-8)   (-3,-17)  (-20,-1)
 5: (-20,8)   (-12,-2)  (7,6)     (0,17)
 6: (-19.5,12.5) (-19.5,-12.5) (19.5,-12.5) (19.5,12.5)
 7: (-6,10)   (-6,-1)   (7,-1)    (8,10)
 8: (-6,10)   (-6,-1)   (7,-1)    (8,10)
 9: (-1.5,1.5) (-1.5,-1.5) (1.5,-1.5) (1.5,1.5)
10: (-1.5,1.5) (-1.5,-1.5) (1.5,-1.5) (1.5,1.5)
11: (0.5,2.5) (-2.5,-0.5) (0.5,-3.5) (3.5,-0.5)
12: (0.5,2.5) (-2.5,-0.5) (0.5,-3.5) (3.5,-0.5)
13: (-1.5,1.5) (-1.5,-1.5) (1.5,-1.5) (1.5,1.5)
14: (-1.5,1.5) (-1.5,-1.5) (1.5,-1.5) (1.5,1.5)
```

Stored Tree variants `15..18` cannot index past this table in an ordinary
loaded Arena: post-load materialization `0x006531B0` replaces them with Scrub
2062 objects, whose painter owns a separate shadow path. With Complex Shadows
disabled, `0x00608AB0` follows its fallback sprite branch and may include the
enabled secondary art for main variants below six; that fallback does not make
the secondary canopy part of the complex projected silhouette.

Monument, Building, Goodie, Scrub, Rails, Wall, and other scenery/fence
painters also reference the Complex Shadows global. This adjacency means the
web seam belongs to the shared Region/world renderer, not to Tree, Gravestone,
or Fence special cases. Native outlines remain class-authored data. Tree must
use the recovered table above; classes whose tables have not yet been extracted
may retain an explicit native-alpha approximation while preserving source
ownership, facing-edge selection, radial projection, opacity endpoints,
painter ordering, and the settings/flag distinction above.

## RegionLayout schema

RegionLayout is embedded in Arena/Region state at `+0x8510`. Its constructor
is `0x006405A0`, vtable is `0x0079F2A4`, and serializer is `0x00653660`.
The serializer always produces exactly fourteen ordered children:

| Index | Runtime field | Encoding | Compiled object type |
| ---: | --- | --- | --- |
| 0 | scenery list `+0x2B4` | polymorphic list | Tree, Monument, Gravestone, Building, Goodie, and other compiled scenery |
| 1 | `TriggerControl` | nested object chunks | fixed class at RegionLayout `+0x18` |
| 2 | origin `+0x3E4` and scalar `+0x3EC` | two floats plus one float | not polymorphic |
| 3 | monster recipes `+0x404` | polymorphic list | `MonsterRecipe` 6001 / `0x1771` |
| 4 | UID groups `+0x450` | polymorphic list | `UIDGroup` 6002 / `0x1772` |
| 5 | roads `+0x300` | polymorphic list | `Road` 3004 / `0x0BBC` |
| 6 | fence specifications `+0x34C` | polymorphic list | `Fence` 3005 / `0x0BBD` |
| 7 | item recipes `+0x580` | polymorphic list | `ItemRecipe` 6003 / `0x1773` |
| 8 | item sets `+0x49C` | polymorphic list | `ItemSet` 6005 / `0x1775` |
| 9 | NPC recipes `+0x4E8` | polymorphic list | `NPCRecipe` 6004 / `0x1774` |
| 10 | layout flag `+0x65C` | one byte | not polymorphic |
| 11 | compact decorations `+0x5CC` | count plus packed 25-byte records | fixed records, no factory type |
| 12 | terrain `+0x398` | polymorphic list | `Terrain` 3009 / `0x0BC1` |
| 13 | timelines `+0x534` | polymorphic list | `TimeLine` 6006 / `0x1776` |

The generic polymorphic serializer at `0x00425580` writes a count followed by
all 32-bit type IDs into the parent payload. It then invokes each object's
virtual serializer, which emits child chunks. On read, the Game factory at
virtual slot `+0x134` constructs each type, object byte `+0x04` is cleared,
virtual slot `+0x14` consumes its fields, and the object is inserted into the
owning list. A scenery object emits base, scenery, and subclass chunks, so its
serialized child-chunk count is three times the object count; that is not
three scenery objects.

### Stock RegionLayout contents

| File | Stored scenery | Roads | Fences | Compact | Terrain | Recipe/script highlights |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| story0 | 60 Tree, 6 Monument, 50 Gravestone | 61 | 21 | 133 | 12 | 1 MonsterRecipe; `Skeletons`, 26 timeline events |
| story1 | 100 Tree, 12 Monument, 117 Gravestone, 1 Building | 48 | 34 | 193 | 7 | 2 MonsterRecipe, 2 NPCRecipe; 603 timeline events |
| survival | none | 0 | 0 | 0 | 0 | 6 MonsterRecipe, 6 UIDGroup; empty `MAIN Time line` |
| tutorial | 26 Tree, 1 Monument, 64 Gravestone, 1 Building | 53 | 28 | 90 | 4 | 7 MonsterRecipe, 6 UIDGroup, 1 ItemRecipe; no TimeLine object |
| sandbox/play | 105 Tree, 299 Gravestone, 1 Building, 3 Goodie | 79 | 18 | 341 | 0 | 15 MonsterRecipe; 562 timeline events |
| new editor save | none | 0 | 0 | 0 | 0 | `Survival Time line`, 593 events |
| flat multiplayer fixture | none | 0 | 0 | 0 | 0 | `Survival Time line`, 571 events |

An editor save with no placed scenery is therefore not an empty script file.
Both blank-looking samples carry hundreds of timeline events.

## RegionLayout materialization and ownership

The post-load/materialization pass is `0x006531B0`. Its order matters:

1. convert each stored scenery object's Y coordinate at `+0x1C` to an integer,
   multiply it by 100, store that deterministic materialization key at `+0x10`,
   and call its virtual `+0x48` setup hook;
2. expand every abstract `Fence` record with `0x0064AC90`;
3. assign the RegionLayout owner at scenery `+0x58`;
4. call virtual hooks `+0x44`, `+0x64`, and `+0x04` to finish world,
   collision, and class initialization;
5. install a special callback (`PTR_FUN_007846DC`) for Gravestone overlay
   selector `+0x142 == 8`;
6. replace Tree variants `+0x140` 15 through 18 with a newly constructed
   `Scrub` 2062 at the same position/variant, insert the Scrub, and delete the
   original Tree; and
7. resolve compact-decoration side effects and finish layout indexing through
   `0x00644C00`.

The scenery list owns stored objects and the fence-derived runtime objects.
Several classes also register collision/spatial handles after their owner is
assigned. Removing only the serialized Fence record is not equivalent to
retiring its materialized posts, leaves, wall geometry, and collision handles.

## Procedural generation

The contiguous fourteen-phase control-flow chart for every instruction in
`0x006388B0` is in
[`boneyard-system.md`](boneyard-system.md#whole-routine-control-flow-map).
That audit covered all 6,165 instructions, all 70 direct call targets, the
recursive reroll, and the returning cleanup path before the per-family findings
below were treated as complete.

`0x006388B0` directly creates these layout records:

| Object | Construction path in generator |
| --- | --- |
| Road | direct factory calls near `0x006395F8`, `0x0063ABAC`, `0x0063ACB4` |
| Goodie | direct factory call near `0x0063A065` |
| Gravestone | direct factory call near `0x0063A27D` |
| Building | direct factory call near `0x0063A5C4` |
| Fence | direct factory call near `0x0063D36A` |
| Tree | helper `0x0062CB00` |

There are exactly seven calls to the general object factory in the routine.
Their pushed IDs account for three Road sites and one each of Goodie,
Gravestone, Building, and Fence. There is no factory call or direct constructor
for Monument `2009` or Terrain `3009`. Working rectangles and lines in the
topology phase are generator scratch geometry, not serialized Terrain records.
All twelve retained stock-generator Boneyards independently have zero Terrain
records and contain no scenery class outside `2001`, `2029`, `2040`, and
`2061`.

The Tree helper constructs type 2001 at a requested position, chooses its
`+0x140/+0x142` variants from generation maps or an explicit override, and
inserts it into RegionLayout scenery. For natural variants 0 through 7 it also
emits compact debris/ground-cover records with randomized position, scale, and
alpha:

| Tree variant | Compact types emitted |
| ---: | --- |
| 0..2 | 0 and 1 |
| 3..5 | 2 and 3 |
| 6 | 6 |
| 7 | 4 and 5 |

Together with the Tree helper, the generator's explicit compact constructors
have this closed output set:

| Generator phase | Compact types | Count/policy |
| --- | --- | --- |
| Tree creation through `0x0062CB00` | `0..6` | Variant-dependent Tree debris, possibly two records per Tree |
| promoted-grave decoration `0x0063BB65..0x0063C4FF` | `7..8` | Directional patches around every selector-8 grave, with a dedicated layout for the reserved nearest site |
| global rock scatter `0x0063E000..0x0063E2E8` | `21..24` | `50..100`, collision accepted; one-in-ten attempts may cluster after the first root |
| environment scatter `0x0063DBCD..0x0063DFFF` | `25..28` | mode `0`: none; mode `1`: `15..35`; mode `2`: `30..70`; excludes Dig-site rectangles |

Compact types `9..20`, `29`, and `30` are valid atlas/serialization values,
but `BoneyardGenerator` has no constructor for them. None occurs in the twelve
retained procedural outputs. They belong to the broader authored-Boneyard
format and must not be added to the random generator merely because the
renderer supports them.

Placement tests at `0x006470E0`, `0x00647720`, and `0x00647B00` reject
terrain conflicts, road conflicts, and intersections with Goodie, Gravestone,
Tree, and other occupied geometry. The generator separately checks existing
Tree 2001 objects and can delete an overlapping candidate.

### Dig-site Gravestone promotion and reservation

The ordinary Gravestone loop does not generate Solomon sites directly. It
constructs type `2029` at `0x0063A27D`, writes the ordinary overlay selector at
`0x0063A35B`, and adds only roots strictly inside the generated layout bounds
inset by `300` on every side to a private candidate list at
`0x0063A3A7..0x0063A3C2`. The inset rectangle is built from
`(bounds.x + 300, bounds.y + 300, bounds.w - 600, bounds.h - 600)` and tested
with strict point-in-rectangle helper `0x00403DA0`.

A later pass promotes a nominal `9..14` of those existing candidates into Dig
sites. At `0x0063B468..0x0063B487`, the generator evaluates
`RandomInt(6) + 5`, stores a separate initial offset of `4`, and continues
until successful promotions have reduced their sum to zero. Each attempt:

1. chooses one candidate uniformly through integer RNG `0x00401170`;
2. skips a grave already using the last overlay-bank selector;
3. obtains that last overlay's native rectangle through `0x0063EDE0`, trims
   it to `x + 10` and `width - 20`, and asks placement owner `0x006470E0`
   whether the site is clear; and
4. on success writes `overlayCount - 1` to Gravestone `+0x142` at
   `0x0063B6CF` and retains the grave in the promoted-site list.

The retail overlay bank has nine entries, so `overlayCount - 1` is selector
`8`. The first 99 failed attempts pass no collision-output list. From attempt
100 onward, a failed test returns the overlapping scenery objects and the
generator removes and destroys them before retrying. The per-site retry count
reaches `200`; its recovery branch may finish short only after at least four
sites have already succeeded. All twelve retained native generator outputs
take the normal path and contain `9..14` selector-8 graves.

The promoted sites are not semantically interchangeable. At
`0x0063B739..0x0063B826`, the generator computes unscaled squared Euclidean
distance from every promoted grave to RegionLayout player spawn
`+0x88F4/+0x88F8`. It retains the first strict minimum. The next scenery pass,
`0x0063BAD0..0x0063BB40`, removes a Tree when that selected root lies inside
the Tree variant's native polygon, using point-in-polygon helper `0x00405160`.
The compact-decoration pass also takes a dedicated branch for this nearest
site at `0x0063BBB1`. Thus the generator reserves and visually clears the same
spawn-nearest site later selected for the opening Solomon encounter; choosing
an arbitrary selector-8 grave can put Solomon at an unreserved site.

Runtime action ownership and the later-wave random-placement exception are in
[`native-solomon-dig-and-wave-director.md`](native-solomon-dig-and-wave-director.md).

## Roads, terrain, and packed decorations

### Road 3004

Road's constructor is `0x00645470`, serializer `0x0063EAA0`, renderer
`0x00640750`, geometry builder `0x0064C1F0`, and destructor `0x006497F0`.
Serialized state includes endpoints at `+0x14/+0x1C`, UID `+0x7C`, style IDs
`+0x84/+0x88`, four control points `+0x3C..+0x54`, texture selector byte
`+0x8C`, and scales `+0x24/+0x28` (nonpositive values normalize to one).

Post-load assigns the owner at `+0x80` and calls `0x0064C1F0(0, 1)`. That
builds eighteen `Vertex2D` records plus indices. Rendering chooses one of the
five loose road textures through the selector and submits the generated mesh
with `0x0041DA00`.

### Terrain 3009

Terrain's constructor is `0x00646A80`, serializer `0x00651720`, renderer
`0x0064EDA0`, builders `0x0064F0F0/0x0064FA90`, and destructor
`0x00649CF0`. It serializes IDs at `+0xC0/+0xC4`, a point array at
`+0x18/+0x1C`, scalar array at `+0x28/+0x2C`, ID `+0xCC`, and scale `+0xBC`.
Zero scalar entries and a zero scale normalize to one.

Post-load stores the owner at `+0xC8` and calls `0x006534B0`, which clears old
geometry and selects one of the two builders from `+0xC0`. The renderer draws
the resulting vertex/index buffers rather than selecting one standalone
sprite.

### Derived river bridges and the wood-footstep predicate

Arena's Region virtual at vtable slot `+0x118` is `0x004679B0`. It does not
classify a point from the visible road or terrain texture. It iterates the
derived bridge list reached at `Arena +0x8B5C` (`RegionLayout +0x64C`), first
tests the strict bounds stored at bridge `+0x10`, and then tests the point
against the bridge quad at `+0x20` as two triangles. The query returns true
only for a point inside one of those exact quads.

RegionLayout rebuild owner `0x00653BF0` clears the bridge storage at
`+0x644/+0x64C/+0x658`, asks `0x00651BF0` for quads only from Terrain style
zero, and tests each Road segment against those river quads with
`0x0063EF20`. Segment-edge intersection helper `0x00410900` supplies the
crossing points. A crossing becomes one 0x60-byte bridge object using exact
DeadHawg record `319`: crop `72 x 135`, logical canvas `200 x 200`, origin
`(0,-0.5)`, local corners `(-36,-67.5)`, `(36,-67.5)`, `(-36,67.5)`, and
`(36,67.5)`, road rotation, scale `(1,0.9,1)`, and the recovered crossing
translation. The center is the midpoint of the two nearest endpoint-directed
intersections, shifted five units along the Road direction; when only one
unique hit exists, the second endpoint is fifteen units along that direction.

`0x00651BF0` does not use the serialized Terrain control polygon directly. It
extracts the central river band from the rebuilt style-zero vertex mesh,
starting after the first paired vertices and stepping six vertices per spline
sample. That mesh is generated by `0x0064FA90` from the Terrain private RNG,
spline sampling, tangents, and randomized bank vertices. A port that labels a
generic Road/Terrain overlap as wood would therefore disagree with stock.

`PlayerActor::Tick` consumes this predicate only after the native movement,
local-player, and 25-tick cadence gates documented in
[`native-audio-events.md`](native-audio-events.md). True selects registry 104
`sounds\\woodstep`; false selects registry 214..215
`sounds\\Step\\step1..2`. The twelve stock-generated files in the Website's
default arena bank all contain zero Terrain records, so every ordinary
footstep in those supported scenes takes the Step1/Step2 branch. The exact
wood branch remains relevant to a future style-zero river scene, but requires
the native derived mesh and bridge list rather than an approximate surface
tag.

### Compact decoration record

The serialized form is exactly 25 bytes:

```text
u32 compact_type
float x
float y
float value_or_rotation
float value_or_scale
float value_or_alpha
u8 flags
```

The runtime record grows to `0x2C` bytes. Bounds at `+0x1C..+0x28` are derived
after loading from DeadHawg compact-decoration records 114 through 144 and
their sprite width/height fields. Arena renderer `0x00470EE0` queries visible
records through `0x00588040`, applies tint/alpha, rotation, scale, and flags,
then renders the selected DeadHawg record. Arena updater `0x00470A90`
specially rebuilds bounds/state for compact types 25 through 29.

Compact type numbers are serialized semantics. The binding is direct:
`DeadHawg record = 114 + compact_type`. The executable does not carry names
for these records, so the descriptions below are visual classifications of the
extracted pixels rather than invented native identifiers. Numeric type and
record remain authoritative.

| Compact type | DeadHawg | Extracted size | Visual classification |
| ---: | ---: | ---: | --- |
| 0 | 114 | 229x215 | broad mixed red/green leaf carpet |
| 1 | 115 | 91x97 | sparse autumn-leaf cluster |
| 2 | 116 | 218x212 | broad green-leaf carpet |
| 3 | 117 | 68x77 | sparse long-leaf cluster |
| 4 | 118 | 233x233 | dense small green-leaf carpet |
| 5 | 119 | 85x85 | large green-leaf cluster |
| 6 | 120 | 260x178 | diffuse dark soil/leaf shadow |
| 7 | 121 | 89x89 | round dark ground patch |
| 8 | 122 | 62x62 | small dark ground patch |
| 9..12 | 123..126 | 28x27, 36x35, 36x33, 32x31 | four small paving-stone variants |
| 13..18 | 127..132 | 22..32 by 21..29 | six pebble/stone-scatter variants |
| 19..20 | 133..134 | 81x70, 80x72 | two crossed broken-twig/lattice variants |
| 21..24 | 135..138 | 64..80 by 56..62 | four large irregular rock variants |
| 25..29 | 139..143 | 56..216 by 49..217 | five irregular opaque shadow/mask silhouettes |
| 30 | 144 | 81x55 | exposed dead-root/stump cluster |

Types 0 through 6 are also proved tree-associated debris by generator
`0x0062CB00`. Arena updater `0x00470A90` gives types 25 through 29 the only
special compact-record update path; this is why their deliberately
featureless mask silhouettes must not be normalized into ordinary scenery.

## Static scenery classes and art selectors

| Type/class | Constructor | Serializer | Update/setup | Render/bounds | Native art |
| --- | ---: | ---: | ---: | ---: | --- |
| 2001 Tree | `0x005E46D0` | `0x005E0050` | `0x005F1A40`, `0x005F1C50` | `0x00608480`, `0x00608830`, `0x00608AB0` | DeadHawg 228..242 bounds/reference, 243..263 overlay/foreground, 264..282 visible trunk/canopy |
| 2009 Monument | `0x005E0DB0` | `0x005E0E20` | `0x005E5BB0` | `0x0060E210`, `0x0060E280` | DeadHawg 156..176 |
| 2029 Gravestone | `0x005E5C30` | `0x005E0F60` | `0x005F2EB0` | `0x0060F0F0`, `0x0060F1F0`, `0x0060F260` | base 97..113; overlay 88..96 |
| 2040 Building | `0x005F2C30` | `0x005E0E20` | `0x005E5BF0` | `0x0060E940`, `0x0060EC50`, `0x0060EDC0` | base 148..151; upper 152..155 |
| 2061 Goodie | `0x005E3D60` | `0x005E3DD0` | `0x005E3E40`, `0x0061F4C0` | `0x0061F070`, `0x0061F180` | DeadHawg array 145..147; BadGuys indicator/effect children |
| 2062 Scrub | `0x005E4040` | `0x005E40F0` | `0x005E40D0` | `0x006200B0`, `0x00620120` | DeadHawg 264..282 |
| 3006 Fencepost | `0x005E1E20` | `0x005E1EA0` | post-load setup | `0x00612CF0`, `0x00612DC0` | DeadHawg 36..42 or 320..347 |

Tree serializes two short selectors at `+0x140/+0x142` and an enable byte at
`+0x144`. Initialization chooses collision rectangles from the main variant.
Its tick tests nearby actors and updates target/current visibility alpha at
`+0x14C/+0x150` for main variants 0 through 5. The renderer composes the main,
secondary foreground, and bounds/shadow groups; the secondary path is
conditional and only applies to the supported variants. The bounds/shadow
painter maps main variants `0..14` directly to auxiliary DeadHawg `228..242`
and exact complex-shadow shapes `0x0081B910 + variant*0x34`; neither mapping
uses the secondary selector. Loaded variants `15..18` become Scrub objects
before this Tree painter can index either 15-entry bank.

Monument and Building share the simple short-selector serializer at
`0x005E0E20`. Gravestone serializes main selector `+0x140`, overlay selector
`+0x142`, and color/tint rectangle `+0x144`; base and overlay are independently
rendered. Scrub serializes sprite selector `+0x140`, two sway/orientation
floats at `+0x144/+0x148`, and a flag at `+0x14C`.

Fencepost serializes a 32-bit selector at `+0x140` and short style at `+0x144`.
Style zero addresses DeadHawg 36..42. A nonzero style addresses 320..347; style
one normalizes the selector modulo seven during its alternate render/bounds
path.

### Tree local occlusion alpha and secondary lighting

Tree constructor `0x005E46D0` initializes scan countdown `+0x148` with
`RandomInteger(25,0)`, target alpha `+0x14C` to `1.0`, and current alpha
`+0x150` to `1.0`. `Tree::Tick 0x005F1C50` first runs the common update, then
returns without the visibility system when secondary byte `+0x144` is false
or main variant `+0x140` exceeds five. Otherwise it performs these operations
in order on the 100 Hz fixed clock:

1. Move current alpha toward target alpha by exactly `0.015`, clamping at the
   target.
2. Decrement the countdown.
3. When the result is below one, reset it to `25`, restore target alpha to
   `1.0`, and scan the Tree's registered spatial cells.
4. Accept an actor only when `(actor+0x14 & 3) != 0` and local/player byte
   `actor+0x5C == 0`. Test that actor's root relative to the Tree against the
   strict secondary bounds and then the exact secondary polygon. Any match
   sets target alpha to `0.4`.

The alpha approach precedes the scan, so a newly detected overlap starts
fading on the following tick. A full `1.0 -> 0.4` transition takes 40 ticks,
or 0.4 seconds. The scan refreshes every 25 ticks and the constructor's
0..24 countdown staggers Trees. This is intentionally viewer-local
presentation: a remote participant is not allowed to fade another client's
Tree.

Setup `0x005F1A40` selects bounds at `0x0081C2F0 + secondaryVariant*0x10`
and polygons at `0x0081C480 + secondaryVariant*0x3C`. Static initializer
`0x005BF6A0` constructs the eight polygons, expands them radially by 75, and
translates variants 0..5 by -375 Y and variants 6..7 by -475 Y. A read-only
float32 dump of the initialized retail process proved that the separate
`(x,y,w,h)` bounds are exactly each expanded polygon's float32 bounding box:

```text
0: (-206.943085,-360.557770,413.162201,388.555267)
1: (-199.163605,-386.493011,392.822845,411.437408)
2: (-201.051453,-385.402252,416.818665,405.374298)
3: (-218.041489,-407.491669,386.139648,530.769165)
4: (-199.769135,-449.740723,410.015289,530.840698)
5: (-219.368698,-372.364441,409.258179,449.605927)
6: (-166.012695,-482.932617,311.304626,526.642273)
7: (-243.751404,-299.276031,439.664734,318.938599)
```

The matching rebased polygon table produced the exact Tree-local vertices
below:

```text
0: (-144.991699,-29.943329) (-0.612213,27.997498)
   (56.565765,24.125244) (168.142761,-46.191010)
   (206.219116,-216.246826) (69.428345,-360.557770)
   (-100.838684,-351.329254) (-206.943085,-220.444397)
1: (34.539063,24.944397) (170.043396,-84.968689)
   (193.659241,-250.134964) (69.607330,-386.493011)
   (-154.267090,-340.797882) (-199.163605,-106.993134)
2: (16.047150,19.972046) (179.940979,-53.378113)
   (215.767212,-244.164093) (105.194061,-385.254395)
   (-90.867462,-385.402252) (-201.051453,-241.984848)
   (-141.134659,-42.068848)
3: (-201.693909,14.099915) (-218.041489,-236.622009)
   (-170.231567,-346.286499) (-55.717346,-407.491669)
   (64.987335,-381.353821) (80.091675,-329.744873)
   (168.098145,-276.497314) (137.144531,60.330048)
   (12.385468,123.277466) (-77.646149,110.349823)
4: (-40.584381,81.099945) (196.159302,-17.644989)
   (210.246155,-236.136841) (126.729889,-403.390472)
   (-50.686035,-449.740723) (-199.769135,-272.130127)
   (-191.674973,2.338562)
5: (83.820404,77.241486) (174.118164,27.862396)
   (189.889465,-185.667053) (125.402710,-358.422302)
   (-55.577576,-372.364441) (-219.368698,-216.946991)
   (-150.751999,70.621979)
6: (59.971069,43.709656) (145.291931,-38.326538)
   (17.297211,-482.735168) (-21.178711,-482.932617)
   (-166.012695,-44.270599) (-92.609528,43.120850)
7: (-143.947876,6.671509) (106.446411,19.662567)
   (195.913330,-154.605316) (123.690857,-299.276031)
   (-151.914612,-293.977936) (-243.751404,-125.898529)
```

The visibility alpha is consumed by both visual halves. Main painter
`0x00608480` receives `+0x150`; secondary painter `0x00608830` also submits
that alpha. The common dispatcher `0x00624B40` samples the analytic Region
lighting scalar at the Tree root and stores it at `+0xCC` for the main pass.
Unlike ordinary late foreground art, `0x00608830` explicitly multiplies
Tree's color scalar `+0xD0` by that stored `+0xCC`, installs the resulting RGB
with current alpha, draws the secondary sprite, and restores white. The Tree
secondary is therefore lit from the same root and faded by the same local
state as the main Tree. Building upper art remains caller-owned; it is not a
precedent for leaving Tree secondary art white.

Evidence is high-confidence instruction/decompiler output for
`0x005E46D0`, `0x005F1A40`, `0x005F1C50`, `0x00608480`, `0x00608830`,
`0x00624B40`, strict bounds helper `0x00403DA0`, polygon helper `0x00405160`,
and retail constants `0.015` and `0.4`, plus the initialized table dump from
the retail executable with SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
The process-global constructor RNG phase is deliberately not claimed
portable; it changes only which 25-tick phase a Tree starts on.

### Shared actor/scenery occlusion and effective Y

These scenery classes do not render into an independent background layer.
`Arena::Render` at `0x0046EC80` gathers main actors (`+0x318/+0x324`), this
scenery population (`+0x87CC/+0x87D8`), and transient actors
(`+0x8B78/+0x8B84`) through queue insertion `0x0068C3B0`. Queue flush
`0x0068C480` invokes vtable slot `+0x0C`; common Puppet dispatcher
`0x00624B40` then calls the object's slot-`+0x1C` main painter. The complete
queue proof and normal-row formula are retained in
[`world-sprite-render-pipeline.md`](../re/world-sprite-render-pipeline.md).

For visible objects, the effective row input is
`trunc(worldY) + trunc(sortBias)`, where world Y is Puppet `+0x1C` and sort
bias is Puppet `+0xA0`. The queue subtracts the local player's truncated Y,
divides by two with truncation toward zero, and paints rows ascending. Same-row
entries retain list-gather order: main actors, then scenery, then transient
actors. Gravestone base, Tree base, Monument, Building base, Goodie, Scrub,
Fencepost, and the non-wall fence-family main painters therefore occlude
actors through this shared queue. Gravestone slot `+0x2C` remains an underlay;
Tree and Building slot `+0x24` art remains a later proxy/foreground pass.
Wall is the exception in this family because its visible mesh is slot
`+0x28`, before the shared main queue.

FenceGrate constructor `0x005E7FB0` writes retail float constant
`0x00787050 == -15.0` to `+0xA0`. Broken grates, Gates, and rails inherit it;
Wall constructor `0x005F88B0` writes the same bias. Fencepost constructor
`0x005E1E20` retains the base `0.0`. Gate rebuild `0x005ED100` sets the
runtime root Y to `max(tip.y, midpoint(hinge, tip).y)`, so a Gate leaf's
effective painter key is that moving root Y minus 15, not its hinge Y. On the
live horizontal gate documented below, both leaf keys are smaller than the
endpoint-post key. The leaves consequently paint first and the posts appear
in front even though materializer `0x0064AC90` created the posts before the
bodies.

This is painter-order occlusion, not depth-buffer testing and not a physical
collision mask. A port may use CSS stacking or multiple canvases, but it must
preserve the shared effective-Y order and the separate underlay, shadow, main,
and foreground lanes.

## Fence specification and derived objects

`Fence` 3005 is only the serialized specification. Constructor
`0x006407B0` and serializer `0x0063EB70` store endpoints `+0x14/+0x1C`, UID
`+0x34`, owner `+0x38`, endpoint/style selectors `+0x3C/+0x40`, and segment
code byte `+0x44`.

Materializer `0x0064AC90` first collects both endpoints of every non-wall
Fence into an `Array<IPoint>` through `0x00428800`. That insertion routine
deduplicates exact `(x, y)` coordinates. It creates one Fencepost 3006 for
each unique coordinate, so an isolated non-wall segment has two posts while
connected segments share their common post. It then converts each Fence into
runtime scenery:

| Fence `+0x44` | Derived class/type | Exact non-post expansion |
| ---: | --- | --- |
| 0 | FenceGrate 3007 | one intact repeating grate |
| 1 | FenceGrate_Broken 3011 | two halves, side flag 0 and 1 |
| 2 | Gate 3012 | two hinged leaves, side flag 0 and 1 |
| 3 | Wall 3013 | one generated Wall plus two `ZFightHelper` objects; no posts |
| 4 | FenceGrate_Rails 3014 | one rail section |

For codes 0, 1, 2, and 4, helper `0x005F43E0` resolves each derived leaf's
endpoints to the nearest already-created posts within the native distance
threshold and stores those post pointers at inherited fields `+0x1AC/+0x1B0`.
The materializer copies the optional Fence selectors, initializes every
derived object, and inserts it into the appropriate RegionLayout owner.

### Intact and broken grates

FenceGrate constructor `0x005E7FB0` initializes type 3007. Serializer
`0x005E2080` writes endpoints, shortened working endpoints, repeat count,
step vector, corner vectors, UV/control vectors, and bounds. Endpoint builder
`0x005E8100` computes the midpoint, shortens the section around posts,
calculates repeat count and spacing, builds the quadrilateral bounds, and
stores the source posts. Collision setup `0x005E8650` registers the segment
after an owner exists. `0x00600ED0` emits repeated textured quad geometry and
`0x005E1EF0` uses the loose `fencegrate` texture loaded by world initializer
`0x005BBD90`.

The intact geometry is exact. Builder `0x005E8100` normalizes the endpoint
vector, moves both working endpoints inward by 12 world units
(`0x007DE9D8`), and places the lower quad edge on those shortened endpoints.
The upper edge is exactly 52 units higher: a 32-unit value at `0x00784CC8`
plus 20 units at `0x007DE920`. The loose 64x64 `fencegrate` image is not
stretched once across the authored segment. Its U span is shortened length
divided by retail constant `53.33333121405716` (`0x0079DB28`), while V spans
the full texture. The related 13.333333-unit step at `0x0079DB30` determines
the generated repeat subdivision. Renderer `0x005E1EF0` draws that textured
quad, then adds two black 3-unit rules: one 9 units below the upper edge and
one 5 units above the lower edge.

Every unique endpoint Fencepost begins with selector zero. After a derived
fence resolves its shared post pointers, materializer `0x0064AC90` overwrites
the start/end post's 32-bit selector at `+0x140` only when the serialized
Fence selector is not `0xFFFFFFFF`. Because connected segments reference the
same post, later source-order overrides win. Stock-generated samples inspected
for this correction store `0xFFFFFFFF` at both ends and therefore retain
DeadHawg record 36, but a parser/projection must preserve explicit selectors
for authored and mod Boneyards rather than dropping them.

FenceGrate_Broken inherits that storage, changes the type to 3011, and adds a
serialized side flag at `+0x1C4` (`0x005E38E0`). Builder `0x005EC6E0`
constructs the selected broken half relative to its endpoint post; setup
`0x005ECD30` registers its collision. Renderer `0x005E38C0` uses DeadHawg
record 3.

### Gates

Gate inherits FenceGrate, changes the type to 3012, and serializes the side
flag, expanded collision endpoints, hinge, live tip, fixed leaf length, and
rest heading through `0x005E3910`. Velocity, damping, live registration handle,
and last-sound tick are transient and are not serialized. Builder `0x005F73C0`
selects a hinge from the side flag, derives the leaf's rest segment from its
endpoint posts, and applies the one-time randomized Y displacement.
`0x005ED4D0` builds/registers the moving collision line; `0x005ECDF0` recovers
its live spatial/collision handle after load.

Tick `0x005ED5F0` advances the Cartesian tip velocity while constraining the
leaf to its fixed length and to 60 degrees from the rest heading, then rebuilds
visual and collision state and rate-limits `GateSqueak`. Gate is therefore
dynamic collidable scenery, not a two-frame prop.

Renderer `0x005ECE40` does **not** plant DeadHawg record 7 at one point. It
passes the full record-7 UV quad and Gate points `+0x16C..+0x188` to custom
textured-quad path `0x00414710 -> 0x0041E990`, so the iron ornament maps over
the current hinge-to-tip leaf. Record 8 remains an ordinary glyph at the upper
edge midpoint plus `(0, 7)`, followed by two three-pixel black rules. The full
field map, call graph, geometry, render lanes, motion state machine,
serialization boundary, lifecycle, evidence ledger, and web-port contract are
charted in
[`native-gate-art-and-lifecycle.md`](native-gate-art-and-lifecycle.md).

### Walls and rails

Wall constructor `0x005F88B0` creates type 3013 with multiple point arrays,
generated vertex data, scalar arrays, index arrays, bounds, and two optional
self-references. Serializer `0x00606770` writes all geometry and arrays and
repairs those self-references after reading. Renderer `0x0061E780` consumes
the generated mesh; collision setup `0x005EEAF0` registers its polygonal
boundary. Wall has no direct fixed DeadHawg sprite selector. The separately
loaded loose `WallTop` image is dormant in this retail executable: world-asset
initializer `0x005BBD90` stores it at owner `+0x31C5F4`, and a full
instruction-level offset scan finds that builder write as the field's only
reference. No Wall method or other stock renderer reads it.

FenceGrate_Rails is type 3014. Serializer `0x005E3F60` writes the inherited
data, side flag, and twelve derived vectors. Builder `0x005F0EC0` produces its
offset rails and collision quadrilateral. Renderer `0x005E3E70` draws
DeadHawg record 23 four times with depth offsets; `0x00607440` handles the
generated line/particle-style geometry path.

### Fence graph teardown

The derived graph is owned by RegionLayout managers, not recursively by the
serialized Fence record. RegionLayout destruction enters `0x0064A1E0` from
deleting destructor `0x0064AC70` and tears down ten embedded ObjectManagers
through `0x00402190`; each manager deletes its owned object list. Fencepost
and FenceGrate destructors route through the shared `Puppet` teardown. Gate,
broken-grate, and rail deleting destructor `0x005A9C40` reaches body
`0x005E1EE0` and then `Puppet` teardown. The two code-3 helpers use the
`ZFightHelper` vtable at `0x0079D224` and the ordinary `Puppet` destructor.

Wall deleting destructor `0x005FB9A0` enters `0x005F8A80`, frees its owned
`Array<float>` at `+0x288/+0x28C`, `Array<RaptPoint>` at `+0x298/+0x29C`,
and `Array<int>` at `+0x2A8/+0x2AC`, then reaches `Puppet` teardown. That base
path invokes world/collision cleanup `0x00482E90` before releasing remaining
arrays and lists. Thus a segment cannot be safely hot-removed by freeing its
Fence specification or one visible leaf: the owner managers must retire the
whole materialized graph so every collision/spatial registration is removed.

## Goodie break sequence and transition into ground loot

Goodie is the first proved bridge between boneyard scenery and the item/loot
system. It serializes short subtype `+0x140`, phase byte `+0x142`, active flag
`+0x143`, timer `+0x144`, and random seed `+0x148`. Initialization assigns the
render/collision reference and chooses a seed in the native random range.

When active, tick `0x0061F4C0` advances an exact staged sequence:

| Timer | Native action |
| ---: | --- |
| 100 | spawn the break flash and twenty particle children; set phase 1 |
| 200 | set phase 2 and play the next break sound |
| 250 | clear active state, construct an `Item_Sack`, select its reward, and materialize or discard it |

The visible DeadHawg selector is `phase + 2 * subtype` into the three-record
array at DeadHawg `+0x1A00`. Before timer 100 an alternating BadGuys indicator
is also drawn while the Goodie is active.

Reward selection uses the stored seed modulo 18. Selectors 0..3 each create
five subtype-0 potions; selectors 4..7 each create six subtype-1 potions;
selectors 8..9 create a small set of level-relative generated items; selector
10 creates one category-4 generated item; selectors 11..12 create three
miscellaneous items using subtype selectors 2..4; selectors 13..16 directly
award a randomized 500/800/1100/1400 currency value; and selector 17 creates
the special multi-potion bundle below.

Selector 17 is statically exact, including a stock allocation bug. Its first
loop allocates four `Item_Potion` objects but overwrites the local pointer on
each iteration without finalizing or inserting the first three. Only the
fourth survives the loop; it is set to subtype 5 and inserted. The branch then
inserts subtypes 0, 1, 4, 2, and 2. The retained six-potion multiset is:

| Potion subtype | Name | Count |
| ---: | --- | ---: |
| 5 | Rejuvenation | 1 |
| 0 | Health | 1 |
| 1 | Mana | 1 |
| 4 | Mind Chug | 1 |
| 2 | Wizard Chug | 2 |

The first three loop allocations are orphaned/leaked; they are not hidden
sack contents and must not be reproduced as retained items by a compatible
parser or content tool.

Each concrete item is finalized through `0x00570C10` and inserted into the
`Item_Sack` through `0x0055FF20`. If the sack has content, Goodie allocates the
ground `Sack` object (type `0x7DD`, constructor `0x005E1460`), stores the
`Item_Sack` pointer at ground Sack `+0x148`, positions it just below the
Goodie, and registers it in the world. An empty sack is destroyed instead.
Pickup collision, exact-pointer inventory transfer, and final Sack destruction
are mapped in
[native-items-equipment-and-loot.md](native-items-equipment-and-loot.md).

## Recipes, triggers, and timelines

These are data objects consumed after the static layout is constructed:

| Class | Type | Serializer | Recovered content |
| --- | ---: | ---: | --- |
| MonsterRecipe | 6001 | `0x0063E890` | UID, name, monster/config IDs, scalar constraints, booleans, and rectangles |
| UIDGroup | 6002 | `0x0064A130` | name, UID, member UID list, and counters |
| ItemRecipe | 6003 | `0x00570D90` | IDs/names, embedded item-data block, selectors, flags, and rectangles; zero ID resolves a default through `0x005B9870` |
| NPCRecipe | 6004 | `0x0063EBD0` | UID, names, IDs, flags, byte arrays, and rectangles |
| ItemSet | 6005 | stub serializer at vtable `+0x14` (`0x0042E260`) | no serialized subclass payload in this retail path |
| TimeLine | 6006 | `0x00646F80` | name, UID, enabled byte, TimeLineEvent list, scalar/ID/flag tail, and a second generic list |
| TimeLineEvent | 6007 | `0x00652040` | UID/type fields, times, arrays of IDs/bytes/floats/strings, flags, and CodeLine list |
| Spawner | 6008 | class-specific serializer | timeline-controlled spawn data |

`TriggerControl` serializer `0x00686400` owns trigger/script structures, and
`CodeLine` serializer `0x00683C10` carries individual script instructions.
The flat fixture contains native `START GAME` and `START WAVE 1` trigger paths
in addition to its 571-event survival timeline. Timeline data schedules and
scripts runtime activity; it should not be described as stored static
scenery.

## Native content boundaries relevant to later mod support

These are recovered constraints, not the website/download implementation:

- The file grammar is open-ended recursively, but object identity is not.
  Polymorphic IDs must exist in the compiled Game factory. A boneyard can
  compose and parameterize compiled classes; stock native code cannot create a
  new class merely because a new numeric ID appears in the file.
- RegionLayout child order is an ABI. Omitting, inserting, or reordering one of
  the fourteen top-level chunks shifts every following serializer.
- Most scenery art is a numeric selector into a fixed compiled atlas
  destination. A boneyard cannot name a new PNG for Tree variant 19. Art mods
  must preserve/replace the expected loose filename or bundle record layout,
  or the loader must add an explicit indirection outside stock behavior.
- Fence records are recipes for derived objects. Deterministic multiplayer
  state must account for the materialized posts, leaves, walls, rails,
  collision geometry, and post-load class fields, not only the 3005 records.
- Generator output depends on native random choices and collision rejection.
  Peers need identical already-materialized content or an identical generation
  seed/state path before play.
- Timeline, recipe, boneyard, Lua, and art files can be independently absent
  from a future mod, but every content component that is present must be
  installed and enabled before the joining peer constructs this world.
- Replacing live scenery requires class destruction and collision/spatial
  unregistration. Clearing a pointer list alone leaks native registrations and
  is not a valid hot-reload mechanism.

## Closure result for this subsystem

The former residuals are closed. Machine-code analysis establishes exact
fence-code expansion, endpoint deduplication, moving Gate collision behavior,
and manager-driven cleanup. Extracted DeadHawg pixels classify every compact
type while retaining its numeric ABI. Full decompilation of selector 17 proves
the six retained potions and three orphaned allocations. Finally, every
SyncBuffer construction path was audited and none enables the latent XOR
facility. The isolated runtime pass independently exercised Arena region 4006
and observed its expected native atlas residency without touching another
agent's process; see
[`native-live-validation.md`](native-live-validation.md).
