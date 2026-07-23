# Solomon Dark Boneyard authoring format

This document extends `boneyard-system.md` from container structure to the
payloads required by an authoring tool. The container grammar, 13-section Arena
envelope, 14-section RegionLayout envelope, and polymorphic manager framing are
not repeated here.

All addresses are image-base virtual addresses in the analyzed retail
`SolomonDark.exe`:

```text
image base  0x00400000
sha256      03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3
```

## Encoding and coordinate conventions

- All integer and floating-point fields are little-endian.
- `bool` is one serialized byte. The loader treats any nonzero value as true.
  `tutorial.boneyard` contains a true value encoded as `2`, so lossless tools
  must preserve the source byte when the Boolean is not edited.
- A native `String` is `u32 byte_count_including_NUL`, UTF-8-compatible bytes,
  and one terminal NUL byte.
- World coordinates are pixels. The origin is at the upper left, positive X is
  right, and positive Y is down.
- Angles are degrees. Positive angles appear clockwise on screen because the Y
  axis points down.
- Object positions are native world reference points, not image upper-left
  corners. Each class renderer applies its own atlas registration.
- Arena bounds are a camera and playfield rectangle, not a hard placement clip.

## Lossless authoring contract

Every semantic record also retains the complete encoded SyncChunk or chunk
subtree as base64 `raw`. Unknown fields and child chunks remain attached to
that raw record. A serializer follows these rules:

1. An unchanged record produces the original bytes.
2. A decoded authorable record may replace only its known fields while
   retaining unknown fields and children.
3. An undecoded or preserve-only record requires `raw` and is emitted without
   reinterpretation.
4. New records use canonical defaults listed below.
5. The source file remains available as `meta.raw.file`; unknown Arena and
   RegionLayout sections are copied from it.

RegionLayout section 0 has a framing trap. Every placeable below has one type
ID in the manager payload but three direct object chunks:

```text
Puppet common A
Puppet common B
concrete subclass payload
```

Thus section 0 `directChildren == 3 * object_count` for the five decoded
classes. The three chunks are one object, not three objects.

## Common placeable payloads

The common call chain is rooted at `Puppet::Sync` `0x00622DC0`. The runtime
field offsets below are evidence labels only. The serialized offsets are the
authoring ABI.

### Common chunk A

Stock chunk length is 41 bytes.

| Serialized offset | Type | Runtime field | Meaning and canonical value |
| ---: | --- | ---: | --- |
| `0x00` | `float2` | `+0x18` | `position`, world pixels |
| `0x08` | `float2` | `+0x20` | secondary motion/state vector, `{0,0}` for static authored objects |
| `0x10` | `f32` | `+0x28` | base lifetime/state scalar, `90000.0` in authored static records |
| `0x14` | `f32` | `+0x2C` | state scalar, `0.0` |
| `0x18` | `f32` | `+0x30` | collision/reference radius; class defaults below |
| `0x1C` | `u32` | `+0x38` | state value, `0` |
| `0x20` | `bool` | `+0x44` | state flag, false |
| `0x21` | `u32` | `+0x40` | state value, `0` |
| `0x25` | `u32` | `+0x3C` | common flags, `16` |

Canonical radii are Tree `8.0`, Monument `1.0`, Gravestone `0.01`, Building
`1.0`, and Goodie `20.0`. Stock Gravestones also contain `1.0`; either value is
accepted by the retail loader.

### Common chunk B

The stock static form is 101 bytes. The nested manager at `0x55` can add child
chunks, but it is empty in authored stock scenery.

| Serialized offset | Type | Runtime field | Meaning and canonical value |
| ---: | --- | ---: | --- |
| `0x00` | `u8` | `+0x5C` | state byte, `0` |
| `0x01` | `u16` | `+0x5E` | state value, `0` |
| `0x03` | `u32` | `+0x14` | category/collision flags; `4`, or `8196` for Goodie |
| `0x07` | `bool` | `+0x68` | state flag, false |
| `0x08` | `f32[6]` | `+0x6C..+0x80` | common state `{0,1,1,0,1,0}` |
| `0x20` | `rect4` | `+0x84` | common color/scale state `{1,1,1,1}` |
| `0x30` | `bool` | `+0x94` | state flag, false |
| `0x31` | `f32` | `+0xA0` | draw/sort Y adjustment; `-50.0` for Building, otherwise `0.0` |
| `0x35` | `f32` | `+0xCC` | state scalar, `1.0` in canonical records |
| `0x39` | `bool` | `+0xD4` | state flag, true |
| `0x3A` | `bool` | `+0xD5` | state flag, false |
| `0x3B` | `bool` | `+0xF8` | state flag, false |
| `0x3C` | `bool` | `+0xF9` | state flag, true |
| `0x3D` | `u32` | `+0xFC` | state value, `1000` |
| `0x41` | `f32` | `+0x120` | state scalar, `1.0` |
| `0x45` | `rect4` | `+0x124` | common color/scale state `{1,1,1,1}` |
| `0x55` | object manager | `+0x104` | smart-action list; canonical count `0` |
| `0x59` | `u32` | `+0x11C` | state value, `0` |
| `0x5D` | `u32` | `+0x138` | state value, `0` |
| `0x61` | `u32` | `+0x134` | state value, `0` |

The six floats and rectangles are common Puppet state, not proved editor
rotation, scale, or flip controls. The five placeable subclass serializers do
not contain rotation, scale, flip, or UID fields. Authoring UIs must not expose
those unsupported transforms as if the retail loader serialized them.

## Placeable subclass payloads

### Tree 2001

Constructor `0x005E46D0`, Sync `0x005E0050`.

| Offset | Type | Semantic field | Native art |
| ---: | --- | --- | --- |
| `0x00` | `u16` | `variant` | main DeadHawg `264 + variant` |
| `0x02` | `u16` | `secondaryVariant` | overlay/foreground DeadHawg `243 + secondaryVariant` |
| `0x04` | `bool` | `secondaryVisible` | enables the supported secondary layer |

Render and bounds evidence is at `0x00608480`, `0x00608830`, and
`0x00608AB0`. The auxiliary/reference bank is DeadHawg 228 through 242. Main
variants 0 through 18 map to DeadHawg 264 through 282. Loaded Tree variants 15
through 18 are replaced by runtime `Scrub` 2062 objects in post-load
materialization `0x006531B0`; the stored file record remains Tree 2001.

### Monument 2009

Constructor `0x005E0DB0`, Sync `0x005E0E20`.

| Offset | Type | Semantic field | Native art |
| ---: | --- | --- | --- |
| `0x00` | `u16` | `variant` | DeadHawg `156 + variant`, valid compiled range 0 through 20 |

Render evidence is at `0x0060E210` and `0x0060E280`.

### Gravestone 2029

Constructor `0x005E5C30`, Sync `0x005E0F60`.

| Offset | Type | Semantic field | Native art |
| ---: | --- | --- | --- |
| `0x00` | `u16` | `variant` | base DeadHawg `97 + variant`, valid range 0 through 16 |
| `0x02` | `u16` | `overlayVariant` | overlay DeadHawg `88 + overlayVariant`, valid range 0 through 8 |
| `0x04` | `float4` | `tint` | RGBA multiplier applied to the composed object |

Render evidence is at `0x0060F0F0`, `0x0060F1F0`, and `0x0060F260`.

### Building 2040

Constructor `0x005F2C30`, Sync `0x005E0E20`.

| Offset | Type | Semantic field | Native art |
| ---: | --- | --- | --- |
| `0x00` | `u16` | `variant` | base `148 + variant`, upper layer `152 + variant`, valid range 0 through 3 |

Render evidence is at `0x0060E940`, `0x0060EC50`, and `0x0060EDC0`.

### Goodie 2061

Constructor `0x005E3D60`, Sync `0x005E3DD0`.

| Offset | Type | Semantic field | Meaning |
| ---: | --- | --- | --- |
| `0x00` | `u16` | `subtype` | Goodie/reward subtype |
| `0x02` | `u8` | `phase` | visual break phase |
| `0x03` | `bool` | `active` | break sequence active |
| `0x04` | `u32` | `timer` | break sequence timer |
| `0x08` | `u32` | `rewardSeed` | deterministic reward selection seed |

The visible selector is `phase + 2 * subtype`, resolved as DeadHawg
`145 + selector` by `0x0061F070` and `0x0061F180`. The compiled visible range
is 145 through 147. A safe newly placed Goodie uses subtype 0, phase 0,
inactive state, timer 0, and a chosen reward seed. The staged break sequence is
advanced by `0x0061F4C0`.

## Roads, fences, and terrain

### Road 3004

Constructor `0x00645470`, Sync `0x0063EAA0`, record length 69 bytes.

| Offset | Type | Semantic field | Meaning |
| ---: | --- | --- | --- |
| `0x00` | `float2` | `points[0]` | start point, world pixels |
| `0x08` | `float2` | `points[1]` | end point, world pixels |
| `0x10` | `u32` | `uid` | Road identity |
| `0x14` | `u32` | `previousUid` | linked Road UID, or `0xFFFFFFFF` |
| `0x18` | `u32` | `nextUid` | linked Road UID, or `0xFFFFFFFF` |
| `0x1C` | `float2` | `quad[0]` | start plus normal edge |
| `0x24` | `float2` | `quad[1]` | start minus normal edge |
| `0x2C` | `float2` | `quad[2]` | end plus normal edge |
| `0x34` | `float2` | `quad[3]` | end minus normal edge |
| `0x3C` | `u8` | `style` | loose road texture selector |
| `0x3D` | `f32` | `startWidthScale` | start width multiplier |
| `0x41` | `f32` | `endWidthScale` | end width multiplier |

For a new isolated segment, compute a unit normal to the center line and use a
55-pixel half-width multiplied by the endpoint scale. Nonpositive scales are
normalized to one by native setup. All non-sentinel `previousUid` and
`nextUid` values in the corpus resolve to Road UIDs.

| Style | Texture |
| ---: | --- |
| 0 | `road.png` |
| 1 | `road2.png` |
| 2 | `road3.png` |
| 3 | `road4.png` |
| 4 | `road5.png` |

The texture order is established by initializer `0x005BBD90`; selection and
mesh submission are at `0x00640750`. Geometry rebuild is `0x0064C1F0`.

### Fence 3005

Constructor `0x006407B0`, Sync `0x0063EB70`, record length 29 bytes. A Fence
is a serialized specification. Post-load materializer `0x0064AC90` creates the
visible and collidable objects.

| Offset | Type | Semantic field | Meaning |
| ---: | --- | --- | --- |
| `0x00` | `float2` | `points[0]` | start point, world pixels |
| `0x08` | `float2` | `points[1]` | end point, world pixels |
| `0x10` | `u32` | `uid` | Fence identity |
| `0x14` | `u32` | `startPostVariant` | optional Fencepost selector 0 through 6, or `0xFFFFFFFF` |
| `0x18` | `u32` | `endPostVariant` | optional Fencepost selector 0 through 6, or `0xFFFFFFFF` |
| `0x1C` | `u8` | `segmentCode` | derived segment class selector |

`style` remains a semantic-model alias for `segmentCode` because the editor
Polyline model already uses that property.

| Segment code | Materialized result |
| ---: | --- |
| 0 | one intact FenceGrate 3007 |
| 1 | two FenceGrate_Broken 3011 halves |
| 2 | two hinged Gate 3012 leaves |
| 3 | one generated Wall 3013; no endpoint Fenceposts |
| 4 | one FenceGrate_Rails 3014 section |

Except for code 3, endpoint Fenceposts 3006 are also emitted. Optional post
variants select DeadHawg 36 through 42 in the normal bank.

#### Fencepost 3006

Constructor `0x005E1E20`, Sync `0x005E1EA0`, record length 6 bytes. Stock
Fence managers do not store Fenceposts directly; they are derived after read.

| Offset | Type | Field | Native art |
| ---: | --- | --- | --- |
| `0x00` | `u32` | `variant` | bank-relative selector |
| `0x04` | `u16` | `bank` | 0 selects `36 + variant`; nonzero selects `320 + variant` |

Render and bounds evidence is at `0x00612CF0` and `0x00612DC0`.

#### FenceGrate 3007

Constructor `0x005E7FB0`, Sync `0x005E2080`, record length 124 bytes. Stock
Fence managers do not store these directly.

| Offset | Type | Field |
| ---: | --- | --- |
| `0x00` | `float2` | source start |
| `0x08` | `float2` | source end |
| `0x10` | `float2` | shortened working start |
| `0x18` | `float2` | shortened working end |
| `0x20` | `u32` | repeat count |
| `0x24` | `float2[9]` | step, corner, UV, and control vectors |
| `0x6C` | `rect4` | derived bounds |

Builder `0x005E8100` derives this payload from source posts. Renderer
`0x005E1EF0` uses loose `fencegrate.png`. Authoring a Fence 3005 and allowing
the retail materializer to derive this record is safer than emitting a direct
FenceGrate.

### Terrain 3009

Constructor `0x00646A80`, Sync `0x00651720`. The payload is variable length.

```text
u32 style
u32 reserved
u32 pointCount
float2 points[pointCount]
u32 uid
u32 profileCount
f32 profileSamples[profileCount]
f32 sideSign
```

`reserved` is `0xCDCDCDCD` throughout the authored stock corpus and is not a
proved selector. `profileSamples` are width/profile multipliers consumed by
the generated mesh; `profileCount` is independent of `pointCount`. Stock
records include 8 points with 9 samples and 13 points with 18 samples.
`sideSign` is normally `-1.0` or `1.0`; zero normalizes to one.

| Style | Builder | Loose texture |
| ---: | ---: | --- |
| 0 | `0x0064FA90` | `river.png` |
| 1 | `0x0064F0F0` | `rise.png` |

Post-load geometry rebuild is `0x006534B0`; render is `0x0064EDA0`.

## RegionLayout section 11 static sprites

`RegionLayout::Sync` `0x00653660` reads a `u32` count followed by fixed
25-byte records. Arena render evidence is `0x00470EE0`; bounds and spatial
registration are rebuilt through `0x00587CF0` and `0x00588040`.

| Offset | Type | Semantic field | Meaning |
| ---: | --- | --- | --- |
| `0x00` | `u32` | `atlasEntry` | compact type, valid compiled range 0 through 30 |
| `0x04` | `float2` | `pos` | world position in pixels |
| `0x0C` | `f32` | `rotationDeg`, alias `s0` | rotation in degrees |
| `0x10` | `f32` | `scale`, alias `s1` | uniform scale |
| `0x14` | `f32` | `alpha`, alias `s2` | alpha multiplier |
| `0x18` | `u8` | `flags` | low two bits defined below |

The serialized `atlasEntry` is local to this compact table:

```text
DeadHawg global record = 114 + atlasEntry
```

It is not a global DeadHawg record number. Semantic parsers expose
`deadHawgEntry` as the computed global alias.

| Flag | Effect |
| ---: | --- |
| `0x01` | multiply X scale by `0.8` |
| `0x02` | multiply RGB by `0.5` |
| `0xFC` | ignored by the retail render path |

There is no serialized depth bias, flip bit, or arbitrary tint field in this
record. Rotation, uniform scale, alpha, X compression, and half-bright tint
are the complete proved controls. `sandbox/play.boneyard` contains garbage in
ignored high flag bits, so lossless tools retain all eight bits.

| Compact types | DeadHawg | Visual classification |
| --- | --- | --- |
| 0..6 | 114..120 | leaf carpets, leaf clusters, and soil shadow |
| 7..8 | 121..122 | dark ground patches |
| 9..12 | 123..126 | small paving stones |
| 13..18 | 127..132 | pebble and stone scatters |
| 19..20 | 133..134 | broken twig or lattice variants |
| 21..24 | 135..138 | large irregular rocks |
| 25..29 | 139..143 | opaque shadow or mask silhouettes with special update behavior |
| 30 | 144 | exposed dead-root or stump cluster |

Safe new-record defaults are rotation `0.0`, scale `1.0`, alpha `1.0`, and
flags `0`.

## Arena section 0

Let `S` be the first byte after the native level-name String.

| Offset from S | Encoding | Semantic field | Load behavior |
| ---: | --- | --- | --- |
| `+0` | `u8` | unknown flag 0 | read and discarded |
| `+1` | `u8` | unknown flag 1 | read and discarded |
| `+2` | `u8` | `arenaRuleMode` | stored at Arena `+0x9029`; enum meaning remains unknown |
| `+3` | `u8` | unknown flag 3 | read and discarded |
| `+4` | `u8` | unknown flag 4 | read and discarded |
| `+5` | `u8` | `sessionFlag` | copied to session state `+0x1C28`; exact meaning remains unknown |
| `+6` | `bool[512]` | compatibility block | read and discarded by `0x0046DC60` |
| `+518` | `u8` | `environmentMode` | stored at Arena `+0x8F20`; values 0..2 select environment/effect behavior |
| `+519` | `float4` | `bounds` | `{left, top, right, bottom}` camera/playfield rectangle in world pixels |
| `+535` | optional `bool` | save-path trailer | written true by `0x0046D7B0`; loader ignores it |

Arena load is `0x0046DC60`; create/save is `0x0046D7B0`. Render/effect uses of
`environmentMode` are at `0x00470EE0` and `0x00468E50`. The generated
`play.boneyard` header uses environment mode 2 and includes the optional final
Boolean. Shipped levels and the flat fixture omit that trailer.

The six leading bytes must still be retained as `header.flags` because only
two have partial semantic names. Semantic aliases `arenaRuleMode` and
`sessionFlag` address bytes 2 and 5.

## RegionLayout sections 2 and 10

Section 2 is exactly 12 bytes in the corpus:

```text
float2 playerSpawn
f32 playerSpawnFacingDeg
```

Arena load `0x0046DC60` copies the tuple into all four player spawn slots.
Coordinates are world pixels and facing is in degrees. Section 10 is one byte,
`layoutFlag`. Every corpus value is zero. No consumer semantics were proved,
so authoring tools preserve it and use zero for fixture-derived new files.

## Recipes

### MonsterRecipe 6001

Constructor `0x006400C0`, Sync `0x0063E890`. Strings make absolute serialized
offsets variable. The sequence below is exact. Runtime offsets are from the
constructed recipe/config object and anchor the field names.

| Order | Encoding | Semantic field | Runtime offset |
| ---: | --- | --- | ---: |
| 1 | `u32` | `enemyType` | `+0x4C` |
| 2 | `String` | `name` | `+0x14` |
| 3 | `u32` | `uid` | `+0x50` |
| 4 | `f32` | `maxHp` | `+0x58` |
| 5 | `f32` | `primaryDamage` | `+0x5C` |
| 6 | `f32` | `chaseSpeed` | `+0x6C` |
| 7 | `f32` | `moveSpeedScale` | `+0x74` |
| 8 | `u32` | `variantMode` | `+0x78` |
| 9 | `u32` | `projectileMode` | `+0x7C` |
| 10 | `u32` | `auraMode` | `+0xBC` |
| 11 | `u8` | `headgearMode` | `+0x80` |
| 12 | `u8` | `unknown81` | `+0x81` |
| 13 | `u8` | `unknown82` | `+0x82` |
| 14 | `u8` | `randomVariant` | `+0x83` |
| 15 | `String` | `archetype` | `+0x30` |
| 16 | `bool` | `hasLinkedUid` | `+0xC1` |
| 17 | `u32` | `linkedUid` | `+0xC4` |
| 18 | `u32` | `behaviorCount` | `+0x84` |
| 19 | `u32` | `behaviorMin` | `+0x88` |
| 20 | `u32` | `behaviorMax` | `+0x8C` |
| 21 | `bool` | `flanking` | `+0xB8` |
| 22 | `u8` | `pathfindingMode` | `+0xB9` |
| 23 | `u8` | `dropOrbs` | `+0xCC` |
| 24 | `u8` | `dropPowerups` | `+0xCD` |
| 25 | `u8` | `dropItems` | `+0xCE` |
| 26 | `u8` | `dropSpecificItems` | `+0xD0` |
| 27 | `u8` | `dropGold` | `+0xCF` |
| 28 | `u8` | `dropPotions` | `+0xD1` |
| 29 | `u8` | `specialSpawnMode` | `+0x54` |
| 30 | `f32` | `attackSpeed` | `+0x70` |
| 31 | `f32` | `xpBonus` | `+0xD4` |
| 32 | `f32` | `secondaryDamage` | `+0x60` |
| 33 | `bool` | `shield` | `+0x94` |
| 34 | `bool` | `shieldOthers` | `+0x95` |
| 35 | `bool` | `unknown96` | `+0x96` |
| 36 | `bool` | `burning` | `+0x97` |
| 37 | `f32` | `tertiaryDamage` | `+0x64` |
| 38 | `f32` | `extraDamage` | `+0x68` |
| 39 | `u32` | `behaviorTimer` | `+0x90` |
| 40 | `rect4` | `rect98` | `+0x98` |
| 41 | `rect4` | `rectA8` | `+0xA8` |
| 42 | `u8` | `castMode` | `+0xC0` |

When `hasLinkedUid` is true, relink `0x0064BC40` resolves `linkedUid` and
stores the live pointer at `+0xC8`. Preserve the original true byte when it is
noncanonical. The Python and TypeScript implementations can edit and re-emit
this payload, but they do not invent gameplay-safe combinations of the
type-specific modes.

### UIDGroup 6002

Sync `0x0064A130`.

```text
String name
u32 uid
u32 memberCount
u32 memberUids[memberCount]
u32 field58
u32 field5C
u32 field60
u32 field34
```

Relink `0x0064BC40` resolves every `memberUids` entry into a parallel pointer
list. The semantic implementations can edit and re-emit UIDGroup records.

### Preserve-only recipes

| Type | Sync | Support level |
| ---: | ---: | --- |
| ItemRecipe 6003 | `0x00570D90` | raw subtree preserved |
| NPCRecipe 6004 | `0x0063EBD0` | raw subtree preserved; three optional UID links are relinked natively |
| ItemSet 6005 | `0x0042E260` | no subclass payload in this executable; raw chunk preserved |

ItemRecipe serializes IDs, three Strings, an embedded polymorphic list,
selectors, flags, and two rectangles. NPCRecipe serializes IDs, Strings,
flags, arrays, rectangles, and three optional linked UIDs. These remain
preserve-only because safe semantic authoring requires gameplay constraints
beyond byte order.

## TimeLine 6006 transplant

TimeLine Sync is `0x00646F80`, TimeLineEvent 6007 Sync is `0x00652040`, and
CodeLine Sync is `0x00683C10`. Full trigger bytecode is outside this format
layer.

The pinned donor is:

```text
Mod Loader/tests/fixtures/boneyards/flat_multiplayer_test.boneyard
sha256 7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d
```

Its default graph has these exact properties:

| Property | Value |
| --- | --- |
| TimeLine name | `Survival Time line` |
| TimeLine UID | 36679 |
| enabled byte | false |
| events | 571, all type 6007 |
| event UIDs | contiguous 36684 through 37254 |
| TriggerControl IDs in the donor | 36680 through 36683; it also references 36679 |
| event first-array UID links | 45, all resolving inside the donor graph |
| CodeLine type-5 UID operands | 0 |
| TimeLine manager subtree | 7,662 chunks including the manager section |

TimeLineEvent X/Y values are editor graph coordinates used for event ordering,
not world positions. They require no translation when world bounds or spawn
position changes.

The safe new-file recipe is:

1. Clone the entire pinned fixture envelope.
2. Change only the Arena name and explicitly authored semantic fields.
3. Retain RegionLayout TriggerControl section 1 verbatim.
4. Retain the TimeLine manager in RegionLayout section 13 verbatim.
5. Empty the world-object, recipe, Road, Fence, Terrain, and static-sprite
   collections before adding authored content.
6. Do not renumber UIDs 36679 through 37254. Allocate new authoring UIDs from
   50001 upward, or another collision-free range below `0xFFFFFFFF`.
7. Let retail relink `0x0064BC40` resolve the copied graph after load.

Copying only the TimeLine subtree into an arbitrary envelope is not the proved
operation because the donor TriggerControl owns IDs 36680 through 36683 and
references TimeLine UID 36679. Fixture-envelope cloning preserves that pair.
No recipe UID, placed-object UID, or world coordinate fixup is required by the
default graph.

## Relink behavior

Main relink pass `0x0064BC40` rewrites or populates runtime pointers only. It
does not rewrite the serialized bytes on disk.

| Serialized data | Relink result |
| --- | --- |
| UIDGroup `memberUids` | parallel member pointer list |
| MonsterRecipe `linkedUid` when enabled | pointer at recipe `+0xC8` |
| NPCRecipe optional linked UIDs | three runtime pointers |
| TimeLineEvent UID arrays | event/object pointers and event ordering |
| CodeLine operand type 5 | serialized UID to runtime pointer |

Placeable common/subclass payloads have no UID. Road, Fence, and Terrain UIDs
are not rewritten by this main pass. Road neighbor repair and owner/geometry
setup occur in their post-load paths.

## Corpus truth and bounds checks

| File | Stored placeables by class | Roads | Fences | Static sprites | Terrain |
| --- | --- | ---: | ---: | ---: | ---: |
| `story0.boneyard` | Tree 60, Monument 6, Gravestone 50 | 61 | 21 | 133 | 12 |
| `story1.boneyard` | Tree 100, Monument 12, Gravestone 117, Building 1 | 48 | 34 | 193 | 7 |
| `survival.boneyard` | none | 0 | 0 | 0 | 0 |
| `tutorial.boneyard` | Tree 26, Monument 1, Gravestone 64, Building 1 | 53 | 28 | 90 | 4 |
| `sandbox/play.boneyard` | Tree 105, Gravestone 299, Building 1, Goodie 3 | 79 | 18 | 341 | 0 |
| flat fixture | none | 0 | 0 | 0 | 0 |
| `New Boneyard 1.boneyard` | none | 0 | 0 | 0 | 0 |

Required position sanity output:

```text
story0.boneyard objects=116 inside=108 outside=8 bounds=(0.000000,0.000000)..(1664.899414,2663.000000)
  Tree (1672.899414, 265.000000)
  Tree (1722.899414, 1333.871948)
  Tree (-103.100464, 1886.330078)
  Tree (1497.576538, 2737.674316)
  Tree (-61.402039, 2759.294922)
  Tree (370.267029, 2807.298828)
  Tree (689.513306, 2841.000000)
  Tree (1086.513306, 2844.000000)
survival.boneyard objects=0 inside=0 outside=0 bounds=(0.000000,0.000000)..(2048.000000,2048.000000)
```

For `story0`, 2 of 122 Road endpoints, 4 of 42 Fence endpoints, 8 of 93
Terrain points, and 3 of 133 static-sprite positions are also outside the
header rectangle. This confirms that `bounds` is not a placement validity
test. `tutorial.boneyard` similarly stores player spawn Y `2070.0703125`
outside its bottom bound `2053.0`.

## File truth versus existing editor/tool assumptions

- A structural report's section 0 `directChildren` counts SyncChunks. It is
  three times the semantic object count for the decoded placeables.
- Static-sprite `atlasEntry` is local 0 through 30. Treating it as a global
  DeadHawg index selects the wrong art by 114 records.
- The current website draft places every DeadHawg palette entry as a section
  11 record. Only global records 114 through 144 have that compact encoding.
- The current website draft initializes `s0`, `s1`, and `s2` to zero. Because
  they are rotation, scale, and alpha, this makes a newly authored static
  sprite scale zero and fully transparent. Correct defaults are 0, 1, and 1.
- The current canvas path does not apply section 11 rotation, scale, alpha, or
  flags and does not draw Terrain meshes. Its picture is therefore not a
  semantic rendering of the file even when record counts are correct.
- Parsed native objects currently need their decoded DeadHawg mappings attached
  to browser sprite assets. Without that integration they appear as generic
  fallback rectangles.
- Runtime materialization replaces stored Tree variants 15 through 18 with
  Scrub 2062 and expands each Fence specification into derived objects. A live
  object-list screenshot is not a one-to-one dump of stored section 0 or 6.
- `tutorial.boneyard` legitimately has no TimeLine manager. A parser that
  assumes every playable file has one adds content that is not present.
- Ignored high bits in generated static-sprite flags are file data, not extra
  flip or tint controls. Preserve them but render only bits 0 and 1.

The semantic parser reports stored file records. Runtime-only derived objects
may be presented as a separate materialized preview, but must not replace file
truth in the editable model.

## Authoring checklist

1. Start from the pinned flat fixture, not an empty SyncBuffer.
2. Preserve the exact Arena and RegionLayout section counts and ordering.
3. Use the three-chunk common template for each new placeable.
4. Use unique UIDs for Road, Fence, Terrain, MonsterRecipe, and UIDGroup.
5. Use `0xFFFFFFFF` for absent Road links and absent Fencepost variants.
6. Use local compact type 0 through 30 for section 11, not a global atlas ID.
7. Use static-sprite defaults rotation 0, scale 1, alpha 1, flags 0.
8. Preserve TriggerControl and the default TimeLine donor together.
9. Preserve every unknown or preserve-only record as raw base64.
10. Run the structural inspector and byte-identical roundtrip checks before
    staging the file.
