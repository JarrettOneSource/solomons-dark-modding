# Solomon Dark Boneyard system

This document records the retail Boneyard file format, the native load/save and
generation paths, and the staging contract used by downloadable mods.

The addresses below are image-base virtual addresses for the analyzed
`SolomonDark.exe`:

- image base: `0x00400000`
- file size: `4,723,200` bytes
- SHA-256: `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`

## Conclusions

- A `.boneyard` is a recursive `SyncBuffer`, not a flat table, ZIP, or text
  format. It has no magic bytes, version header, compression, or checksum.
- The file contains an Arena envelope with 13 chunks. Arena section 12 contains
  a `RegionLayout` envelope with 14 sections.
- `RegionLayout` stores placed world objects, triggers, recipes, roads, fences,
  terrain, timelines, and a compact static-sprite placement list.
- Polymorphic lists store a count and native type IDs in the parent payload;
  each object serializes itself through virtual slot `+0x14` in child chunks.
- Loading is two-phase. Native objects are deserialized first, then serialized
  integer IDs are resolved back to live pointers and owner/spatial links are
  repaired.
- The stock editor passes logical paths such as
  `DarkCloud\mylevels\Name.boneyard` to the path resolver. In sandbox mode the
  resolver prepends `sandbox\`. A staged custom level must therefore live at
  `sandbox/DarkCloud/mylevels/Name.boneyard`.
- An editor “blank” Boneyard is not an empty file or an empty runtime arena. It
  has the complete native envelope and a large default `TimeLine` graph; stock
  startup logic can still materialize scenery, set pieces, and waves.

## Native object model

`Arena` derives from `Region`. Its allocation is `0x9068` bytes. The Region
constructor at `0x00652830` constructs an embedded `RegionLayout` at Arena
offset `+0x8510` through `0x006405A0`.

| Object | Vtable | Constructor or anchor | Sync method |
| --- | ---: | ---: | ---: |
| `Arena` | derived Region vtable | `0x00464EE0` | Arena header is handled directly by `0x0046DC60` / `0x0046D7B0` |
| `Region` | `0x0079F3E4` | `0x00652830` | `0x00648480` at virtual `+0x14` |
| `RegionLayout` | `0x0079F2A4` | `0x006405A0` | `0x00653660` at virtual `+0x14` |
| `BoneyardGenerator` | `0x0079E814` | cleanup/anchor `0x0062DFC0` | generator body `0x006388B0` |
| `SyncBuffer` | not polymorphic here | `0x00423F70` | recursive read `0x004245B0`, recursive write `0x00424A60` |

The embedded layout owns definitions and editor objects. The live Arena/Region
owns the materialized runtime lists. Relevant live lists include scenery at
Arena `+0x87C4`, roads at `+0x8810`, fences at `+0x885C`, and transient actors
at `+0x8B70`. Those runtime collections are not a byte-for-byte view of the
RegionLayout lists.

## SyncBuffer byte grammar

All integers in the container grammar are unsigned 32-bit little-endian
values. `payload_length` does not include the length field, child count, or
children.

```text
SyncChunk :=
    u32 payload_length
    byte[payload_length] payload
    u32 child_count
    SyncChunk[child_count]

SyncBuffer :=
    SyncChunk root
    u32 named_buffer_count
    repeat named_buffer_count times:
        u32 name_length_including_NUL
        byte[name_length_including_NUL] name
        SyncBuffer nested_buffer
```

The name field has one terminal NUL byte. The seven stock/captured files in the
corpus all have zero named buffers and consume the file exactly at the end of
the root `SyncBuffer`.

The native primitives used inside chunk payloads are:

| Address | Recovered operation |
| ---: | --- |
| `0x004247B0` | enter/start child chunk |
| `0x00424860` | leave/end child chunk |
| `0x00424DA0` | one byte |
| `0x00424E30` | 32-bit value |
| `0x00424EC0` | 16-bit value |
| `0x00424F60` | Boolean |
| `0x00425000` | two-component vector |
| `0x00425130` | native `String` |
| `0x00425210` | 32-bit scalar/float |
| `0x004252C0` | four-component rectangle/vector |
| `0x00425580` | polymorphic object-manager list |

Opening for read is `0x004243C0`; opening for write is `0x004242D0`; the final
write/commit is `0x00424890`. String payloads use `0x00422370` for read and
`0x004227A0` for write.

## Boneyard envelope

Every inspected Boneyard has this structural envelope:

```text
SyncBuffer.root                    payload=0, children=1
└── Arena                          payload=0, children=13
    ├── Arena section 0            header/settings payload
    ├── Arena section 1            optional editor/run metadata
    ├── Arena sections 2..10       reserved compatibility chunks
    ├── Arena section 11           reserved/legacy payload
    └── Arena section 12           payload=0, children=1
        └── RegionLayout           payload=0, children=14
            └── sections 0..13
```

Arena section 0 is 546-554 bytes in the corpus and includes a native String,
flags, a 512-Boolean block, a byte, and a rectangle. Sections 1 and 11 differ
between editor/test and shipped levels. Their opaque fields are preserved by
the stock serializer but are not needed to identify or safely stage a
Boneyard. The structural validator deliberately verifies the exact envelopes
and recursively bounds every payload and child list; it does not rewrite
unknown payload bytes.

## RegionLayout sections

`RegionLayout::Sync` at `0x00653660` enters the following 14 child chunks in
this exact order.

| Index | RegionLayout field | Encoding / role |
| ---: | --- | --- |
| 0 | `+0x2B4` world objects | Polymorphic object manager; Tree, Monument, Gravestone, Building, Goodie, and other placed objects |
| 1 | `TriggerControl` | Three-child trigger/controller graph serialized by `0x00686400` |
| 2 | `+0x3E4`, `+0x3EC` | Region geometry: vector plus scalar |
| 3 | `+0x404` MonsterRecipe | Polymorphic type `6001` |
| 4 | `+0x450` UIDGroup | Polymorphic type `6002` |
| 5 | `+0x300` Road | Polymorphic type `3004` |
| 6 | `+0x34C` Fence | Polymorphic type `3005` |
| 7 | `+0x580` ItemRecipe | Polymorphic type `6003` |
| 8 | `+0x49C` ItemSet | Polymorphic type `6005` |
| 9 | `+0x4E8` NPCRecipe | Polymorphic type `6004` |
| 10 | `+0x65C` | One-byte layout flag |
| 11 | `+0x5CC` static sprite placements | Count plus 25 bytes per record; resolved against the `DeadHawg` atlas and inserted into a spatial grid on read |
| 12 | `+0x398` Terrain | Polymorphic type `3009` |
| 13 | `+0x534` TimeLine | Polymorphic type `6006` |

For an object-manager section, the parent payload is:

```text
u32 object_count
u32 native_type_id[object_count]
```

The manager constructs each type through the native factory, enters the
corresponding child chunk, and invokes the object's virtual `Sync` method at
slot `+0x14`. A world object may itself use several direct child chunks, so the
number of child chunks is not necessarily the object count. Road, Fence,
Terrain, recipe, and TimeLine entries in the corpus each have one immediate
object child.

Known IDs relevant to Boneyards include:

| ID | Native class | ID | Native class |
| ---: | --- | ---: | --- |
| 2001 | Tree | 3004 | Road |
| 2009 | Monument | 3005 | Fence |
| 2029 | Gravestone | 3006 | Fencepost |
| 2040 | Building | 3007 | FenceGrate |
| 2061 | Goodie | 3009 | Terrain |
| 6001 | MonsterRecipe | 6004 | NPCRecipe |
| 6002 | UIDGroup | 6005 | ItemSet |
| 6003 | ItemRecipe | 6006 | TimeLine |

Section 11 does not use the polymorphic manager. Each in-memory record is
`0x2C` bytes, but its serialized form is exactly 25 bytes:

```text
u32 atlas_entry_id
float2 position
float scalar_0
float scalar_1
float scalar_2
u8 flags
```

During read, `RegionLayout::Sync` resolves the atlas entry through the global
`DeadHawg` atlas, calculates its bounds, and calls `0x00587CF0` to register the
record in the relevant spatial cells.

## Load, link, and activation

The main Arena load routine is `0x0046DC60`.

1. It optionally invokes the procedural create/save path when the random-level
   global is active.
2. It constructs a read `SyncBuffer`, opens the resolved path, and enters the
   root and Arena chunks.
3. It reads the Arena header and compatibility sections.
4. It invokes virtual `+0x14` on the embedded RegionLayout at Arena `+0x8510`.
5. It closes the buffer and copies loaded world bounds into the Arena runtime
   fields.
6. `0x0064BC40` resolves serialized integer object IDs into pointers across
   UID groups, MonsterRecipe/NPCRecipe relationships, TimeLines, and code
   chunks. Timeline entries are also ordered by their stored coordinates.
7. RegionLayout read completion restores owner pointers for world objects,
   roads, and terrain and rebuilds their native registrations.
8. Trigger/TimeLine startup is dispatched, the Arena is marked loaded, and
   `0x004685E0` counts active Goodies (type `2061`) into Arena `+0x9060`.

`Arena_Create` at `0x0046EA90` initializes the `DeadHawg` atlas, selects
`play.boneyard` or `testrun.boneyard`, resolves the path, calls the same Arena
load routine, then initializes the loaded region and timeline systems.

The load is not safe to emulate by copying raw records into live memory. Object
factory construction, virtual deserialization, pointer relinking, owner repair,
atlas/spatial registration, and timeline activation are all required. File
overlay staging works because it lets the retail loader perform this lifecycle.

## Create, editor save, and procedural generation

The create/save path is `0x0046D7B0`:

1. allocate and construct an Arena through `0x00464EE0`;
2. initialize generator state through `0x0062FDF0`;
3. run `BoneyardGenerator` at `0x006388B0`;
4. open a write `SyncBuffer`;
5. write the symmetric 13-section Arena envelope;
6. invoke RegionLayout virtual `+0x14` to write its 14 sections;
7. commit through `0x00424890`.

`BoneyardGenerator` is a 6,165-instruction routine with 70 direct call targets.
The recovered phases are:

- establish and log the random seed (`Random Boneyard Seed: %d`);
- build working arrays of rectangles, lines, points, floats, and indices;
- partition/interpolate arena geometry and place roads, fences, terrain, and
  object candidates;
- load wave definitions through `WaveData_LoadFromFile` at `0x006387F0`;
- construct default Trigger/TimeLine scripts, including `on START GAME`,
  `on START WAVE 1`, `on SOLOMON RUNS`, `Fortify Monster HP`, and
  `Fortify Monster Speed` actions;
- attach the generated definitions to RegionLayout and release temporary
  geometry arrays.

The generator contains one recursive call at `0x0063ADC9`. Its empty-candidate
interpolation branch is at `0x0063D78F`, immediately after the candidate lookup
at `0x0063D781`. The loader's existing Boneyard generator patch redirects that
branch to cleanup when the candidate count is zero, preventing stock code from
interpolating an empty candidate list.

The editor path builder at `0x005824A0` formats
`%s\mylevels\%s.boneyard` (and the parallel ratings path), then passes it to
the shared resolver. The editor open/setup path at `0x00582CA0` uses the same
resolved file.

## Path resolution and staging

The shared resolver is `0x004237D0`. When sandbox mode is active it emits
`sandbox\%s`. This yields two distinct valid overlay use cases:

| Mod intent | Manifest target |
| --- | --- |
| Replace a shipped level | `data/levels/survival.boneyard` (or another exact stock path) |
| Install an editor/custom level | `sandbox/DarkCloud/mylevels/Name.boneyard` |

Using `DarkCloud/mylevels/Name.boneyard` as a stage-relative target is wrong:
the file is copied outside the `sandbox` tree that `0x004237D0` reads.

The launcher now validates the native container before discovering either a
manual or downloaded Boneyard mod. The website performs the same validation
before publication. Website packages may contain Boneyards, Lua, or both; a
website download may not contain native DLL entry points.

The website remains an acquisition path, not a runtime dependency. Join
preflight uses the host's exact mod ID, version, and content hash, prefers an
exact manual installation or cache entry, downloads a missing package when the
configured website can provide it, and stages only that exact set. If the
website is unavailable, an exact manually installed/enabled set still reaches
the normal native multiplayer fingerprint check over direct P2P.

## Corpus results

All files below parse to exact EOF with maximum chunk depth 9 and zero named
buffers.

| File | Bytes | Chunks | Objects | Monster recipes | Roads | Fences | Sprite records | Terrain | TimeLines |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `story0.boneyard` | 40,565 | 879 | 116 | 1 | 61 | 21 | 133 | 12 | 1 |
| `story1.boneyard` | 212,160 | 9,015 | 230 | 2 | 48 | 34 | 193 | 7 | 1 |
| `survival.boneyard` | 3,059 | 73 | 0 | 6 | 0 | 0 | 0 | 0 | 1 |
| `tutorial.boneyard` | 33,220 | 676 | 92 | 7 | 53 | 28 | 90 | 4 | 0 |
| `sandbox/play.boneyard` | 252,690 | 9,704 | 408 | 15 | 79 | 18 | 341 | 0 | 1 |
| `New Boneyard 1.boneyard` | 154,858 | 8,061 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| committed flat fixture | 148,413 | 7,721 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

The committed fixture SHA-256 is
`7c7d23f2fbfcdf73b5bb7f4af0f836cc9d199997fe9c7dd38183c7659b6d949d`.
It was produced by the stock Create New Boneyard flow before placing an editor
prop. Its RegionLayout object lists and sprite list are empty, but its single
default TimeLine occupies 7,662 chunks. This is why a valid “blank Boneyard”
cannot be represented by a zero-byte test payload.

## Inspection tool

`tools/inspect_boneyard.py` validates the exact recursive grammar and native
Arena/RegionLayout envelope, calculates the file hash, and reports section and
native type counts.

```bash
python3 tools/inspect_boneyard.py path/to/level.boneyard
python3 tools/inspect_boneyard.py --json path/to/level.boneyard
```

The parser rejects empty, truncated, trailing, over-deep, over-large, and
structurally invalid files. It is an inspector and admission validator, not a
Boneyard editor: unknown native payload bytes remain opaque and are never
rewritten.

## Confidence and remaining boundaries

The container grammar, envelope counts, RegionLayout section order, object
manager encoding, native paths, and load/save call graph are directly verified
against the decompiler and all seven corpus files. Class names and type IDs are
cross-checked against the repository's native class/factory catalogs.

Some Arena header and reserved compatibility payload fields remain unnamed.
Their semantics are not required for safe distribution because validation is
read-only and the retail loader remains the sole materializer. Full authoring
of those fields or arbitrary Trigger/TimeLine bytecode would require a separate
editor-format project rather than additional join/download plumbing.
