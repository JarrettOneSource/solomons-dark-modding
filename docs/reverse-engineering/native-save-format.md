# Native save format and launcher persistence boundary

Status: **G10 closed** for retail `SolomonDark.exe` SHA-256
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.

The committed live corpus is
[`save-format-goldens.json`](../../tests/fixtures/webgame/save-format-goldens.json),
SHA-256 `eff14fb768603abfb47c6d94006a71d04dd2b77954c2458703ca06d773373b8d`.
It contains a fresh profile, a scripted mid-progression profile, and a
post-unlock profile. Every binary tree and every text settings file in those
captures reconstructs to the recorded byte length and SHA-256. The native
decoder/encoder is [`native_save_format.py`](../../tools/native_save_format.py),
and the self-provenancing live recorder is
[`record_live_save_format_goldens.py`](../../tests/re/record_live_save_format_goldens.py).
Raw native files are evidence-only; they are not committed.

This is a compatibility contract, not permission to inspect or modify an
owner's installation. The G10 evidence was generated in campaign-owned
`sav-*` instances from an isolated game replica. A browser importer must copy
a source first, hash the copy, decode the copy strictly, and leave the source
untouched.

## Conclusions an implementation must preserve

1. Retail has no save-file magic, schema version, or checksum. Its binary
   container is an untagged recursive little-endian `SyncBuffer` tree.
2. `darkdata.cfg` adds repeating-key XOR and a marker/LZ stream, but still has
   no integrity field. The codec is deterministic and is reproduced
   byte-for-byte by the committed encoder.
3. Retail binary saves are **not crash-safe**. They are created/truncated and
   replaced by one direct write. There is no temporary file, backup, flush,
   checksum, or rename transaction.
4. The durable profile and a resumable run are different lifetimes.
   `darkdata.cfg` holds cross-run profile state. `gamestate.sav` and
   `RegionN._cache` hold one named run. Run completion deliberately deletes
   region caches while preserving the profile.
5. Retail has one process-local profile root, not eight slots and not an
   account. The launcher supplies eight directories, metadata, archive
   validation, cloud API calls, and directory-level replacement around that
   native model.
6. The current launcher source has an important routing gap: it reports and
   junctions the selected slot at `stage\savegames`, while the observed native
   process writes below `stage\sandbox\savegames`. P6 must close that seam
   before claiming that native play, automatic backup, or restore targets the
   selected slot.

## Evidence and notation

Addresses are preferred-image virtual addresses for the retail executable
named above. The principal static entry points are:

| Address | Recovered role |
| ---: | --- |
| `0x00422240` | direct IOBuffer file writer |
| `0x004243C0` | IOBuffer reader and scalar zero-fill behavior |
| `0x004248F0` | direct `SyncBuffer` writer |
| `0x004258B0` | retail marker/LZ compressor |
| `0x005A8390` | missing-profile default initializer |
| `0x005BDB50` | `darkdata.cfg` profile loader |
| `0x005BC1B0` | profile-to-`SyncBuffer` serializer |
| `0x005BE0B0` | profile save and `darkdata.cfg` writer |
| `0x005BA1C0` | `gamestate.sav` path builder |
| `0x005CBE10` / `0x005CC210` | gameplay save/load |
| `0x005BA2B0` | `Region%d._cache` path builder |
| `0x00649F90` / `0x0063F460` | `Region::GoToSleep` save / `WakeUp` load |
| `0x005A13A0` / `0x005BC400` | Hall of Fame load / save |
| `0x0040C690` | `settings.txt` load-or-create and direct writer |
| `0x005BED10` | `Portraits\portrait%d.raw` writer |
| `0x00423120` | recursive `._cache` deletion |

`u32` and `i32` below are four-byte little-endian integers. A `bool` is one
byte and retail writes `00` or `01`. “Payload offset” means an offset inside a
node payload after decoding the `darkdata.cfg` wrapper; compressed file offsets
cannot be stable because one changed field can change every later back-reference.

The evidence bundle is `D:\codex-evidence\savere-20260806`. It includes the
read-only Ghidra extracts, live routing and corruption probes, the raw capture
trees, exact process cleanup receipts, the mutation table, and Windows-side
hashes.

## Files

### Native root

The paths are relative to the native `sandbox` root copied into a retail or
staged game. In G10's isolated launches that root was `<stage>\sandbox`. The
profile root below it is `savegames\solomondark`. A named in-progress run adds
`savegames\<RUN-NAME>` under that profile root. The uppercase run directory is
a resume namespace, not an account id; independent fresh captures produced
`INGENUIUS` and `SATURNINUS`.

The live launcher's `APPDATA` profile is separate from this observed relative
path. Do not infer that changing `APPDATA`, or reporting a
`SavegamesRootPath`, redirects the native relative `sandbox\savegames` path.

### Player persistence census

| Native relative path | Lifetime and content | Read | Write / delete | Physical write pattern |
| --- | --- | --- | --- | --- |
| `settings.txt` | Process settings, controls, legacy identity/auth strings, resume selector | Boot/config construction at `0x0040C690` | Created when absent and rewritten by the configuration owner | Inline `_wcreat`/close, `_wopen(0x8002)`, one `__write`, close; in-place, no backup |
| `savegames\solomondark\darkdata.cfg` | Cross-run profile: gold, class selector state, tutorial/profile flags, Luthacus storage, Hagatha state, Shlorio fee, portrait counters | Boot/profile construction at `0x005BDB50` | `0x005BE0B0`; confirmed after profile operations, completed-run archival, tutorial completion, and game destruction/quit | `0x00422240`: direct create/truncate and one write; no atomic rename or backup |
| `savegames\solomondark\halloffame.dat` | Durable Hall of Fame entries and referenced wizard/portrait state | Hall construction at `0x005A13A0` | `0x005BC400`; a death path calls it when the death timer reaches 300 | Plain `SyncBuffer`, same direct writer |
| `savegames\solomondark\savegames\<RUN-NAME>\gamestate.sav` | Top-level resumable gameplay/session object graph | Resume/load at `0x005CC210` | Gameplay snapshot/destruction at `0x005CBE10`; run lifecycle decides whether it remains resumable | Plain `SyncBuffer`, same direct writer |
| `savegames\solomondark\savegames\<RUN-NAME>\Region<N>._cache` | Sleeping region object graph: world actors, region-local state, and serialized actor/progression payloads | `Region::WakeUp` at `0x0063F460` | `Region::GoToSleep` at `0x00649F90`; recursively deleted by `0x00423120` at retry/new-run/completed-run teardown | Plain `SyncBuffer`, same direct writer; deletion is direct and recursive |
| `Portraits\portrait<N>.raw` | Raw Hall of Fame portrait pixels; `N` is carried by profile counters | Hall/portrait presentation | `0x005BED10` writes a captured graphics buffer and advances profile `+0xF8/+0xFC` | Direct raw buffer write; no header, checksum, or backup |

There is no native profile-slot manifest. There is also no confirmed native
routine that atomically replaces, backs up, or deletes `darkdata.cfg`. The
confirmed destructive cleanup targets files whose suffix is `._cache`; it does
not select a “best” duplicate and does not recover one.

### Read-only or adjacent persistent files

These paths are part of the native filesystem surface but are not the player's
portable save ledger:

| Path | Status |
| --- | --- |
| `playfactor.cfg` | Optional boot-time tuning configuration loaded by `0x005BAB60`; no native writer was found. It is input, not player progression. |
| `social\__achievements.dat` | Achievement/content registry input read at `0x00445480`. It was absent from all live G10 captures and no writer was found. |
| `DarkCloud\mylevels\*.boneyard` and `play.boneyard` | User/editor map content and selected-map materialization, not profile state. Their format belongs to [`native-boneyards-and-world.md`](native-boneyards-and-world.md) and must not be merged into a save-account record. |
| `.sdmod\`, logs, runtime flags, mod storage | Launcher/loader state, not retail player persistence. |

## Binary format

### `SyncBuffer`: the common container

There is no leading header. Parsing starts at byte zero with one `Buffer`:

```text
Buffer := Node
          u32 named_buffer_count
          repeated named_buffer_count times {
            u32 name_byte_count_including_NUL
            u8  utf8_name[name_byte_count_including_NUL]  // final byte 00
            Buffer nested_buffer
          }

Node := u32 payload_byte_count
        u8  payload[payload_byte_count]
        u32 child_count
        Node children[child_count]
```

All counts and scalar payload values recovered in this campaign are
little-endian. Names are NUL-terminated UTF-8, and their encoded length includes
the NUL. The stream has:

- no magic;
- no version;
- no root byte length;
- no per-node type tag;
- no checksum; and
- no trailing index.

The end of the recursively parsed root plus its named buffers must be the end of
the file for an unambiguous strict decode. Retail's object-specific serializer
and vtable call order supply all types. A portable preservation tool must retain
every payload byte and child order, even when semantics are unknown.

Names are lookup keys. A browser decoder must reject two named buffers with the
same name in one `Buffer`; silently choosing first or last creates an
implementation-dependent save. The committed decoder also refuses truncated
lengths, unclaimed trailing bytes, non-NUL names, impossible child counts,
excessive depth, and excessive size instead of guessing.

`gamestate.sav`, `halloffame.dat`, and every `Region<N>._cache` are exactly this
plain stream. The live Region 4 files in each G10 fixture are 2,068 bytes,
contain one buffer and 34 nodes, have maximum child depth four, carry 1,792
payload bytes, and round-trip byte-identically. Their three distinct SHA-256
values prove the recorder did not collapse changing opaque payloads into a
schema-only representation.

### `darkdata.cfg` wrapper

`darkdata.cfg` stores a `SyncBuffer`, but applies these transforms in order when
writing:

```text
SyncBuffer bytes -> repeating-key XOR -> marker/LZ compressor -> file bytes
```

Decoding reverses them: marker/LZ decompress, then repeating-key XOR, then
`SyncBuffer` parse. The exact UTF-8 XOR key is:

```text
MagicEncryptionWord="SolomonDarkEncryption"|there$w#st w&187sfj21<TAB>89n4v 1984x98mn12xc39931c87241@@@@@@
```

`<TAB>` is one byte `09`, not the five literal characters shown here. The
fixture records the key SHA-256 as
`27c0dc1eb34b7d60a2f79cbb60cab0a2da05e336dbf8d75ff8b68d4fad5d0cf3`.
Byte `i` is XORed with `key[i % key_length]`.

The compressed stream is:

```text
u8 marker
commands until physical EOF:
  byte != marker       => literal byte
  marker 00            => literal marker
  marker length offset => copy `length` bytes from output[-offset]
```

`length` and `offset` are unsigned base-128 integers written most-significant
group first. Bit 7 means another group follows; bits 0..6 carry the group.
Offsets are backward distances and may overlap the bytes being emitted. Retail
caps compression candidates at distance 99,999 and the decompressor's output at
32 MiB.

To reproduce retail bytes, choose the least-frequent byte as the marker, with
the lower byte winning a frequency tie. The compressor indexes two-byte
prefixes, examines newest candidates first, takes only a strictly longer match,
and therefore preserves the newest candidate on equal lengths. Matches of
length at least eight are accepted. Lengths four through seven are accepted
only when their encoded distance fits respectively one, two, three, or four
base-128 groups. Remaining bytes are literals. These details are why a merely
compatible compressor does not meet the round-trip bar.

The wrapper has no magic, version, salt, nonce, authentication tag, or checksum.
The XOR is obfuscation, not encryption or integrity protection.

## `darkdata.cfg` field census

After wrapper decoding, the root node has an empty payload and exactly six
ordered child nodes. It has no named buffers.

| Root child | Payload layout | Runtime source | Meaning |
| ---: | --- | --- | --- |
| 0 | fixed 118-byte core, detailed below | profile object `0x0081A330` | gold, class/profile state, portrait/stat fields |
| 1 | polymorphic inventory serialization | profile `+0x8C` (`DAT_0081A3BC`) | Luthacus Scavenged Goods storage |
| 2 | `u32 count`, then `i32 selector[count]` | profile `+0x60/+0x64` | Hagatha bulk selector list |
| 3 | `bool first_mix[30]` | profile `+0x6C..+0x89` | per-selector first-mix/purchase flags |
| 4 | one `i32` | profile `+0x100` (`DAT_0081A430`) | current Shlorio Dowsing fee |
| 5 | empty payload, zero children | reserved | retail writes an empty reserved node |

The child's payloads are exact preservation boundaries. Child 1 is decoded
structurally, but item subclass payload meanings are not guessed; its payload
hex and descendants remain in every fixture. Empty fresh storage is four zero
bytes and zero descendants.

### Core child 0

The following offsets are relative to child 0's 118-byte payload. Array ranges
are contiguous and their runtime ranges are inclusive.

| Payload bytes | Type | Runtime field | Portable meaning | Fresh value |
| ---: | --- | ---: | --- | --- |
| `0x00..0x03` | `i32` | profile `+0x58` | persistent profile gold | `500` |
| `0x04..0x0D` | `bool[10]` | `+0x90..+0x99` | class-availability selector flags; class-name mapping not yet reversed | `0,1,1,1,0,1,1,0,0,1` |
| `0x0E` | `bool` | `+0x104` | stock tutorial/game-over gate | `1` |
| `0x0F..0x18` | `bool[10]` | `+0x9A..+0xA3` | class-selection enabled flags; class-name mapping not yet reversed | ten `1` bytes |
| `0x19..0x40` | `i32[10]` | `+0xA4..+0xCB` | class display-order permutation | `9,1,0,2,7,4,3,8,5,6` |
| `0x41..0x44` | `i32` | `+0xF4` | opaque persistent statistic | `1000` |
| `0x45..0x6C` | `i32[10]` | `+0xCC..+0xF3` | canonical class-selector permutation | `0,1,2,3,4,5,6,7,8,9` |
| `0x6D..0x70` | `i32` | `+0xF8` | next `portrait<N>.raw` index | `100` |
| `0x71..0x74` | `i32` | `+0xFC` | most recently written portrait index | `0` |
| `0x75` | `bool` | `+0x105` | opaque profile flag | `0` |

The JSON expands every array element into an individual row with payload
offset, size, type, runtime offset, semantic status, and captured value. That is
the authoritative machine-readable field table.

### Byte-exact first persisted profile

`0x005A8390` initializes the core defaults above, an empty Hagatha selector
list, 30 clear first-mix flags, empty Luthacus storage, and a Shlorio fee:

```text
(Integer(10) + 10) * 50  => 500, 550, ..., 950
```

The profile serializer then sets first-mix flag index 27 before emitting child
3. Thus “fresh in memory before first save” has 30 zero bytes, while the first
settled file has only byte 27 set. Conflating those states makes a nominal
default fixture disagree with what retail actually persists.

For the committed fresh capture, the random fee was 500. The decoded default
tree is exactly 220 bytes:

| Decoded stream location | Contents |
| ---: | --- |
| `0x000` | root payload length `0`, then child count `6` |
| `0x008`, payload `0x00C..0x081` | child 0, 118-byte core |
| `0x086`, payload `0x08A..0x08D` | child 1, `00 00 00 00` |
| `0x092`, payload `0x096..0x099` | child 2, selector count `0` |
| `0x09E`, payload `0x0A2..0x0BF` | child 3, 30 flags; only index 27 is `01` |
| `0x0C4`, payload `0x0C8..0x0CB` | child 4, fee `F4 01 00 00` |
| `0x0D0` | empty child 5 |
| `0x0D8` | root named-buffer count `0`; stream ends at `0x0DC` |

After XOR and retail compression it is 211 bytes, starts with marker `00`, and
has SHA-256
`acd77847db8ffdcb6915184eeaa77656e9d127502ff7858542d4dadf7db1a5c9`.
The fixture embeds the complete decoded tree, so the raw evidence file is not
needed in the repository to reproduce those 211 bytes exactly.

## Content semantics and runtime mapping

### Durable profile versus run state

The G8 hub investigation established the state which survives region
replacement and completed-run return. Its
[`State crossing the hub/run boundary`](native-hub-and-economy.md#state-crossing-the-hubrun-boundary)
section is the semantic authority; G10 identifies where the durable subset is
serialized.

| Gameplay state | Runtime owner | Persistence boundary |
| --- | --- | --- |
| gold | profile `+0x58` | `darkdata` core child 0, payload `0x00` |
| Luthacus storage | profile `+0x8C` | `darkdata` child 1 polymorphic inventory tree |
| Hagatha bulk list | profile `+0x60/+0x64` | `darkdata` child 2 |
| Hagatha first-mix flags | profile `+0x6C` | `darkdata` child 3 |
| Shlorio fee | profile `+0x100` | `darkdata` child 4 |
| active backpack/equipment | Gameplay `+0x13B8/+0x1410` and participant ledger | serialized in resumable gameplay/region object trees; completed-run archival moves eligible contents into Luthacus child 1 |
| selected Boneyard and map unlock state | Gameplay `+0x1BD8` / `+0x1CDC` | run/session serializers, not the fixed `darkdata` core |
| generated hub actors/catalogs | region/hub objects | regenerated after return; region caches are disposable |

This matches G8's observed loop: a finished run retains eligible equipment and
backpack contents in a named Sack, optionally sweeps Last Word ground goods and
gold, writes profile gold/inventory/progression/storage, rebuilds hub catalogs,
and lets the next run consume the same participant-private profile state.

### Skills, books, class, and loadout

G6's dedicated progression campaign was not landed at the source revision of
the G10 capture, so the recording did not infer field meanings from an empty
skill book. The now-landed
[`native progression and per-skill effects`](native-progression-and-skills.md#persistence-boundary)
document supplies those meanings and the per-actor boundary. The earlier
[`Skill Concentration and Discipline`](../re/skills-concentration-discipline.md#persistence-and-lifecycle)
analysis establishes the current persistence boundary:

- progression serializer `0x0065EE80` serializes permanent ranks, selected
  element root at progression `+0x82C`, discipline root at `+0x830`, starting
  primary at `+0x86C`, starting secondary at `+0x870`, and Hagatha ownership
  bytes `+0x7CC..+0x7FD` inside the resumable run object graph;
- concentration A/B process lanes and the Mind Chug timer `+0x828` are not
  serialized;
- the actor exposes progression at actor `+0x200`, with row table pointer/count
  at progression `+0x20/+0x24`; rows are `0x70` bytes, permanent rank is row
  `+0x20`, effective rank row `+0x22`, and category row `+0x26`; and
- learned run ranks and loadout must not be mistaken for the cross-run class
  selector arrays in `darkdata` child 0.

The browser's per-entity progression/book model is therefore populated from
the resumable `gamestate`/Region object graph when resuming a run. A completed
run keeps only the fields explicitly archived into the durable profile. The
machine decoder preserves every opaque progression node byte-for-byte, but the
unmapped object-to-node field census remains under *Not Yet Reversed* until G6
or a dedicated save-object pass names it.

### Profile identity and statistics

Retail exposes no durable account UUID in `darkdata.cfg`. Identity-like values
are split across:

- the named run directory and serialized gameplay/player name;
- `settings.txt` legacy `System.Username`, `System.Userpassword`, and
  `System.Token` strings;
- `System.ComputerName`, which varied across isolated processes and is not a
  stable account key;
- Hall of Fame wizard records and portrait indices; and
- opaque profile statistic `+0xF4`.

None is a safe web account identity. A migration must bind the imported data to
the already-authenticated website account and must never import or upload the
legacy password/token settings.

### `settings.txt`

The live file is UTF-8-compatible text with one `key=value` entry per line,
CRLF line endings, and a final CRLF. It has no header, version, escaping layer,
or checksum. Retail's writer emits values in registry order. All three captures
contain 37 entries and are fully decoded in the fixture:

| Group | Keys and values carried |
| --- | --- |
| Graphics | `Resolution`, `Fullscreen`, `SaveVideoMemory` |
| Legacy system | `Username`, `Userpassword`, `Token`, `ComputerName`, `IPAddress`, `PlayCount` |
| Presentation | `ComplexLighting`, `ZoomFX`, `ComplexShadows`, `MultipleShadows`, `FastCPU`, `LightQuality` |
| Gameplay | `CastSecondariesOnMouse`, `KidMode`, `Controls`, `ItemRecipeUID`, `UID`, `Resume`, `Shredded` |
| Keyboard controls | up/down/left/right, inventory, skills, menu, and belt slots 1 through 8 |

The fixture stores line number, row kind, key, value, encoding, newline policy,
and final-newline presence. Re-encoding those fields reproduces the raw hashes.
Browser display preferences should be mapped deliberately; process addresses,
network addresses, credentials, resume paths, and native-only renderer toggles
must not be copied blindly.

## Lifecycle

### Boot and resume

1. Configuration construction reads or creates `settings.txt`.
2. Profile construction tries `darkdata.cfg`. A missing or unreadable file
   takes the missing-profile initializer path. A structurally short file does
   not necessarily take that path; see *Corruption behavior*.
3. Hall construction reads `halloffame.dat` if present.
4. `playfactor.cfg` and achievement content are optional boot inputs.
5. A requested resumable run loads `gamestate.sav`; regions materialize from
   `Region<N>._cache` when woken.

No step compares a save version or checksum because none exists.

### Region transition and hub return

`Region::GoToSleep` serializes the outgoing region directly to its numbered
cache. `Region::WakeUp` parses the incoming cache, or builds the region through
its normal constructor path when no usable cache is supplied. The hub objects
themselves are regenerated, while profile-owned gold, Luthacus storage,
Hagatha state, class/profile state, and the active run's actor/progression
objects live outside a replaced region.

### Run end

Completed-run processor `0x005BE320`, called from game-over archival
`0x005C9670`, moves eligible run output into the durable profile and invokes
`0x005BE0B0`. Return path `0x005CF920` switches back to the hub, removes
disposable `._cache` files recursively, and rebuilds hub catalogs. It does not
turn region caches into durable account state.

### Quit

The gameplay destructor at `0x005CD3A0` writes the profile and the resumable
gameplay snapshot. Because both are independent direct overwrites, a crash or
power loss may leave one new and one old, or a truncated file. There is no
multi-file transaction. A browser implementation should transact its own
normalized state atomically, but a native export intended for retail must stage
the complete file set and replace the directory only after every encoded file
has been verified.

### Delete

Retail's confirmed cleanup recursively deletes every `._cache` match for the
target run tree during retry/new-run/return teardown. It does not preserve the
newest of duplicates or move them to a recycle location. No native global
profile-slot deletion contract was found because retail does not expose the
launcher's eight-slot model.

The current launcher UI has remote cloud-slot deletion through
`DELETE api/saves/{slot}`. Its local catalog has select, rename, import, restore,
and backup-receipt operations; no local “delete this slot” operation is present
in [`LocalSaveCatalog.cs`](../../SolomonDarkModLauncher.UI/src/Infrastructure/LocalSaveCatalog.cs).
A P6 local delete must therefore be specified explicitly rather than inferred
from cloud deletion.

## Corruption behavior

Retail's `0x004243C0` reader tracks an internal error state, but scalar reads at
or beyond EOF yield zero/false and the profile caller does not enforce the
error. A live G10 probe placed a one-byte `darkdata.cfg` in a disposable
campaign-owned replica. Retail:

1. did not reject it;
2. did not rename it or create a backup;
3. loaded zeroed profile fields, including gold `0` and zero arrays;
4. generated a current Shlorio fee; and
5. later overwrote the file with a normalized 135-byte save derived from that
   partial/zero state.

This is not the same as a missing file, whose profile defaults include 500
gold and the class arrays above. A faithful native-mode loader must distinguish
“missing” from “truncated” and must not silently substitute fresh defaults for
the latter.

The browser migration boundary should still fail closed: strict-decode a copied
source, report the corrupt/truncated field and offset, and do not create or
replace a web save. That is an importer safety rule, not a claim that retail
itself is safe. Native parity for corrupt `gamestate.sav`, Hall of Fame trees,
polymorphic inventory nodes, and Region caches has not been live-matrixed; those
cases are explicitly *Not Yet Reversed* rather than assigned guessed recovery.

## Launcher layer

The launcher source is first-class evidence for everything in this section.
It does not change the native bytes; it wraps directories and archives around
them.

### Local slots and settings ownership

[`LauncherUiSettingsStore.cs`](../../SolomonDarkModLauncher.UI/src/Infrastructure/LauncherUiSettingsStore.cs)
normally owns `%LOCALAPPDATA%\SolomonDarkMultiplayerBeta` through the shared
path policy. Beneath it:

```text
settings.json                 active slot and launcher UI settings
runtime\                      launcher runtime work
saves\slot-1\slot.json       display name and last cloud-backup receipt
saves\slot-1\savegames\      complete native savegames root
...
saves\slot-8\...
```

The active slot is zero-based in `settings.json`, range-checked to `0..7`, and
falls back to slot zero when out of range. `settings.json` and each `slot.json`
are written to a sibling `.tmp` and then moved over the destination. There are
exactly eight slots. Slot metadata is launcher state, not part of a native
archive's `solomondark` tree.

Import accepts only a selected `savegames` directory containing a
`solomondark` child. It copies the complete source into a sibling
`.incoming-<GUID>` directory, moves the old destination to
`.previous-<GUID>`, moves incoming to the destination, then deletes previous.
On failure before the new destination exists, it moves previous back. It
rejects overlapping paths and file/directory reparse points and preserves file
modification times. Restore uses the same
[`SaveDirectoryMirror.cs`](../../SolomonDarkModLauncher.UI/src/Infrastructure/SaveDirectoryMirror.cs)
replacement and clears the prior backup receipt.

That directory swap protects against the retail writer's lack of atomicity only
when the native process is actually writing the selected directory and is not
concurrently active during replacement.

### Current selected-slot routing defect

The intended path is:

```text
Settings active slot
  -> LocalSaveCatalog.Active.SavegamesRootPath
  -> launcher --savegames-root
  -> stage\savegames junction/mirror
  -> native writes selected slot
```

The last arrow is false in the current source/runtime combination. Stage build
first calls
[`StageSandboxCompatibilityLinks.Materialize(stageRoot)`](../../SolomonDarkModLauncher/src/Staging/StageSandboxCompatibilityLinks.cs),
which points `stage\savegames` at `stage\sandbox\savegames`. Launch with an
override recreates only `stage\savegames` toward the selected slot. It does not
redirect `stage\sandbox\savegames`.

The isolated `sav-route` proof passed an owned
`--savegames-root D:\sd-savere-20260806\runtime\savere-owned-slot\savegames`.
The launch receipt reported that exact path and `stage\savegames` resolved to
it, yet `darkdata.cfg` and `Region4._cache` appeared only beneath
`stage\sandbox\savegames\solomondark`; the requested root remained empty.

Consequences:

- `CloudSaveBackupCoordinator.Start` validates a reported path, not the native
  file location;
- a Windows watcher on the selected slot sees no native changes;
- the final close backup can archive an empty/stale selected slot; and
- a restore into the slot need not affect the native sandbox used by the next
  launch.

G10 documents this seam and does not change launcher behavior. P6 must fix it
and add an end-to-end path proof: write a native sentinel through retail,
observe it inside the selected slot, archive it, restore it to a different
empty slot, launch that slot, and observe the native field. Source-level path
assertions alone are insufficient.

### Cloud archive

[`CloudSaveArchive.cs`](../../SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveArchive.cs)
defines launcher archive version 1. This version is **not** a native save-file
version. The ZIP contains:

```text
manifest.json
savegames/solomondark/...
```

Files are sorted case-insensitively and get stable ZIP timestamp
`2000-01-01T00:00:00Z`. The manifest carries schema version, zero-based slot,
optional name, and for every file its path, uncompressed byte count, and
SHA-256. The launcher also fingerprints the complete ZIP.

Validation limits are 16 MiB compressed, 64 MiB expanded, 256 files, and a
128 KiB manifest. Restore rejects duplicate/case-colliding paths, traversal,
absolute or colon paths, backslashes, symlinks, entries outside
`savegames/solomondark`, wrong slot/version, count/size/hash mismatches, and
overlong names. It extracts into `.restore-<GUID>\savegames`, validates each
file while writing, and only then invokes the directory swap.

Automatic backup watches the effective tree. Native-junction mode waits for a
three-second quiet period and uploads; Wine mirror mode copies the stage tree
back only on close. Close always performs a final backup, and a watcher failure
is reported for retry at close. Unchanged archive SHA skips upload.

## Account linkage and the P6 seam

### What exists today

The UI client obtains a short-lived Steam website session by invoking launcher
`directory-auth`. The returned model contains a bearer token, Steam ID, expiry,
and optional linked website account `(id, username)`. It keeps the token in
memory; no website password is stored by this flow. Unlink calls
`DELETE api/auth/steam`.

[`CloudSaveClient.cs`](../../SolomonDarkModLauncher.UI/src/Infrastructure/CloudSaveClient.cs)
assumes these authenticated endpoints:

| Method/path | Client expectation |
| --- | --- |
| `GET api/saves` | list linked account's slots |
| `PUT api/saves/{slot}` | upload ZIP and return matching version/count/size/SHA receipt |
| `GET api/saves/{slot}` | download ZIP for strict local validation/restore |
| `DELETE api/saves/{slot}` | delete remote slot |

If no website account is linked, listing is empty and backup/restore/delete are
disabled. The launcher client and archive contract are present. This G10
checkout does not contain or verify a deployed server implementation of those
save endpoints, and the live selected-slot defect prevents treating the client
flow as an end-to-end native backup proof.

### What P6 needs

The webgame should ride the existing authenticated `api/` boundary. G10 does
not add website routes, database tables, or publication. P6 must choose and
implement one authoritative server representation:

- a normalized, explicitly versioned browser-save document; or
- the launcher ZIP as a lossless native attachment plus a separately versioned
  browser projection.

Whichever is chosen, the seam must enforce:

1. the authenticated website account is the owner; native usernames, tokens,
   computer values, and run-directory names are never account keys;
2. slot and schema version are server-validated;
3. upload has optimistic concurrency or an explicit overwrite confirmation;
4. content hash, size, and receipt are verified end to end;
5. import is an explicit copy operation with preview, never an implicit scan of
   a retail install;
6. raw native source and pre-migration web save remain recoverable;
7. duplicate named buffers, malformed paths, truncated fields, and unknown
   schema versions are rejected without choosing a candidate; and
8. credentials from native `settings.txt` are excluded.

A real-player migration can then be implemented without another binary pass:
copy the user-selected launcher archive or `savegames` tree, hash it, strict
decode through the G10 codec, present the decoded profile/run inventory, map
only understood fields into the current browser schema, retain opaque source
bytes as an attachment if policy allows, re-encode and verify the native copy,
then create a new account-owned web save. No step writes the original native
tree.

## Golden corpus

The recorder derives its own Git revision and Windows-side executable/loader
hashes; it has no provenance override parameters. Each native tree was required
to produce at least 40 consecutive identical structural samples spanning at
least two seconds while the exact owned process remained runnable. “Process
exited” is a broken setup; “not yet stable” is busy and bounded by a separate
deadline.

| Scenario | Driver | `darkdata.cfg` SHA-256 | Decoded distinguishing state | Settle proof |
| --- | --- | --- | --- | --- |
| `fresh_profile` | native initializer `0x005A8390`, then native save `0x005BE0B0` | `acd77847db8ffdcb6915184eeaa77656e9d127502ff7858542d4dadf7db1a5c9` | gold 500; settled flag 27; fee 500 | 40 identical samples, 5.475 s |
| `mid_progression_after_scripted_run` | live reward checkpoints 500 -> 625 -> 875, then native save | `7d870123ceb96050a0a437f51188855b15a643742a27693595232c724536359e` | gold 875; settled flag 27; fee 650 | 40 identical samples, 5.363 s |
| `post_unlock` | native Hagatha perk apply selector 0, matching first-mix flag, 250 gold, then save | `01c95c269093610fdb31a9a1857bff5f23a134555318032609c0fe0435ba10e2` | gold 250; flags 0 and 27; progression selector 0 observed live; fee 600 | 40 identical samples, 5.351 s |

Every scenario also carries its own Region 4 tree and 37-entry `settings.txt`.
All nine files re-encode to the committed length and SHA. Addresses observed in
live memory are provenance, not portable persisted values.

## Browser implementation contract

An implementing agent can treat the following as the minimum safe design:

- Use the strict decoder for import/preservation and keep bounds on byte count,
  node count, depth, decompressed darkdata size, and path count.
- Preserve ordered opaque nodes and reject ambiguous named buffers.
- Keep a versioned browser schema even though retail has no version.
- Commit browser saves transactionally as one account/slot revision. Never
  imitate retail's multi-file partial-write hazard internally.
- For native export, encode every file into a new staging directory, parse it
  again, compare bytes/hashes, then use the launcher's recoverable directory
  swap while no native process is running.
- Separate durable profile fields from resumable run/object graphs. Do not carry
  concentration lanes, timers, generated hub catalogs, or disposable region
  caches into a fresh run merely because they appear in a snapshot.
- Preserve the native missing-versus-truncated distinction in any retail-parity
  load mode. The account importer remains strict and non-destructive.
- Never derive account linkage from native strings. Use the authenticated web
  account and explicit user action.

## Not Yet Reversed

These boundaries are deliberately opaque rather than speculative:

- The semantic class names corresponding to the two 10-boolean arrays and two
  10-integer permutations in `darkdata` child 0. Bounds, types, offsets,
  defaults, and stability are known.
- Profile statistic `+0xF4` and flag `+0x105`. Both are byte-exact and stable in
  all three captures; consumers were not identified.
- The item-subclass field census inside nonempty Luthacus child 1. The complete
  polymorphic `SyncBuffer` subtree is preserved, and G8 establishes its storage
  semantics, but G10 did not generate a nonempty storage specimen.
- The complete object-to-node semantic maps for `gamestate.sav`,
  `halloffame.dat`, and arbitrary `Region<N>._cache`. Their container is fully
  decoded and re-encoded; payload bounds/order/hex are retained. Naming every
  polymorphic object field needs dedicated specimens and vtable serializers.
- Exact raw portrait width, height, pixel format, and orientation. The file is
  headerless and its writer/counters are known, but no portrait was generated
  in the isolated corpus.
- Live failure matrices for corrupt/truncated gamestate, Hall of Fame,
  nonempty polymorphic inventory, and region files. Only `darkdata.cfg` was
  mutated live; inventing recovery for the others would be unsafe.
- Production deployment of the browser P6 save service. The 2026-08-20
  integration trace below records the local normalized-schema and concurrency
  policy; no production publication is claimed by this native report.
- A nonempty permanent skill-book save specimen. G6 now supplies the runtime
  field semantics and serializer boundary cited above; G10's byte offsets and
  round-trip preservation do not need to be re-derived.

## 2026-08-20 web-port integration trace

The first browser-save implementation pass re-ran the save/load and terminal
cleanup call graph against the same read-only analyzed retail executable named
at the top of this report. This does not change the G10 byte-format findings;
it closes the caller membership needed to place browser checkpoints and the
single-slot Game Over deletion boundary.

### Complete direct-reference census

`0x005BE0B0` has exactly eleven direct code references in the analyzed image:

| Caller | Recovered persistence edge |
| --- | --- |
| `0x004FA290` | `LACE!` selector/unlock mutation sets profile flag `0x0081A435`. |
| `0x00562520` | inventory/stat presentation consumes a one-shot profile milestone and saves it. |
| `0x005684C0` | dirty `InventoryScreen` close/destruction. |
| `0x0056C230` | dirty `PerkShop` close/destruction. |
| `0x0056C340` | accepted Hagatha/perk purchase records its first-mix flag. |
| `0x0056CCA0` | `InventoryShop` close/destruction. |
| `0x005BE320` | completed-run item/profile archival. |
| `0x005C3DB0` | legacy `PlayAccount` destruction. |
| `0x005CDDD0` | every requested gameplay region switch, before the same-region no-op test. |
| `0x005CD3A0` | full `Game` destruction, immediately before the resumable gameplay writer. |
| `0x005CF4F0` | Boneyard Game Over completion, immediately before completed-run archival. |

The resumable gameplay writer `0x005CBE10` has exactly two direct callers:
MapPicker/run entry `0x0050E5E0` and `Game` destruction `0x005CD3A0`.
The resumable gameplay loader `0x005CC210` has exactly one direct caller,
front-end resume constructor `0x005AAA30`.

Recursive cache cleanup `0x00423120` has seven direct references in six
functions: its own recursion plus full reset `0x005CF920`, Mortuary teardown
`0x00509200`, retry/new-game handling `0x0058F500`, both normal and Boneyard
completion branches in `GameOver::Tick` `0x005CF4F0`, and Survival new-run
entry `0x0058E8C0`. The helper selects only the `._cache` suffix; it does not
physically delete `gamestate.sav`.

### Terminal resume consequence

At the completion edge, `GameOver::Tick` closes its surface, runs completed-run
profile archival, replaces the active run string with the empty string, builds
the run cleanup path, recursively removes the region caches, and then enters
the stock front-end lineage. Therefore the old run is no longer an active
`Last Game` candidate even though an orphaned `gamestate.sav` byte stream may
remain on disk. Retail's observable contract is invalidation of the resume
namespace, not secure erasure of every byte.

The first browser pass owned one transactional normalized document instead of
the retail profile/run/cache file split and deleted that whole document on the
first authoritative Game Over edge. That is not native-equivalent: it removes
the durable profile together with the resume namespace, even though retail
archives the completed run into `darkdata.cfg` before invalidating Last Game.
The 2026-08-23 reopening below supersedes that browser mapping. One atomic web
record remains appropriate, but it must contain two independently lived parts:
a durable profile and a nullable resumable continuation.

### Browser checkpoint mapping

The web host remains the only producer of save contents. It emits a versioned
owner-only document at construction, accepted economy/progression mutations,
Hub/Boneyard transitions, pause boundaries, and a bounded periodic
active-run checkpoint. The browser is only a storage adapter: authenticated
owners transact account slot zero; anonymous owners transact IndexedDB slot
zero. `Last Game` returns the opaque document to a fresh host, which validates
and revives the authoritative simulation before admitting the player.

This normalized document is a web schema, not native `SyncBuffer`, and does
not claim native export compatibility. The existing launcher ZIP and eight
launcher slots remain a separate lossless-native attachment system. A future
mod-list field and native import/export projection are outside this first-slot
pass.

## 2026-08-22 clean-leave and autosave lifecycle recheck

The browser leave/autosave reopening revalidated the save owner against the
same read-only Ghidra project and retail executable identified above. The
executable was re-hashed as
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`;
all addresses below remain preferred-image virtual addresses.

### Clean leave is a save-before-teardown edge

- `Game` destruction at `0x005CD3A0` first installs the `Game` vtable, retires
  any live modal, clears the profile gate, calls profile writer `0x005BE0B0`,
  then calls resumable-run writer `0x005CBE10`. Object/world teardown follows
  those two writes.
- The deleting wrapper `0x005CFA60` has the destructor as its sole direct call.
  The stock gameplay `MAIN MENU` action leaves the gameplay owner through this
  ordinary destruction lineage; it is not a save-less socket-style exit.
- `0x005CBE10` still has exactly two direct callers: run entry
  `0x0050E5E0` and clean `Game` destruction `0x005CD3A0`. The sole loader
  `0x005CC210` still has exactly one caller, front-end Last Game constructor
  `0x005AAA30`.
- Region request `0x005CDDD0` still calls profile writer `0x005BE0B0` before
  testing whether the target is the current region. This confirms semantic
  boundary writes independently of clean destruction.
- Game Over `0x005CF4F0` retains its separate archive/profile/invalidation and
  cache-cleanup lineage. It must not be changed into a resumable leave save.

### No native periodic whole-run writer

The complete direct-reference census above remains unchanged. No fixed-tick,
wall-clock, frame, or idle caller of `0x005CBE10` exists. Retail therefore has
no periodic whole-run autosave interval to copy. Its protection comes from
semantic profile writes, region cache transitions, run-entry serialization,
and the synchronous final writer in `Game` destruction. Its direct overwrite
format remains non-crash-safe.

For the browser port, periodic active-run persistence is consequently a named
platform adaptation, not a recovered retail constant. It bounds loss when a
tab/process disappears before JavaScript can complete IndexedDB or an
authenticated HTTP write. The exact stock-equivalent browser path is the
explicit in-game leave action: request a final host-authored owner projection,
commit it to the selected storage adapter, and only then destroy the client
session. A browser process killed before that acknowledgement remains
fundamentally weaker than retail's synchronous destructor.

## 2026-08-23 durable-profile and update-compatibility reopening

The browser report that a deployment left Last Game unavailable and that an
attempted resume disconnected exposed two separate violations of the native
persistence boundary: historical web schema versions were discarded rather
than migrated, and Game Over deleted the durable profile together with the
active continuation. The retail executable was re-hashed as
`03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
Targeted read-only queries used the canonical `SolomonDark` Ghidra project
through replica slot 1; all addresses below are preferred-image addresses.

### Completed-run archival gate

Raw instructions at `0x005C9670` close the previously unresolved boolean passed
to completed-run processor `0x005BE320`:

- `Player +0x1C0` is initialized to zero by Player constructor `0x0052A500`.
- `0x005C9670` reads that byte, applies `SETZ`, and passes the result as the
  ordinary equipment/backpack-transfer flag. Clear means carried items are
  eligible for the retained Sack; set means that ordinary transfer is skipped.
- Player tick `0x00533520` sets `+0x1C0 = 1` only after a nearby active Ether
  Drain receives capture callback `0x005EE840`. This is the consumed-corpse
  branch, not a generic alive, victory, insurance, or disconnect flag.
- The adjacent argument remains progression `+0x7D8`, the Last Word gate that
  additionally sweeps eligible ground Sacks and Gold.

Thus the completed-run membership is exact: archive durable gold/profile
fields; retain eligible carried contents unless the corpse was consumed by
Ether Drain; optionally sweep Last Word ground contents; persist the resulting
profile; invalidate only the active run name and disposable caches.

### Browser consequence

A normalized browser row may remain one revision-conditional atomic document,
but its schema must represent the two native lifetimes explicitly:

- a durable participant profile containing the web-owned equivalents of gold,
  Luthacus storage, Hagatha ownership/first-mix/capacity and exact one-shot
  runtime state, Shlorio fee, permanent unforge/stat bonuses, and stable item
  identity; and
- a nullable owner-only continuation containing the active Hub/Boneyard
  simulation, loaded Boneyard identity, run state, mod state, and resume
  summary.

Game Over writes the archived profile with a null continuation. Last Game is
disabled for that record, but New Game consumes the same profile. Clean leave,
semantic checkpoints, periodic browser checkpoints, and deployment drain write
both parts with a live continuation. Known browser schemas 1 through 4 are
historical inputs to an explicit migration path; an update may not dim Last
Game or disconnect merely because implementation-owned runtime fields were
added. Every browser WebSocket layer must also admit the full declared document
bound; a smaller public-proxy cap rejects a valid run before migration can run.
Unknown/corrupt structures still fail closed, and the browser's abrupt
termination window remains the sole platform-blocked persistence edge.

## 2026-08-23 active-wizard replacement and saved-run distinction

The browser follow-up exposed a second lifetime collapse: it used one
`continuation` both for a saved current wizard and for the claim that an active
Boneyard run exists. It also retained a page-global checkpoint sequence and the
port's 10,000-gold fresh-player grant. The canonical executable was re-hashed
as `03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3`.
All queries below used the canonical read-only `SolomonDark` Ghidra project via
replica slot 1; addresses are preferred-image addresses.

### Title New Game owns current-wizard retirement

`0x0058E260` constructs the common MsgBox used before replacing a current
wizard. Its exact static strings are:

- title `Kill character?` at `0x00798474`;
- body `Starting a new game will kill off your current game and character
  (Lucritius will scavenge his equipment)!` at `0x00798408`; and
- common primary/secondary labels `YES` / `NO` at `0x0078C4CC` /
  `0x0078C4C8`.

The function has one direct caller, `0x0058E600`. That caller invokes it only
on the New Game control while its selected-profile/current-wizard flag at
owner `+0x474` is set. A false result returns without transitioning. A true
result obtains the current run namespace, clears/rebuilds profile/game state,
executes completed-wizard archival through the established save family, and
continues toward Create. Thus New Game does not silently reuse or replace the
current wizard.

### A saved Boneyard timeline is a different owner

`0x0058F500` is a separate selected-level branch with two dispatch references
in `UiOwner_DispatchControlAction 0x005A5530`. When the requested level already
has resume data, its MsgBox uses:

- title `RESUME PREVIOUS GAME?` at `0x00798540`; and
- body `Do you want to resume the previous game you were playing in this
  level?` at `0x007984F8`.

Acceptance calls the front-end Last Game constructor `0x005AAA30`, whose one
load call is `0x005CC210`. Refusal clears the prior selected-level cache and
continues with a new level. This per-level timeline decision is neither the
durable `darkdata.cfg` profile nor the title's current-wizard existence test.
A Hub game save can therefore be resumable without claiming an active
Boneyard run; its scene-local region, transition, and coordinate state are
regenerated on load.

### Fresh-profile value and tutorial boundary

The instruction body of missing-profile initializer `0x005A8390` begins with
`MOV dword ptr [profile+0x58], 500` and later writes tutorial-pending byte
`profile+0x104 = 1`. The existing G10 `fresh_profile` golden independently
records 40 settled samples with gold 500 and that pending field. The Website's
10,000 was never a retail default and must be removed.

This pass does not infer tutorial entry, rewards, dialogue, completion behavior,
or any field beyond the proven pending byte. The correct integration boundary
is the one fresh-profile/player constructor: it emits the proven 500-gold and
tutorial-pending defaults, after which the future tutorial system may apply
only evidence-backed mutations before handing the same participant to
Hub/Boneyard persistence. Save migration must never reset an existing profile
to the fresh values; legacy web wizards migrate pending false.

### Browser consequence

- The next normalized schema must distinguish saved current-wizard state from
  the derived active-Boneyard-run bit while still accepting schemas 1 through
  5.
- A Hub resume keeps durable wizard state but reconstructs its Hub scene and
  spawn. A Boneyard resume retains its exact active world/run.
- Each provisioned host owns its own checkpoint sequence. The browser store
  owns a separate monotonically revised slot; `(client stream, checkpoint
  sequence)` identifies the operation that a deployment/leave acknowledgement
  waits for.
- Every host-authored active document must carry the exact scavenged profile
  projection used if title New Game retires that wizard. The title may then
  invalidate the continuation after strict validation without synthesizing
  state from a rendered snapshot.
