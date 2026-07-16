# Multiplayer Participant Model

This document describes the participant model that the Lua bot runtime and future
multiplayer layer share. It is the implementation-facing bridge between bot work
and real remote-player work.

## Source Map

- `SolomonDarkModLoader/include/multiplayer_runtime_state.h` owns the shared
  participant, character profile, scene intent, and runtime snapshot types.
- `SolomonDarkModLoader/src/multiplayer_runtime_state.cpp` owns local/remote
  participant upsert, validation, and Steam bootstrap state projection.
- `SolomonDarkModLoader/src/bot_runtime/` owns Lua-controlled participant
  lifecycle, movement, casting, skill choices, snapshots, and pending sync.
- `SolomonDarkModLoader/src/mod_loader_gameplay/` owns materialization into the
  stock game world and publishes gameplay snapshots back to the runtime state.
- `SolomonDarkModLoader/include/multiplayer_runtime_protocol.h` is the current
  fixed-packet scaffold. It is not yet the final networking packet taxonomy from
  `docs/networking/README.md`.

## Participant Identity

There is one participant ownership model:

```cpp
enum class ParticipantKind {
    LocalHuman,
    RemoteParticipant,
};

enum class ParticipantControllerKind {
    Native,
    LuaBrain,
};
```

The local player is `ParticipantKind::LocalHuman` with a native controller.
Lua bots are `RemoteParticipant + LuaBrain`. Future networked players should be
`RemoteParticipant + Native`, not a separate actor/state family.

The first local multiplayer transport uses this future path now: UDP peer state
packets upsert `RemoteParticipant + Native` rows, then the existing participant
materialization rail spawns those rows as remote wizard actors. Once an actor is
materialized, incoming network transforms update the participant runtime snapshot
and the gameplay tick performs native-remote playback toward that target. The
sync queue is not used as a per-packet transform pump, because that queue is
deliberately throttled for stock-safe spawn/rematerialization work. The local UDP
state packet carries the participant display name, and the gameplay HUD/nameplate
path resolves the materialized actor back to that participant name.

The runtime reserves:

- `kLocalParticipantId = 1`
- `kFirstLuaControlledParticipantId = 0x1000000000001000`

The runtime participant carries Steam/session metadata, display name, readiness,
transport flags, a character profile, and a live runtime snapshot.

Lua validation can inspect networked remote players through
`sd.bots.get_participants()`, `sd.bots.get_participant_state(id)`, and
`sd.bots.get_nameplate(actor_address)`. Those APIs are intentionally query-only
for native remote players.

## Character Profile

`MultiplayerCharacterProfile` is the canonical participant character contract.
It replaces the old pattern of treating a single `wizard_id` or element value as
the whole character.

The profile contains:

- `element_id`
- `discipline_id`
- four appearance choice ids
- primary/combo/secondary loadout entry indices
- `level`
- `experience`

Validation currently accepts element ids `0..4` and the three stock disciplines
`Mind`, `Body`, and `Arcane`.

The important design rule is that remote participants and bots do not load each
other's save files. A local save or create-screen choice can be translated into a
profile, and that profile is then translated locally into the stock source
profile, progression, appearance, and loadout data needed by the game.

## Participant-Owned Inventory And Books

The multiplayer participant owns gameplay progression state that stock
single-player stores on local slot 0 or in process-global fields:

- the owner process's one stock scene inventory root and equipment sinks
- gold
- spellbook unlock/upgrade state
- statbook allocation/upgrade state
- current loadout derived from those books

Joined clients should use temporary multiplayer profile storage so a host's
world state cannot corrupt the client's primary single-player save. During a
session, host-confirmed rewards and progression deltas update the participant
state first. The stock UI and actor runtime can then be pointed at, or refreshed
from, that participant-owned state as a presentation layer.

This is different from the existing character profile summary in `StatePacket`.
The profile gets a participant into the world; participant-owned inventory,
spellbook, and statbook state is mutable run/session state. Loot pickup must
credit that mutable participant state, not `DAT_0081A388` global gold or
`DAT_0081C264 + 0x13B8` as an unconditional slot-0 inventory root.

The runtime now carries an explicit `ParticipantOwnedProgressionState` on each
`ParticipantInfo`. The first fields are intentionally bounded: initialized flag,
gold, a gold revision, full inventory rows,
progression-book/statbook/skillbook/spellbook rows, current ability loadout, and
inventory/spellbook/statbook/loadout revision
counters. Local UDP refresh populates the local participant's gold from live
player state, advances the gold revision when that value changes, and
`sd.runtime.get_multiplayer_state()` exposes the participant ledger so live
tests can prove loot pickup work is targeting participant state instead of
silently falling back to the stock global economy.

The first concrete pickup paths are host-authorized gold, health/mana orbs, and
item/potion carrier drops.
A connected client sends `LootPickupRequest` for a host-owned drop id; the host
validates run, distance, duplicate state, and drop identity, then sends
`LootPickupResult`. Accepted gold results credit only the requesting
participant's owned gold, advance that participant's `gold_revision`, consume
the host drop, and leave the host process-global gold unchanged. Accepted orb
results apply the host-authored health or mana resource result to the requesting
participant's runtime vitals and to the client's local HP/MP presentation.
Accepted item/potion carrier results clear the host carrier's held-item pointer
and credit the requesting participant's replicated inventory ledger by item type,
slot, stack count, exact recipe identity, and wearable color when applicable.
The owning process materializes the item through the stock recipe-clone and
inventory insertion paths. Observer processes intentionally do not create a
second native inventory root: all recovered stock inventory, equip, storage,
and merchant consumers address the one process-local scene root without a
participant parameter. Observers retain the authoritative participant rows,
native remote equipment presentation, and mirrored progression/stat/skill/
spellbook state.

Shared experience and level-up choices follow the same participant-owned rule.
The host owns the shared XP/level event. When the host levels, it synchronizes
each connected native participant's materialized progression to the shared level,
rolls that participant's native skill-picker options against that participant's
current book state, and sends a private `LevelUpOffer`. A non-host client
suppresses its local native level-up picker/event while connected, exposes the
host offer through `sd.runtime.get_multiplayer_state()`, and submits a selected
option through `sd.runtime.choose_level_up_option(...)`. The host accepts only an
option index/id that exists in the issued offer, applies it to that participant's
materialized progression, and returns `LevelUpChoiceResult` for the client's
local progression to apply. Protocol v54 wraps those private offers in one
host-authored cohort barrier: every participant pauses together, accepted
choosers wait on the remaining count, the host auto-picks unresolved offers at
60 seconds, and repeated final result/resume packets keep every peer on the same
pause revision.

The loader now has a read-only native inventory audit surface at
`sd.player.get_inventory_state()`. It decodes the local gameplay scene's
embedded item list root, starter potion rows, and gameplay-owned visual sink
helpers for hat/robe/staff. `sd.player.get_progression_book_state()` reads the
local native progression table that currently exposes 83 book rows in the
starter hub state. Local UDP protocol v30 mirrors bounded full participant-owned
inventory rows in `StatePacket` plus up to 128
progression-book/statbook/skillbook/spellbook rows and the current ability
loadout. That proves inventory/book/loadout content visibility between peers.
The pickup request/result protocol also mirrors accepted item/potion carrier
metadata through `LootPickupResult`; for verified health/mana potions, the
owning client now transfers the native held item through the stock inventory
insert/stack ABI and publishes the resulting row. Exact recipe-backed hat, robe,
staff, wand, ring, and amulet pickups and equips are verified. Host-authorized
Random Skill, Damage x4, and Bonus Skill powerups are verified in both ownership
directions. Luthacus storage plus Fomentius and Hagatha purchases remain
owner-local stock UI operations and publish their resulting participant state.
Nested sack browsing, the remaining Hagatha catalog, non-shop quest/reward
insertion, and durable cross-session persistence remain open.

## Scene Intent

Participant scene ownership is explicit:

```cpp
enum class ParticipantSceneIntentKind {
    SharedHub,
    PrivateRegion,
    Run,
};
```

`SharedHub` means the participant belongs in the shared hub space.
`PrivateRegion` means the participant belongs in a specific hub interior and
must carry either `region_index` or `region_type_id`. `Run` means the participant
belongs to the active run scene.

Lua may omit scene intent on bot creation. The runtime then derives the default
from the active scene: hub root becomes `SharedHub`, hub interiors become
`PrivateRegion`, and `testrun` becomes `Run`.

## Lua Runtime Handoff

`sd.bots.create` and `sd.bots.update` parse profile and scene tables in
`lua_engine_parser_helpers.cpp` / `lua_engine_parser_requests.cpp`, then enter
the bot runtime through `CreateBot` or `UpdateBot`.

Bot creation:

1. Allocates a `RemoteParticipant + LuaBrain`.
2. Applies the character profile and scene intent.
3. Schedules a movement intent.
4. Dispatches or queues an entity sync into gameplay.

Bot update:

1. Mutates display name, profile, scene intent, readiness, and/or transform.
2. Dispatches or queues an entity sync when the profile, scene, or transform
   changes.
3. Rejects transform-only updates for materialized registered `GameNpc` actors,
   because raw transform writes do not satisfy the stock relocation contract for
   that rail.

## Gameplay Materialization

Gameplay consumes pending participant sync requests and chooses a materialization
rail based on scene context.

Current rail rules:

- Arena scenes use open gameplay slots when available, so stock hostile
  selection can target bot participants through the player-slot array.
- Hub and other non-arena scenes use the standalone wizard clone rail.
- The registered `GameNpc` rail is disabled until a true long-lived `GameNpc`
  publication contract is recovered.

Materialized bindings store the participant's actor address, rail kind, character
profile, scene intent, controller state, movement state, and stock runtime
handles. Gameplay publishes those bindings back into runtime snapshots so Lua and
debug tooling can see the live actor state.

`RemoteParticipant + Native` bindings additionally cache a sampled replicated
transform target. Incoming `StatePacket` transforms are appended to the
participant's short transform history. During each player-actor tick, the loader
samples that history about 120 ms in the past, writes the interpolated
position/heading to the materialized actor, and snaps only for large
discontinuities such as scene changes. The participant collision resolver treats
native remote players as solid against the local player and can push both actors
apart; Lua bot collisions keep the older rule where the local player remains
solid and the bot-owned actor yields.

## Networking Boundary

The current protocol uses fixed-layout packets shared by both Steam Networking
Messages and the explicit local-UDP test backend:

- `SessionHelloPacket`, `SessionHelloAckPacket`, and `SessionGoodbyePacket`
- `StatePacket`
- `CastPacket`
- `ProgressionPacket`
- `WorldSnapshotPacket`
- `LootSnapshotPacket`
- `SpellEffectSnapshotPacket` and `AirChainSnapshotPacket`
- reliable loot/pickup packets for host-owned drops and per-participant
  inventory/spellbook/statbook deltas
- reliable level-up offer/choice/result packets for host-authored shared XP
  level-up choices

Protocol v50 authenticates Steam lobby members with the lobby ID, Steam identity,
session nonce, required capability bits, and deterministic staged-build manifest
hash before gameplay packets are admitted. The host remains authoritative for
world, loot, progression choices, and relaying participant-authored state and
casts.

The multiplayer service loop currently pumps Steam bootstrap/callback state every
50 ms and mirrors readiness into `RuntimeState`. For rapid local development it
can also pump a UDP loopback transport that exchanges `StatePacket` transform
snapshots plus participant-owned gold/revision ledger values, host-owned
`WorldSnapshot` actor snapshots, and host-owned run `LootSnapshot` data for
gold/orb drop presentation plus pickup identity. The host's `StatePacket` also owns the
local UDP run-entry scene intent: connected clients cannot call
`sd.hub.start_testrun` or directly switch themselves into the arena, but they
queue the normal stock-safe hub-to-run transition when the configured host reports `in_run`.
Protocol v38 identifies that host explicitly in direct and relayed state
packets, so a relayed non-host participant cannot impersonate run-entry or
shared-pause authority merely because its datagram arrived from the host endpoint.
The UDP path remains a development backend for the same participant and
replication boundary used by Steam P2P.

## Invariants

- One participant model must serve local humans, Lua bots, and future remote
  humans.
- Character profile owns appearance/loadout identity; save files are not the
  multiplayer identity object.
- Scene intent owns participant presence; ad hoc inference from the local
  player's current region is not enough.
- Gameplay-world mutation stays on stock-safe gameplay phases, not on an
  independent simulation thread.
- Dev/debug mutators need a multiplayer runtime profile gate before real peer
  networking ships.
