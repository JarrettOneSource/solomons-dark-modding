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

The runtime reserves:

- `kLocalParticipantId = 1`
- `kFirstLuaControlledParticipantId = 0x1000000000001000`

The runtime participant carries Steam/session metadata, display name, readiness,
transport flags, a character profile, and a live runtime snapshot.

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

## Networking Boundary

The current protocol header is still a small fixed-packet scaffold:

- `StatePacket`
- `LaunchPacket`
- `CastPacket`
- `ProgressionPacket`

Those structs are useful for early shape checks, but the actual co-op design in
`docs/networking/README.md` requires a broader reliable/unreliable packet family
for manifest handshake, join/bootstrap, entity lifecycle, input, snapshots,
gameplay events, progression deltas, and reconnect.

The multiplayer service loop currently pumps Steam bootstrap/callback state every
50 ms and mirrors readiness into `RuntimeState`. It does not yet own peer
sessions, packet transport, or replication.

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
