# Native default Boneyard load, seed, and decor materialization

This document maps the retail run-start path that selects, procedurally
generates, saves, reloads, and materializes the default Boneyard. It also
records the multiplayer seed boundary and the pre-fix root cause of
process-dependent compact decoration.

The addresses are image-base virtual addresses for the analyzed
`SolomonDark.exe`:

- image base: `0x00400000`
- file size: `4,723,200` bytes
- SHA-256:
  `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

The container and RegionLayout grammar remain documented in
[`boneyard-system.md`](boneyard-system.md). This document is the run-start and
multiplayer ownership map.

## Result

The framework already gives every peer the host's 30-bit run-generation seed
and reapplies it to the retail global RNG immediately before `Arena_Create`.
For the same run, the host and client therefore generated the same Tree
objects, Tree variants, positions, roads, fences, compact-decoration geometry,
and other seeded layout content.

The remaining divergence was native uninitialized data. Seven paths in
`BoneyardGenerator` allocate a `0x2C` compact-decoration record and use:

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

The class-level correction is to initialize the complete flags byte to
`0x01` at all seven sites. It is a local native determinism repair at the
shared seeded generation boundary; it does not add or change a network field.

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

### Replication boundary

| State | Owner and transport |
| --- | --- |
| Run-generation seed | Host-authored `run_nonce`, authenticated and sent to clients. |
| Derived six-digit retail seed | Not sent separately; every peer derives it from the synchronized run seed at the same native boundary. |
| Generated `play.boneyard` bytes | Not transported. Each peer runs the same retail create/save/load path locally. |
| Tree/Scrub, Gravestone, Building, Goodie, Road, Fence, terrain, and compact decor layout | Locally materialized from the host seed. Equality depends on deterministic native initialization. |
| Participants, enemies, live loot, casts, and transient effects | Replicated by their dedicated framework ownership/snapshot paths. |
| Run-static Solomon Dig (`0x1391`) and Lantern (`0x1392`) | Host snapshot state; separate from RegionLayout Tree/Scrub/compact decoration. |

No framework packet serializes the RegionLayout scenery list or compact
section directly. The framework owns authority and seed propagation; the
retail loader remains the materializer.

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
