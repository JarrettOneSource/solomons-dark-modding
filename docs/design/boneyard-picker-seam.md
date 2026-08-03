# Boneyard picker seam

This design is intentionally limited to Boneyard discovery, host selection,
stock launch handoff, multiplayer resolution, and the smallest usable
placeholder. ATC owns the visual frontend. Editor integration, Boneyard
authoring, new validation policy, preview generation, and general-purpose file
transfer are outside this change.

The stock boundary that this design preserves is documented in
[`docs/re/map-picker.md`](../re/map-picker.md).

## Ownership

The active multiplayer mod catalog is the source of truth. In launcher terms,
an installed Boneyard is selectable when its mod is enabled in the stage being
launched. This qualification is required by the existing join contract: a
client downloads and stages the host's exact enabled mod set after consent;
disabled local installations are neither advertised nor distributed. Making a
disabled mod selectable would create a choice that the existing distribution
path cannot deliver.

Only the multiplayer authority may open the picker or publish a selection.
Clients never choose a replacement. Solo and client start controls retain
their existing behavior. A process with zero catalog entries does not install
the MapPicker hook, so its start control remains the original stock code.

## Staged catalog

The launcher reuses validated manifest overlays and `ModCatalog.EnabledMods`.
Every enabled overlay whose source and target are `.boneyard` files becomes a
picker entry. Discovery does not rescan arbitrary files outside the manifest,
and it does not change the existing Boneyard admission rules.

At staging time, each entry receives:

- display name: source filename without `.boneyard`;
- source mod ID, display name, and version;
- source filename and manifest-relative source path;
- lowercase SHA-256 of the exact Boneyard bytes;
- an immutable stage-local stock path;
- file length, SyncBuffer chunk count, named-buffer count, and maximum depth
  from the already-bounded Boneyard inspector.

The immutable copy is placed beneath
`data/levels/.sdmod-picker/<sha256>.boneyard`. The bootstrap contains the
relative stock path and absolute stage path. Duplicate bytes may produce two
display entries, but share one immutable file and one network identity. The
launcher deletes stale files in this reserved directory on each stage build.

The runtime bootstrap adds `boneyard_count` and `[boneyard.N]` sections. This
keeps source attribution after overlays are applied, including Boneyard-only
mods that do not have a Lua entry script.

## Frontend provider contract

ATC builds against `SolomonDarkModLoader/include/boneyard_picker.h`. The stable
frontend calls are:

```cpp
BoneyardPickerSnapshot GetBoneyardPickerSnapshot();
bool PickBoneyard(std::size_t index, std::string* error_message);
bool CancelBoneyardPicker(std::string* error_message);
```

`BoneyardPickerSnapshot::catalog` is a
`std::shared_ptr<const BoneyardPickerCatalog>`. The catalog is immutable for
the process lifetime, so polling the snapshot is constant-size and does not
copy a large entry list. `catalog->entries` contains
`BoneyardPickerEntry` records with exactly the staged fields above.

The snapshot reports one of:

```text
Closed
Choosing
WaitingForPeers
Launching
Error
```

It also carries `selected_index`, `selection_revision`, selected SHA-256,
`is_open`, missing participant IDs, and a user-facing error message. `is_open`
is the presentation gate: a successful stock handoff retains its replicated
selection state for late join without leaving the picker frontend visible.
The frontend treats
`PickBoneyard(index)` and `CancelBoneyardPicker()` as events: both validate and
queue intent, while the game-thread pump performs native calls. No renderer is
allowed to call stock code directly.

The initial placeholder uses this same public contract. It draws a bounded
visible window over the immutable list and supports Up/Down, Page Up/Page Down,
Enter, and Escape. It contains no visual API that ATC must preserve.

The native frontend draws through the complete stock HUD render at
`0x005D2520`. Its detour calls the stock trampoline first, then submits the
picker's ExactText and untextured quads while the native renderer still owns
the HUD presentation boundary. It never draws from the subordinate
`0x00512060` dispatcher or the D3D9 `EndScene` callback. Those earlier seams
either let later stock passes overwrite the picker or invoke engine renderer
primitives after their valid lifetime.

## Stock start hijack

The config-driven hook target is the recovered Courtyard start-run function at
`0x0050E5E0`.

```text
stock start control
  no catalog entries                         -> no loader hook installed
  hook installed for a non-empty catalog
    not multiplayer authority                -> trampoline immediately
    authority                                -> Open picker provider
```

The zero-entry process never patches `0x0050E5E0`, resolves the native String
helper, or initializes picker-only gameplay seams. The stock function therefore
runs byte-for-byte as shipped. The hook's non-authority branch calls its
trampoline without picker state mutation.

A second start-control activation while the loader picker is open is treated
as `CancelBoneyardPicker()`. Cancel clears any pending custom selection and
calls the stock trampoline on the live Courtyard. The ordinary stock
`MapPicker` then opens and owns selection or its own cancel path.

`QueueHubStartMatch()` uses the same provider decision so Lua/input-driven
multiplayer start requests cannot bypass the authority picker. Its zero-entry
path remains the existing generated-run queue.

## Selection and stock launch handoff

The selected wire value is the 32-byte content SHA-256. Absolute paths never
cross the network. Each peer resolves the digest against its immutable local
catalog.

Once the authority and all connected human peers resolve the selection, the
game-thread handoff:

1. resolves the live Gameplay and Courtyard objects;
2. assigns the peer-local absolute stage path into the native Gameplay String
   at `Gameplay + 0x1BD8` through the recovered native String assign helper;
3. invokes the original Courtyard start-run trampoline; and
4. lets the constructed stock `MapPicker` detect the preselected String and
   execute its native completion path.

That absolute path is the loader-side equivalent of the path that stock
`0x00423A30` resolves before copying the selected String. It is never sent to
another peer; the digest is the wire identity and each process supplies its own
stage path. This is not a parallel Arena loader. The stock path prepares
`play.boneyard`, transitions through the stock picker completion tick, and
lets `Arena_Create` resolve and load the working Boneyard. Clients execute the
same preselected-String handoff when following the authenticated host Run
intent. Existing run-seed, scene-intent, loading-barrier, and Arena lifecycle
hooks remain in control around that native transition.

## Replication protocol

Protocol state adds the same fixed-width selection fields to `StatePacket`
and `ParticipantFramePacket`:

- selection revision;
- local resolution status (`None`, `Ready`, or `Missing`);
- reserved bytes; and
- 32-byte Boneyard SHA-256.

The fields have two role-specific meanings:

| Sender | Meaning |
| --- | --- |
| Authority | Current authoritative revision and selected digest; zero digest means no custom selection. |
| Client | Acknowledgement of the exact authority revision and digest, plus that client's local resolution result. |

Clients accept selection changes only from the authenticated configured
authority. The host accepts acknowledgements only from authenticated current
participant sessions. Acknowledgements with a different revision or digest do
not satisfy the launch barrier.

The host publishes the choice before entering the run and waits for every
connected remote human. Host-owned Lua participants do not resolve files and
therefore do not enter this barrier. A disconnected participant is removed
from the required set by the existing participant lifecycle.

The authority keeps the active revision and digest while the run is active.
A late join therefore resolves the catalog entry before the existing scene
follow logic sees the authority Run intent. If resolution has not succeeded,
the client does not queue the stock transition.

## Missing Boneyard behavior

Resolution checks that the digest exists in the local catalog and that the
immutable staged file still exists with the staged length and exact SHA-256.
The digest is checked again immediately before each native handoff. Failure is
fail-closed:

- the client publishes `Missing`, retains the host revision/digest, refuses
  run entry, and exposes the error in its provider snapshot and placeholder;
- the host observes that acknowledgement, does not launch, and exposes an
  error naming the missing participant IDs;
- if the acknowledgement belongs to a late join after launch, the active run
  continues, that client remains outside it, and the host surfaces the same
  participant-specific error until the client recovers or disconnects;
- both sides log the revision and digest; and
- the state is retried while the choice remains active, allowing a repaired
  staged file to become `Ready` without inventing a different map.

The existing launcher fingerprint normally prevents this state because every
peer stages the host's exact enabled mods. The explicit runtime error still
handles deletion, disk failure, or a damaged stage without a crash or silent
generated-map fallback.

## State evidence

The semantic scene snapshot exposes whether the picker is open, plus the
active Boneyard revision, digest, resolution status, and applied stock-relative
path. A peer reports an applied path only after its native selected-String
handoff succeeds. Live acceptance must combine those per-peer state values
with the corresponding run scene and working-file identity; screenshots prove
presentation only.

## Explicit non-goals

- no editor or Dark Cloud browser integration;
- no Boneyard schema changes or new validation policy;
- no image/thumbnail generation;
- no arbitrary runtime mod download protocol;
- no fallback to another Boneyard, procedural generation, or an absolute host
  path after a custom selection fails; and
- no production release or owner-install mutation.
