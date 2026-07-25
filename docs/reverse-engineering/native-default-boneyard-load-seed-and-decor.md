# Native default Boneyard load, seed, and decor materialization

This document maps the retail run-start path that selects, procedurally
generates, saves, reloads, materializes, updates, and renders the default
Boneyard. It also records the multiplayer seed boundary and every
render-relevant decor family found after the beta.16 visual counter-evidence.

The addresses are image-base virtual addresses for the analyzed
`SolomonDark.exe`:

- image base: `0x00400000`
- file size: `4,723,200` bytes
- SHA-256:
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

The container and RegionLayout grammar remain documented in
[`boneyard-system.md`](boneyard-system.md). This document is the run-start and
multiplayer ownership map.

## Revised result after beta.16 counter-evidence

The framework gives every peer the host's 30-bit run-generation seed and
reapplies it to the retail global RNG immediately before `Arena_Create`. For
the same run, the host and client generate the same serialized Boneyard
layout: Tree positions and variants, roads, Fence specifications, Terrain
inputs, and all compact-decoration records and bounds match in native order.

That does **not** make the rendered world deterministic. Published
`v0.1.0-beta.16` fixed one real source of divergence: seven generator paths
allocated a `0x2C` compact-decoration record and used:

```text
OR byte ptr [ESI+0x18], 0x01
```

The allocator does not clear the record. The instruction establishes the
X-compression bit but preserves process-specific heap data in the half-bright
tint bit and the ignored upper six bits. Two peers can consequently have the
same compact type, position, rotation, scale, and alpha but render it with
different brightness. Tree-adjacent ground cover and dark patches use this
same compact table, which makes an otherwise identical tree region look
different.

The beta.16 class-level correction initializes the complete flags byte to
`0x01` at all seven sites. It is a local native determinism repair at the
shared seeded generation boundary; it does not add or change a network field.

Live visual counter-evidence exposed six additional peer-local presentation
paths outside that old seven-site table:

1. Tree `+0x148/+0x14C/+0x150` sway state is not serialized. The Tree tick
   uses peer-local actor/spatial lists to change the target and current scale.
2. Scrub `+0x134` animation phase is seeded from the process-global RNG,
   incremented by the common scenery tick, omitted from Scrub serialization,
   and consumed by the renderer.
3. Goodie `+0x144` is serialized and conditionally consumed by its renderer,
   but its constructor does not initialize it.
4. `Arena_Render` draws the serialized compact table and then makes two
   process-global RNG decisions that can spawn transient ground effects. Those
   effects do not exist in the compact table or any replicated snapshot.
5. The common Puppet/scenery constructor at `0x006287D0` does not initialize
   `+0xCC`, and the common scenery render dispatcher at `0x00624B40`
   subsequently rewrites it from peer-local visibility and lighting queries.
   Tree's complex-lighting overlay reads that scalar at `0x00608912`, so
   allocator residue or a different local light query can change the Tree
   overlay even when every Tree-specific field matches.
6. `Arena_Render` also draws four Arena marker glyphs in two passes. The tint
   draws at `0x004712BB` and `0x004726E3` consume the process-global floating
   RNG during rendering, outside the compact and scenery tables.

Thus the beta.16 digest proved seeded layout equality but did not cover every
input used to produce pixels. The corrected acceptance boundary is the
native-order render-input tables plus exact matched-camera decor pixels.

## Run-start selection and load path

The default run reaches the generated Arena through this native call chain:

| Address | Recovered role |
| ---: | --- |
| `0x0058E8C0` | Main-menu run selection dispatch. Case 3 sets `DAT_00B3BEDC` to 1, selects `data\levels\survival.boneyard`, and enters the gameplay loader. |
| `0x005BB970` | Constructs Gameplay, stores the selected Boneyard template at Gameplay `+0x1BD8`, and invokes its create/start virtual methods. |
| `0x005CFA80` | Finalizes gameplay startup. Its branch uses Gameplay `+0x1BB4` (test-run mode), Gameplay `+0x1C05`, `DAT_00B3BEDC`, and the selected template. |
| `0x005CDDD0` | `Gameplay_SwitchRegion`; selects region 5 and dispatches creation through the region vtable. |
| `0x0063F460` | Arena enter/start dispatch; invokes the region create method at vtable `+0xB4` or the already-created synchronization path at `+0xE4`. |
| `0x0046EA90` | `Arena_Create`; chooses `play.boneyard` when Gameplay `+0x1BB4` is zero and `testrun.boneyard` otherwise, resolves the path, loads it through `0x0046DC60`, then calls the materialization wrapper `0x00653550`. |

The menu's `survival.boneyard` selection is the Gameplay template. The
procedural run Arena itself is written and read through resolved
`play.boneyard` or `testrun.boneyard`; these are distinct decisions in the
startup chain.

### Procedural create, save, reload

`Arena_Create` calls the structured loader at `0x0046DC60`. When
`DAT_00B3BEDC == 1`, that loader first calls `0x0046D7B0`:

1. choose an Arena environment mode in the range 0 through 2;
2. allocate and construct a temporary `0x9068`-byte Arena;
3. initialize `BoneyardGenerator` state through `0x0062FDF0`;
4. invoke the generator at `0x006388B0`;
5. serialize the temporary Arena and embedded RegionLayout through
   `SyncBuffer`;
6. commit the resolved Boneyard through `0x00424890`; and
7. destroy the temporary Arena.

The enclosing `0x0046DC60` call then reads that file through the normal
structured loader. It constructs native object types, deserializes the
14-section RegionLayout, repairs owners and serialized pointer relationships,
and starts the loaded trigger/timeline systems. `Arena_Create` finally invokes
`0x00653550`, which reaches RegionLayout materialization at `0x006531B0`.

This save/reload cycle matters. Replicating only a final list of visible Tree
coordinates would skip generated roads, fences, recipes, collision,
Trigger/TimeLine state, compact decorations, and stock object initialization.

## RNG origin and propagation

### Retail RNG

`0x00818B08` is a pointer to the active native RNG object. In the normal
retail path it points at the fixed `0xE8`-byte object at `0x00818B10`.

| Address | Recovered operation |
| ---: | --- |
| `0x00401110` | Construct/default the native RNG object. |
| `0x00401120` | Initialize its 30-bit additive, 55-state sequence. |
| `0x00401170` | Draw an integer in a requested range. |
| `0x00401310` | Draw a floating-point value. |

At `0x006388FE`, `BoneyardGenerator` resolves the active RNG. The integer draw
at `0x0063890D` chooses a derived seed in `0..999999`. The generator constructs
a stack RNG, initializes it from that value at `0x00638928`, and logs
`Random Boneyard Seed: %d` near `0x0063893D`. Instructions
`0x0063895B..0x0063896D` copy all `0x3A` dwords of the resulting state into
the active global object. Every following random placement and choice in the
generator consumes that state.

The copy at `0x0063E2E9..0x0063E2F9` copies `0x3A` dwords from the fixed object
at `0x00818B10` to the active object. Because the retail active pointer
normally names that same fixed object, this is not a second independent seed
source.

### Multiplayer ownership

The host creates the run seed with `BuildHostRunGenerationSeed()`. It combines
host-only entropy, normalizes the result to the native 30-bit domain, records
it as the authority participant's `run_nonce`, and publishes it in the
authenticated participant/state stream. Clients do not invent a replacement:
they cache the authority Run intent and queue local run entry with that exact
value.

Immediately before the stock `Arena_Create` call, the framework invokes:

```text
ReinitializeAppliedRunGenerationSeedForArenaCreate("arena_create_pre_stock")
```

That boundary is after peer-specific loader cleanup and before the first stock
Boneyard RNG draw. It prevents earlier local cleanup work from shifting the
generation stream. The six-digit seed logged by `BoneyardGenerator` is not a
separate wire field; it is the deterministic first derived draw from the
host-authored 30-bit run seed.

## Generated and materialized world state

`BoneyardGenerator` at `0x006388B0` owns the common seeded path for:

- Tree, Gravestone, Goodie, and Building object records;
- roads, fences, fence-derived geometry, and terrain/layout geometry;
- compact decoration records, including Tree-adjacent leaves, ground cover,
  shadows, and dark patches;
- recipes, UID groups, triggers, and the default TimeLine graph.

The Tree helper at `0x0062CB00` constructs type 2001, chooses the Tree fields
at `+0x140/+0x142`, and inserts it into the RegionLayout scenery list.
Natural variants 0 through 7 also emit compact types 0 through 6 with seeded
position, scale, alpha, and flags.

After reload, `0x006531B0`:

1. derives the scenery materialization key at `+0x10` from Y position times
   100;
2. runs native initialization and collision hooks;
3. expands Fence specifications;
4. replaces Tree variants 15 through 18 with Scrub type 2062; and
5. rebuilds compact-decoration bounds and spatial registration through
   `0x00644C00`.

Tree construction at `0x005E46D0` also draws a value into Tree `+0x148`.
Tree serialization at `0x005E0050` writes the geometry/variant fields
`+0x140`, `+0x142`, and `+0x144`, but not `+0x148`. The latter is local
presentation/tick state, not a missing serialized Tree position or type.

## Complete decor-family inventory

The inventory below distinguishes persistent seeded layout from derived
scenery and render-only transient clutter. “Serialized” means the field
crosses the temporary Boneyard save/reload boundary. It does not mean the
framework sends the field over multiplayer.

### Scenery objects and derived props

| Family / native type | Creation and materialization | Render-relevant selectors | Ownership finding |
| --- | --- | --- | --- |
| Tree `2001` | `0x0062CB00` creates the record; `0x005E46D0` constructs it; `0x006531B0` materializes it. | Position/radius, materialization key `+0x10`, common tint/scale/color, common lighting scalar `+0xCC`, Tree variant `+0x140`, overlay `+0x142/+0x144`, render parameter `+0x13C`, sway target/current `+0x14C/+0x150`. Main/overlay/foreground renderers are `0x00608480`, `0x00608830`, and `0x00608AB0`. | Position, type, variants, overlay, and serialized common draw state match from the seed. Sway does not: `0x005F1C50` decrements local `+0x148`, scans peer-local nearby actors, and changes `+0x14C/+0x150`. The base constructor `0x006287D0` leaves `+0xCC` unwritten, and `0x00624B40` later derives it from peer-local lighting; `0x00608912` consumes it when complex lighting is enabled. |
| Scrub `2062` | Tree variants 15–18 are replaced by Scrub in `0x006531B0`; constructor and tick override are `0x005E4040`/`0x005E40D0`. | Position, variant `+0x140`, phase `+0x134`, orientation/deformation `+0x144/+0x148`, collision flag `+0x14C`; renderer `0x00620120`. | Variant and geometry are deterministic. Constructor RNG at `0x005E40A4`, the common tick `0x00624AC0`, and the additional tick RNG at `0x005E40E2` all change the local phase. The final add is at `0x005E40E7`, after the common tick returns. `0x005E40F0` omits `+0x134`, while the renderer uses it. |
| Monument `2009` | Constructor `0x005E0DB0`, setup `0x005E5BB0`. | Serialized simple variant `+0x140` and common scenery draw state; renderers `0x0060E210`/`0x0060E280`. | Deterministically generated and serialized. |
| Gravestone `2029` | Constructor `0x005E5C30`, setup `0x005F2EB0`. | Variant `+0x140`, overlay `+0x142`, tint `+0x144..+0x150`; renderers `0x0060F0F0`, `0x0060F1F0`, and `0x0060F260`. | Constructor RNG at `0x005E5CCC` is overwritten by serialized values in `0x005E0F60`; render inputs match. |
| Building `2040` | Constructor/setup `0x005F2C30`/`0x005E5BF0`. | Serialized simple variant and common state; base/upper/bounds renderers `0x0060E940`, `0x0060EC50`, `0x0060EDC0`. | Deterministically generated and serialized. |
| Goodie `2061` | Constructor `0x005E3D60`, setup `0x005E3E40`. | Subtype `+0x140`, glyph/phase `+0x142`, active flag `+0x143`, indicator timer/value `+0x144`, reward seed `+0x148`; renderer `0x0061F070`. | `0x005E3DD0` serializes every listed field, but the constructor initializes `+0x142/+0x143` and skips `+0x144`. Inactive beta.16 objects showed `0` versus `0x00FFFFFF`; if activated, that residue becomes a render condition. |
| Fence post `3006` | Fence specs are expanded by `0x0064AC90`; ctor/sync `0x005E1E20`/`0x005E1EA0`. | Variant/bank `+0x140/+0x144`, position and common state; renderer `0x00612CF0`. | Derived synchronously from matching Fence inputs. |
| Fence grate `3007` | Constructor/builder/setup `0x005E7FB0`, `0x005E8100`, `0x005E8650`. | Geometry `+0x140..+0x1A4`, bounds `+0x1B4..+0x1C0`; renderers `0x00600ED0` and `0x005E1EF0`. | Serialized by `0x005E2080`; inputs match. |
| Broken grate `3011` | Builder/setup `0x005EC6E0`/`0x005ECD30`. | Grate geometry/bounds plus leaf side `+0x1C4`; renderer `0x005E38C0`. | Builder uses a local RNG initialized from deterministic geometry and side, rather than the process-global stream. |
| Gate `3012` | Builder `0x005F73C0`, collision/spatial setup `0x005ED4D0`/`0x005ECDF0`. | Grate geometry/bounds, side `+0x1C4`, render state `+0x1CC..+0x1F0`; renderer `0x005ECE40`. | Builder draw at `0x005F75C5` occurs on the matching deterministic Fence path. Later actor-driven gate motion is dynamic gameplay state, not seeded decor. |
| Wall `3013` | Constructor/setup `0x005F88B0`/`0x005EEAF0`. | Fixed geometry `+0x140..+0x284` excluding self pointers, plus scalar/point/index arrays at `+0x28C/+0x29C/+0x2AC`; renderer `0x0061E780`. | Serialized by `0x00606770`; process-local self pointers are excluded from the render digest. |
| Rails `3014` | Builder `0x005F0EC0`. | Grate geometry/bounds, side, state `+0x1C8..+0x220`; renderers `0x005E3E70`/`0x00607440`. | Serialized by `0x005E3F60`; inputs match. |

The common scenery tick at `0x00624AC0` increments `+0x134` once per local
tick. That word is not universally a render field: it is excluded for
families whose renderers do not read it and included for Scrub, whose renderer
does. Likewise Tree `+0x148` is a future-update countdown, while the
instantaneous rendered shape is controlled by `+0x14C/+0x150`.

The nearby common scalar at `+0xCC` is a different field. The base constructor
at `0x006287D0` initializes `+0xD0` to `1.0` but never writes `+0xCC`.
The common serializer at `0x00622DC0` does include `+0xCC`, so the procedural
generation allocation residue survives the temporary save/reload boundary.
Tree's overlay renderer multiplies those two words at
`0x0060890C..0x00608912` when complex lighting is enabled. The other scenery
renderers in the inventory do not read object `+0xCC`. Excluding the word
globally because the Gravestone renderer does not consume it was therefore a
digest bug: it must be included and canonicalized for Tree.

Constructor canonicalization alone is insufficient. Headless decompilation
and instruction inspection recovered the common scenery render dispatcher
`0x00624B40`, which runs before the object's virtual draw. It writes `+0xCC`
at all six of these instructions:

| Address | Recovered render-time source |
| ---: | --- |
| `0x00624C2F` | Initial zero while visibility is evaluated. |
| `0x00624C4E` | Zero on the early culled return. |
| `0x00624C89` | Forced `1.0` for the unconditional render branch. |
| `0x00624D3E` | Result of the local transformed-light query `0x0057E490`. |
| `0x00624DAD` | Result of local light queries `0x0057F980` or `0x0057F0E0`. |
| `0x00624DC7` | Forced `1.0` when the owning Arena lighting lane is disabled. |

The dispatcher then calls the Tree virtual renderer. The overlay entry
`0x00608830` reads the final value at `0x00608912`, after every constructor
and tick hook has already run. A live expanded-table capture caught exactly
this last-writer failure: one otherwise identical Tree had host bits
`0x3DD62F07` and client bits `0x3E145B97`. Therefore the multiplayer repair
must canonicalize the Tree scalar both as persistent dump state and at the
Tree overlay entry immediately before its final read. Patching only allocation
or generation cannot close this render-time path.

### Roads, fences, and terrain

| Family | Creation / sync / render | Seed and render inputs |
| --- | --- | --- |
| Road | Constructor `0x00645470`, sync `0x0063EAA0`, geometry builder `0x0064C1F0`, render `0x00640750`. | Endpoints, width scales, quad, and style are serialized and match. UID and previous/next UID fields are process-local identifiers and are not renderer inputs; beta.16 differed by a constant UID offset only. |
| Fence specification | Constructor `0x006407B0`, sync `0x0063EB70`, expansion `0x0064AC90`. | Endpoints, start/end post variants, and segment code match. The process-local UID is not rendered. Expanded posts/grates/gates/walls/rails are covered above. |
| Terrain | Constructor `0x00646A80`, sync `0x00651720`, rebuild `0x006534B0`, render `0x0064EDA0`. | Control-point/scalar arrays, scale/style/reserved values, and seed `+0xCC` are serialized. Constructor RNG at `0x00646B56` establishes that seed; builders `0x0064F0F0` and `0x0064FA90` initialize private RNGs from it. |

### Compact decoration and ground clutter

RegionLayout section 11 contains native-order `0x2C` records. The renderer
loop beginning at `0x004716B1` consumes type `+0x00`, position `+0x04/+0x08`,
rotation `+0x0C`, scale `+0x10`, alpha `+0x14`, flags `+0x18`, and runtime
bounds `+0x1C..+0x28`. Bounds are rebuilt by `0x00470A90`; they are part of
the render-input digest even though only the first `0x19` bytes are serialized.

| Type range | Visual family | Creation and selection |
| ---: | --- | --- |
| 0–6 | Tree leaves, grass, soil, and tree-adjacent ground cover | Tree helper `0x0062CB00`; the shared generator RNG selects type, offset, rotation, scale, alpha, and flags. |
| 7–8 | Dark ground patches | `BoneyardGenerator` `0x006388B0`; among the seven corrected flag sites `0x0063BC10..0x0063C45F`. |
| 9–12 | Paving and flat stones | Same generator and shared RNG path; persistent record contains every draw selector. |
| 13–18 | Pebbles and small rock scatter | Same generator and shared RNG path. |
| 19–20 | Twigs and lattice clutter | Same generator and shared RNG path. |
| 21–24 | Large irregular ground rocks and boulders | Same generator and shared RNG path. The expanded beta.16 baseline contained 50 on both peers with identical full records and bounds. |
| 25–29 | Shadow/mask sprites and special ground effects | Same persistent generator path; renderer selects art from the table at `0x0081BD20`. The persistent records match, but their render loop also owns a local ambient-effect branch described below. |
| 30 | Dead roots and stumps | Same generator and shared RNG path. |

No additional persistent compact creator outside the Tree helper and
`BoneyardGenerator` was found. The missing family was instead transient:

- At `0x004717E9`, the first branch admits Arena render-list records whose
  object-local byte at `+0x8F20` is 1 or 2. This is the only native guard
  immediately before the first random spawn decision.
- At `0x00471805`, `Arena_Render` performs a 1-in-2 global-RNG draw while
  traversing compact types 25–29. It draws X, Y, and lifetime at
  `0x0047182A`, `0x0047184A`, and `0x004718D5`, then calls effect spawn
  `0x00649D10` at `0x0047191C`.
- At `0x004723A6`, the second branch applies the same object-local byte
  test before its random spawn decision.
- At `0x004723C2`, a second Arena ambient list performs a 1-in-8 global-RNG
  draw. It draws position/lifetime/scale at `0x004723F1`, `0x0047240D`,
  `0x00472479`, and `0x00472493`, then calls the same effect spawn at
  `0x004724E4`.

These draws happen during rendering, consume whatever process-global RNG state
each peer has at that frame, and create no serialized or replicated record.
They can therefore change boulder/rock/clutter pixels while every compact row
and its digest remains equal. Instruction inspection also rules out the
runtime enhanced-effects option as an authority input for these two branches:
their immediate guards are the Arena object's `+0x8F20` byte, not the
enhanced-effects global. A visual acceptance profile may disable enhanced
effects to remove unrelated peer-local rain and weather from the comparison
without bypassing either Boneyard ambient RNG callsite.

### Arena marker glyph tint

The complete `Arena_Render` RNG audit found two additional presentation draws
outside the compact loop:

- the first marker pass calls the floating RNG at `0x004712BB`, sets a random
  tint, and draws one of four world marker glyphs at the marker object's
  `+0x18/+0x1C` position;
- after restoring the render transform, the second marker pass repeats the
  tint draw at `0x004726E3` before drawing the same marker family.

Both callsites pass sign mode 0 and the float scale stored at `0x00785D34`
(`0.0500000119`). The caller then adds the double bias stored at `0x00784E20`
(`0.9499999881`) before converting the tint to a float. Thus the complete
stock tint input is the peer-local RNG state, callsite, fixed scale, fixed
sign mode, and fixed bias; the visible range is approximately 0.95 through
1.0.

Both paths iterate the four marker slots rooted at
`DAT_0081C264 + 0x1358`. The marker objects and glyph selection can be
identical while their brightness differs because the calls consume the
peer-local global RNG during presentation. These pixels can overlap nearby
Tree, boulder, rock, and ground-clutter regions, so the two RNG calls are part
of the full render-materialization boundary even though the markers are not
RegionLayout compact records.

The same audit found a floating RNG call at `0x0045A556` in
`Anim_FlickerLight` render `0x0045A510`. Its sole constructor reference is the
Heartmonger death path `0x0049FB60`; it is a live combat/death effect, not a
default-Boneyard decor creator. It remains outside the seeded decor repair and
is excluded from decor pixels together with actors and their transient
effects.

### Replication boundary

| State | Owner and transport |
| --- | --- |
| Run-generation seed | Host-authored `run_nonce`, authenticated and sent to clients. |
| Derived six-digit retail seed | Not sent separately; every peer derives it from the synchronized run seed at the same native boundary. |
| Generated `play.boneyard` bytes | Not transported. Each peer runs the same retail create/save/load path locally. |
| Tree/Scrub, Gravestone, Building, Goodie, Road, Fence, terrain, and compact decor layout | Locally materialized from the host seed. Equality depends on deterministic native initialization. |
| Tree sway/common lighting scalar, Scrub phase, Arena marker tint, and Arena ambient ground effects | Not replicated by stock or framework packets in beta.16; stock updates, initializes, draws, or spawns them from allocator residue and peer-local actor, tick, and RNG state. |
| Participants, enemies, live loot, casts, and transient effects | Replicated by their dedicated framework ownership/snapshot paths. |
| Run-static Solomon Dig (`0x1391`) and Lantern (`0x1392`) | Host snapshot state; separate from RegionLayout Tree/Scrub/compact decoration. |

No framework packet serializes the RegionLayout scenery list or compact
section directly. The framework owns authority and seed propagation; the
retail loader remains the materializer. A foundational repair therefore has
to make all presentation derived from that host seed deterministic (or
disable non-authoritative transients consistently), rather than adding
per-tree position packets.

## Pre-fix multiplayer evidence

An isolated Windows host/client pair used loopback UDP ports 48672 and 48673,
separate instance directories, and the same authenticated host seed
`0x1F4E1493`. Both logs recorded native RNG reinitialization at
`arena_create_pre_stock`.

The existing live gate found the following equal materialized state:

| Lane | Host and client result |
| --- | --- |
| Scenery | 468 objects, digest `0x14C35D88` |
| Tree | 122 objects, digest `0x81D04B82` |
| Static circles | 451, digest `0x9F3E0135` |
| Static shapes | 17, digest `0x7FB87034` |
| Stored world objects | 434 total: 122 Tree, 305 Gravestone, 7 Goodie |
| Other layout records | 68 roads, 16 fences, 252 compact decorations |

However, that gate did not inspect RegionLayout section 11. The generated
`play.boneyard` files were both 262,398 bytes but had different SHA-256 values:

```text
host   825a73e456ce8a9e3f8af8d95b4349e8f6032d9792cf00d515f93c3773a0fd85
client ff4f0ba8e66ad4aa82dc8cedc4da48dce203f662f056c078d59cd5381dee750d
```

A whole-file hash is not a semantic equality gate because other stock
serialized fields can contain process addresses or ignored uninitialized
bytes. Parsing the exact 25-byte compact records isolated the relevant
difference. Section 11 hashes were:

```text
host   dcda61661f020a4f5a26893ddcabfefc179fa6a5a75f689d27fffa6e97043b01
client a175eb810b817880c8678ff2315c109f5b99260f2582c1f73880c1c8c28f9b5e
```

Compact record 120 had identical generated semantics except for flags:

| Field | Host | Client |
| --- | ---: | ---: |
| compact type | 7 | 7 |
| x | 1126.70361328125 | 1126.70361328125 |
| y | 1735.8126220703125 | 1735.8126220703125 |
| rotation | -3.399200201034546 | -3.399200201034546 |
| scale | 0.977383017539978 | 0.977383017539978 |
| alpha | 1.0 | 1.0 |
| flags | `0x13` (low bits `3`) | `0x79` (low bits `1`) |

Bit `0x02` halves RGB in the retail renderer, so this is a visible difference,
not merely a raw-file mismatch. Record 119 also differed only in ignored high
bits (`0x79` versus `0x91`), confirming that the entire flags byte retained
allocator residue.

## Root cause sites and repair boundary

The seven faulty instructions are all in `BoneyardGenerator`:

| Address | Stock bytes | Recovered action |
| ---: | --- | --- |
| `0x0063BC10` | `80 4E 18 01` | OR bit 0 into uninitialized compact flags. |
| `0x0063BD1F` | `80 4E 18 01` | Same. |
| `0x0063BDFB` | `80 4E 18 01` | Same. |
| `0x0063BF30` | `80 4E 18 01` | Same. |
| `0x0063C03B` | `80 4E 18 01` | Same. |
| `0x0063C117` | `80 4E 18 01` | Same. |
| `0x0063C45F` | `80 4E 18 01` | Same. |

Each site follows allocator `0x0074784D`, initializes the type and floating
fields, derives bounds, and then ORs the flags byte. Tree-helper compact types
0 through 6 already initialize the byte with a full `MOV`, as do later
generator paths near `0x0063DFA4` and `0x0063E288`. The intended convention is
therefore established by neighboring stock code.

The same-length correction at every site is:

```text
stock  80 4E 18 01    OR  byte ptr [ESI+0x18], 0x01
fixed  C6 46 18 01    MOV byte ptr [ESI+0x18], 0x01
```

This initializes the intended X-compression bit, clears the unintended tint
bit, and removes ignored heap residue. Applying it to all creators fixes the
record class rather than special-casing Tree entities or copying host
positions after generation.

Because the authority seed and packet representation do not change, the
network protocol version must remain unchanged for this repair.

## Revised repair boundary

The full class is “locally rendered state reached from seeded Boneyard
materialization,” not “compact flags” or “Tree positions.” A complete repair
must satisfy these invariants whenever multiplayer transport is active:

- Tree render target/current cannot depend on which peer-local actors happen
  to be near the Tree during a local tick.
- Tree's complex-lighting scalar cannot retain allocator residue from the
  common constructor.
- Scrub render phase must be a stable function of the shared run seed and
  stable object identity, not local global-RNG or tick consumption.
- Goodie construction must initialize every conditionally rendered and
  serialized field.
- Arena render passes cannot spawn non-replicated ground decor from a
  peer-local RNG stream.
- Arena marker tint must be a stable function of the shared run seed, not the
  process-global RNG state at presentation time.
- Single-player behavior remains stock.

These changes do not alter any framework message or serialized network field.
The existing host run seed remains the sole authority input, so the protocol
version remains 84 unless implementation later introduces a wire change.

## Implemented multiplayer presentation boundary

The framework now enforces those invariants only while local multiplayer
transport is active. The stock single-player paths remain untouched.

| Family or pass | Multiplayer behavior |
| --- | --- |
| Persistent compact types 0–30 | The seven incomplete flag writes remain full-byte `MOV 0x01` initializations, eliminating allocator-derived tint and ignored bits for ground cover, patches, paving, pebbles, twigs, boulders, shadow/mask sprites, and roots. |
| Tree `2001` | The constructor initializes common scalar `+0xCC` before the temporary save/reload can preserve heap residue. After materialization, a stable per-Tree hash of the host run seed, exact X/Y bits, type, and packed variant/overlay word selects sway scale and complex-lighting scalar. The Tree tick reasserts `+0x148/+0x14C/+0x150`; the overlay hook writes `+0xCC` immediately before `0x00608912`; and the common lighting-dispatch hook restores the same scalar after `0x00624B40` returns so both pixels and live table dumps observe the deterministic value. |
| Scrub `2062` | The constructor hook first replaces its RNG phase with zero, preventing a divergent pre-first-tick frame. The full Scrub tick hook reasserts the same seed/position/type/variant-derived phase after both the common increment and the additional RNG add at `0x005E40E7`, preventing later tick-count or RNG drift. |
| Goodie `2061` | The constructor initializes `+0x144` to zero before procedural serialization. A later load may overwrite it only with the now-canonical serialized value. This fixes the object class at construction rather than hiding residue in the digest. |
| Arena ambient ground effects | The integer RNG calls at `0x00471805` and `0x004723C2` are redirected to return the native non-spawn result in multiplayer. No peer creates these non-authoritative, non-replicated transient ground effects. |
| Arena marker glyphs | The floating RNG calls at `0x004712BB` and `0x004726E3` are redirected to values derived from the host run seed and a callsite salt. Each pass therefore selects the same tint on every peer without consuming peer-local presentation RNG. |

The deterministic scenery hash never uses an address, allocator state,
container index, local tick count, actor list, or render-iteration order.
Position and variant inputs already come from the shared seeded
materialization path. The Arena-only redirects use the synchronized run seed
and fixed callsite salts. No RegionLayout field or framework packet changes,
so the network protocol remains version 84.

The patch installer validates the supported stock bytes at all seven compact
sites and all four Arena render-RNG callsites before writing anything. Failure
rolls back every byte patch and installed presentation hook. Shutdown restores
the stock callsites and hooks.

## Corrected digest and pixel acceptance

The live verifier preserves native order and compares exact renderer inputs,
not a sorted or position-only projection:

- common scenery position, materialization key, scale, color, render
  parameter, and the proved family-specific arrays and fields;
- Tree variants, overlay state, deterministic sway target/current, and the
  final complex-lighting scalar;
- Scrub phase, variant, orientation/deformation, and collision selector;
- Monument, Gravestone, Building, Goodie, Fence-post, grate, broken-grate,
  Gate, Wall, and Rails render fields;
- Road geometry/style, Fence specifications, complete Terrain inputs and
  private-RNG seed, and every compact type 0–30 record including rebuilt
  bounds; and
- the host run seed plus the fixed Arena ambient-suppression policy and the
  two seed-derived marker tint inputs.

Process-local Road/Fence UIDs, Wall self-pointers, and common `+0x134` words
whose family renderer never reads them remain diagnostic-only. An inactive
Goodie timer is canonicalized to zero in both construction and the semantic
digest; an active timer remains included.

For visual acceptance, each fresh seed selects four distinct, dense,
camera-safe areas: Trees, large rocks/boulders, ground clutter, and scenery
props. Both owners and their replicated mirrors are parked on traversable
native-nav samples outside the central 120-world-unit decor region. The
verifier applies identical render options to both peers with complex lighting,
complex shadows, multiple shadows, and zoom effects enabled. Enhanced effects
are disabled only to remove unrelated peer-local weather; the two Boneyard
ambient branches are independently suppressed by the repair above.

Each peer contributes 16 native-backbuffer captures per area. Pixels that are
unchanged throughout both sequences must match exactly, including their hash,
with no unexplained channel delta. The temporal RGB envelopes of the remaining
animated pixels must overlap with zero channel gap. The gate also requires
non-empty, color-rich regions and stores the host image, client image, stable
mask, exact difference image, temporal minima/maxima, and envelope-gap image.
Actors are excluded spatially, not painted out, and the verifier injects no
damage or spell presentation. A correlation score is retained only as an
alignment diagnostic and cannot pass the gate.

## Beta.16 acceptance gate and its blind spot

`tools/verify_run_static_layout_sync.py` ran three fresh host/client pairs in
isolated instance groups over loopback UDP. For each run it compared the full
decoded Tree table and full compact-decoration table, including exact IEEE-754
position/rotation/scale/alpha bits, Tree variants, and compact types and flags.
It also focused both native cameras on the same selected Tree and rejected the
screenshots unless both grayscale and edge landmarks correlated.

This was an alignment gate, not a visual equality gate. Correlation tolerates
different Tree silhouettes, shadows, boulders, tint, and clutter as long as
large landmarks remain in approximately the same place. The published
beta.16 control images pass that correlation test while visibly differing:

- `/mnt/d/codex-evidence/boneyard-visual-20260724/beta16-render-control-audio/screenshots/run-01-host.png`
- `/mnt/d/codex-evidence/boneyard-visual-20260724/beta16-render-control-audio/screenshots/run-01-client.png`

| Run | Authority seed | Trees | Tree digest | Compact decor | Compact digest | Gray / edge correlation |
| ---: | --- | ---: | --- | ---: | --- | --- |
| 1 | `0x20C8A4C4` | 99 | `0x05578935` | 319 | `0xEA27EE7F` | 0.9689 / 0.9373 |
| 2 | `0x016B0955` | 96 | `0xB102C6A7` | 351 | `0xB3CDE95F` | 0.9897 / 0.9007 |
| 3 | `0x3CC84FEC` | 111 | `0xE676A3C3` | 320 | `0x66260DAC` | 0.9979 / 0.9841 |

The other locally materialized lanes from the same generator also matched:

| Run | Scenery type/geometry | Static collision circles | Collision shapes | Replicated run-static actors |
| ---: | --- | --- | --- | --- |
| 1 | 487 / `0x165174E1` | 469 / `0xAE700889` | 18 / `0x3D256503` | 2 / `0x43BCB9E9` |
| 2 | 480 / `0x010EAF17` | 456 / `0x77DBB79A` | 14 / `0x7FD0E4CA` | 2 / `0x902FF326` |
| 3 | 466 / `0x3419F3B2` | 445 / `0x2BC31C35` | 17 / `0x01A2FBF9` | 2 / `0xA7E5B130` |

Every field included by that old gate matched host versus client. All compact
records had zero ignored high flag bits, and every type 7/8 record had the
canonical flags byte `0x01`. The three authority seeds and resulting layouts
were distinct. Both peer logs in every run recorded the same seed at
`arena_create_pre_stock` and `compact_flags_sites=7` at patch installation.
The gate excluded Tree/Scrub presentation inputs, conditional Goodie state,
compact runtime bounds, roads, fences, Terrain, and render-spawned effects.

The expanded pre-repair baseline at
`/mnt/d/codex-evidence/boneyard-visual-20260724/render-input-baseline/result.json`
preserved native order and recorded every recovered persistent renderer input.
For seed `0x1CC440E4`, both peers had 435 scenery objects, 87 Trees/Scrubs,
85 roads, 19 Fence specs, 266 compact records, and identical full compact
digest `0x01C318AB`. The compact family counts also matched exactly: 154
tree/ground-cover records, 34 dark patches, 50 large rocks, and 28
shadow/mask records. The mismatches isolated by the expanded dump were:

- all scenery `+0x134` tick counters differed by the peer tick-count delta;
- Tree render target/current matched at the sample instant, but local
  countdown `+0x148` differed and controls future peer-local sway updates;
- six inactive Goodies had uninitialized `+0x144` (`0` versus
  `0x00FFFFFF`);
- Road/Fence geometry matched while non-rendered UIDs differed by one.

The corrected digest excludes process-local Road/Fence identifiers and common
tick words that no renderer consumes, but includes Scrub phase, Tree current
render shape and complex-lighting scalar, conditional Goodie state, all
derived geometry arrays, compact bounds, and native list order. The pixel gate
also has to make the two Arena marker tint draws deterministic and suppress
the two non-authoritative ambient-effect spawn decisions. Final acceptance
additionally requires exact decor-pixel equality in several matched-camera
regions for at least three distinct seeds; correlation alone is retained only
as an alignment diagnostic.

Evidence is retained locally under:

- `runtime/evidence/boneyard-seed-sync/acceptance/seeded-decor-host-client.json`
- `runtime/evidence/boneyard-seed-sync/acceptance/screenshots/`
- `runtime/evidence/boneyard-seed-sync/acceptance/logs/`

The verifier stops only processes it launched after validating exact PIDs and
executable paths. It never performs machine-wide Solomon Dark cleanup.
