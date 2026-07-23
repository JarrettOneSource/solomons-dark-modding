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

`0x006388B0` directly creates these layout records:

| Object | Construction path in generator |
| --- | --- |
| Road | direct factory calls near `0x006395F8`, `0x0063ABAC`, `0x0063ACB4` |
| Goodie | direct factory call near `0x0063A065` |
| Gravestone | direct factory call near `0x0063A27D` |
| Building | direct factory call near `0x0063A5C4` |
| Fence | direct factory call near `0x0063D36A` |
| Tree | helper `0x0062CB00` |

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

Placement tests at `0x006470E0`, `0x00647720`, and `0x00647B00` reject
terrain conflicts, road conflicts, and intersections with Goodie, Gravestone,
Tree, and other occupied geometry. The generator separately checks existing
Tree 2001 objects and can delete an overlapping candidate.

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
Its tick tests nearby actors and updates sway at `+0x14C/+0x150` for variants
0 through 5. The renderer composes the main, overlay, and foreground groups;
the overlay path is conditional and only applies to the supported variants.

Monument and Building share the simple short-selector serializer at
`0x005E0E20`. Gravestone serializes main selector `+0x140`, overlay selector
`+0x142`, and color/tint rectangle `+0x144`; base and overlay are independently
rendered. Scrub serializes sprite selector `+0x140`, two sway/orientation
floats at `+0x144/+0x148`, and a flag at `+0x14C`.

Fencepost serializes a 32-bit selector at `+0x140` and short style at `+0x144`.
Style zero addresses DeadHawg 36..42. A nonzero style addresses 320..347; style
one normalizes the selector modulo seven during its alternate render/bounds
path.

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

FenceGrate_Broken inherits that storage, changes the type to 3011, and adds a
serialized side flag at `+0x1C4` (`0x005E38E0`). Builder `0x005EC6E0`
constructs the selected broken half relative to its endpoint post; setup
`0x005ECD30` registers its collision. Renderer `0x005E38C0` uses DeadHawg
record 3.

### Gates

Gate inherits FenceGrate, changes the type to 3012, and serializes the side
flag plus hinge/end vectors, movement vector, and scalar motion state through
`0x005E3910`. Builder `0x005F73C0` selects a hinge from the side flag, derives
the leaf's rest segment from its endpoint posts, and initializes randomized
motion parameters. `0x005ED4D0` builds/registers the moving collision line;
`0x005ECDF0` creates its spatial/collision handle.

Tick `0x005ED5F0` integrates angular/leaf velocity, tests the proposed segment
against the world, rolls movement back and damps/reverses velocity on a hit,
rebuilds collision state, and rate-limits an interaction sound to at least 250
ticks. Gate is therefore dynamic collidable scenery, not a two-frame prop.
Renderer `0x005ECE40` composes DeadHawg records 7 and 8 around the moving
segment.

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
