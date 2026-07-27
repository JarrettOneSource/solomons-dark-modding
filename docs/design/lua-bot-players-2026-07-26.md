# Lua-controlled multiplayer bot players

Date: 2026-07-26
Issues: #58 (Lua-controlled bot players), #59 (autonomous wave-five brain)
Status: design gate; implementation must preserve the invariants below

## Decision

A Lua bot is a **synthetic remote participant** owned by the transport host. It
is not a loader-owned standalone actor and it is not an alias of the local
player.

The host creates a normal multiplayer participant with:

- a synthetic 64-bit participant id;
- a transport session nonce and the host participant id as authority;
- `ParticipantKind::RemoteParticipant`;
- `ParticipantControllerKind::LuaBrain`;
- a persona name and character profile;
- one stock gameplay slot in the range 1..3; and
- an actor created, registered, ticked, damaged, killed, and rendered through
  the same participant entity path used for a real remote peer.

The host alone runs the Lua brain. Movement and cast intents enter the existing
remote-input seams. The resulting participant state, casts, spell effects,
damage, death presentation, and world changes replicate to real peers through
the existing multiplayer streams.

This is the architecture boundary. A change that requires a standalone bot
actor, a slot-0 alias, a second spell dispatcher, or a bot-only combat/damage
system is a design question for the owner rather than an implementation
shortcut.

## Located foundation seams

### Participant registration

The existing runtime model already has the required identity:

- `ParticipantKind::RemoteParticipant`
- `ParticipantControllerKind::LuaBrain`
- `UpsertRemoteParticipant(RuntimeState&, participant_id, controller_kind)`
- synthetic ids beginning at `0x1000000000001000`

`CreateBot` currently uses those types, assigns the name/profile/scene intent,
marks the participant transport-connected, and requests participant entity
synchronization. The implementation will make that participant a
host-authoritative replicated session member rather than a host-local runtime
record.

The synthetic participant owns a fresh nonzero session nonce. State and frame
packets use:

- `participant_id = synthetic participant id`
- `participant_session_nonce = synthetic participant nonce`
- `authority_participant_id = host participant id`
- `controller_kind = LuaBrain`

Clients accept that identity only from the configured host endpoint. A host
never accepts a network peer claiming `LuaBrain`. Late packets for a retired
synthetic nonce are rejected.

### Remote avatar materialization

Real remote state enters
`ApplyRemoteStatePacket`/`ApplyRemoteParticipantFramePacket`, calls
`UpsertRemoteParticipant`, and queues the shared participant entity request.
That request is consumed by:

1. `ExecuteParticipantEntitySyncNow`
2. `TrySpawnGameplaySlotBotParticipantEntity`
3. `CreateGameplaySlotBotActor`
4. `FinalizeGameplaySlotBotRegistration`

The stock/native seams used by this path are:

| Purpose | Binary layout key | Address |
| --- | --- | ---: |
| create a stock player slot | `gameplay_create_player_slot` | `0x005CB870` |
| register the actor in the world slot list | `actor_world_register_gameplay_slot_actor` | `0x00641090` |
| unregister the actor from the world slot list | `actor_world_unregister_gameplay_slot_actor` | `0x00641130` |
| stock player tick | `player_actor_tick` | `0x00548B00` |

`TryFindOpenGameplayBotSlot` selects a free slot 1..3. Synthetic participants
must stay on this rail in both the shared hub and a run. The existing
`standalone_clone` materialization rail is not a fallback for this feature.

Stock slot creation and world registration are what make the actor visible to
the normal hostile-target selection, ally-HUD enumeration, collision, damage,
corpse, and retargeting systems. Those consequences are acceptance tests, not
separate features to emulate.

The implementation must not write the bot actor to
`local_player_actor` (`0x0081D5BC`) and must not give it slot 0. A local
slot-0 actor may be read as a stock visual/collision template only; it never
becomes the bot's identity or owner.

### Movement ingress

The host-owned synthetic participant records a destination intent. Its stock
actor tick consumes that intent through the established native movement seam:

- stock tick: `player_actor_tick` at `0x00548B00`;
- movement accumulator: actor `+0x158` / `+0x15C`;
- native tick input vector: actor `+0x218`;
- native collision/move step: `player_actor_move_step` at `0x00525800`;
- placement tests: `movement_collision_test_circle_placement` at
  `0x00523C90` and the extended form at `0x005238C0`.

`ApplyWizardBotMovementStep` is the mechanics reference and must continue to
call the native movement/collision path. Lua does not teleport the actor or
reimplement the cell-grid test.

The host samples the resulting stock actor transform into the participant
state/frame stream. A real client treats a host-authored `LuaBrain` participant
like its other packet-driven remote actors: interpolate/apply received
transform and presentation, and do not run a local Lua movement controller.

### Cast ingress

The wire-level ingress is `CastPacket` followed by
`ApplyRemoteCastPacket`. It supplies the participant/run identity, cast
sequence, cast kind, secondary slot, input phase, resolved skill/profile,
origin, heading, aim/cursor coordinates, and optional target network actor id.
The owner-log snapshot confirms primary `pressed` / `held` / `released`
lifecycles and one-shot secondary `pressed` packets.

`bot:cast(...)` constructs that exact packet shape on the host, injects it into
the same validated ingress core as a packet received from a peer, and sends the
same packet to real clients. The ingress produces a `BotCastRequest` with
`remote_input_controlled=true`; it does not call a second dispatcher.

The native lifecycle remains:

- spell/pure-primary dispatcher: `0x00548A00`;
- per-spell initialization gate: actor `+0x5C == 0` and
  actor `+0x27C == 0xFF`;
- active handler fields observed at actor `+0x160` and `+0x1EC`;
- dispatch once, then let `PlayerActorTick` drive the handler;
- release through `cast_active_handle_cleanup` at `0x0052F3B0`.

Host-local injection is legal only for a locally owned synthetic participant.
On clients, a synthetic cast is legal only when its participant already has an
authenticated `LuaBrain` state epoch from the configured host. A client cannot
author a bot cast, and an external client cannot spoof one to the host.

## Ownership and replication

There are two distinct execution modes for the same participant kind:

| Machine | Synthetic actor ownership | Transform/presentation | Lua control |
| --- | --- | --- | --- |
| transport host | locally simulated stock slot actor | sampled and published | enabled |
| real client | packet-driven remote stock slot actor | received and played back | disabled |

Code must therefore test “packet-driven on this machine,” not merely
`controller_kind == Native`, when selecting remote playback, vitals, death,
collision, and cast-replay behavior.

The host publishes each active synthetic participant on the normal
`StatePacket` and `ParticipantFramePacket` streams. State is reliable and
periodic; frames use the normal high-rate transform cadence. Run, profile,
loadout, vitals, statuses, movement animation, visual links, and death
presentation come from the stock actor snapshot.

The protocol lifecycle adds an explicit retired state to the reliable
participant stream. Despawn sends the retirement before local removal. A client
then:

1. records the retired session nonce;
2. destroys the queued/materialized participant entity;
3. removes the participant from runtime/session membership; and
4. ignores late frames, casts, or state from that retired epoch.

This requires a protocol version bump because retirement is a wire contract,
not a timeout heuristic.

Synthetic participants follow host scene intent automatically. A bot persists
as one participant identity across shared-hub and run transitions, is
rematerialized through the participant entity synchronizer, and adopts the
current host run nonce. The public Lua API does not expose scene surgery.

## Stock-system acceptance spine

The following are required consequences of the participant architecture:

1. **Hostile targeting:** the actor occupies a real registered gameplay slot,
   so native enemy selection can acquire it. No
   `HookMonsterPathfindingRefreshTarget` promotion is added.
2. **Ally HUD:** the stock player-list/ally-healthbar path enumerates the slot.
   The existing participant-name lookup supplies the persona name. No extra
   loader HUD row is drawn.
3. **Damage out:** stock spells originate from the bot's registered slot actor,
   and authoritative damage/effect streams resolve that actor back to the
   synthetic participant id.
4. **Damage in:** the host applies normal stock player damage to the bot actor;
   clients receive authoritative vitals/presentation.
5. **Death:** the host records the stock player death transition and publishes
   a durable death epoch. Clients require both zero HP and the replicated death
   presentation signal, render the standard corpse, and never infer death from
   HP alone.
6. **Retargeting:** the standard dead-wizard hostile-target clearing and native
   reacquisition path moves enemies to a surviving player.
7. **Two-human parity:** in a host/client session, a host-spawned bot is the
   same third participant, slot, persona, avatar, vitals, actions, and corpse on
   both peers.

## Lua API contract

`sd.bots` is multiplayer-native and host-authoritative. Mutating methods fail
closed on a non-host. Read methods operate on the replicated participant
snapshot available on either peer.

```lua
local bot = sd.bots.spawn({
  name = "Ember",
  class = "fire",
})

bot:despawn()
bot:move_to(x, y)
bot:stop()
bot:cast(skill_slot, target_x, target_y [, hold_ms])
bot:position()       -- x, y
bot:hp()             -- current HP
bot:max_hp()
bot:alive()
bot:slot()           -- 1..3 when materialized
bot:participant_id()

local bots = sd.bots.list()
```

Contract details:

- `spawn` validates a nonempty bounded persona name, a supported class, host
  authority, and available participant/slot capacity. It returns a stable
  handle or `nil, error`.
- Classes are `fire`, `water`, `earth`, `air`, and `ether`, mapped to the
  native element ids. The wave-five brain uses `fire`.
- A handle captures only the participant id. Each call resolves current
  runtime state, so a stale/despawned handle fails rather than retaining native
  pointers.
- `despawn`, `move_to`, `stop`, and `cast` return `true` on acceptance or
  `false, error`.
- `position` returns `x, y` or `nil, error`.
- `hp`/`max_hp` return a number or `nil, error`.
- `alive` is true only for a valid materialized participant with positive HP
  and no committed death epoch.
- `slot` returns 1..3 or `nil` while not materialized.
- `participant_id` returns the stable 64-bit id represented with the existing
  Lua integer convention.
- `list` returns handles for active synthetic participants in participant-id
  order.
- `skill_slot == 0` means the class primary. Slots 1..8 select the queued
  secondary belt entries.
- A primary cast emits `pressed`, optional `held`, then `released`. `hold_ms`
  is bounded and defaults to a short primary activation. A secondary cast is a
  one-shot `pressed` input.
- `target_x`/`target_y` become the wire aim and cursor coordinates. The host
  derives origin, heading, profile, resolved skill id, run nonce, and monotonic
  cast sequence from the authoritative participant.

The older flat bot functions remain mechanics/diagnostic compatibility during
this delivery but are not used by the new brain. New feature documentation and
examples use the handle API exclusively.

Lua brain callbacks ride the existing `runtime.tick` service. No private
thread, timer loop, or native AI hook is introduced.

## Autonomous brain v1

The standard-layout mod is `mods/bot-brain/`. It owns one fire-class bot when
the local process is the transport host.

### Think cadence

The brain receives every `runtime.tick` event and makes a decision every
250 ms. It keeps issuing movement through `bot:move_to`; native placement and
collision remain authoritative. It continues moving during wave transitions.

### Threat-repulsion kiting

For each tracked live enemy inside the threat radius:

1. compute the vector from enemy to bot;
2. normalize it;
3. weight it by inverse distance, with a finite near-distance clamp; and
4. add it to a threat-repulsion vector.

Blend the normalized repulsion vector with a weaker vector toward the current
arena center. The center bias increases near the arena perimeter so the bot
does not kite into a corner. Project a short look-ahead destination and pass it
to `move_to`; Lua never writes the actor transform.

If no enemy is inside the threat radius, continue orbiting around the arena
center rather than becoming stationary.

### Targeting and offense

Select the nearest live enemy within the native fire-primary cast window.
While HP is at least 35%, cast the fire primary at the target on a steady,
bounded cadence. Fire is selected because its multiplayer damage element is
verified exact; earth and frost are outside this brain's acceptance scope.

### Survival

Below 35% HP, enter flee mode:

- use pure threat repulsion plus center recovery;
- issue no casts; and
- remain in flee mode until HP recovers above a small hysteresis threshold.

Death ends the run attempt and is recorded, never hidden by respawning or
fabricated success.

### Result telemetry

Each unattended run produces `result.json` containing at least:

- run id and completion reason;
- highest wave reached;
- whether the bot was alive at wave five;
- sampled HP timeline;
- casts issued and accepted;
- accumulated kite-path distance; and
- death wave/cause evidence when applicable.

The acceptance harness, not the brain, writes the evidence file from observed
runtime state and logs. Success requires three consecutive host-plus-one-bot
runs that reach wave 5 with the bot alive, plus a both-peer screenshot at wave
3 or later with the bot in combat.

## Verification gates

Implementation proceeds only after this design document is committed.

### Phase 1: participant lifecycle

- host spawn yields a named synthetic member and slot 1..3;
- stock avatar and stock ally-HUD row are visible;
- a native hostile acquires the bot;
- despawn unregisters the slot and removes the member cleanly;
- the same identity, slot, avatar, HUD, and lifecycle are observed by a real
  loopback client.

### Phase 2: control and convergence

- `move_to` produces native collision-aware movement and convergent peer
  transforms;
- `cast` uses the cast ingress lifecycle, creates effects, deals authoritative
  damage, and converges;
- HP/damage in both directions use standard multiplayer state;
- bot death publishes the standard death epoch/corpse and enemies retarget a
  survivor;
- API access and host-only mutation contracts have regression tests.

### Phase 3: autonomous run

- three consecutive unattended runs reach wave 5 with the bot alive;
- each run has the required result telemetry;
- both peers show the same bot mid-fight at wave 3 or later.

Every newly depended-on native address receives a binary-layout/static
contract. Final dispatch includes the current source-organization,
workspace/build, native, Python, static-RE, and Windows launcher-contract
suites after rebasing on current `origin/main`.

## Explicit non-goals and rejected mechanisms

- no standalone bot materialization;
- no slot-0 or `local_player_actor` alias;
- no loader-owned transform playback on the host stock actor;
- no client-side bot brain;
- no cell-grid collision reimplementation;
- no custom hostile-target promotion or
  `HookMonsterPathfindingRefreshTarget`;
- no bot-only HUD, damage, death, corpse, or replication lane;
- no automatic transport fallback or NFO dependency; and
- no claim of wave-five success without observed three-run evidence.
